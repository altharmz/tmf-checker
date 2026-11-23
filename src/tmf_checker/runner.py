"""Run the selected checks over every resource of a spec, then clean up."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace

from tmf_checker.checks import (
    Context,
    Forbidden,
    create,
    errors,
    fields,
    filters,
    lists,
    missing,
    patch,
    profile,
)
from tmf_checker.findings import Finding, unique_sorted
from tmf_checker.spec import Resource

CheckFn = Callable[[Context, Resource], Iterable[Finding]]

# name -> (function, writes)
CHECKS: dict[str, tuple[CheckFn, bool]] = {
    "errors": (errors.run, False),
    "lists": (lists.run, False),
    "fields": (fields.run, False),
    "filters": (filters.run, False),
    "missing": (missing.run, False),
    "profile": (profile.run, False),
    "location": (create.run_location, True),
    "requires": (create.run_requires, True),
    "roundtrip": (create.run_roundtrip, True),
    "polymorphism": (create.run_polymorphism, True),
    "patch-formats": (patch.run_formats, True),
    "patch": (patch.run_patch, True),
}
DEFAULT_READ = ("errors", "lists", "fields", "filters")  # `missing` is opt-in: see its docstring
DEFAULT_WRITE = ("location", "requires", "roundtrip", "polymorphism", "patch-formats", "patch")


# they read what the write checks created, so they run after them
READ_LAST = ("missing", "profile")


def default_checks(allow_writes: bool, with_profile: bool = False) -> list[str]:
    return [
        *DEFAULT_READ,
        *(DEFAULT_WRITE if allow_writes else ()),
        *(("profile",) if with_profile else ()),
    ]


def run(ctx: Context, checks: Iterable[str], resources: Iterable[str] = ()) -> list[Finding]:
    """All findings, sorted and unique. `resources` limits the run to these collections
    (names without the slash). Created resources are deleted even when a check raises."""
    checks = list(checks)
    for name in checks:
        if name not in CHECKS:
            raise ValueError(f"unknown check {name!r} (known: {', '.join(CHECKS)})")
        if CHECKS[name][1] and not ctx.allow_writes:
            raise ValueError(f"check {name!r} writes to the API: pass --allow-writes")
        if name == "profile" and ctx.profile is None:
            raise ValueError("check 'profile' needs --profile")
    checks.sort(key=lambda name: name in READ_LAST)
    wanted = {r.strip("/") for r in resources}
    found: list[Finding] = []
    try:
        for resource in ctx.spec.resources():
            if wanted and resource.collection.strip("/") not in wanted:
                continue
            for name in checks:
                try:
                    found.extend(list(CHECKS[name][0](ctx, resource)))
                except Forbidden as exc:
                    method = exc.response.method
                    found.append(
                        ctx.finding(
                            method,
                            resource.collection,
                            "skipped",
                            f"{name} forbidden",
                            exc.response,
                        )
                    )
    finally:
        found.extend(create.cleanup(ctx))
    return unique_sorted(_optional_operations(ctx, found))


def _optional_operations(ctx: Context, found: list[Finding]) -> Iterator[Finding]:
    """An operation the profile does not make mandatory may be unimplemented."""
    for f in found:
        if (
            f.kind == "unimplemented"
            and ctx.profile
            and ctx.profile.optional_operation(f.method, f.path)
        ):
            yield replace(f, kind="skipped", detail="profile optional-operation")
        else:
            yield f
