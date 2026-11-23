"""PATCH checks (`--allow-writes`), on the resource the base create made (create.py).

- `patch-formats`: with each content type the spec declares (docs/spec-quirks.md #4), a
  PATCH that sets `description` (else `name`) to a new marker value, in the body shape
  the type needs: an object for `application/json` and merge-patch, a JSON Patch array
  for the `json-patch` types. Not a no-op, because a server may rightly refuse a PATCH
  that changes nothing. A refusal is `content-type <type>`; a 200/204 whose change does
  not show on read is `content-type <type> ignored`; when every type answers 404, 405 or
  501 the PATCH is `unimplemented`.
- `patch`: each optional attribute of the PATCH schema, one at a time, with the merge
  type, then read back: `read-only` (4xx), `server-error` (5xx), `dropped`, `rewritten`.
  A value equal to the current one proves nothing and is `unprobed <attr> same-value`; a
  409 is a conflict with the resource's state (TMF630), not proof the attribute is
  read-only, and is `unprobed <attr> conflict`.
  `state` and `status` are not probed: a refusal may be a transition rule, not a gap.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tmf_checker.checks import NOT_IMPLEMENTED, Context, check_auth, item_path
from tmf_checker.checks.create import SERVER_SET, diff, prepare, values
from tmf_checker.client import Response
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource
from tmf_checker.values import Unbuildable, Values

PREFERRED = ("description", "name")  # description: renaming may break references
STATE_MACHINE = {"state", "status"}


def _target(ctx: Context, resource: Resource, check: str) -> tuple[Any, list[Finding]]:
    op = resource.op("PATCH", item=True)
    if op is None or not resource.op("POST"):
        return None, []
    creation, findings = prepare(ctx, resource, check)
    if creation is None or creation.id is None:
        return None, findings
    return creation, findings


def _patch(ctx: Context, resource: Resource, rid: str, body: Any, ctype: str) -> Response:
    response = ctx.client.request(
        "PATCH", item_path(resource, rid), json_body=body, content_type=ctype
    )
    check_auth(response)
    ctx.record_sent(resource.collection, rid, body)
    return response


def _base(ctx: Context, resource: Resource) -> tuple[dict[str, Any] | None, str | None]:
    """The PATCH schema's required attributes (v5: `@type`), or the reason there are none."""
    schema = ctx.spec.request_schema(resource.op("PATCH", item=True))
    if schema is None:
        return None, "no-patch-schema"
    try:
        with values(ctx).scope(resource.schema):
            return values(ctx).minimal(schema), None
    except Unbuildable as exc:
        return None, str(exc).split()[0]


def run_formats(ctx: Context, resource: Resource) -> Iterator[Finding]:
    creation, findings = _target(ctx, resource, "patch-formats")
    yield from findings
    if creation is None:
        return
    item = resource.item
    schema = ctx.spec.request_schema(resource.op("PATCH", item=True))
    props = ctx.spec.properties(schema) if schema else {}
    attr = next((a for a in PREFERRED if a in props and a in creation.body), None)
    base, reason = _base(ctx, resource)
    if attr is None or base is None:
        yield ctx.finding("PATCH", item, "skipped", f"patch-formats {reason or 'no-attribute'}")
        return
    answers: list[tuple[str, Response, Finding | None]] = []
    types = ctx.spec.request_content_types(resource.op("PATCH", item=True))
    for number, ctype in enumerate(types):
        value = f"tmf-checker-{ctx.run_id}-patch-{number}"
        if "json-patch" in ctype:
            body: Any = [{"op": "replace", "path": f"/{attr}", "value": value}]
        else:
            body = {**base, attr: value}
        response = _patch(ctx, resource, creation.id, body, ctype)
        ignored = None
        if response.status in (200, 204):  # read it back now, before the next type
            read = ctx.client.get(item_path(resource, creation.id))
            check_auth(read)
            got = read.json()
            if read.ok and isinstance(got, dict) and got.get(attr) != value:
                ignored = ctx.finding(
                    "PATCH",
                    item,
                    "content-type",
                    f"{ctype} ignored",
                    read,
                    sent=value,
                    returned=got.get(attr),
                )
        answers.append((ctype, response, ignored))
    if answers and all(r.status in NOT_IMPLEMENTED for _, r, _ in answers):
        first = answers[0][1]
        yield ctx.finding("PATCH", item, "unimplemented", str(first.status), first)
        return
    for ctype, response, ignored in answers:
        if not response.ok:
            yield ctx.finding("PATCH", item, "content-type", ctype, response)
        elif ignored:
            yield ignored


def merge_type(types: list[str]) -> str | None:
    for wanted in ("application/merge-patch+json", "application/json"):
        found = next((t for t in types if t.startswith(wanted)), None)
        if found:
            return found
    return None


def run_patch(ctx: Context, resource: Resource) -> Iterator[Finding]:
    creation, findings = _target(ctx, resource, "patch")
    yield from findings
    if creation is None:
        return
    item = resource.item
    op = resource.op("PATCH", item=True)
    ctype = merge_type(ctx.spec.request_content_types(op))
    base, reason = _base(ctx, resource)
    if ctype is None or base is None:
        yield ctx.finding("PATCH", item, "skipped", f"patch {reason or 'no-merge-type'}")
        return
    schema = ctx.spec.request_schema(op)
    required = ctx.spec.required(schema)
    for attr, sub in ctx.spec.properties(schema).items():
        if attr in required or attr in SERVER_SET or attr.startswith("@"):
            continue
        if attr in STATE_MACHINE:
            yield ctx.finding("PATCH", item, "unprobed", f"{attr} state-machine")
            continue
        try:
            with values(ctx).scope(resource.schema):
                sent = values(ctx).value(sub, attr)
        except Unbuildable as exc:
            yield ctx.finding("PATCH", item, "unprobed", f"{attr} {str(exc).split()[0]}")
            continue
        if attr in creation.body and diff(sent, creation.body[attr], attr) is None:
            yield ctx.finding("PATCH", item, "unprobed", f"{attr} same-value")
            continue
        response = _patch(ctx, resource, creation.id, {**base, attr: sent}, ctype)
        if response.status == 409:
            yield ctx.finding("PATCH", item, "unprobed", f"{attr} conflict", response)
            continue
        if 400 <= response.status < 500:
            if Values.made_up(attr, sent):
                yield ctx.finding("PATCH", item, "unprobed", f"{attr} made-up-value", response)
            else:
                yield ctx.finding("PATCH", item, "read-only", attr, response)
            continue
        if response.status >= 500:
            yield ctx.finding("PATCH", item, "server-error", attr, response)
            continue
        if response.status == 202:
            yield ctx.finding("PATCH", item, "unprobed", f"{attr} async", response)
            continue
        read = ctx.client.get(item_path(resource, creation.id))
        check_auth(read)
        body = read.json()
        if not read.ok or not isinstance(body, dict):
            yield ctx.finding("PATCH", item, "unprobed", f"{attr} read-failed", read)
            continue
        gap = diff(sent, body.get(attr), attr)
        if gap:
            yield ctx.finding(
                "PATCH", item, gap[0], gap[1], read, sent=sent, returned=body.get(attr)
            )
