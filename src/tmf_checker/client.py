"""HTTP client for the API under test: standard library only.

The base URL is always the full API root the user gives (docs/spec-quirks.md #3); spec
paths are appended to it. Every exchange is logged for evidence, with credentials
redacted. Non-2xx answers are answers, not exceptions; only a transport failure raises.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

SENSITIVE = ("authorization", "cookie", "set-cookie", "proxy-authorization")
SENSITIVE_PARTS = ("token", "secret", "key", "password", "session")
EVIDENCE_BODY_LIMIT = 2000
_NO_BODY = object()


class TransportError(Exception):
    """The API could not be reached at all."""


def redact(headers: dict[str, str]) -> dict[str, str]:
    def hidden(name: str) -> bool:
        low = name.lower()
        return low in SENSITIVE or any(part in low for part in SENSITIVE_PARTS)

    return {k: ("<redacted>" if hidden(k) else v) for k, v in headers.items()}


@dataclass
class Response:
    method: str
    url: str
    status: int
    headers: dict[str, str]  # names lower-cased
    body: bytes
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: bytes | None = None
    _json: Any = field(default=_NO_BODY, repr=False)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        """The parsed body, or None when it is empty or not JSON."""
        if self._json is _NO_BODY:
            try:
                self._json = json.loads(self.body) if self.body.strip() else None
            except ValueError:
                self._json = None
        return self._json

    def evidence(self) -> dict[str, Any]:
        def clip(data: bytes | None) -> str | None:
            if data is None:
                return None
            text = data.decode("utf-8", "replace")
            return text if len(text) <= EVIDENCE_BODY_LIMIT else text[:EVIDENCE_BODY_LIMIT] + "…"

        return {
            "request": f"{self.method} {self.url}",
            "request_headers": redact(self.request_headers),
            "request_body": clip(self.request_body),
            "status": self.status,
            "response_headers": redact(self.headers),
            "response_body": clip(self.body),
        }


class Client:
    def __init__(
        self, base_url: str, headers: dict[str, str] | None = None, timeout: float = 30.0
    ) -> None:
        if urlsplit(base_url).scheme not in ("http", "https"):
            raise ValueError(f"base URL must be http(s): {base_url!r}")
        self.base_url = base_url.rstrip("/")
        self.headers = {"Accept": "application/json", **(headers or {})}
        self.timeout = timeout
        self.log: list[Response] = []

    def url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self.base_url + "/" + path.lstrip("/")
        return url + ("?" + urlencode(params) if params else "")

    def resolve(self, ref: str) -> str:
        """An href or Location, absolute or relative, as an absolute URL."""
        return urljoin(self.base_url + "/", ref)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = _NO_BODY,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> Response:
        url = self.url(path, params)
        headers = dict(self.headers)
        data = raw_body
        if json_body is not _NO_BODY:
            data = json.dumps(json_body).encode()
        if data is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                status, resp_headers, body = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            status, resp_headers, body = err.code, err.headers, err.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            raise TransportError(f"{method} {url}: {getattr(err, 'reason', err)}") from err
        response = Response(
            method=method,
            url=url,
            status=status,
            headers={k.lower(): v for k, v in resp_headers.items()},
            body=body,
            request_headers=headers,
            request_body=data,
        )
        self.log.append(response)
        return response

    def get(self, path: str, **params: Any) -> Response:
        return self.request("GET", path, params=params or None)
