"""`missing` (opt-in): attributes the resource schema defines that no returned resource has.

Reads up to `SAMPLE` listed resources by id (not leftovers of earlier runs, named
`tmf-checker-...`), plus every resource this run created (it runs
after the write checks, so what `roundtrip` sent is there to be read), and reports each
top-level attribute none of them has, and, one level into the attributes they do have,
each nested one (`a.b`), the form a nested gap list takes. `@`-attributes are not
reported.

It does not look into references or `...RefOrValue` unions (a reference's optional
fields are not the server's to fill), and skips what `roundtrip` already reported
(`unprobed`, `refused`, `dropped`, `server-error`): that absence is explained there.

This is a claim about the data as much as about the server: a catalog that never set an
attribute looks the same as a server that cannot return it. So it runs only when asked
for (`--checks missing`), on data that is known to be complete, and `roundtrip` (which
sends the attribute first) is the stronger evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tmf_checker.checks import Context, check_auth, item_path
from tmf_checker.checks.create import values
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource

SAMPLE = 20


def run(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if not (resource.op("GET", item=True) and resource.schema):
        return
    listing = ctx.listing(resource)
    yield from listing.findings
    # leftovers of earlier tmf-checker runs (a resource that could not be deleted) carry
    # our made-up values: what they lack says nothing about the server
    listed = [
        i["id"]
        for i in listing.items or ()
        if "id" in i and not str(i.get("name", "")).startswith("tmf-checker-")
    ]
    ids = listed[:SAMPLE]
    ids += [rid for res, rid in ctx.created if res.collection == resource.collection]
    ids = list(dict.fromkeys(ids))
    if not ids:
        yield ctx.finding("GET", resource.item, "skipped", "missing no-items")
        return
    bodies = []
    for resource_id in ids:
        response = ctx.client.get(item_path(resource, resource_id))
        check_auth(response)
        if response.ok and isinstance(response.json(), dict):
            bodies.append(response.json())
    if not bodies:
        return
    spec = ctx.spec
    props = spec.properties({"$ref": f"{spec.schemas_pointer}/{resource.schema}"})
    for name, schema in props.items():
        if name.startswith("@"):
            continue
        returned = [b[name] for b in bodies if b.get(name) is not None]
        if not returned:
            if (resource.collection, name) not in ctx.explained:
                yield ctx.finding("GET", resource.item, "missing", name, sampled=len(bodies))
            continue
        # present (perhaps set by the server): look one level in even if it was refused
        nested = _objects(returned)
        if not nested:
            continue
        for sub in _nested_props(ctx, schema):
            if sub.startswith("@") or (resource.collection, f"{name}.{sub}") in ctx.explained:
                continue
            if all(o.get(sub) is None for o in nested):
                yield ctx.finding(
                    "GET", resource.item, "missing", f"{name}.{sub}", sampled=len(nested)
                )


def _objects(values: list[Any]) -> list[dict[str, Any]]:
    out = []
    for value in values:
        out.extend(
            v for v in (value if isinstance(value, list) else [value]) if isinstance(v, dict)
        )
    return out


def _nested_props(ctx: Context, schema: dict[str, Any]) -> list[str]:
    """The properties one level in, for a value object; none for a reference or a union."""
    resolved = ctx.spec.resolve(schema)
    if resolved.get("type") == "array":
        schema = resolved.get("items", {})
    name = (schema.get("$ref") or "").rsplit("/", 1)[-1] or None
    target = ctx.spec.resolve(schema)
    if target.get("oneOf") or target.get("anyOf") or values(ctx).is_reference(name):
        return []
    return list(ctx.spec.properties(schema))
