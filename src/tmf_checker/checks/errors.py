"""`errors`: error answers carry the right status and the spec's `Error` body (TMF630).

- GET of an unknown id: 404 and an `Error`. The id is a real one with a suffix, so a
  server that validates id syntax (URNs, UUIDs) still sees a well-formed id.
- POST of malformed JSON (writes only, as it is a POST): 400 and an `Error`.
"""

from __future__ import annotations

from collections.abc import Iterator

from tmf_checker.checks import NOT_IMPLEMENTED, Context, check_auth, item_path
from tmf_checker.client import Response
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource
from tmf_checker.validate import errors

MALFORMED = b'{"name": "tmf-checker", '


def run(ctx: Context, resource: Resource) -> Iterator[Finding]:
    if resource.op("GET") and ctx.listing(resource).response.status in NOT_IMPLEMENTED:
        return  # `lists` reports it as unimplemented; its error answers follow from that
    if resource.op("GET", item=True):
        yield from _unknown_id(ctx, resource)
    if ctx.allow_writes and resource.op("POST"):
        yield from _malformed(ctx, resource)


def _unknown_id(ctx: Context, resource: Resource) -> Iterator[Finding]:
    listing = ctx.listing(resource)
    known = [str(i["id"]) for i in listing.items or () if "id" in i]
    unknown = (known[0] if known else "tmf-checker") + f"-unknown-{ctx.run_id}"
    response = ctx.client.get(item_path(resource, unknown))
    check_auth(response)
    yield from _expect(ctx, "GET", resource.item, response, 404, "unknown-id")


def _malformed(ctx: Context, resource: Resource) -> Iterator[Finding]:
    response = ctx.client.request("POST", resource.collection, raw_body=MALFORMED)
    check_auth(response)
    yield from _expect(ctx, "POST", resource.collection, response, 400, "malformed-json")


def _expect(
    ctx: Context, method: str, path: str, response: Response, status: int, probe: str
) -> Iterator[Finding]:
    if response.status != status:
        yield ctx.finding(method, path, "error-status", probe, response, expected=status)
    if response.ok:
        return
    body = response.json()
    problems = ["the body is not JSON"] if body is None else errors(ctx.spec, "Error", body)
    if problems:
        yield ctx.finding(method, path, "error-body", probe, response, problems=problems)
