"""Findings: one gap per line, sorted and stable, so a report can be locked as a baseline.

A line is `<API> <METHOD> <spec path> <kind> <detail>`. The detail holds only stable facts
(attribute paths, schema keywords, the probe used), never ids, timestamps or counts; those
go in the evidence, which the JSON report carries and the line format does not.

A baseline is a text file of lines. `#` comments and blank lines are kept on update and
ignored on comparison, so each accepted gap can carry its reason next to it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# kind -> what it means. docs/checks.md is the long form.
KINDS: dict[str, str] = {
    "unimplemented": "an operation the spec defines answers 404, 405 or 501",
    "invalid": "a response body does not conform to its schema (detail: path and keyword)",
    "null-value": "an attribute is null where the schema does not allow it",
    "error-status": "an error case answers with the wrong status",
    "error-body": "an error answer is not the spec's Error resource",
    "list-body": "a list answer is not a JSON array",
    "count-header": "X-Result-Count or X-Total-Count disagrees with the answer",
    "paging-ignored": "limit or offset has no effect",
    "fields-ignored": "a fields= projection returns attributes that were not selected",
    "fields-dropped": "a fields= projection omits the attribute that was selected",
    "filter-refused": "an equality filter ?attr=value on the list is refused (TMF630)",
    "filter-ignored": "an equality filter returns resources with other values (TMF630)",
    "filter-empty": "an equality filter on a value a listed resource has returns nothing",
    "missing": "an attribute never comes back in any returned resource ('a.b': one level in)",
    "create-status": "a create with only the spec's required attributes is not a 201",
    "href": "a resource's href is not a URL of that resource (TMF630)",
    "location": "a 201 has no Location header, or it is not the new resource's href",
    "param-refused": "a query parameter the spec declares is refused (4xx)",
    "server-error": "a request the spec defines answers 5xx (detail: the probe)",
    "requires": "the server refuses a create without an attribute the spec leaves optional",
    "read-only": "a PATCH of an attribute the PATCH schema defines is refused (4xx)",
    "content-type": "a PATCH with a content type the spec declares is refused",
    "refused": "a create with one more attribute the spec defines is refused (4xx)",
    "dropped": "an attribute accepted on create does not come back on read",
    "rewritten": "an attribute accepted on create comes back with another value",
    "unprobed": "an attribute could not be probed (detail: attribute and reason)",
    "cleanup-failed": "a resource this run created could not be deleted",
    "skipped": "a check could not run here (detail: check and reason)",
}


@dataclass(frozen=True, order=True)
class Finding:
    api: str
    method: str
    path: str
    kind: str
    detail: str
    evidence: dict[str, Any] | None = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown finding kind {self.kind!r}")
        if not self.detail.strip() or self.detail != " ".join(self.detail.split()):
            raise ValueError(f"detail must be one line of single-spaced words: {self.detail!r}")

    @property
    def line(self) -> str:
        return f"{self.api} {self.method} {self.path} {self.kind} {self.detail}"

    @property
    def is_skip(self) -> bool:
        return self.kind in ("skipped", "unprobed")


def unique_sorted(findings: Iterable[Finding]) -> list[Finding]:
    """One finding per line, in line order; the first evidence seen wins."""
    seen: dict[str, Finding] = {}
    for f in findings:
        seen.setdefault(f.line, f)
    return [seen[line] for line in sorted(seen)]


# -- baselines ----------------------------------------------------------------------------


def _is_gap(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def read_baseline(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if _is_gap(line)}


@dataclass(frozen=True)
class Comparison:
    new: list[str]  # found now, not in the baseline: fails CI
    fixed: list[str]  # in the baseline, not found now: delete the line


def compare(current: Iterable[str], baseline: set[str]) -> Comparison:
    current = set(current)
    return Comparison(new=sorted(current - baseline), fixed=sorted(baseline - current))


def updated_baseline(text: str, current: Iterable[str]) -> str:
    """The baseline file with fixed lines removed and new lines inserted in sorted position.
    Comments and blank lines stay; a comment right above a gap line stays attached to it."""
    current = set(current)
    lines = text.splitlines()
    kept = [line for line in lines if not _is_gap(line) or line.strip() in current]
    present = {line.strip() for line in kept if _is_gap(line)}
    out = list(kept)
    for new in sorted(current - present):
        # before the first gap line that sorts after it, else at the end
        at = next(
            (i for i, line in enumerate(out) if _is_gap(line) and line.strip() > new), len(out)
        )
        while at < len(out) and at > 0 and out[at - 1].lstrip().startswith("#"):
            at -= 1  # above the comment that explains the next gap
        out.insert(at, new)
    return "\n".join(out) + "\n"
