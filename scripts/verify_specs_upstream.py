#!/usr/bin/env python3
"""Re-fetch each vendored spec's git blob SHA from the GitHub API and compare it with
src/tmf_checker/specs/README.md. Run via `make specs-verify`.

Needs the network, so it is not part of `make test`. This is the check that ties the SHAs
recorded in the README to upstream; tests/test_spec_provenance.py only ties the local
files to the README. Standard library only.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "src" / "tmf_checker" / "specs" / "README.md"

# | `<file>` | ... blob/<commit>/<path>) | ...   - the source table
SOURCE_ROW = re.compile(
    r"^\| `([^`]+)` \|.*github\.com/tmforum-apis/([^/]+)/blob/([0-9a-f]{40})/([^)]+)\)",
    re.MULTILINE,
)
# | `<file>` | `<40 hex>` |                      - the "Upstream blob SHAs" table
BLOB_ROW = re.compile(r"^\| `([^`]+)` \| `([0-9a-f]{40})` \|$", re.MULTILINE)


def upstream_blob_sha(repo: str, commit: str, path: str) -> str | None:
    url = f"https://api.github.com/repos/tmforum-apis/{repo}/git/trees/{commit}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URL
        tree = json.load(resp)
    for entry in tree["tree"]:
        if entry["path"] == path and entry["type"] == "blob":
            return entry["sha"]
    return None


def main() -> int:
    text = README.read_text()
    sources = SOURCE_ROW.findall(text)
    recorded = dict(BLOB_ROW.findall(text))
    if not sources or {s[0] for s in sources} != set(recorded):
        print("FAILED: the source table and the blob SHA table list different files")
        return 1

    bad = 0
    for name, repo, commit, path in sources:
        try:
            upstream = upstream_blob_sha(repo, commit, path)
        except OSError as exc:
            print(f"ERROR     {name}: cannot reach the GitHub API: {exc}")
            bad += 1
            continue
        if upstream == recorded[name]:
            print(f"ok        {name} {upstream} ({repo}@{commit[:12]})")
        else:
            print(f"MISMATCH  {name}: README {recorded[name]}, upstream {upstream}")
            bad += 1
    if bad:
        print(f"FAILED: {bad} of {len(sources)} files not verified against upstream")
        return 1
    print(f"verified: {len(sources)} recorded blob SHAs match upstream at the pinned commits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
