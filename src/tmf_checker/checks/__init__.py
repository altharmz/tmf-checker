"""Check families. Each module has `run(ctx, resource) -> Iterable[Finding]`.

`Context` holds what checks share: the spec, the client, the run id, a cache of list
answers, and the resources this run created (deleted at the end by `cleanup`).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from tmf_checker.client import Client, Response
from tmf_checker.findings import Finding
from tmf_checker.spec import Resource, Spec
from tmf_checker.validate import issues

# Statuses that mean "this operation is not there", not "it answered wrongly".
NOT_IMPLEMENTED = (404, 405, 501)
# Attributes a fields= projection may return besides the selection (TMF630).
ALWAYS_ALLOWED = {"id", "href"}


class Unauthorized(Exception):  # noqa: N818
    """The API answered 401: the run cannot go on without credentials."""


class Forbidden(Exception):  # noqa: N818
    """The API answered 403: this check cannot judge this resource. The runner turns it
    into a `skipped <check> forbidden` line, never a gap."""

    def __init__(self, response: Response) -> None:
        super().__init__(f"{response.method} {response.url} answered 403")
        self.response = response


@dataclass
class Listing:
    response: Response
    items: list[dict[str, Any]] | None  # None when the list could not be read
    findings: list[Finding]


@dataclass
class Context:
    api: str
    spec: Spec
    client: Client
    run_id: str
    allow_writes: bool = False
    allow_orders: bool = False
    listings: dict[str, Listing] = field(default_factory=dict)
    created: list[tuple[Resource, str]] = field(default_factory=list)
    fixtures: dict[str, dict[str, Any]] = field(default_factory=dict)  # class -> resource
    preferred: dict[str, Any] = field(default_factory=dict)  # property name -> value
    creations: dict[str, Any] = field(default_factory=dict)  # collection -> create.Creation
    building: set[str] = field(default_factory=set)  # fixtures being created (cycle guard)
    # (collection, attribute path) a write check already reported: missing skips them
    explained: set[tuple[str, str]] = field(default_factory=set)

    def finding(
        self,
        method: str,
        path: str,
        kind: str,
        detail: str,
        response: Response | None = None,
        **extra: Any,
    ) -> Finding:
        evidence = response.evidence() if response is not None else {}
        evidence.update(extra)
        if kind in ("unprobed", "refused", "dropped", "server-error", "read-only"):
            # keyed by collection: a PATCH finding is on the item path
            self.explained.add((path.split("/{", 1)[0], detail.split()[0]))
        return Finding(self.api, method, path, kind, detail, evidence or None)

    def schema_findings(
        self, method: str, path: str, schema: str, body: Any, response: Response, **kw: Any
    ) -> Iterator[Finding]:
        """One `invalid` (or `null-value`) finding per (attribute path, keyword)."""
        for issue in issues(self.spec, schema, body, **kw):
            if issue.keyword == "null":
                yield self.finding(method, path, "null-value", issue.path, response)
            else:
                yield self.finding(
                    method,
                    path,
                    "invalid",
                    f"{issue.path} {issue.keyword}",
                    response,
                    message=issue.message,
                )

    def listing(self, resource: Resource) -> Listing:
        """The collection GET, once per run; `findings` says why `items` may be None."""
        if resource.collection in self.listings:
            return self.listings[resource.collection]
        response = self.client.get(resource.collection)
        check_auth(response)
        body = response.json()
        findings: list[Finding] = []
        items = None
        path = resource.collection
        if response.status in NOT_IMPLEMENTED:
            findings.append(
                self.finding("GET", path, "unimplemented", str(response.status), response)
            )
        elif not response.ok:
            findings.append(self.finding("GET", path, "error-status", "list", response))
        elif not isinstance(body, list):
            findings.append(self.finding("GET", path, "list-body", "not-an-array", response))
        else:
            items = [item for item in body if isinstance(item, dict)]
        listing = Listing(response, items, findings)
        self.listings[resource.collection] = listing
        return listing


def check_auth(response: Response) -> None:
    """401 stops the run; 403 stops this check on this resource (see `Forbidden`)."""
    if response.status == 403:
        raise Forbidden(response)
    if response.status == 401:
        raise Unauthorized(
            f"{response.method} {response.url} answered 401: pass credentials with --header"
        )


def item_path(resource: Resource, resource_id: str) -> str:
    """The item URL path for an id (the spec's `{id}` placeholder filled in)."""
    assert resource.item is not None
    prefix = resource.item.split("{", 1)[0]
    return prefix + quote(str(resource_id), safe="")
