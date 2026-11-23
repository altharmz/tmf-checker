# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- TMF620, TMF622, TMF637, TMF666 and TMF678 specs, v4 and v5, with upstream provenance.
- Spec loader for Swagger 2.0 and OpenAPI 3.0 with schema walking.
- TMF-aware schema validator (discriminator branches, self-mapping discriminators).
- CLI: `specs`, `operations`, `validate`.
- `run`: probe a live API and report one stable line per gap; `--allow-writes`,
  `--checks`, `--resource`, `--header`, `--json` (with evidence), `--baseline` and
  `--update-baseline`. Exit 0 (no gaps, or none new), 1 (gaps), 2 (error).
- Checks `errors`, `lists` (items, listed ids, count headers, `href`, paging), `fields`,
  `missing` (opt-in), and with `--allow-writes` `location` and `roundtrip`; everything
  created is deleted.
- The validator checks `date-time` values (RFC 3339) and reports a `null` once.
- `--fixtures FILE`: existing resources by class for references to other APIs, class-scoped
  entries, and preferred `values:` for a server's vocabulary.
- Checks `requires` (names each attribute the server requires and the spec does not),
  `polymorphism`, `patch-formats` and `patch`; `roundtrip` one level into objects.
- `--html FILE` report; `--allow-orders` (orders are not created without it).

### Fixed

- The validator accepts a TMF630 extension subtype inside a `...RefOrValue` (an unknown
  `@type` with a known `@baseType`) and validates it as that base type. A non-string
  `@type` is an error instead of a crash.
