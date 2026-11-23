# Quirks of the upstream specs

Facts about the published TMF specs that a checker must work around. Each entry says where
it was seen and what tmf-checker does about it. Add new ones with a source.

| # | Quirk | Seen in | What we do |
|---|-------|---------|------------|
| 1 | Every v5 schema has a `discriminator` mapping its own name to itself next to `allOf`. Stock OAS validators (openapi-schema-validator) follow it and recurse forever. | all bundled v5 specs | `validate.TmfValidator` treats `allOf`/`anyOf` as plain JSON Schema. Proven in `tests/test_validate.py`. |
| 2 | `...RefOrValue` is a `oneOf` of two permissive schemas, so a plain reference is valid under both and plain JSON Schema rejects it. | all v5 specs | A `oneOf` with a discriminator validates only the branch `@type` selects. |
| 3 | v4 `basePath` includes `/tmf-api/...` with a trailing slash. TMF620 v5's server URL is `https://serverRoot/productCatalogManagement/v5/` without `/tmf-api`. TMF622, TMF637, TMF666 and TMF678 v5 declare only `https://serverRoot`, with no API path at all. | bundled specs | The base path cannot be derived from a v5 spec. The user always gives the API root URL. |
| 4 | v4 PATCH declares only `application/json;charset=utf-8`. v5 PATCH declares four types: `application/json`, `application/merge-patch+json`, `application/json-patch+json` and `application/json-patch-query+json` (TMF630). | bundled specs | The PATCH-format check probes what each spec declares. |
| 5 | TMF637 v5 `ProductStatusType` spells the last value `'aborted '`, with a trailing space. | TMF637 v5.0.0 | Compare enum values after `strip()` and report the typo as a spec quirk, not a server gap. |
| 6 | Example `href`s disagree with the server URL: TMF629 v5 examples say `customerManagement`, its server URL `customer/v5`; TMF632 examples say `party/v5`. | TMF629 v5.0.1, TMF632 v5.0.0 (not bundled yet) | When they disagree, the server URL wins, because generated clients use it. |
| 7 | Money `value` and Quantity `amount` are `type: number, format: float`. | v4 and v5 | Values are compared as decimals, never as floats. |
| 8 | TM Forum says the **conformance profile**, not the OAS or the CTK, is the source of truth when they disagree. The CTK may require attributes the OAS leaves optional (TMF702 `name`). | TM Forum Engage threads (see docs/plan.md, References) | Report against the OAS. Optionally accept a user-supplied profile later (M4). |
| 9 | `ProductOffering_FVO`, `ProductOfferingPrice_FVO` and `ProductSpecification_FVO` require `lastUpdate` and `lifecycleStatus` on create. A server usually sets both. | TMF620 v5.0.0 | The minimal body sends both, because the spec requires them. `roundtrip` treats `lastUpdate` as server-set, so a new value is not `rewritten`. |
| 10 | No bundled spec declares a `Location` header on the `201` of a POST. | all bundled specs | `location` checks a TMF630 rule, not the OAS. Its kind says so (`location`), and it can be turned off with `--checks`. |
| 11 | v4 list GETs declare only `200`, with `X-Result-Count` and `X-Total-Count`. TMF630 v4 describes `206` for partial pages. | all bundled v4 specs | A `200` for a partial page is not reported. |
| 12 | v5 POST, PATCH and DELETE declare `202` (asynchronous processing) next to `201`/`200`/`204`. | all bundled v5 specs | A `202` is not a gap. `roundtrip` and `location` skip that resource with the reason `async`. |
| 13 | TMF630 extension pattern: a subclass sends its own `@type` and names the class it extends in `@baseType`. The v5 discriminator mappings list only the spec's own classes. | TMF630; all v5 specs | Inside a discriminated `oneOf`, an unknown `@type` is validated as its `@baseType`. Proven in `tests/test_validate.py`. |
| 14 | List GETs declare `X-Result-Count` and `X-Total-Count` without `required: true` (OAS response headers are optional unless marked). | all bundled specs | `lists` reports a count header only when present and wrong, never when absent. |
| 15 | The OAS `components.examples` contain typos and mixed vocabularies: TMF637 v5 shows `priceType: reccurring`; TMF620 v5 uses `lifecycleStatus: Active` 78 times and `In Design` once. | TMF637 v5.0.0, TMF620 v5.0.0 | `values` uses the value the examples use **most** for a free string, so one typo does not win. A refusal of such a value is still reported, with the value in the evidence. |
