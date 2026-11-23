# Contributing

Thanks for your interest. The project is pre-alpha, so open an issue before larger changes.

## Setup

```sh
make install   # needs uv: https://docs.astral.sh/uv/
make check     # ruff + pytest; CI runs the same
```

## Rules

- One change per pull request, with a test that fails without it.
- `make fmt` before committing; CI fails on lint or format drift.
- A new check is documented in [docs/checks.md](docs/checks.md): what it sends, what counts
  as a gap, and the spec or TMF630 rule behind it.
- Bundled specs are never edited. To add one, follow
  [specs/README.md](src/tmf_checker/specs/README.md) and run `make specs-verify`.
- A quirk of an upstream spec (a typo, a contradiction) goes in
  [docs/spec-quirks.md](docs/spec-quirks.md) with a link to its source.
- Dependencies are locked in `uv.lock`; change them deliberately (`uv add`, `uv lock`).
