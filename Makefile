.DEFAULT_GOAL := dev

.PHONY: dev
dev:
	uv run -m uvicorn podmanfleet.main:app --reload --host 127.0.0.1 --port 8400

.PHONY: format-backend
format-backend:
	uv run ruff format
	uv run ruff check --fix

.PHONY: check-backend-format
check-backend-format:
	uv run ruff check
	uv run ruff format --check

.PHONY: format-yaml
format-yaml:
	uv run yamlfix $$(find . -type f \( -name '*.yml' -o -name '*.yaml' \) | grep -v -E '\.venv/')

.PHONY: check-yaml-format
check-yaml-format:
	uv run yamlfix --check $$(find . -type f \( -name '*.yml' -o -name '*.yaml' \) | grep -v -E '\.venv/')

.PHONY: format
format: format-backend format-yaml

.PHONY: typecheck
typecheck:
	uv run ty check

.PHONY: test
test:
	uv run pytest -m "not e2e"

.PHONY: e2e-test
e2e-test:
	uv run pytest -v -s tests/test_api_e2e.py

.PHONY: check
check: check-backend-format check-yaml-format typecheck
