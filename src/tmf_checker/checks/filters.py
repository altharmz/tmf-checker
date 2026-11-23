"""`filters`: an equality filter `?<attr>=<value>` on the list returns only the resources
whose attribute has that value (TMF630 basic filtering).

The attribute is a top-level string the resource schema defines (no date-times, which a
server may rightly normalise), and two listed items must have different values for it,
so a server that ignores the filter is seen: the unfiltered page holds the other value.
The value is one a listed item has, so an empty answer is the server's doing. Values with
characters TMF630 gives a meaning (`,` lists alternatives, `.` and operators are advanced
filtering) are never used. Only the equality filter is checked: comma lists, operators
and `sort` are left out until their rules are confirmed from TMF630 itself.

Not judged, to keep false positives out: items without the attribute (a server may omit
an empty one), and values that differ only in case.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from tmf_checker.checks import ALWAYS_ALLOWED, Context, check_auth
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource

PREFERRED = ("lifecycleStatus", "status", "state", "name")
SAFE_VALUE = re.compile(r"[A-Za-z0-9 _:-]{1,100}")
DATE_LIKE = re.compile(r"\d{4}-\d{2}-\d{2}")


def run(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if not resource.op("GET"):
        return
    listing = ctx.listing(resource)
    yield from listing.findings
    if listing.items is None:
        return
    path = resource.collection
    picked = pick(ctx, resource, listing.items)
    if picked is None:
        yield ctx.finding("GET", path, "skipped", "filters no-distinct-values")
        return
    attr, value = picked
    response = ctx.client.get(path, **{attr: value})
    check_auth(response)
    if not response.ok:
        yield ctx.finding("GET", path, "filter-refused", "equality", response, attribute=attr)
        return
    body = response.json()
    if not isinstance(body, list):
        yield ctx.finding("GET", path, "list-body", "not-an-array", response)
        return
    returned = [i for i in body if isinstance(i, dict)]
    if not returned:
        yield ctx.finding(
            "GET", path, "filter-empty", "equality", response, attribute=attr, value=value
        )
        return
    others = sorted(
        {
            str(i[attr])
            for i in returned
            if attr in i and str(i[attr]).casefold() != value.casefold()
        }
    )
    if others:
        yield ctx.finding(
            "GET",
            path,
            "filter-ignored",
            "equality",
            response,
            attribute=attr,
            value=value,
            other_values=others[:5],
        )


def pick(ctx: Context, resource: Resource, items: list[dict[str, Any]]) -> tuple[str, str] | None:
    """An (attribute, value) pair to filter on, or None when no attribute qualifies."""
    if not resource.schema:
        return None
    spec = ctx.spec
    props = spec.properties({"$ref": f"{spec.schemas_pointer}/{resource.schema}"})
    candidates = []
    for name, schema in props.items():
        if name in ALWAYS_ALLOWED or name.startswith("@"):
            continue
        schema = spec.resolve(schema)
        if schema.get("type") != "string" or schema.get("format") in ("date-time", "date"):
            continue
        values = [i[name] for i in items if _usable(i.get(name))]
        if len({v.casefold() for v in values}) >= 2:
            candidates.append((name, values[0]))
    candidates.sort(key=lambda c: PREFERRED.index(c[0]) if c[0] in PREFERRED else len(PREFERRED))
    return candidates[0] if candidates else None


def _usable(value: Any) -> bool:
    return (
        isinstance(value, str)
        and SAFE_VALUE.fullmatch(value) is not None
        and value.strip() == value
        and not DATE_LIKE.match(value)
    )
