"""Reports: the text lines (what a baseline locks) and JSON (lines plus evidence)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from tmf_checker import __version__
from tmf_checker.findings import Finding


def text(findings: Sequence[Finding]) -> str:
    return "".join(f.line + "\n" for f in findings)


def summary(findings: Sequence[Finding]) -> str:
    gaps = sum(not f.is_skip for f in findings)
    skips = len(findings) - gaps
    return f"{gaps} gap(s), {skips} skip(s)"


def as_json(findings: Sequence[Finding], meta: dict[str, Any]) -> str:
    doc = {
        "tool": "tmf-checker",
        "version": __version__,
        **meta,
        "findings": [
            {
                "line": f.line,
                "api": f.api,
                "method": f.method,
                "path": f.path,
                "kind": f.kind,
                "detail": f.detail,
                "evidence": f.evidence,
            }
            for f in findings
        ],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


_STYLE = """
:root { color-scheme: light dark; --bg: #fff; --fg: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7;
  --gap: #b3261e; --skip: #6e6e73; --code: #f5f5f7; }
@media (prefers-color-scheme: dark) { :root { --bg: #161617; --fg: #f5f5f7; --muted: #a1a1a6;
  --line: #3a3a3c; --gap: #ff8a80; --skip: #a1a1a6; --code: #232325; } }
body { background: var(--bg); color: var(--fg); margin: 0 auto; max-width: 1100px;
  padding: 24px 16px; font: 14px/1.5 system-ui, sans-serif; }
h1 { font-size: 20px; margin: 0 0 4px; } .meta { color: var(--muted); margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; } td, th { text-align: left; padding: 6px 8px;
  border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 500; } .gap { color: var(--gap); }
.skip { color: var(--skip); } code, pre { font: 12px/1.45 ui-monospace, monospace; }
pre { background: var(--code); padding: 8px; overflow-x: auto; white-space: pre-wrap;
  word-break: break-word; margin: 6px 0 0; } summary { cursor: pointer; }
.counts span { margin-right: 16px; }
"""


def as_html(findings: Sequence[Finding], meta: dict[str, Any]) -> str:
    """One self-contained page. Every value is escaped: evidence is the server's text."""
    from html import escape

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    rows = []
    for f in findings:
        evidence = (
            escape(json.dumps(f.evidence, indent=2, ensure_ascii=False)) if f.evidence else ""
        )
        detail = (
            f"<details><summary><code>{escape(f.detail)}</code></summary><pre>{evidence}</pre>"
            "</details>"
            if evidence
            else f"<code>{escape(f.detail)}</code>"
        )
        rows.append(
            f'<tr class="{"skip" if f.is_skip else "gap"}"><td>{escape(f.method)}</td>'
            f"<td><code>{escape(f.path)}</code></td><td>{escape(f.kind)}</td><td>{detail}</td></tr>"
        )
    count_html = "".join(f"<span>{escape(kind)}: {n}</span>" for kind, n in sorted(counts.items()))
    meta_html = " · ".join(f"{escape(str(k))}: {escape(str(v))}" for k, v in meta.items())
    title = escape(f"tmf-checker {meta.get('api', '')}".strip())
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{_STYLE}</style></head><body>"
        f'<h1>{title}</h1><div class="meta">{meta_html}<br>{escape(summary(findings))}</div>'
        f'<p class="counts">{count_html}</p>'
        f"<table><thead><tr><th>Method</th><th>Path</th><th>Kind</th><th>Detail</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f'<p class="meta">Not a TM Forum conformance certification. tmf-checker {__version__}</p>'
        f"</body></html>\n"
    )
