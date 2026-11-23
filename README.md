# tmf-checker

Check a TM Forum Open API implementation against the published specifications, from the
outside, over HTTP.

> **Status: pre-alpha.** `run` probes a live API with read-only checks and, when allowed,
> write checks; references to other APIs come from a fixtures file. See
> [docs/plan.md](docs/plan.md).

## Why

Schema validation alone says little about a TMF API. Almost every attribute in a TMF schema
is optional, so a server that silently drops what it does not store still returns valid
JSON. What integrators trip over is behaviour:

- an attribute is accepted on POST but never comes back, or comes back rewritten;
- the server requires attributes the spec leaves optional;
- `fields=` projections, paging headers and `Location` do not follow the TMF API design
  guidelines (TMF630);
- non-2xx responses are not the TMF `Error` body;
- PATCH content types listed in the spec are refused.

tmf-checker sends targeted requests, reads the answers back, and reports each gap as one
line, so a report can be committed as a baseline and locked in CI: fixing a gap means
deleting its line.

It complements, and does not replace, TM Forum's official Conformance Test Kits and
certification.

## Install

```sh
pip install tmf-checker        # or: uvx tmf-checker ...
```

Python 3.12 or newer.

## Use

```sh
# probe a running API (read-only): one line per gap, exit 1 if there are any
tmf-checker run --api TMF620 --major 4 --base-url http://localhost:8632

# also create, read back and delete resources; JSON report with request/response evidence
tmf-checker run --api TMF620 --base-url https://host/tmf-api/productCatalogManagement/v5 \
    --header "Authorization: Bearer $TOKEN" --allow-writes --json report.json

# references to other APIs (a party, a billing account) and a server's vocabulary
tmf-checker run --api TMF637 --base-url ... --allow-writes --fixtures fixtures.yaml --html report.html

# lock today's gaps, then fail CI only on new ones
tmf-checker run ... --baseline tmf-gaps.txt --update-baseline
tmf-checker run ... --baseline tmf-gaps.txt
```

Write checks on an API that references other APIs (an inventory product needs a billing
account and an offering) need existing resources to point at. Name them by class in a
fixtures file; anything without a fixture is reported as `unprobed ... no-fixture`, never
as a gap:

```yaml
# fixtures.yaml
values:                    # preferred values, for servers with a fixed vocabulary
  role: customer
Party: {id: "25fa...", "@referredType": Individual}
BillingAccount: {id: "aca9...", href: "https://host/tmf-api/accountManagement/v5/billingAccount/aca9..."}
ProductOffering: {id: "6a57..."}
```

Details: [docs/checks.md](docs/checks.md#values-and-fixtures).

A report looks like this (FIWARE's TMF620 v4 2.2.1, seeded, with writes; reported to FIWARE
as [tmforum-api#189](https://github.com/FIWARE/tmforum-api/issues/189)):

```
TMF620 GET /catalog href not-a-url
TMF620 GET /importJob unimplemented 404
TMF620 POST /productOffering error-body malformed-json
TMF620 POST /productOffering location missing
TMF620 POST /productOffering unprobed agreement no-fixture
```

`--base-url` is always the full API root. Checks: `errors`, `lists`, `fields` (default);
`location`, `requires`, `roundtrip`, `polymorphism`, `patch-formats`, `patch` (with
`--allow-writes`; orders also need `--allow-orders`); `missing` (opt-in). What each sends and
reports: [docs/checks.md](docs/checks.md). A check that cannot judge prints a `skipped` or
`unprobed` line with its reason; it never guesses.

### In GitHub Actions

```yaml
- uses: altharmz/tmf-checker@v0.1.0
  with:
    base-url: https://test-env.example.com/tmf-api/productCatalogManagement/v5
    api: TMF620
    baseline: tmf-gaps.txt          # fail only on gaps not in the baseline
    headers: |
      Authorization: Bearer ${{ secrets.TMF_TOKEN }}
    args: --allow-writes --fixtures tmf-fixtures.yaml
```

The step fails on new gaps (`exit-code` output: 0, 1 or 2) and uploads the HTML report as
the `tmf-checker-report` artifact. Other inputs: `major`, `spec`, `html`, `upload-report`,
`artifact-name`, `python-version` ([action.yml](action.yml)). Point it at a test
environment, never production.

Other commands:

```sh
tmf-checker specs                                   # bundled specs
tmf-checker operations --api TMF622 --major 4       # operations of a spec
tmf-checker validate --api TMF620 --schema ProductOffering body.json
tmf-checker validate --spec my-spec.yaml --schema Error - < body.json
```

`validate` exits 0 when the body conforms, 1 with one line per problem otherwise. Use
`--partial` for a `fields=` projection, where unselected required attributes are allowed.

### Why another validator

Stock OpenAPI validators fail on TMF v5 specs: every schema carries a discriminator that maps
its own name to itself next to `allOf`, and following it recurses forever. And the
`...RefOrValue` schemas are a `oneOf` of two permissive shapes, so plain JSON Schema finds a
reference valid under both and rejects it. tmf-checker selects the branch by `@type`. The
tests prove both failures and the fix.

## Bundled specs

TMF620, TMF622, TMF637, TMF666 and TMF678, each as v4 (Swagger 2.0) and v5 (OpenAPI 3.0),
unmodified from [tmforum-apis](https://github.com/tmforum-apis) at pinned commits, with
recorded upstream hashes: [specs/README.md](src/tmf_checker/specs/README.md). Any other spec
file can be passed with `--spec`.

## Safety

`run` sends only GETs unless `--allow-writes` is given. With it, tmf-checker creates
resources named `tmf-checker-<run id>` in the API under test and deletes them at the end,
reporting any it could not delete. Never point it at production. Credentials passed with
`--header` are redacted from all evidence.

## Development

```sh
make install   # uv sync
make check     # ruff + pytest
make help      # all targets
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence and trademarks

Apache License 2.0, see [LICENSE](LICENSE). The bundled specifications are © TM Forum,
also under Apache 2.0, see [NOTICE](NOTICE).

TM Forum, Open API and Open Digital Architecture are trademarks of TM Forum. This project is
independent, not affiliated with or endorsed by TM Forum, and its results are not a TM Forum
conformance certification.
