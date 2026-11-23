"""Validate JSON bodies against a TMF spec's schemas.

Built on jsonschema's Draft 4 validator (what OAS 3.0 and Swagger 2.0 schemas extend) plus
the OAS 3.0 keywords that change validation, with TMF-aware discriminator handling:

- `nullable: true` admits `null` (OAS 3.0.3). A required property marked `readOnly` or
  `writeOnly` may be absent, as in openapi-schema-validator, which this replaced. Other OAS
  keywords (`discriminator` outside `oneOf`, `example`, `xml`, ...) are annotations.
- A `discriminator` next to `allOf` is not dispatched on. Every TMF v5 schema has one that
  maps its own name to itself, so dispatching recurses forever (stock OAS validators do).
  Here `allOf`/`anyOf` are plain JSON Schema; such a discriminator only declares that
  subclasses may exist.
- Plain JSON Schema cannot validate the `...RefOrValue` schemas: they are a `oneOf` of two
  permissive schemas, so a plain reference matches both branches. Here a `oneOf` with a
  discriminator validates only the branch that `@type` selects. A subclass `@type` outside
  the mapping (the TMF630 extension pattern) is validated as the branch its `@baseType`
  names.

`date-time` values are format-checked (RFC 3339 section 5.6, as OAS specifies; leap seconds
are refused, the `T` and `Z` may be lower case); no other format is,
because TMF formats such as `uri` are used loosely and a false positive costs more than a
missed gap.

`issues()` gives each problem as a stable (path, keyword) pair for findings; `errors()`
gives human-readable lines for the `validate` command.

tests/test_validate.py proves each statement.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from jsonschema import Draft4Validator, FormatChecker, ValidationError, validators
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT4

from tmf_checker.spec import Spec


def _one_of(validator, one_of, instance, schema):
    discriminator = schema.get("discriminator")
    if discriminator is None:
        yield from Draft4Validator.VALIDATORS["oneOf"](validator, one_of, instance, schema)
        return
    prop = discriminator["propertyName"]
    if not isinstance(instance, dict) or prop not in instance:
        yield ValidationError(f"{prop!r} is a required property (discriminator)")
        return
    mapping = discriminator.get("mapping", {})

    def lookup(value: Any) -> str | None:
        return mapping.get(value) if isinstance(value, str) else None

    ref = lookup(instance[prop])
    if ref is None:
        # TMF630 extension pattern: a subclass names its own @type and the class it extends
        # in @baseType. Validate it as that base class.
        ref = lookup(instance.get("@baseType"))
    if ref is None:
        yield ValidationError(
            f"{instance[prop]!r} is not a known {prop} for this oneOf, and no known @baseType"
        )
        return
    yield from validator.descend(instance, {"$ref": ref})


def _type(validator, types, instance, schema):
    if instance is None and schema.get("nullable") is True:
        return
    yield from Draft4Validator.VALIDATORS["type"](validator, types, instance, schema)


def _required(validator, required, instance, schema):
    if not validator.is_type(instance, "object"):
        return
    properties = schema.get("properties", {})
    for name in required:
        prop = properties.get(name)
        exempt = isinstance(prop, dict) and (prop.get("readOnly") or prop.get("writeOnly"))
        if name not in instance and not exempt:
            yield ValidationError(f"{name!r} is a required property")


def _format(validator, format, instance, schema):
    if instance is not None:
        yield from Draft4Validator.VALIDATORS["format"](validator, format, instance, schema)


TmfValidator = validators.extend(
    Draft4Validator,
    validators={"oneOf": _one_of, "type": _type, "required": _required, "format": _format},
)

_DATE_TIME = re.compile(
    r"(\d{4})-(0[1-9]|1[0-2])-(\d{2})T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d+)?"
    r"(Z|[+-]([01]\d|2[0-3]):[0-5]\d)",
    re.ASCII,
)
_FORMATS = FormatChecker(formats=())


@_FORMATS.checks("date-time")
def _is_date_time(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    m = _DATE_TIME.fullmatch(instance.upper())
    if m is None:
        return False
    year, month, day = int(m[1]), int(m[2]), int(m[3])
    return year > 0 and 1 <= day <= calendar.monthrange(year, month)[1]


@cache
def _validator(spec: Spec, schema: str) -> Draft4Validator:
    if schema not in spec.schemas:
        raise KeyError(f"{spec.name} has no schema named {schema!r}")
    uri = f"urn:tmf-checker:{id(spec)}"
    registry = Registry().with_resource(uri, Resource(contents=spec.doc, specification=DRAFT4))
    return TmfValidator(
        {"$ref": f"{uri}{spec.schemas_pointer}/{schema}"},
        registry=registry,
        format_checker=_FORMATS,
    )


@dataclass(frozen=True, order=True)
class Issue:
    """One problem, stable across runs: `path` uses `[]` for any array index, and `keyword`
    names the rule (`type:string`, `required`, `format:date-time`, `null`, ...)."""

    path: str
    keyword: str
    message: str = field(compare=False)


_REQUIRED = re.compile(r"^'(.+)' is a required property")


def _path(parts: Any) -> str:
    out = ""
    for part in parts:
        out += "[]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _issue(error: ValidationError) -> Issue:
    path = _path(error.absolute_path)
    validator, value = error.validator, error.validator_value
    if validator == "required" and (m := _REQUIRED.match(error.message)):
        path = f"{path}.{m.group(1)}" if path else m.group(1)
        keyword = "required"
    elif error.instance is None:
        keyword = "null"  # "not nullable" and "not of type" both say this
    elif validator in ("type", "format") and isinstance(value, str):
        keyword = f"{validator}:{value}"
    elif validator == "oneOf" and "discriminator" in error.schema:
        keyword = "discriminator"
    else:
        keyword = str(validator)
    return Issue(path or "<root>", keyword, error.message)


def issues(spec: Spec, schema: str, instance: Any, *, partial: bool = False) -> list[Issue]:
    """Problems as (path, keyword) pairs, one per pair, sorted. See `errors` for `partial`."""
    found: dict[tuple[str, str], Issue] = {}
    for error in _validator(spec, schema).iter_errors(instance):
        if partial and error.validator == "required" and not error.absolute_path:
            continue
        issue = _issue(error)
        found.setdefault((issue.path, issue.keyword), issue)
    return sorted(found.values())


def errors(spec: Spec, schema: str, instance: Any, *, partial: bool = False) -> list[str]:
    """Human-readable validation errors, sorted; empty when the instance conforms.

    `partial=True` is for `fields=` projections: a top-level required attribute that was not
    selected is not an error. Nested required attributes are still checked.
    """
    found = _validator(spec, schema).iter_errors(instance)
    return sorted(
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in found
        if not (partial and e.validator == "required" and not e.absolute_path)
    )
