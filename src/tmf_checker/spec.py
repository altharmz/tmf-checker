"""Load TM Forum Open API specifications (v4 Swagger 2.0 and v5 OpenAPI 3.0) and walk them.

A `Spec` wraps one parsed document. The bundled specs are addressed by API and major
version (`Spec.bundled("TMF620", 5)`); any other file can be loaded by path. Schema walking
follows `$ref`, `allOf` and the branches of `oneOf`/`anyOf`, which is how TMF models
inheritance and the `...RefOrValue` choice.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

SPECS_DIR = Path(str(files("tmf_checker") / "specs"))

# (API, major version) -> bundled file. specs/README.md records provenance for each.
BUNDLED: dict[tuple[str, int], str] = {
    ("TMF620", 4): "TMF620-ProductCatalog-v4.1.0.swagger.json",
    ("TMF620", 5): "TMF620-Product_Catalog_Management-v5.0.0.oas.yaml",
    ("TMF622", 4): "TMF622-ProductOrder-v4.0.0.swagger.json",
    ("TMF622", 5): "TMF622-ProductOrdering-v5.0.0.oas.yaml",
    ("TMF637", 4): "TMF637-ProductInventory-v4.0.0.swagger.json",
    ("TMF637", 5): "TMF637-ProductInventory-v5.0.0.oas.yaml",
    ("TMF666", 4): "TMF666-Account-v4.0.0.swagger.json",
    ("TMF666", 5): "TMF666-Account_Management-v5.0.0.oas.yaml",
    ("TMF678", 4): "TMF678-CustomerBill-v4.0.0.swagger.json",
    ("TMF678", 5): "TMF678-CustomerBill-v5.0.0.oas.yaml",
}

METHODS = ("get", "post", "patch", "put", "delete")


@dataclass(frozen=True)
class Operation:
    method: str  # upper case
    path: str  # as written in the spec, e.g. /productOffering/{id}
    item: dict[str, Any]  # the operation object


@dataclass(frozen=True)
class Resource:
    """A TMF resource: a collection path and, when the spec has one, its item path."""

    collection: str  # /productOffering
    item: str | None  # /productOffering/{id}
    schema: str | None  # the schema the item GET (else the list) returns, e.g. ProductOffering
    operations: dict[tuple[str, str], Operation]  # (METHOD, path) -> operation

    def op(self, method: str, item: bool = False) -> Operation | None:
        path = self.item if item else self.collection
        return self.operations.get((method, path)) if path else None


def schema_name(schema: dict[str, Any] | None) -> str | None:
    """The component name a schema refers to, through one level of array `items`."""
    if not schema:
        return None
    if schema.get("type") == "array":
        schema = schema.get("items", {})
    ref = schema.get("$ref", "")
    return ref.rsplit("/", 1)[-1] if ref.startswith("#/") else None


def _parse(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # libyaml is ~6x faster
    return yaml.load(text, Loader=loader)  # noqa: S506 - a safe loader either way


class Spec:
    def __init__(self, doc: dict[str, Any], name: str = "spec") -> None:
        self.doc = doc
        self.name = name

    @classmethod
    def load(cls, path: str | Path) -> Spec:
        path = Path(path)
        return cls(_parse(path), path.name)

    @staticmethod
    @cache
    def bundled(api: str, major: int) -> Spec:
        try:
            filename = BUNDLED[(api, major)]
        except KeyError:
            known = ", ".join(f"{a} v{m}" for a, m in sorted(BUNDLED))
            raise KeyError(f"no bundled spec for {api} v{major} (bundled: {known})") from None
        return Spec.load(SPECS_DIR / filename)

    # -- document facts -------------------------------------------------------------------

    @property
    def is_swagger(self) -> bool:
        """Swagger 2.0 (the TMF v4 specs) rather than OpenAPI 3."""
        return "swagger" in self.doc

    @property
    def title(self) -> str:
        return self.doc.get("info", {}).get("title", "")

    @property
    def version(self) -> str:
        return str(self.doc.get("info", {}).get("version", ""))

    @property
    def schemas(self) -> dict[str, Any]:
        if self.is_swagger:
            return self.doc.get("definitions", {})
        return self.doc.get("components", {}).get("schemas", {})

    @property
    def schemas_pointer(self) -> str:
        return "#/definitions" if self.is_swagger else "#/components/schemas"

    def server_path(self) -> str:
        """The base path the spec declares: Swagger `basePath`, or the first OAS server URL's
        path with its variables replaced by their defaults."""
        if self.is_swagger:
            return self.doc.get("basePath", "")
        server = self.doc["servers"][0]
        url = server["url"]
        for name, variable in server.get("variables", {}).items():
            url = url.replace("{" + name + "}", str(variable["default"]))
        return urlsplit(url).path

    def operations(self, *, listeners: bool = False) -> Iterator[Operation]:
        """Every operation, in document order. `/listener/*` is the client's side of the
        notification contract (a subscriber implements it), so it is skipped by default."""
        for path, item in self.doc.get("paths", {}).items():
            if path.startswith("/listener/") and not listeners:
                continue
            for method in METHODS:
                if method in item:
                    yield Operation(method.upper(), path, item[method])

    def resources(self) -> list[Resource]:
        """Every resource with a collection GET or POST, in document order. `/hub` (event
        subscription) and `/listener/*` are not resources."""
        ops = {(op.method, op.path): op for op in self.operations()}
        paths = list(dict.fromkeys(path for _, path in ops))
        found = []
        for path in paths:
            if path.count("/") != 1 or path == "/hub":
                continue
            if ("GET", path) not in ops and ("POST", path) not in ops:
                continue
            item = next((p for p in paths if p.startswith(path + "/{") and p.count("/") == 2), None)
            mine = {key: op for key, op in ops.items() if key[1] in (path, item)}
            schema = None
            for key in (("GET", item), ("GET", path), ("POST", path)):
                if key in mine:
                    code = next(
                        (c for c in ("200", "201") if c in mine[key].item["responses"]), None
                    )
                    schema = schema_name(self.response_schema(mine[key], code)) if code else None
                    if schema:
                        break
            found.append(Resource(path, item, schema, mine))
        return found

    def response_schema(self, operation: Operation, status: str) -> dict[str, Any] | None:
        """The body schema of one response (Swagger `schema`, OAS JSON content)."""
        response = operation.item.get("responses", {}).get(status)
        if response is None:
            return None
        response = self.resolve(response)
        if self.is_swagger:
            return response.get("schema")
        content = response.get("content", {})
        media = content.get("application/json") or next(iter(content.values()), None)
        return media.get("schema") if media else None

    def declared_statuses(self, operation: Operation) -> set[str]:
        return set(operation.item.get("responses", {}))

    # -- schema walking -------------------------------------------------------------------

    def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Follow local `$ref`s until a schema without one."""
        while "$ref" in schema:
            node: Any = self.doc
            for part in schema["$ref"].removeprefix("#/").split("/"):
                node = node[part.replace("~1", "/").replace("~0", "~")]
            schema = node
        return schema

    def properties(self, schema: dict[str, Any], _seen: frozenset[str] = frozenset()) -> dict:
        """Name -> schema of every property, through `allOf` and the branches of
        `oneOf`/`anyOf` (a RefOrValue accepts both shapes on input). Cycles stop."""
        key = schema.get("$ref")
        if key in _seen:
            return {}
        seen = _seen | {key} if key else _seen
        schema = self.resolve(schema)
        found: dict[str, Any] = {}
        for part in (*schema.get("allOf", ()), *schema.get("oneOf", ()), *schema.get("anyOf", ())):
            found.update(self.properties(part, seen))
        found.update(schema.get("properties", {}))
        return found

    def required(self, schema: dict[str, Any]) -> set[str]:
        """Required property names, through `allOf` (not through oneOf/anyOf branches)."""
        schema = self.resolve(schema)
        names = set(schema.get("required", ()))
        for part in schema.get("allOf", ()):
            names |= self.required(part)
        return names

    def request_schema(self, operation: Operation) -> dict[str, Any] | None:
        """The body schema of an operation: Swagger's `in: body` parameter, or the first
        content type of OAS `requestBody`."""
        if self.is_swagger:
            for parameter in operation.item.get("parameters", ()):
                if parameter.get("in") == "body":
                    return parameter["schema"]
            return None
        body = operation.item.get("requestBody")
        if body is None:
            return None
        content = self.resolve(body)["content"]
        return next(iter(content.values()))["schema"]

    def request_content_types(self, operation: Operation) -> list[str]:
        """Content types the operation accepts for its body (Swagger: `consumes`)."""
        if self.is_swagger:
            return list(operation.item.get("consumes", self.doc.get("consumes", ())))
        body = operation.item.get("requestBody")
        return sorted(self.resolve(body)["content"]) if body else []
