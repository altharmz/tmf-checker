"""`lists`: the collection GET and the item GET of what it lists.

- The list answers 200 with a JSON array whose items validate against the resource schema.
- The first listed items read back by id with 200, and validate.
- `X-Result-Count` and `X-Total-Count`, when present, agree with the answer. Their absence
  is not reported: the specs declare them without `required` (docs/spec-quirks.md #14).
- A listed item's `href` is an http(s) URL whose path is the item's path (TMF630: the
  hyperlink to the resource). Only the path is compared: a proxy may change the host.
- `limit=1` returns at most one item and `offset=1` another one (needs two items).
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import unquote, urlsplit

from tmf_checker.checks import Context, check_auth, item_path
from tmf_checker.client import Response
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource

READ_BACK = 3  # listed items read by id


def run(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if not resource.op("GET"):
        return
    listing = ctx.listing(resource)
    yield from listing.findings
    items = listing.items
    if items is None:
        return
    path = resource.collection
    if resource.schema:
        for item in items:
            yield from ctx.schema_findings("GET", path, resource.schema, item, listing.response)
    yield from _counts(ctx, path, listing.response, len(items))
    if resource.op("GET", item=True):
        yield from _read_back(ctx, resource, items)
    yield from _paging(ctx, resource, items)


def _counts(ctx: Context, path: str, response: Response, returned: int) -> Iterator[Finding]:
    def header(name: str) -> int | None | str:
        raw = response.headers.get(name.lower())
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return "not-an-integer"

    result, total = header("X-Result-Count"), header("X-Total-Count")
    if result is not None and result != returned:
        yield ctx.finding(
            "GET", path, "count-header", "X-Result-Count", response, returned=returned
        )
    if total is not None and (not isinstance(total, int) or total < returned):
        yield ctx.finding("GET", path, "count-header", "X-Total-Count", response, returned=returned)


def _read_back(ctx: Context, resource: Resource, items: list[dict]) -> Iterator[Finding]:
    for item in [i for i in items if "id" in i][:READ_BACK]:
        yield from _href(ctx, resource, item)
        response = ctx.client.get(item_path(resource, item["id"]))
        check_auth(response)
        if not response.ok:
            yield ctx.finding("GET", resource.item, "error-status", "listed-id", response)
            continue
        if resource.schema:
            yield from ctx.schema_findings(
                "GET", resource.item, resource.schema, response.json(), response
            )


def _href(ctx: Context, resource: Resource, item: dict) -> Iterator[Finding]:
    href = item.get("href")
    if not isinstance(href, str):
        return
    url = urlsplit(ctx.client.resolve(href))
    path = resource.collection
    if url.scheme not in ("http", "https"):
        yield ctx.finding("GET", path, "href", "not-a-url", href=href, id=item["id"])
    elif not unquote(url.path).rstrip("/").endswith(unquote(item_path(resource, item["id"]))):
        yield ctx.finding("GET", path, "href", "not-the-item", href=href, id=item["id"])


def _paging(ctx: Context, resource: Resource, items: list[dict]) -> Iterator[Finding]:
    path = resource.collection
    if len(items) < 2:
        yield ctx.finding("GET", path, "skipped", "paging fewer-than-2-items")
        return
    first = ctx.client.get(path, limit=1)
    check_auth(first)
    page = first.json()
    if not first.ok:
        yield ctx.finding("GET", path, "param-refused", "limit", first)
        return
    if not isinstance(page, list) or len(page) > 1:
        yield ctx.finding("GET", path, "paging-ignored", "limit", first)
        return
    second = ctx.client.get(path, offset=1, limit=1)
    check_auth(second)
    if not second.ok:
        yield ctx.finding("GET", path, "param-refused", "offset", second)
        return
    first_id, second_id = _first_id(page), _first_id(second.json())
    if first_id is not None and first_id == second_id:
        yield ctx.finding("GET", path, "paging-ignored", "offset", second)


def _first_id(page: object) -> object:
    if isinstance(page, list) and page and isinstance(page[0], dict):
        return page[0].get("id")
    return None
