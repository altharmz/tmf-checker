# tmf-checker

Open-source Python CLI that checks TM Forum Open API implementations against the published
specs, over HTTP. Pre-alpha. Plan, decisions and the M1 task list:
[docs/plan.md](docs/plan.md). Read it before starting work, and record new decisions there.

## Commands

```
make install        # uv sync --locked
make check          # ruff + pytest (what CI runs)
make fmt            # auto-format
make specs-verify   # bundled specs vs upstream (network)
make build          # sdist + wheel
```

## Layout

- `src/tmf_checker/spec.py` loader and schema walking (v4 Swagger 2.0, v5 OAS 3.0)
- `src/tmf_checker/validate.py` TMF-aware validator (see its docstring)
- `src/tmf_checker/cli.py` argparse CLI
- `src/tmf_checker/profile.py` `--profile` conformance profile (rules in its docstring)
- `src/tmf_checker/specs/` bundled specs, unmodified, provenance in its README
- `docs/checks.md` check catalogue · `docs/spec-quirks.md` upstream quirks

## Rules

- Small, light, few dependencies. Ask before adding a runtime dependency.
- Every check is proven both ways in tests: it finds the gap, and it passes when the gap is
  fixed. A false positive is worse than a missed gap.
- Never edit bundled specs. A quirk goes in `docs/spec-quirks.md` with its source.
- Probing is read-only unless `--allow-writes`. Never point tests or examples at real
  services; tests use a local stub server.
- Keep "TM Forum" out of names and branding, and never claim certification.
- Work on a branch with a PR to `main`. CI must be green. Update `CHANGELOG.md`
  (Unreleased) with user-visible changes.
- Private test targets are never named in tracked files. Their notes, if any, are in the
  gitignored `CLAUDE.local.md`.
