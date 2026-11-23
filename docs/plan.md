# Plan

What the project is, the decisions taken, and the road to v0.1.0. Update it when a decision
changes. Record decisions here, not in issues.

## Goal and positioning

An open-source CLI that checks a running TM Forum Open API implementation against the
published OAS, from the outside, over HTTP, and reports each gap as one stable line. A
report can be committed as a baseline and locked in CI.

- **For:** vendors preparing for TM Forum certification, operators checking a vendor's
  API before buying, integrators, ODA component builders.
- **Complements** TM Forum's official Conformance Test Kits (CTKs). It is a CI linter for
  the time before certification, never a certification. No "TM Forum" in the name or
  branding (trademark); "for TM Forum Open APIs" in descriptions is fine.
- **Differentiator:** TMF-specific behaviour that generic OpenAPI tools (Schemathesis,
  Specmatic) don't check: attributes dropped or rewritten in a round trip, attributes the
  server requires but the spec doesn't, TMF630 list and `fields=` rules, the `Error`
  body, PATCH formats, `@type` polymorphism, and later hub events.

### Market check (2026-11-22)

- **Official CTKs:** the public ones (github.com/tmforum-rand/CTK-*, 2021) are v4 Postman
  collections under TM Forum's RAND licence. v5 kits come from the TM Forum portal (login).
  The ODA Component CTK (github.com/tmforum-oda/oda-component-ctk, Apache-2.0) tests a
  Kubernetes component's metadata and bundles only v4 TMF620, TMF637 and TMF669 kits.
- **Reported CTK pain** (TM Forum Engage): spec/kit mismatches, mock endpoints needed just
  to pass, harness bugs, invalid definitions. TM Forum says the conformance profile, not the
  OAS or the kit, is the source of truth.
- **No third-party TMF conformance tool found** on GitHub. The closest are generic tools
  (Schemathesis, Specmatic's TMF621 example) and two small mock servers.
- **Expect a niche:** TMF repositories get 10-60 stars. Measure success by users, forum
  mentions and consulting leads, not stars.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Name, owner, licence | `tmf-checker`, `github.com/altharmz/tmf-checker`, Apache-2.0 | The human's choice. Apache-2.0 matches the bundled specs |
| Visibility | Public from M3 (2026-11-23); history squashed to one commit first | Publish with a real finding, not an empty repo. The squash keeps notes on a private test target out of the public history |
| Language and tooling | Python >= 3.12, uv (`uv.lock`), hatchling, ruff, pytest, argparse | Light. Reuses proven code. Few dependencies |
| Runtime dependencies | jsonschema, referencing, pyyaml. No HTTP library: the client is `urllib` (2026-11-22, replaces "httpx in M1"). openapi-schema-validator dropped (2026-11-23, M3): `nullable`, the readOnly/writeOnly `required` rule and the `date-time` check are a few lines in `validate.py` | Nothing else without a reason; the client needs no pooling or async. The drop removed nine packages, among them the compiled pydantic-core |
| Spec versions | v4 (Swagger 2.0) **and** v5 (OAS 3.0) from day one | FIWARE's implementation, the best public target, serves **v4**. The private v5 target serves v5 |
| Bundled APIs | TMF620, 622, 637, 666, 678, v4 and v5, unmodified, pinned, with upstream blob SHAs | The core commerce APIs. Any other spec works with `--spec` |
| Base URL | Always the full API root given by the user | Most v5 specs declare no API path (docs/spec-quirks.md #3) |
| Safety | Read-only by default; writes need `--allow-writes`; created resources are named `tmf-checker-<run id>` and deleted where the API allows | It writes to someone else's API |
| Output | One line per gap: `<API> <METHOD> <path> <kind> <detail>`, sorted, stable; plus JSON (with evidence) and later HTML reports | The proven baseline idea: a fix deletes a line, anything new fails CI |
| Skips | A check that cannot judge emits `skipped <check> <reason>` or `unprobed <attr> <reason>`; 403 is a skip, 401 stops the run | Never silence, never a false gap |
| Baseline | `--baseline` fails on new lines only and lists fixed ones; `--update-baseline` keeps comments attached to their gap | A fix should not break CI; the update is one command |
| Opt-in checks | `missing` runs only with `--checks missing` | Absent data and a server that drops look the same |
| Ground truth | The OAS. A user-supplied conformance profile later (M4) | Profiles are member-only and can't be bundled |

## Architecture

```
src/tmf_checker/
  spec.py        load v4/v5, resolve, walk schemas, operations, resources
  validate.py    TMF-aware JSON Schema validation; issues() as stable (path, keyword)
  cli.py         specs, operations, validate, run
  client.py      urllib client: API root, extra headers, timeouts, redacted request log
  values.py      values for a schema; references to fixtures of the same API
  findings.py    Finding, kinds, line format, baseline compare and update
  report.py      text and JSON (HTML in M2)
  runner.py      selected checks over every resource, then cleanup
  checks/        errors, lists, fields, missing, create (location, roundtrip, cleanup)
  fixtures/      (M2) YAML per API: how to create resources of other APIs
tests/stub.py    spec-driven stub server, one switch per deliberate gap
```

Checks (planned catalogue in [checks.md](checks.md)): `errors`, `lists`, `fields`,
`location`, `roundtrip`, `requires`, `patch-formats`, `polymorphism`, later `hub`.

### Black-box round trip (the core algorithm)

An in-process probe can classify a refusal by reading its own error messages. A generic
tool can't. Most implementations silently ignore unknown attributes,
so gaps are found by reading back:

1. Build a minimal valid body: the spec's required attributes, with values from examples,
   enums, formats or types, plus fixture references. POST it. Expect 201, a `Location`
   equal to `href`, and a body that validates.
2. For each other attribute of the request schema (`_FVO` / `_Create`), one at a time (M1:
   top level; M2: one level into objects and arrays): POST the minimal body plus it.
   - **4xx:** `refused` (keep the status and the error `reason`).
   - **2xx:** GET by id. Then `kept` if equal after normalisation (date-times to UTC,
     decimals, server-set attributes ignored), `dropped` if absent, `rewritten` otherwise.
3. **requires:** a body with only the spec's required attributes is refused. Find the
   culprits by adding optional attributes one at a time.
4. **reads:** for each top-level resource attribute, a `fields=<attr>` GET. Report
   `missing` when no created resource ever returns it, and `fields-ignored` when other
   attributes come back (TMF630 allows only `id`, `href` and `@type` besides the
   selection).
5. Delete created resources where DELETE exists; report what could not be cleaned up.

## Milestones

| Milestone | Scope | Exit |
|---|---|---|
| **M0** (done) | Repo, licence, NOTICE, CI, 10 specs with provenance, loader, validator, CLI `specs`/`operations`/`validate`, tests | `make check` green; pushed (private) |
| **M1 spike** (done, go/no-go below) | `client.py`, `findings.py`, `values.py`; read-only checks `errors`, `lists`, `fields`, response validation; `roundtrip` and `location` for TMF620 (no cross-API dependencies); `run` with text and JSON output; tests against a small stub server | **Go/no-go:** run against FIWARE TMF620 v4 and a private v5 implementation. Go if it finds real, non-trivial gaps the FIWARE maintainers confirm |
| **M2** (done, exit below) | Fixtures and write checks for TMF622, 637, 666, 678; `patch-formats`, `requires`, `polymorphism`; baseline compare and update; HTML report | Against a private v5 implementation, reproduces its own locked gap list (below) or explains each difference |
| **M3 launch** | Public repo, `v0.1.0` tag, PyPI via trusted publishing, a composite GitHub Action, README with a sample report, FIWARE results published after notifying them | Release out |
| **M4 later** | Hub registration and event payloads (local listener), user-supplied conformance profile, more APIs, TMF630 filters | — |

### M1 task list (done 2026-11-22, branch `m1-spike`)

- [x] `client.py` (stdlib, not httpx), `--header`, timeouts, redacted evidence log
- [x] `findings.py`, `report.py` (text, JSON), baselines
- [x] `checks/errors.py`: unknown id (shaped like a real one), malformed JSON (writes);
      no unknown-path probe: no spec defines it, and gateways answer it
- [x] `checks/lists.py`: items and listed ids validate, count headers (spec-quirks #14),
      `href` (TMF630), paging
- [x] `checks/fields.py`; `checks/missing.py` (opt-in)
- [x] `values.py`, `checks/create.py` (`location`, `roundtrip`, cleanup with a retry pass)
- [x] `run`: `--api --major --spec --base-url --header --allow-writes --checks --resource
      --json --baseline --update-baseline --timeout`
- [x] Tests: `tests/stub.py`; every check proven both ways
- [x] Spike targets: FIWARE TMF620 v4 and a private TMF620 v5 implementation (below)
- [x] Go/no-go write-up (below)

### M1 go/no-go (2026-11-22)

**Recommendation: go, with one open condition** (FIWARE confirmation, the human's step).

How the targets ran, without changing either project:

- **FIWARE** `quay.io/fiware/tmforum-product-catalog:2.2.1` with Orion-LD 1.9.0 and
  MongoDB 4.0 (compose file in the session scratchpad; Docker Hub was unreachable, so
  `mirror.gcr.io`). API root `http://host:8632` (no `/tmf-api` prefix). Its committed
  `api/tm-forum/product-catalog/api.json` equals upstream TMF620 4.1.0 (paths and
  definitions).
- **The private v5 target** (a BSS with its own in-process conformance probe and a locked
  gap list) from its own image with a fresh database, unchanged. Its details stay out of
  this repository.

What tmf-checker found, each read from the evidence:

| Target | Line | Verdict |
|---|---|---|
| FIWARE | `POST /{catalog,category,productOffering,productOfferingPrice,productSpecification} error-body malformed-json` (5) | **Real.** Malformed JSON gets Micronaut's default body (`message`, `_links`, `_embedded`), not the TMF `Error`; FIWARE's own errors do use `Error` |
| FIWARE | `POST ... location missing` (5) | **Real** (TMF630, not the OAS: spec-quirks #10). No `Location` on 201 |
| FIWARE | `GET /importJob unimplemented 404`, `GET /exportJob unimplemented 404` | **Real**, likely known to FIWARE |
| FIWARE | `GET /{catalog,category,productOffering,productOfferingPrice,productSpecification} href not-a-url` (5) | **Real** (TMF630): `href` is the URN id (`urn:ngsi-ld:catalog:...`), so a client cannot follow it |
| FIWARE | (read-only, seeded) paging, `fields`, item validation | No gaps: FIWARE honours paging and projections |
| FIWARE | `roundtrip` over every TMF620 attribute with a same-API fixture | No `dropped`/`rewritten`: FIWARE stores what it accepts |
| Private | `POST /category refused subCategory` | **Real, and new**: `Category_FVO` lets a client set `subCategory`; the server refuses it as server-set. Not in its locked list |
| Private | `POST /productOfferingPrice create-status minimal` | **Real, and new**: a recurring price without `recurringChargePeriodType` (optional in the spec) is refused |
| Private | (read-only, seeded) lists, paging, `fields`, `href`, errors | No gaps, which agrees with its locked list (no TMF620 lines) |

Not reported, noted for a robustness check later: before the reference rules (below),
FIWARE answered 500 to a v4 `bundledProductOffering` without `id`, which the v4 schema
allows.

False positives found and fixed on the way (each now a test):

1. Made-up references (`relatedParty` with `id: tmf-checker`, `parentId`) refused by a
   server that checks references: references now point at created fixtures or are
   `unprobed ... no-fixture`.
2. v4 references without `Ref` in their name (`RelatedParty`, `BundledProductOffering`):
   detected by `@referredType` / `Bundled` + `id`.
3. A made-up `lifecycleStatus` refused by a vocabulary: free strings use the spec's
   examples (spec-quirks #15).
4. 403 (an account not yet allowed to call) read as `error-status`: 403 is now a skip.
5. Cleanup refused while another created resource referenced the target: a retry pass.

Against the exit criterion: the gaps are real and confirmed by evidence; "non-trivial"
holds for the two private-target findings, which its own in-process probe missed, and for FIWARE's
error body. **Open:** the FIWARE maintainers have not confirmed anything; contacting them
is the human's call (draft an issue for the error body and `Location`).

### M3 task list (next)

Decisions taken (the human, 2026-11-23):
- **Contact FIWARE:** yes. Filed
  [FIWARE/tmforum-api#189](https://github.com/FIWARE/tmforum-api/issues/189) on
  2026-11-23 after reproducing each finding with curl on 2.2.1 (still their latest
  release): the malformed-JSON error body, no `Location`, `href` is the URN id. Left out:
  `missing pricingLogicAlgorithm.href` / `tax.href` (M2), a probe artefact: the run sent
  those values without `href` and FIWARE returned exactly what it was sent; `href` is
  optional there. Also left out: `importJob`/`exportJob` 404 (not implemented, likely
  known).
- **Drop `openapi-schema-validator`:** yes. Done: a differential run of the old and new
  validator over 86,824 generated bodies (every schema of the ten bundled specs, with
  nulls, wrong types and dropped attributes) gave identical issues; the `date-time` check
  matched `rfc3339-validator` on 400,000 fuzzed strings except a trailing newline, which
  the library's `$` accepted and we now reject.
- **Go public:** yes, now. Done: the private repository (PRs #1-#4, whose diffs named
  a private test target) was renamed `altharmz/tmf-checker-private` and kept private; a
  new public `altharmz/tmf-checker` starts from one squashed commit of the scrubbed tree,
  with the same merge settings. Commits use the GitHub noreply address.

Work:
- [ ] FIWARE TMF637/666 v4 runs (images `quay.io/fiware/tmforum-product-inventory:2.2.1`,
      `tmforum-account:2.2.1`; quay's CDN failed on 2026-11-22, retry).
- [x] `v0.1.0`: version bump, CHANGELOG release section, `make build` check. The tag
      `v0.1.0` is pushed once the PyPI trusted publisher exists.
- [x] PyPI via trusted publishing: `.github/workflows/release.yml` (tag `v*`: tests, tag
      equals `__version__`, build, publish from environment `pypi`, GitHub release with the
      CHANGELOG section). The pending publisher on PyPI is the human's step.
- [x] Composite GitHub Action (`action.yml`): install, `run` with a baseline, upload the
      HTML report.
- [x] README: a sample report (FIWARE TMF620, linked to the FIWARE issue), the fixtures
      file, the Action. The Action installs from its own ref (no PyPI needed) and is tested
      end to end in CI against `tests/serve.py`.
- [x] `missing` false positive: a nested attribute of a value the run itself sent without
      it (FIWARE `pricingLogicAlgorithm.href`) is not the server's gap. `Context.sent`
      records the top-level attributes each created resource was sent (POST and PATCH);
      `missing` reads one level into the other values only. The stub reproduced the two
      FIWARE lines before the fix.
- [ ] Not started, candidates: a robustness check (a 5xx for a spec-valid body; FIWARE
      answered 500 to a v4 `bundledProductOffering` without `id`), `missing` on TMF678
      with real bills (needs a target with billing history).

### M2 task list (done 2026-11-22, branch `m2`)

- [x] `--fixtures FILE` (YAML): existing resources by class, for references to other APIs;
      `<Scope>.<Class>` (may be `null`) and a `values:` section of preferred values
      (`role: customer`, `FinancialAccount.role: owner`). A class the API under test can
      create is created by the run and the fixture is only the fallback: in an early run a
      category probe linked itself to the user's fixture offering and changed it.
      Creating fixtures through another API's endpoint stays deferred.
- [x] `requires`: discovery of an accepted body (attributes the refusal names, all, each
      alone, all but one), then removal proves each culprit (400/422 only). The server's
      minimal body is the base for every write check.
- [x] `roundtrip` one level in, for optional and required object attributes.
- [x] `patch-formats` (a real change per type, read back) and `patch` (`read-only`,
      `dropped`, `rewritten`).
- [x] `polymorphism` (`@baseType`).
- [x] `--html FILE`; `--allow-orders` (orders start processes).
- [x] Runs against the private v5 target, all five bundled APIs (below).
- [x] FIWARE TMF620 v4 again, with every M2 check: `requires`, `polymorphism`,
      `patch-formats` and `patch` find it conformant; the only new lines are `missing
      pricingLogicAlgorithm.href` and `missing tax.href` (embedded entities without an
      `href`, a kind the private target locks too; on FIWARE a probe artefact, see M3).
      FIWARE TMF637/666 v4: not run,
      quay.io's CDN kept resetting the image downloads; first thing for M3.

### M2 exit (2026-11-22): against the private v5 target

Run from its own image with a fresh database and fixtures made through its own TMF APIs
(an individual, a customer, a billing account, an offering and a price).

- **Its 7 comparable locked lines:** 3 reproduced (TMF637 `requires` x2, TMF666 `missing`
  one level deep). 4 not reproduced: TMF678 `missing` on bills and applied rates, which a
  fresh instance does not have (a billing worker makes them at a period end). `missing`
  runs and says `skipped missing no-items`; the same mechanism reproduces the TMF666
  nested line.
- **Lines its locked list does not have:** each read from the evidence, all real by the
  OAS rule and most of them deliberate design: server-set attributes refused from clients,
  dates rewritten to a billing-day boundary, fixed values, conditional requirements,
  server-built values lacking nested attributes, and resources not deletable in their
  lifecycle state (`cleanup-failed`). Its probe runs in process and reads its own
  messages; these lines say what an outside client sees against the OAS.

**False positives found on it and fixed** (each now a test): a refused made-up free
string (`ratingType`, a vocabulary) is `unprobed made-up-value`; a no-op PATCH may be
refused, so `patch-formats` changes something; a PATCH or create to the current value or
in conflict with state (409) is `unprobed same-value` / `conflict`; a reference's `name`
may be refreshed (compare by `id`); names and nested ids are unique; a nested `X_MVO`
value is completed as `X_FVO`; error keys (`status`) are not attribute names; `missing`
does not look into references, skips explained and leftover resources, and runs after the
writes; the run creates its own same-API references instead of linking to fixtures.

### Pre-spike analysis (2026-11-22)

What the specs and the targets say before any probing code exists. Decisions taken from it:

- **The two targets do different jobs.** The private v5 target serves TMF620 and TMF622 v5
  from byte-identical spec files and its locked list has **no** TMF620/622 lines; its probe
  refuses unknown attributes and looks one level into returned values. Against it, every
  TMF620 attribute finding is a false positive until shown otherwise; only behaviour
  checks (`lists`, `fields`, `errors`, `location`, `rewritten`) can find new gaps there.
  FIWARE (v4) is the gap-discovery target. Go/no-go needs both: real gaps on FIWARE, and
  every private-target finding explained.
- **Only 7 of its locked lines are comparable** (TMF637 `requires` x2, TMF666 `missing` x1, TMF678
  `missing` x4). Five are `missing` on read-only resources (customer bills, applied rates)
  that no TMF API call creates: `missing` must read whatever the list returns, and M2's
  exit uses the target's own data.
- **Kinds to add** to match that list: `missing` one level deep (`a.b`), `read-only` (an
  attribute refused on PATCH), `unprobed` (could not look below an attribute, with the
  reason) and `content-type`. A skip is a line with a reason, never silence.
- **Baseline files** keep `#` comments and blank lines (a locked list explains each accepted
  gap inline); comparison ignores them.
- **The OAS rules, not TMF630 folklore** (spec-quirks #9-#12): no `206` rule; `Location` is a
  TMF630 rule no spec declares, so it gets its own kind; `202` means async, so `roundtrip`
  and `location` skip with the reason `async`; TMF620 v5 create requires `lastUpdate` and
  `lifecycleStatus`.
- **Validator** (done in this pass): an extension subtype inside a RefOrValue (`@type`
  unknown, `@baseType` known) was a false positive; it is now validated as its base type.
  A non-string `@type` crashed the validator; it is now an error.
- **Validator, done in M1:** `date-time` is format-checked (RFC 3339) through
  jsonschema's `FormatChecker`, which uses the already-installed `rfc3339-validator`; a
  `null` is one `null-value` line per attribute (`validate.issues`).
- **Proposed, needs the human (runtime dependency):** `openapi-schema-validator` 0.9 pulls
  in pydantic, pydantic-core (compiled), pydantic-settings and python-dotenv. We already
  replace its `oneOf`/`allOf`/`anyOf`, the part that recursed on TMF specs; what is left
  is `nullable` and the OAS format checker, a few dozen lines on top of jsonschema's
  `Draft4Validator` (jsonschema's own `FormatChecker` does `date-time` with
  `rfc3339-validator`). Dropping it removes seven packages, among them the compiled
  pydantic-core.

## Risks

- **TM Forum automates v5 CTKs** and the gap closes: position as the CI linter that runs
  first; stay complementary.
- **Test data:** cross-API references (an order needs an offering, an account, a party) are
  the hard part. Fixtures are declarative, and missing ones degrade to skipping with a
  reason, never to a false gap.
- **False positives** destroy trust. Every finding carries evidence (request, response)
  and an exact kind, and every check is proven both ways in tests.

## References

- TM Forum CTK threads: [extra endpoints and mocks](https://engage.tmforum.org/discussion/tmf-ctk-compliance-handling-extra-endpoints-and-mock-implementations),
  [TMF702 spec vs CTK](https://engage.tmforum.org/discussion/tmf702-discrepancy-between-specification-and-ctk-on-resource-name-mandatory-attribute),
  [TMF681 v4](https://engage.tmforum.org/discussion/tmf681-communication-management-v40-inconsistencies),
  [TMF638 v5 CTK](https://engage.tmforum.org/discussion/issues-found-during-tmf638-v5-ctk-testing),
  [TMF620 v5 CTK](https://engage.tmforum.org/discussion/tmf620-v5000-ctk-expected-results-file-mismatch)
- [TM Forum certification process](https://www.tmforum.org/conformance-certification/process-overview),
  [Open API CTK install guide](https://projects.tmforum.org/wiki/x/cAuyB)
- [tmforum-apis](https://github.com/tmforum-apis) (specs, Apache-2.0),
  [tmforum-rand CTKs](https://github.com/tmforum-rand),
  [ODA Component CTK](https://github.com/tmforum-oda/oda-component-ctk)
- [FIWARE/tmforum-api](https://github.com/FIWARE/tmforum-api)
- Generic tools: [Schemathesis](https://schemathesis.readthedocs.io/en/stable/),
  [Specmatic TMF example](https://awesome.ecosyste.ms/projects/github.com%2Fznsio%2Fspecmatic-examples-tmf)
