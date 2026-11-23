"""`fields`: a `fields=<attr>` projection returns the selected attribute and nothing else
but `id`, `href` and `@`-attributes (TMF630), on the list and by id.

The attribute is one the first listed item has, so its absence from the projection is the
server's doing, not the data's.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tmf_checker.checks import ALWAYS_ALLOWED, Context, check_auth, item_path
from tmf_checker.client import Response
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource

PREFERRED = ("name", "description", "lifecycleStatus", "status", "state")


def run(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if not resource.op("GET"):
        return
    listing = ctx.listing(resource)
    yield from listing.findings
    if listing.items is None:
        return
    item = next((i for i in listing.items if "id" in i), None)
    attr = item and _pick(item)
    if not attr:
        yield ctx.finding("GET", resource.collection, "skipped", "fields no-items")
        return
    response = ctx.client.get(resource.collection, fields=attr)
    yield from _judge(ctx, "GET", resource.collection, "list", response, attr, many=True)
    if resource.op("GET", item=True):
        response = ctx.client.get(item_path(resource, item["id"]), fields=attr)
        yield from _judge(ctx, "GET", resource.item, "by-id", response, attr, many=False)


def _pick(item: dict[str, Any]) -> str | None:
    candidates = [k for k in item if k not in ALWAYS_ALLOWED and not k.startswith("@")]
    return next((k for k in PREFERRED if k in candidates), candidates[0] if candidates else None)


def _judge(
    ctx: Context, method: str, path: str, where: str, response: Response, attr: str, *, many: bool
) -> Iterator[Finding]:
    check_auth(response)
    if not response.ok:
        yield ctx.finding(method, path, "param-refused", f"fields {where}", response)
        return
    body = response.json()
    objects = body if many and isinstance(body, list) else [body]
    objects = [o for o in objects if isinstance(o, dict)]
    if not objects:
        return
    extra = sorted(
        {
            k
            for o in objects
            for k in o
            if k != attr and k not in ALWAYS_ALLOWED and not k.startswith("@")
        }
    )
    if extra:
        yield ctx.finding(
            method, path, "fields-ignored", where, response, selected=attr, extra=extra
        )
    if not many and attr not in objects[0]:
        yield ctx.finding(method, path, "fields-dropped", where, response, selected=attr)
