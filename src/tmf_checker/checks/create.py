"""Write checks (`--allow-writes`) on one shared base create per resource.

The base create posts the spec's minimal body (values.py). When the server refuses it
(4xx), `requires` discovery first finds a body it accepts, trying in order: the minimal
body plus the optional attributes the refusal mentions by name, plus every buildable
optional attribute, plus each one alone, and every attribute but one. Then it removes
each optional attribute from that body: a refusal proves an attribute the server requires
and the spec does not, one `requires <attr>` line each. Reading the message only picks
where to start; the proof is the removal. The base is then the spec's minimal body
plus those attributes, so a server with business rules can still be probed.

References point at the user's fixtures or at resources of the same API created first;
without one an attribute is `unprobed ... no-fixture`, never a gap. Task resources (jobs,
cancellations, on-demand bills) are never created; orders start real processes and are
created only with `--allow-orders`.

- `location`: the base create answers 201 with a `Location` that is the new resource's
  `href` (TMF630; no spec declares the header: docs/spec-quirks.md #10).
- `requires`: the lines above.
- `roundtrip`: for each optional attribute of the create schema, the base plus that
  attribute, read back: `refused` (4xx), `server-error` (5xx), `dropped`, `rewritten`.
  One level in: an object attribute's optional properties that its generated value
  leaves out are probed too (`refused a.b`), its own `id` included (a characteristic's
  id is the client's); a 409 is a conflict with state, `unprobed ... conflict`. Only what
  was sent is compared, date-times as instants and numbers as decimals.
- `polymorphism`: `@baseType` (TMF630) on create, read back. `@schemaLocation` is not
  probed: a server that validates against it would fetch a schema we cannot provide.

Everything created is deleted at the end by `cleanup`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from tmf_checker.checks import Context, Forbidden, check_auth, item_path
from tmf_checker.client import Response
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource
from tmf_checker.values import SERVER_MANAGED, Unbuildable, Values, is_id_string

SERVER_SET = {"id", "href", "lastUpdate"}  # lastUpdate: docs/spec-quirks.md #9
VALIDATION = (400, 422)  # a refusal of the body itself; 409 is a conflict with state


@dataclass
class Creation:
    skip: str | None = None  # why there is no base resource
    response: Response | None = None  # the accepted base create
    body: dict[str, Any] = field(default_factory=dict)  # its answer
    base: dict[str, Any] = field(default_factory=dict)  # the body the server accepted
    findings: list[Finding] = field(default_factory=list)

    @property
    def id(self) -> str | None:
        return _created_id(self.response, self.body)


def _created_id(response: Response | None, body: dict[str, Any]) -> str | None:
    if response is None or not response.ok or response.status == 202:
        return None
    if body.get("id") is not None:
        return str(body["id"])
    location = response.headers.get("location")
    return location.rstrip("/").rsplit("/", 1)[-1] if location else None


def task_reason(ctx: Context, resource: Resource) -> str | None:
    name = resource.collection.strip("/")
    if name.endswith("Job") or name.startswith("cancel") or name.endswith("OnDemand"):
        return "task-resource"
    if name.endswith("Order") and not ctx.allow_orders:
        return "orders-not-allowed"
    return None


def values(ctx: Context) -> Values:
    if "values" not in ctx.creations:
        ctx.creations["values"] = Values(
            ctx.spec,
            ctx.run_id,
            refs=lambda r: reference(ctx, r),
            extra_classes=ctx.fixtures,
            preferred=ctx.preferred,
        )
    return ctx.creations["values"]


def reference(ctx: Context, target_class: str) -> dict[str, Any] | None:
    """The resource a reference to `target_class` points at, or None.

    A class this API creates gets a resource created by the run, so the user's data is never
    linked to (and changed by) what the run creates; the fixture is the fallback. A class of
    another API gets its fixture: `<Scope>.<Class>` while that resource class is being built
    (`null` there means none in that scope), else `<Class>`.
    """
    resource = next((r for r in ctx.spec.resources() if r.schema == target_class), None)
    if (
        resource is not None
        and resource.op("POST")
        and not task_reason(ctx, resource)
        and resource.collection not in ctx.building
    ):
        creation = base_create(ctx, resource)
        if creation.id is not None:
            href = creation.body.get("href") or ctx.client.url(item_path(resource, creation.id))
            ref = {"id": creation.id, "href": href}
            if "name" in creation.body:
                ref["name"] = creation.body["name"]
            return ref
    scope = values(ctx).current_scope
    scoped = f"{scope}.{target_class}"
    if scope and scoped in ctx.fixtures:
        return ctx.fixtures[scoped]  # may be None: no such fixture in this scope
    return ctx.fixtures.get(target_class)


def post(ctx: Context, resource: Resource, body: Any) -> tuple[Response, dict[str, Any]]:
    """POST and remember what it created, for cleanup."""
    response = ctx.client.request("POST", resource.collection, json_body=body)
    check_auth(response)
    answer = response.json() if isinstance(response.json(), dict) else {}
    created = _created_id(response, answer)
    if created is not None:
        ctx.created.append((resource, created))
    return response, answer


def create_schema(ctx: Context, resource: Resource) -> dict[str, Any] | None:
    op = resource.op("POST")
    return ctx.spec.request_schema(op) if op else None


def probe_attributes(ctx: Context, schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The optional attributes of a create schema that the checks send: not server-set,
    not `@`-attributes."""
    required = ctx.spec.required(schema)
    return {
        name: sub
        for name, sub in ctx.spec.properties(schema).items()
        if name not in required and name not in SERVER_SET and not name.startswith("@")
    }


# -- the base create and requires ----------------------------------------------------------


def base_create(ctx: Context, resource: Resource) -> Creation:
    key = resource.collection
    if key in ctx.creations:
        return ctx.creations[key]
    creation = Creation()
    ctx.creations[key] = creation
    schema = create_schema(ctx, resource)
    if schema is None:
        creation.skip = "no-create-schema"
        return creation
    ctx.building.add(key)
    try:
        with values(ctx).scope(resource.schema):
            minimal = values(ctx).minimal(schema)
    except Unbuildable as exc:
        creation.skip = str(exc)
        return creation
    finally:
        ctx.building.discard(key)
    try:
        response, answer = post(ctx, resource, minimal)
        if 400 <= response.status < 500:
            _discover(ctx, resource, schema, minimal, response, creation)
            return creation
    except Forbidden:
        creation.skip = "forbidden"
        return creation
    creation.response, creation.body, creation.base = response, answer, minimal
    path = resource.collection
    declared = ctx.spec.declared_statuses(resource.op("POST"))
    if response.status == 202:
        pass
    elif not response.ok or str(response.status) not in declared:
        creation.findings.append(ctx.finding("POST", path, "create-status", "minimal", response))
    elif resource.schema:
        creation.findings.extend(
            ctx.schema_findings("POST", path, resource.schema, answer, response)
        )
    return creation


def _discover(
    ctx: Context,
    resource: Resource,
    schema: dict[str, Any],
    minimal: dict[str, Any],
    refused: Response,
    creation: Creation,
) -> None:
    """The minimal body was refused: find what the server requires (module docstring)."""
    path = resource.collection
    extra: dict[str, Any] = {}
    for name, sub in probe_attributes(ctx, schema).items():
        try:
            with values(ctx).scope(resource.schema):
                extra[name] = values(ctx).value(sub, name)
        except Unbuildable:
            continue
    working: dict[str, Any] | None = None
    accepted: tuple[Response, dict[str, Any]] | None = None
    message = _error_text(refused)
    named = {k: v for k, v in extra.items() if re.search(rf"\b{re.escape(k)}\b", message)}
    candidates = [
        *([{**minimal, **named}] if named else []),
        {**minimal, **extra},
        *({**minimal, name: value} for name, value in extra.items()),
        *({**minimal, **{k: v for k, v in extra.items() if k != name}} for name in extra),
    ]
    for body in candidates if extra else []:
        response, answer = post(ctx, resource, body)
        if response.ok and response.status != 202:
            working, accepted = body, (response, answer)
            break
    if working is None:
        creation.findings.append(
            ctx.finding(
                "POST",
                path,
                "create-status",
                "minimal",
                refused,
                discovery="no body the server accepts",
            )
        )
        creation.skip = "create-refused"
        return
    culprits: dict[str, Response] = {}
    for name in [k for k in working if k in extra]:
        response, _ = post(ctx, resource, {k: v for k, v in working.items() if k != name})
        if response.status in VALIDATION:
            culprits[name] = response
    base = {**minimal, **{name: working[name] for name in culprits}}
    if culprits:
        response, answer = post(ctx, resource, base)
        if response.ok and response.status != 202:
            accepted = (response, answer)
        else:
            base = working
    else:
        base = working  # refused alone, accepted in company: no single culprit
        creation.findings.append(
            ctx.finding(
                "POST", path, "create-status", "minimal", refused, discovery="no single culprit"
            )
        )
    for name, response in culprits.items():
        creation.findings.append(
            ctx.finding(
                "POST", path, "requires", name, response, minimal_refused=refused.evidence()
            )
        )
    creation.response, creation.body = accepted
    creation.base = base


def _error_text(response: Response) -> str:
    """The words of an error answer: its string values, not its keys (`status`, `code`
    are also attribute names) and not the status code."""
    body = response.json()
    if body is None:
        return response.body.decode("utf-8", "replace")
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in ("@type", "code", "status"):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            texts.append(node)

    walk(body)
    return " ".join(texts)


def prepare(ctx: Context, resource: Resource, check: str) -> tuple[Creation | None, list]:
    """The shared base create, or the skip line that explains why there is none."""
    path = resource.collection
    reason = task_reason(ctx, resource)
    if reason is None:
        creation = base_create(ctx, resource)
        reason = creation.skip
        if reason is None and creation.response is not None and creation.response.status == 202:
            reason = "async"
        if reason is None:
            return creation, list(creation.findings)
        if reason == "create-refused":
            return None, list(creation.findings)
    return None, [ctx.finding("POST", path, "skipped", f"{check} {reason}")]


# -- location and requires -----------------------------------------------------------------


def run_location(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if not resource.op("POST"):
        return
    creation, findings = prepare(ctx, resource, "location")
    yield from findings
    if creation is None or creation.id is None:
        return
    response = creation.response
    location = response.headers.get("location")
    path = resource.collection
    if not location:
        yield ctx.finding("POST", path, "location", "missing", response)
        return
    expected = creation.body.get("href") or (
        ctx.client.url(item_path(resource, creation.id)) if resource.item else None
    )
    if expected and _norm(ctx.client.resolve(location)) != _norm(ctx.client.resolve(expected)):
        yield ctx.finding("POST", path, "location", "not-href", response, expected=expected)


def _norm(url: str) -> str:
    return url.rstrip("/")


def run_requires(ctx: Context, resource: Resource) -> Iterator[Finding]:
    """The base create reports `requires`; this check only makes sure it runs."""
    if resource.op("POST"):
        yield from prepare(ctx, resource, "requires")[1]


# -- roundtrip and polymorphism ------------------------------------------------------------


def run_roundtrip(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if not resource.op("POST"):
        return
    creation, findings = prepare(ctx, resource, "roundtrip")
    yield from findings
    if creation is None or creation.id is None:
        return
    if not resource.op("GET", item=True):
        yield ctx.finding("POST", resource.collection, "skipped", "roundtrip no-item-get")
        return
    path = resource.collection
    schema = create_schema(ctx, resource)
    # one level into the required object attributes too (an order's productOrderItem)
    for attr in sorted(ctx.spec.required(schema)):
        sub = ctx.spec.properties(schema).get(attr)
        if sub is not None and not attr.startswith("@") and attr in creation.base:
            yield from _nested(ctx, resource, creation.base, attr, sub, creation.base[attr])
    for attr, sub in probe_attributes(ctx, schema).items():
        try:
            with values(ctx).scope(resource.schema):
                sent = values(ctx).value(sub, attr)
        except Unbuildable as exc:
            yield ctx.finding("POST", path, "unprobed", f"{attr} {str(exc).split()[0]}")
            continue
        found, accepted = probe(ctx, resource, creation.base, attr, sent)
        yield from found
        if accepted:
            yield from _nested(ctx, resource, creation.base, attr, sub, sent)


def _nested(
    ctx: Context, resource: Resource, base: dict, attr: str, schema: dict, sent: Any
) -> Iterator[Finding]:
    """One level in: the optional properties the generated value left out."""
    one = sent[0] if isinstance(sent, list) and sent else sent
    if not isinstance(one, dict):
        return
    spec = ctx.spec
    resolved = spec.resolve(schema)
    item = resolved.get("items", {}) if resolved.get("type") == "array" else schema
    if values(ctx).is_reference((item.get("$ref") or "").rsplit("/", 1)[-1] or None):
        return  # a reference: its fields are the target's, not ours to vary
    path = resource.collection
    for name, sub in spec.properties(item).items():
        if name in one or name.startswith("@") or name == "href":
            continue
        label = f"{attr}.{name}"
        if name in SERVER_MANAGED:  # never sent as an extra (values.py)
            yield ctx.finding("POST", path, "unprobed", f"{label} server-managed")
            continue
        if is_id_string(name):  # a reference by id: never made up
            yield ctx.finding("POST", path, "unprobed", f"{label} no-fixture")
            continue
        if name.endswith("Relationship") and not values(ctx).is_reference(_item_name(spec, sub)):
            # names another part of the same body (an order item's sibling)
            yield ctx.finding("POST", path, "unprobed", f"{label} sibling-reference")
            continue
        try:
            with values(ctx).scope(resource.schema):
                value = values(ctx).value(sub, name)
        except Unbuildable as exc:
            yield ctx.finding("POST", path, "unprobed", f"{label} {str(exc).split()[0]}")
            continue
        nested = {**one, name: value}
        yield from probe(
            ctx, resource, base, attr, [nested] if isinstance(sent, list) else nested, label
        )[0]


def _item_name(spec: Any, schema: dict[str, Any]) -> str | None:
    resolved = spec.resolve(schema)
    item = resolved.get("items", {}) if resolved.get("type") == "array" else schema
    return (item.get("$ref") or "").rsplit("/", 1)[-1] or None


def run_polymorphism(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if not resource.op("POST") or not resource.schema:
        return
    schema = create_schema(ctx, resource)
    if schema is None or "@baseType" not in ctx.spec.properties(schema):
        return
    creation, findings = prepare(ctx, resource, "polymorphism")
    yield from findings
    if creation is None or creation.id is None or not resource.op("GET", item=True):
        return
    yield from probe(ctx, resource, creation.base, "@baseType", resource.schema)[0]


def probe(
    ctx: Context, resource: Resource, base: dict, attr: str, sent: Any, label: str = ""
) -> tuple[list[Finding], bool]:
    """POST the base plus one attribute and read it back; (findings, accepted)."""
    path = resource.collection
    label = label or attr
    response, answer = post(ctx, resource, {**base, attr: sent})
    if response.status == 202:
        return [ctx.finding("POST", path, "unprobed", f"{label} async", response)], False
    if response.status == 409:
        return [ctx.finding("POST", path, "unprobed", f"{label} conflict", response)], False
    if 400 <= response.status < 500:
        if Values.made_up(attr, sent):
            unprobed = ctx.finding("POST", path, "unprobed", f"{label} made-up-value", response)
            return [unprobed], False
        return [ctx.finding("POST", path, "refused", label, response)], False
    if response.status >= 500:
        return [ctx.finding("POST", path, "server-error", label, response)], False
    created = _created_id(response, answer)
    if created is None:
        return [ctx.finding("POST", path, "unprobed", f"{label} no-id", response)], True
    read = ctx.client.get(item_path(resource, created))
    check_auth(read)
    body = read.json()
    if not read.ok or not isinstance(body, dict):
        return [ctx.finding("GET", resource.item, "unprobed", f"{label} read-failed", read)], True
    gap = diff(sent, body.get(attr), attr)
    if not gap:
        return [], True
    kind, where = gap
    finding = ctx.finding("POST", path, kind, where, read, sent=sent, returned=body.get(attr))
    return [finding], True


# -- comparison ----------------------------------------------------------------------------


def diff(sent: Any, got: Any, path: str) -> tuple[str, str] | None:
    """The first difference: ("dropped" | "rewritten", attribute path), or None."""
    if got is None:
        return ("dropped", path)
    if isinstance(sent, dict):
        if not isinstance(got, dict):
            return ("rewritten", path)
        if "id" in sent and ("@referredType" in sent or "href" in sent):
            # a reference: its name and href are copies the server may refresh
            return None if str(got.get("id")) == str(sent["id"]) else ("rewritten", f"{path}.id")
        for key, value in sent.items():
            found = diff(value, got.get(key), f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(sent, list):
        if not isinstance(got, list):
            return ("rewritten", path)
        if not got:
            return ("dropped", f"{path}[]")
        for value in sent:
            results = [diff(value, g, f"{path}[]") for g in got]
            if all(results):
                # report the closest miss: the one that got furthest into the value
                return max(results, key=lambda r: len(r[1]))
        return None
    return None if _same_scalar(sent, got) else ("rewritten", path)


def _same_scalar(sent: Any, got: Any) -> bool:
    if isinstance(sent, bool) or isinstance(got, bool):
        return sent is got
    if isinstance(sent, int | float) and isinstance(got, int | float):
        return _decimal(sent) == _decimal(got)
    if isinstance(sent, str) and isinstance(got, str):
        if sent == got:
            return True
        a, b = _instant(sent), _instant(got)
        return a is not None and a == b
    return sent == got


def _decimal(value: int | float) -> Decimal | None:
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _instant(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


# -- cleanup -------------------------------------------------------------------------------


def cleanup(ctx: Context) -> Iterator[Finding]:
    """Delete what this run created, newest first, then once more for what was refused (a
    resource another one still referenced). One line per resource type that kept some."""
    created = list(reversed(ctx.created))
    ctx.created.clear()
    kept: list[tuple[Resource, str, Response | None]] = [
        (resource, rid, None) for resource, rid in created if not resource.op("DELETE", item=True)
    ]
    pending = [(resource, rid) for resource, rid in created if resource.op("DELETE", item=True)]
    refused: list[tuple[Resource, str, Response | None]] = []
    for _ in range(2):
        refused = []
        for resource, rid in pending:
            response = ctx.client.request("DELETE", item_path(resource, rid))
            if not response.ok and response.status != 404:
                refused.append((resource, rid, response))
        pending = [(resource, rid) for resource, rid, _ in refused]
        if not pending:
            break
    by_type: dict[tuple[str, bool], list[tuple[Resource, str, Response | None]]] = {}
    for resource, rid, response in kept + refused:
        by_type.setdefault((resource.collection, response is None), []).append(
            (resource, rid, response)
        )
    for (_, no_delete), entries in by_type.items():
        resource, _, response = entries[0]
        yield ctx.finding(
            "DELETE",
            resource.item or resource.collection,
            "cleanup-failed",
            "no-delete-operation" if no_delete else "delete-refused",
            response,
            ids=[rid for _, rid, _ in entries],
        )
