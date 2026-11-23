"""A local TMF API stub for tests: standard library only, driven by a bundled spec.

It serves every resource the spec lists under `/api`, conformant by default. Each field of
`Gaps` switches on one deliberate deviation, so every check can be proven both ways: it
finds the gap when the switch is on, and nothing when it is off.
"""

from __future__ import annotations

import copy
import json
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from tmf_checker.spec import Spec

ALWAYS = {"id", "href"}


@dataclass
class Gaps:
    unimplemented: set[str] = field(default_factory=set)  # collections answering 404
    forbidden: set[str] = field(default_factory=set)  # collections answering 403
    unknown_id_status: int = 404
    plain_errors: bool = False  # error answers are text, not the Error resource
    malformed_status: int = 400
    wrong_result_count: bool = False
    ignore_limit: bool = False
    ignore_offset: bool = False
    ignore_fields: bool = False
    drop_selected_field: bool = False
    # equality filters ?attr=value: None (applied), "ignore", "refuse" (400), "empty",
    # "lenient" (case-insensitive, and items without the attribute pass: not judged)
    filters: str | None = None
    null_unset: tuple[str, ...] = ()  # attributes returned as null when unset
    bad_dates: bool = False  # lastUpdate without a timezone
    # href style: None (absolute URL), "relative", "other-host" (conformant); "urn" (the URN
    # id), "other" (another resource's URL)
    href: str | None = None
    no_location: bool = False
    wrong_location: bool = False
    create_status: int = 201
    refuse: set[str] = field(default_factory=set)  # 400 when sent on create
    require: set[str] = field(default_factory=set)  # 400 when absent on create
    drop: set[str] = field(default_factory=set)  # accepted, never returned
    rewrite: dict[str, Any] = field(default_factory=dict)  # returned with this value
    require_together: set[str] = field(default_factory=set)  # 400 unless all present at once
    name_missing: bool = False  # the 400 for a missing attribute names it
    conflict: set[str] = field(default_factory=set)  # 409 when sent on create (state)
    server_sets: dict[str, Any] = field(default_factory=dict)  # added to every resource
    refuse_patch_types: set[str] = field(default_factory=set)  # PATCH content types answering 415
    no_patch: bool = False  # PATCH answers 405
    read_only: set[str] = field(default_factory=set)  # 400 when sent on PATCH
    patch_drop: set[str] = field(default_factory=set)  # accepted on PATCH, not stored
    refuse_noop_patch: bool = False  # 400 for a PATCH that changes nothing (allowed)
    ignore_json_patch: bool = False  # JSON Patch answers 200 but changes nothing
    patch_conflict: set[str] = field(default_factory=set)  # 409 when sent on PATCH (state)
    refuse_base_type: bool = False  # 400 when @baseType is sent
    no_create: bool = False  # POST answers 405
    no_delete: bool = False  # DELETE answers 405
    refuse_referenced_delete: bool = False  # DELETE answers 409 while another resource refers
    cookie: str | None = None  # when set, requests without this Cookie answer 401


class Stub:
    def __init__(self, spec: Spec, gaps: Gaps) -> None:
        self.spec = spec
        self.gaps = gaps
        self.v5 = not spec.is_swagger
        self.store: dict[str, dict[str, dict[str, Any]]] = {
            r.collection.strip("/"): {} for r in spec.resources()
        }
        self.base_url = ""  # set when serving
        self.requests: list[tuple[str, str]] = []

    # -- data -----------------------------------------------------------------------------

    def add(self, collection: str, body: dict[str, Any]) -> dict[str, Any]:
        rid = str(body.get("id") or uuid.uuid4())
        obj = copy.deepcopy(body)
        obj.update(copy.deepcopy(self.gaps.server_sets))
        obj["id"] = rid
        obj["href"] = {
            None: f"{self.base_url}/{collection}/{rid}",
            "urn": f"urn:ngsi-ld:{collection}:{rid}",
            "other": f"{self.base_url}/{collection}/someone-else",
            "relative": f"/api/{collection}/{rid}",
            "other-host": f"https://public.example/tmf/api/{collection}/{rid}",
        }[self.gaps.href]
        if self.v5:
            obj.setdefault("@type", collection[:1].upper() + collection[1:])
        if "lastUpdate" in obj:
            obj["lastUpdate"] = (
                "2026-01-01T00:00:00" if self.gaps.bad_dates else "2026-01-01T00:00:00Z"
            )
        self.store[collection][rid] = obj
        return obj

    def view(self, obj: dict[str, Any], fields: str | None = None) -> dict[str, Any]:
        out = {k: v for k, v in obj.items() if k not in self.gaps.drop}
        for k, v in self.gaps.rewrite.items():
            if k in out:  # a dict rewrites only the keys it names
                out[k] = {**out[k], **v} if isinstance(v, dict) and isinstance(out[k], dict) else v
        for k in self.gaps.null_unset:
            out.setdefault(k, None)
        if fields and not self.gaps.ignore_fields:
            keep = set(fields.split(",")) | ALWAYS
            out = {k: v for k, v in out.items() if k in keep or k.startswith("@")}
            if self.gaps.drop_selected_field:
                out = {k: v for k, v in out.items() if k not in fields.split(",")}
        return out

    def error(self, status: int, reason: str) -> tuple[int, Any]:
        if self.gaps.plain_errors:
            return status, reason
        body: dict[str, Any] = {"code": str(status), "reason": reason}
        if self.v5:
            body["@type"] = "Error"
        return status, body


class _Handler(BaseHTTPRequestHandler):
    stub: Stub

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _send(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        data = b""
        if body is not None:
            data = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(status)
        ctype = "application/json" if not isinstance(body, str) else "text/plain"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _route(self) -> tuple[str | None, str | None, dict[str, list[str]]]:
        url = urlsplit(self.path)
        parts = url.path.removeprefix("/api").strip("/").split("/")
        query = parse_qs(url.query)
        if not parts or parts[0] not in self.stub.store:
            return None, None, query
        return parts[0], (parts[1] if len(parts) > 1 else None), query

    def _guard(self) -> bool:
        stub = self.stub
        stub.requests.append((self.command, self.path))
        if stub.gaps.cookie and self.headers.get("Cookie") != stub.gaps.cookie:
            self._send(*stub.error(401, "Unauthorized"))
            return False
        collection, _, _ = self._route()
        if collection in stub.gaps.forbidden:
            self._send(*stub.error(403, "Forbidden"))
            return False
        if collection is None or collection in stub.gaps.unimplemented:
            self._send(*stub.error(404, "Not Found"))
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard():
            return
        stub = self.stub
        collection, rid, query = self._route()
        fields = query.get("fields", [None])[0]
        if rid is not None:
            obj = stub.store[collection].get(rid)
            if obj is None:
                self._send(*stub.error(stub.gaps.unknown_id_status, "Not Found"))
                return
            self._send(200, stub.view(obj, fields))
            return
        objs = list(stub.store[collection].values())
        wanted = {k: v[0] for k, v in query.items() if k not in ("fields", "offset", "limit")}
        if wanted and stub.gaps.filters == "refuse":
            self._send(*stub.error(400, "Unknown query parameter"))
            return
        if wanted and stub.gaps.filters != "ignore":
            lenient = stub.gaps.filters == "lenient"

            def match(o: dict[str, Any], k: str, v: str) -> bool:
                if k not in o:
                    return lenient
                return str(o[k]).casefold() == v.casefold() if lenient else str(o[k]) == v

            objs = [o for o in objs if all(match(o, k, v) for k, v in wanted.items())]
            if stub.gaps.filters == "empty":
                objs = []
        items = [stub.view(o, fields) for o in objs]
        total = len(items)
        offset = int(query.get("offset", ["0"])[0])
        limit = query.get("limit", [None])[0]
        if not stub.gaps.ignore_offset:
            items = items[offset:]
        if limit is not None and not stub.gaps.ignore_limit:
            items = items[: int(limit)]
        count = len(items) + (1 if stub.gaps.wrong_result_count else 0)
        self._send(200, items, {"X-Result-Count": str(count), "X-Total-Count": str(total)})

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard():
            return
        stub = self.stub
        collection, _, _ = self._route()
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            self._send(*stub.error(stub.gaps.malformed_status, "Malformed JSON"))
            return
        if stub.gaps.no_create:
            self._send(*stub.error(405, "Method Not Allowed"))
            return
        if set(body) & stub.gaps.conflict:
            self._send(*stub.error(409, "Conflict"))
            return
        together = stub.gaps.require_together
        if (
            set(body) & stub.gaps.refuse
            or stub.gaps.require - set(body)
            or (together and not together <= set(body))
            or (stub.gaps.refuse_base_type and "@baseType" in body)
        ):
            missing = sorted((stub.gaps.require | together) - set(body))
            reason = f"missing: {', '.join(missing)}" if stub.gaps.name_missing else "Bad Request"
            self._send(*stub.error(400, reason))
            return
        obj = stub.add(collection, body)
        headers = {}
        if not stub.gaps.no_location:
            headers["Location"] = obj["href"] + ("/other" if stub.gaps.wrong_location else "")
        self._send(stub.gaps.create_status, stub.view(obj), headers)

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._guard():
            return
        stub = self.stub
        collection, rid, _ = self._route()
        ctype = self.headers.get("Content-Type", "")
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if stub.gaps.no_patch:
            self._send(*stub.error(405, "Method Not Allowed"))
            return
        if ctype in stub.gaps.refuse_patch_types:
            self._send(*stub.error(415, "Unsupported Media Type"))
            return
        obj = stub.store[collection].get(rid)
        if obj is None:
            self._send(*stub.error(404, "Not Found"))
            return
        body = json.loads(raw)
        if isinstance(body, list):  # JSON Patch: replace only
            if stub.gaps.ignore_json_patch:
                self._send(200, stub.view(obj))
                return
            body = {op["path"].lstrip("/"): op["value"] for op in body if op.get("op") == "replace"}
        changes = {k: v for k, v in body.items() if k != "@type" and obj.get(k) != v}
        if stub.gaps.refuse_noop_patch and not changes:
            self._send(*stub.error(400, "PATCH changes nothing"))
            return
        if set(body) & stub.gaps.patch_conflict:
            self._send(*stub.error(409, "Conflict: the resource is completed"))
            return
        if set(body) & stub.gaps.read_only:
            self._send(*stub.error(400, "Bad Request"))
            return
        obj.update({k: v for k, v in body.items() if k not in stub.gaps.patch_drop})
        self._send(200, stub.view(obj))

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._guard():
            return
        stub = self.stub
        collection, rid, _ = self._route()
        if stub.gaps.no_delete:
            self._send(*stub.error(405, "Method Not Allowed"))
            return
        if stub.gaps.refuse_referenced_delete and any(
            rid in json.dumps(o)
            for c, objs in stub.store.items()
            if c != collection
            for o in objs.values()
        ):
            self._send(*stub.error(409, "Conflict: still referenced"))
            return
        if stub.store[collection].pop(rid, None) is None:
            self._send(*stub.error(404, "Not Found"))
            return
        self._send(204)


@contextmanager
def serve(spec: Spec, gaps: Gaps | None = None) -> Iterator[Stub]:
    stub = Stub(spec, gaps or Gaps())
    handler = type("Handler", (_Handler,), {"stub": stub})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    stub.base_url = f"http://127.0.0.1:{server.server_address[1]}/api"
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        yield stub
    finally:
        server.shutdown()
        server.server_close()
