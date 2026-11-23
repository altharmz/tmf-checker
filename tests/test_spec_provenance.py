"""Every bundled spec is byte-identical to the upstream blob recorded in specs/README.md.

The SHA is git's blob id, recomputed offline: sha1(b"blob <len>\\0" + content). A file
without a recorded SHA, or a recorded SHA without a file, is a failure.
`make specs-verify` ties the recorded SHAs to upstream (it needs the network).
"""

import hashlib
import re

from tmf_checker.spec import BUNDLED, SPECS_DIR

NOT_SPECS = {"README.md", "SHA256SUMS"}
# | `<file>` | `<40 hex>` |  - only the "Upstream blob SHAs" table has this shape
BLOB_ROW = re.compile(r"^\| `([^`]+)` \| `([0-9a-f]{40})` \|$", re.MULTILINE)


def _git_blob_sha(data: bytes) -> str:
    # sha1 is git's object id here, not a security primitive
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def test_git_blob_sha_matches_git():
    # `git hash-object` of an empty file and of "hello\n"
    assert _git_blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert _git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_spec_files_match_recorded_upstream_blob_shas():
    recorded = dict(BLOB_ROW.findall((SPECS_DIR / "README.md").read_text(encoding="utf-8")))
    on_disk = {p.name for p in SPECS_DIR.iterdir() if p.is_file()} - NOT_SPECS
    assert recorded, "no blob SHAs found in specs/README.md"
    assert set(recorded) == on_disk, "spec files and recorded blob SHAs differ"
    for name, expected in recorded.items():
        actual = _git_blob_sha((SPECS_DIR / name).read_bytes())
        assert actual == expected, f"{name} differs from its upstream blob in specs/README.md"


def test_every_bundled_file_is_registered():
    on_disk = {p.name for p in SPECS_DIR.iterdir() if p.is_file()} - NOT_SPECS
    assert set(BUNDLED.values()) == on_disk
