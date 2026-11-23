"""Serve the test stub until killed, for end-to-end tests of the CLI and the GitHub Action.

    python -m tests.serve --api TMF620 --major 5 --url-file url.txt [--gap href='"urn"']

Each collection the spec can create is seeded with two conformant resources. `--gap` sets
one `Gaps` field from JSON (`--gap no_location=true`). The base URL is written to
`--url-file` once the server answers.
"""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from tests.conftest import seed
from tests.stub import Gaps, serve
from tmf_checker.spec import Spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--major", type=int, default=5)
    parser.add_argument("--url-file", required=True)
    parser.add_argument("--gap", action="append", default=[], help="FIELD=JSON")
    args = parser.parse_args()
    gaps = Gaps()
    for item in args.gap:
        name, _, value = item.partition("=")
        if not hasattr(gaps, name):
            parser.error(f"no such gap: {name}")
        setattr(gaps, name, json.loads(value))
    spec = Spec.bundled(args.api, args.major)
    with serve(spec, gaps) as stub:
        for resource in spec.resources():
            if resource.op("POST") and spec.request_schema(resource.op("POST")):
                seed(stub, resource.collection.lstrip("/"), 2, description="seeded")
        Path(args.url_file).write_text(stub.base_url + "\n")
        print(stub.base_url, flush=True)
        threading.Event().wait()


if __name__ == "__main__":
    main()
