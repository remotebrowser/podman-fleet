# AGENTS Instructions

This file provides guidance when working with code in this repository.

## Overview

A FastAPI server that orchestrates remote, containerized browsers over [CDP](https://developer.chrome.com/docs/devtools). It exposes a REST API plus WebSocket endpoints (CDP bridge). The server itself is stateless; browser sessions live in the Podman containers.

## Architecture

All code lives in the `podmanfleet` package (installed with `uv sync`); importing the package configures logging. The server is organized into a few concerns:

- HTTP layer — FastAPI app exposing a REST API under `/api/v1/browsers` (launch, terminate, query, list), health endpoints, and a server-rendered web UI at `/` (thumbnail grid built from the running browser ids; a small JS fetches activity stamps asynchronously). Static assets (`rfb.min.js`) are served from a static mount at `/`
- Browser orchestration — a browser is a Podman container named `chromium-{browser_id}`; ids are server-assigned at launch. Containers publish ports 9222 (CDP) and 5900 (VNC) to ephemeral host ports. Podman is driven via its CLI; remote Podman hosts are supported
- CDP bridge — WebSocket endpoints that relay CDP sessions verbatim between clients and containers, discovering debugger URLs via the container's CDP HTTP endpoints with retries
- Live view — a noVNC page plus a WebSocket↔TCP bridge to the container's VNC port
- Settings — pydantic-settings reading `.env`; see `.env.template` for keys

## Common Commands

```bash
# Dev server
make dev                                  # uvicorn on :8400, --reload

# Static analysis (matches CI + pre-push hook)
make check                                # all of the below
make check-backend-format                 # ruff check + ruff format --check
make format-backend                       # ruff format + ruff check --fix
make typecheck                            # ty check
make check-yaml-format                    # yamlfix --check

# Tests
make test                                 # unit tests (CI)
```

E2E tests in `tests/test_api_e2e.py` are marked `@pytest.mark.e2e` and excluded from `make test`; CI runs them against a live server with an otel-gui container verifying trace export. pytest runs with `--cov=podmanfleet --cov-report=term-missing` (see `pytest.ini`).

## Conventions

- Python 3.11+ — annotate returns and avoid `Any` drift
- ruff lint selects `I, UP045, UP006, UP007` (isort + modern typing) with `line-length = 100`, `preview = true`, `combine-as-imports`; first-party packages are `podmanfleet` and `tests`
- ty for typechecking (`invalid-argument-type` rule ignored in `pyproject.toml`)
- Logging via loguru (`from loguru import logger`), not stdlib logging
- Settings via pydantic `BaseSettings` reads `.env`; see `.env.template` for keys
