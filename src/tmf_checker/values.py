"""Generate request values from a spec's schemas.

A value comes from, in order: the user's preferred value for that property name (the
`values:` section of `--fixtures`, for a server's own vocabulary such as `role: customer`;
`FinancialAccount.role: owner` applies only while a FinancialAccount is being built),
the property's `example` (scalars without a format only),
its first `enum` value (stripped: docs/spec-quirks.md #5), its `format`, the value the
spec's own examples use most for a string property of that name (`lifecycleStatus` is a
free string, but servers keep a vocabulary, and `Active` is what TMF620 v5 shows), its
`type`. `name` and `description` always carry our marker, so created data is findable.
Objects get their required properties, and nested objects also their optional scalar
ones, so a `validFor` carries both dates and a `Money` both unit and value. v5 objects
carry `@type`, the class name of their schema.

A reference is never made up, because a server that checks references rightly refuses a
fake one. A schema is a reference when it is a `...Ref` (or a v4 `...RefOrValue`), has
`@referredType`, or is a `Bundled...` with an `id`. It points at the resource of this API
whose class name it contains, or at a fixture class the user supplied (the longest match:
`ProductOfferingPriceRef` is a price, not an offering); `refs` returns that resource. A
union of references (`PartyRefOrPartyRoleRef`) takes the branch of its target. A nested
object includes its optional references when they can be built, and is `Unbuildable` when
it has references and none can (a related party without a party is not worth sending).
A reference without a target, and a plain `...Id` string (`parentId`), is `Unbuildable`
with a reason, and the caller skips with it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from tmf_checker.spec import Spec

SUFFIXES = ("_FVO", "_MVO", "_Create", "_Update")
PLACEHOLDER = "tmf-checker"  # a free string with no example, preferred value or enum
MAX_DEPTH = 4
REF_FIELDS = {"id", "href", "name", "@type", "@referredType"}
OWN_MARKER = {"name", "description"}
# Optional nested attributes a server usually sets: never sent as extras.
SERVER_MANAGED = {
    "state",
    "status",
    "lastUpdate",
    "creationDate",
    "completionDate",
    "orderDate",
    "statusChangeDate",
    "lastUpdateDate",
}


class Unbuildable(Exception):  # noqa: N818 - a reason, not an error
    """No value can be built; `str(exc)` is `<reason> <attribute>`."""


def class_name(schema_name: str) -> str:
    for suffix in SUFFIXES:
        if schema_name.endswith(suffix):
            return schema_name.removesuffix(suffix)
    return schema_name


def _ref_name(schema: dict[str, Any]) -> str | None:
    ref = schema.get("$ref", "")
    return ref.rsplit("/", 1)[-1] if ref.startswith("#/") else None


def is_id_string(name: str) -> bool:
    return name.endswith("Id") and name != "id"


def example_strings(spec: Spec) -> dict[str, str]:
    """Property name -> the string value the spec's examples use most for it (OAS 3
    `components.examples`; v4 specs have none)."""
    seen: dict[str, Counter] = defaultdict(Counter)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and not key.startswith(("$", "@")):
                    seen[key][value] += 1
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for example in spec.doc.get("components", {}).get("examples", {}).values():
        walk(example.get("value"))
    return {key: counts.most_common(1)[0][0] for key, counts in seen.items()}


class Values:
    def __init__(
        self,
        spec: Spec,
        run_id: str,
        refs: Callable[[str], dict[str, Any] | None] = lambda _: None,
        extra_classes: Iterable[str] = (),
        preferred: dict[str, Any] | None = None,
    ) -> None:
        self.spec = spec
        self.run_id = run_id
        self.refs = refs  # resource class name -> {"id", "href", "name"} of one, or None
        own = {r.schema for r in spec.resources() if r.schema and r.op("POST")}
        self.classes = sorted(own | set(extra_classes), key=len, reverse=True)
        self.examples = example_strings(spec)
        self.preferred = preferred or {}
        self._scopes: list[str] = []
        self._names = 0
        # whole seconds in UTC: the form most servers return unchanged
        self._clock = datetime.now(UTC).replace(microsecond=0)

    @contextmanager
    def scope(self, resource_class: str | None) -> Iterator[None]:
        """Build values for this resource class (for class-scoped preferred values)."""
        self._scopes.append(resource_class or "")
        try:
            yield
        finally:
            self._scopes.pop()

    @property
    def current_scope(self) -> str:
        return self._scopes[-1] if self._scopes else ""

    def _preferred(self, name: str) -> tuple[bool, Any]:
        scoped = f"{self._scopes[-1]}.{name}" if self._scopes else None
        for key in (scoped, name):
            if key and key in self.preferred:
                return True, self.preferred[key]
        return False, None

    # -- public ---------------------------------------------------------------------------

    def minimal(self, schema: dict[str, Any]) -> dict[str, Any]:
        """A body with only the schema's required properties."""
        return self._object(schema, _ref_name(schema), depth=0, optional=False, name="")

    def value(self, schema: dict[str, Any], name: str = "") -> Any:
        return self._value(schema, name, depth=1)

    @staticmethod
    def made_up(name: str, value: Any) -> bool:
        """A value nothing vouches for: the placeholder for a free string that may have a
        vocabulary. A refusal of it proves nothing about the attribute."""
        return value == PLACEHOLDER and name not in OWN_MARKER

    def is_reference(self, schema_name: str | None) -> bool:
        """A reference has an `id` (or is a union of references) and is named `...Ref`,
        has `@referredType`, or is a `Bundled...`. `RelatedPartyRefOrPartyRoleRef` has no
        `id`: it is a value that holds a reference."""
        if not schema_name:
            return False
        pointer = {"$ref": f"{self.spec.schemas_pointer}/{schema_name}"}
        props = self.spec.properties(pointer)
        union = len(self.spec.resolve(pointer).get("discriminator", {}).get("mapping", {})) > 1
        if "id" not in props and not union:
            return False
        name = class_name(schema_name).removesuffix("OrValue")
        return name.endswith("Ref") or "@referredType" in props or name.startswith("Bundled")

    def targets(self, schema_name: str) -> list[str]:
        """The classes a reference schema may point at, longest name first.

        Each referenced name (`RelatedPartyRefOrPartyRoleRef`: `RelatedParty`, `PartyRole`)
        is the class or ends with it (`RelatedParty` is a `Party`, `BundledProductOffering`
        a `ProductOffering`). A class that only starts the name is another class:
        `ProductOfferingRef` never points at a `Product`."""
        name = class_name(schema_name).removesuffix("OrValue")
        parts = [p for p in re.split(r"RefOr|Ref$", name) if p]
        return [c for c in self.classes if any(p.endswith(c) for p in parts)]

    def target(self, schema_name: str) -> str | None:
        found = self.targets(schema_name)
        return found[0] if found else None

    # -- building -------------------------------------------------------------------------

    def _value(self, schema: dict[str, Any], name: str, depth: int) -> Any:
        if depth > MAX_DEPTH:
            raise Unbuildable(f"too-deep {name}")
        ref = _ref_name(schema)
        if self.is_reference(ref):
            return self._reference(ref, name, depth)
        resolved = self.spec.resolve(schema)
        one_of = resolved.get("oneOf") or resolved.get("anyOf")
        if one_of:
            return self._value(one_of[0], name, depth)  # the Ref branch comes first
        kind = resolved.get("type")
        found, preferred = self._preferred(name)
        if found and kind not in ("object", "array"):
            return preferred
        example = resolved.get("example")
        plain = not isinstance(example, dict | list) and not resolved.get("format")
        if name == "id" and kind in (None, "string"):
            # an id inside a value (an order item's): unique, siblings must not collide
            self._names += 1
            return f"{example if isinstance(example, str) else 'tmf-checker'}-{self._names}"
        if example is not None and plain and not is_id_string(name):
            return example
        if resolved.get("enum"):
            first = resolved["enum"][0]
            return first.strip() if isinstance(first, str) else first
        kind = resolved.get("type")
        if kind == "array":
            return [self._value(resolved.get("items", {}), name, depth + 1)]
        if kind == "object" or (kind is None and self.spec.properties(resolved)):
            return self._object(schema, ref, depth, optional=True, name=name)
        if is_id_string(name):
            raise Unbuildable(f"no-fixture {name}")
        return self._scalar(resolved, name)

    def _scalar(self, schema: dict[str, Any], name: str) -> Any:
        kind, fmt = schema.get("type"), schema.get("format")
        if kind == "integer":
            return 1
        if kind == "number":
            return 12.5
        if kind == "boolean":
            return True
        if fmt == "date-time":
            # a period ends after it starts, whatever the property order
            ends = name.lower().startswith(("end", "termination", "expir", "close"))
            days = 30 if ends else 1
            return (self._clock + timedelta(days=days)).isoformat().replace("+00:00", "Z")
        if fmt == "uri":
            return "https://example.com/tmf-checker"
        if fmt in ("byte", "base64"):
            return "dG1mLWNoZWNrZXI="
        if kind in (None, "string") and not fmt and name in self.examples:
            if name not in OWN_MARKER:
                return self.examples[name]
        if name == "name":
            self._names += 1  # unique: some servers refuse a second resource with a name
            return f"tmf-checker-{self.run_id}-{self._names}"
        return PLACEHOLDER

    def _object(
        self, schema: dict[str, Any], ref: str | None, depth: int, *, optional: bool, name: str
    ) -> dict[str, Any]:
        props = self.spec.properties(schema)
        required = self.spec.required(schema)
        if depth > 0 and ref and ref.endswith("_MVO"):
            # a nested merge value: complete it as its full value object (_FVO) would be,
            # e.g. an ExternalIdentifier with its id
            full = ref.removesuffix("_MVO") + "_FVO"
            if full in self.spec.schemas:
                required |= self.spec.required({"$ref": f"{self.spec.schemas_pointer}/{full}"})
        out: dict[str, Any] = {}
        missed: str | None = None  # an optional reference that could not be built
        for prop, sub in props.items():
            if prop in required:
                if prop == "@type" and ref:
                    out[prop] = class_name(ref)
                else:
                    out[prop] = self._value(sub, prop, depth + 1)
            elif optional and depth > 0 and self._is_plain_scalar(prop, sub):
                out[prop] = self._value(sub, prop, depth + 1)
            elif optional and depth > 0 and self.is_reference(_ref_name(sub)):
                try:
                    out[prop] = self._value(sub, prop, depth + 1)
                except Unbuildable:
                    missed = missed or prop
        has_ref = any(self.is_reference(_ref_name(props[p])) for p in out if p in props)
        if missed and not has_ref:
            raise Unbuildable(f"no-fixture {name or missed}")
        return out

    def _is_plain_scalar(self, prop: str, schema: dict[str, Any]) -> bool:
        if prop.startswith("@") or prop in ("id", "href") or is_id_string(prop):
            return False
        if prop in SERVER_MANAGED:
            return False
        if self.is_reference(_ref_name(schema)):
            return False
        return self.spec.resolve(schema).get("type") in ("string", "number", "integer", "boolean")

    def _reference(self, schema_name: str, name: str, depth: int) -> dict[str, Any]:
        found, target_class = None, None
        for candidate in self.targets(schema_name):  # PartyRole, then Party
            found = self.refs(candidate)
            if found is not None:
                target_class = candidate
                break
        if found is None or target_class is None:
            raise Unbuildable(f"no-fixture {name or schema_name}")
        mapping = (
            self.spec.resolve({"$ref": f"{self.spec.schemas_pointer}/{schema_name}"})
            .get("discriminator", {})
            .get("mapping", {})
        )
        if len(mapping) > 1:  # a union of references: the branch of the target
            branch = next((k for k in mapping if k == f"{target_class}Ref"), None) or next(
                (k for k in mapping if target_class in k), None
            )
            if branch:
                schema_name = mapping[branch].rsplit("/", 1)[-1]
        pointer = {"$ref": f"{self.spec.schemas_pointer}/{schema_name}"}
        props = self.spec.properties(pointer)
        out: dict[str, Any] = {}
        for prop in sorted(self.spec.required(pointer) - REF_FIELDS):
            out[prop] = self._value(props[prop], prop, depth + 1)
        out.update({k: v for k, v in found.items() if k in props and k != "@type"})
        if "@type" in props and not self.spec.is_swagger:
            out["@type"] = class_name(schema_name).removesuffix("OrValue")
        if "@referredType" in props and "@referredType" not in found:
            out["@referredType"] = target_class
        return out
