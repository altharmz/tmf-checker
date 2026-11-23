"""`profile` (with `--profile`): the profile's mandatory attributes are in every resource
the server returns.

Reads the listed items, up to `SAMPLE` of them by id (not leftovers of earlier runs, named
`tmf-checker-...`), and every resource this run created (it runs after the write checks).
One `profile-missing <attr>` line per attribute any of them lacks (absent or null), on the
collection path whichever read showed it; the evidence names the resource. `a.b` is
judged in each present value of `a` only.

A resource this run created holds what the run sent, so on it an attribute the client
could have sent and the run did not is not judged, nor `a.b` in a value the run built
(the same rule as `missing`). It still must have what the run sent and what only the
server sets (`id`, `href`). An attribute the client must provide belongs in the profile's
`create`, which the run then sends.

Unlike `missing`, this is not a claim about the data: the profile makes the attribute
mandatory, so a resource without it is a gap whatever the data. The rules are in
`tmf_checker.profile`.
"""

from __future__ import annotations

from collections.abc import Iterator

from tmf_checker.checks import Context, check_auth, item_path
from tmf_checker.client import Response
from tmf_checker.findings import Finding
from tmf_checker.profile import lacking
from tmf_checker.spec import Resource

SAMPLE = 20


def run(ctx: Context, resource: Resource) -> Iterator[Finding]:
    rules = ctx.profile.get(resource) if ctx.profile else None
    if rules is None or not rules.attributes:
        return
    # one line per attribute, on the collection path, whichever read showed it
    path = resource.collection
    reported: set[str] = set()
    judged = 0

    op = resource.op("POST")
    schema = ctx.spec.request_schema(op) if op else None
    settable = set(ctx.spec.properties(schema)) if schema else set()
    created = list(
        dict.fromkeys(rid for res, rid in ctx.created if res.collection == resource.collection)
    )

    def judged_here(rid: object) -> tuple[str, ...]:
        if rid not in created:
            return rules.attributes
        sent = ctx.sent.get((resource.collection, str(rid)), set())
        out = []
        for name in rules.attributes:
            top, _, sub = name.partition(".")
            if (sub and top in sent) or (top in settable and top not in sent):
                continue  # the run's own body: it lacks what the run left out
            out.append(name)
        return tuple(out)

    def judge(body: object, response: Response, rid: object) -> Iterator[Finding]:
        nonlocal judged
        if not isinstance(body, dict):
            return
        judged += 1
        for name in lacking(body, judged_here(rid)):
            if name not in reported:
                reported.add(name)
                yield ctx.finding("GET", path, "profile-missing", name, response, id=rid)

    ids: list[str] = []
    if resource.op("GET"):
        listing = ctx.listing(resource)
        yield from listing.findings
        for item in listing.items or ():
            if str(item.get("name", "")).startswith("tmf-checker-"):
                continue  # a leftover of an earlier run: our made-up body
            yield from judge(item, listing.response, item.get("id"))
            if "id" in item:
                ids.append(item["id"])
    ids = ids[:SAMPLE]
    ids += list(created)
    if resource.op("GET", item=True):
        for rid in dict.fromkeys(ids):
            response = ctx.client.get(item_path(resource, rid))
            check_auth(response)
            if response.ok:
                yield from judge(response.json(), response, rid)
    if not judged:
        yield ctx.finding("GET", path, "skipped", "profile no-items")
