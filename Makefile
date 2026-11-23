.DEFAULT_GOAL := help
.PHONY: help install lint fmt test check specs-verify build clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Create .venv with the locked dependencies (uv)
	uv sync --locked

lint: ## ruff check and format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format and fix what ruff can
	uv run ruff format .
	uv run ruff check --fix .

test: ## Unit tests (offline)
	uv run pytest

check: lint test ## Everything CI runs

specs-verify: ## Compare bundled specs with upstream blob SHAs (network)
	uv run python scripts/verify_specs_upstream.py
	cd src/tmf_checker/specs && sha256sum -c --quiet SHA256SUMS

build: ## Build sdist and wheel into dist/
	uv build

clean: ## Remove build and cache output
	rm -rf dist build .pytest_cache .ruff_cache
