"""A user-supplied conformance profile (`--profile`): what an implementation must support
beyond the OAS.

TM Forum's conformance profiles are member-only and cannot be bundled, and they, not the
OAS, are the reference when the two disagree (docs/spec-quirks.md #8). So the user writes
the part they need as YAML, keyed by collection:

    productOffering:
      operations: [list, retrieve, create, patch, delete]   # mandatory operations
      attributes: [id, href, name, lifecycleStatus, validFor.startDateTime]
      create: [name, lifecycleStatus]

- `operations`: the mandatory ones, from `list`, `retrieve`, `create`, `patch`, `delete`.
  An operation the spec defines and the list leaves out may be unimplemented: its
  `unimplemented` line becomes `skipped profile optional-operation`.
- `attributes`: mandatory in every resource the server returns. `a.b`: in every value of
  `a` that is present (each element of an array). The `profile` check reports each one a
  returned resource lacks (absent or null) as `profile-missing`.
- `create`: attributes a create must carry, so a server may require them. They join the
  spec's minimal body, so `requires` never reports them.

Every key is optional; a collection the profile leaves out is checked against the OAS
alone. Names are checked against the spec when the profile loads: a typo is an error, not
a silent no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tmf_checker.spec import Resource, Spec

# profile name -> (method, on the item path)
OPERATIONS: dict[str, tuple[str, bool]] = {
    "list": ("GET", False),
    "retrieve": ("GET", True),
    "create": ("POST", False),
    "patch": ("PATCH", True),
    "delete": ("DELETE", True),
}
KEYS = ("operations", "attributes", "create")


@dataclass(frozen=True)
class Rules:
    """The profile of one collection. `operations` is None when the profile does not
    say, which is not the same as an empty list."""

    operations: frozenset[tuple[str, str]] | None = None  # (METHOD, spec path)
    attributes: tuple[str, ...] = ()
    create: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    rules: dict[str, Rules] = field(default_factory=dict)  # collection path -> rules

    def get(self, resource: Resource) -> Rules | None:
        return self.rules.get(resource.collection)

    def optional_operation(self, method: str, path: str) -> bool:
        """True when the profile lists the mandatory operations of this path's collection
        and this one is not among them."""
        rules = self.rules.get("/" + path.strip("/").split("/", 1)[0])
        return (
            rules is not None
            and rules.operations is not None
            and ((method, path) not in rules.operations)
        )


def load(path: str | Path, spec: Spec) -> Profile:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return parse(data, spec, str(path))


def parse(data: Any, spec: Spec, source: str = "profile") -> Profile:
    if not isinstance(data, dict):
        raise ValueError(f"{source}: a profile maps collection names to rules")
    resources = {r.collection.strip("/"): r for r in spec.resources()}
    rules: dict[str, Rules] = {}
    for name, body in data.items():
        where = f"{source}: {name}"
        resource = resources.get(str(name).strip("/"))
        if resource is None:
            raise ValueError(f"{where}: no such collection in {spec.title} {spec.version}")
        body = body or {}
        if not isinstance(body, dict) or set(body) - set(KEYS):
            raise ValueError(f"{where}: rules are a mapping with keys {', '.join(KEYS)}")
        rules[resource.collection] = Rules(
            _operations(body.get("operations"), resource, where),
            _attributes(body.get("attributes"), resource, spec, where),
            _create(body.get("create"), resource, spec, where),
        )
    return Profile(rules)


def _names(raw: Any, where: str, key: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(n, str) and n for n in raw):
        raise ValueError(f"{where}: {key} must be a list of names")
    return raw


def _operations(raw: Any, resource: Resource, where: str) -> frozenset | None:
    if raw is None:
        return None
    ops = set()
    for name in _names(raw, where, "operations"):
        if name not in OPERATIONS:
            raise ValueError(f"{where}: unknown operation {name!r} (from: {', '.join(OPERATIONS)})")
        method, item = OPERATIONS[name]
        op = resource.op(method, item=item)
        if op is None:
            raise ValueError(f"{where}: the spec defines no {name} operation here")
        ops.add((op.method, op.path))
    return frozenset(ops)


def _attributes(raw: Any, resource: Resource, spec: Spec, where: str) -> tuple[str, ...]:
    names = _names(raw, where, "attributes")
    if names and not resource.schema:
        raise ValueError(f"{where}: the spec gives no resource schema to check attributes in")
    props = spec.properties({"$ref": f"{spec.schemas_pointer}/{resource.schema}"}) if names else {}
    for name in names:
        top, _, sub = name.partition(".")
        if top not in props:
            raise ValueError(f"{where}: {resource.schema} has no attribute {top!r}")
        if "." in sub:
            raise ValueError(f"{where}: {name!r}: one level in at most (a.b)")
        if sub:
            inner = spec.resolve(props[top])
            if inner.get("type") == "array":
                inner = inner.get("items", {})
            known = spec.properties(inner)
            if known and sub not in known:  # a union may not list them: then trust the user
                raise ValueError(f"{where}: {top!r} has no attribute {sub!r}")
    return tuple(dict.fromkeys(names))


def _create(raw: Any, resource: Resource, spec: Spec, where: str) -> tuple[str, ...]:
    names = _names(raw, where, "create")
    if not names:
        return ()
    op = resource.op("POST")
    schema = spec.request_schema(op) if op else None
    if schema is None:
        raise ValueError(f"{where}: the spec defines no create body here")
    props = spec.properties(schema)
    for name in names:
        if name not in props:
            raise ValueError(f"{where}: the create body has no attribute {name!r}")
    return tuple(dict.fromkeys(names))


def lacking(body: dict[str, Any], attributes: tuple[str, ...]) -> list[str]:
    """The mandatory attributes a returned resource lacks (absent or null)."""
    out = []
    for name in attributes:
        top, _, sub = name.partition(".")
        value = body.get(top)
        if not sub:
            if value is None:
                out.append(name)
            continue
        values = value if isinstance(value, list) else [value] if value is not None else []
        if any(isinstance(v, dict) and v.get(sub) is None for v in values):
            out.append(name)
    return out
