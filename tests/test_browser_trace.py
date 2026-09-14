from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from podmanfleet import browser_trace, podman_browsers
from podmanfleet.browser_trace import router as browser_trace_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(browser_trace_router)
    return TestClient(app)


def _alive(monkeypatch: MonkeyPatch, *, host_port: int | None = 51234) -> None:
    async def fake_container_exists(container_name: str) -> bool:
        return True

    async def fake_get_host_port(container_name: str, container_port: int) -> int | None:
        assert container_port == podman_browsers.BROWSER_TRACE_PORT
        return host_port

    monkeypatch.setattr(podman_browsers, "container_exists", fake_container_exists)
    monkeypatch.setattr(podman_browsers, "get_host_port", fake_get_host_port)


def test_logs_rejects_malformed_browser_id() -> None:
    payload = quote('"><svg onload=alert(1)>', safe="")

    response = _client().get(f"/api/v1/browsers/{payload}/logs")

    assert response.status_code == 404


def test_logs_404_when_container_missing(monkeypatch: MonkeyPatch) -> None:
    async def fake_container_exists(container_name: str) -> bool:
        return False

    monkeypatch.setattr(podman_browsers, "container_exists", fake_container_exists)

    response = _client().get("/api/v1/browsers/Pabc23456/logs")

    assert response.status_code == 404


def test_logs_404_when_trace_port_unpublished(monkeypatch: MonkeyPatch) -> None:
    """An older container image without browser-trace must not read as a server error."""
    _alive(monkeypatch, host_port=None)

    response = _client().get("/api/v1/browsers/Pabc23456/logs")

    assert response.status_code == 404


def test_logs_returns_browser_trace_payload(monkeypatch: MonkeyPatch) -> None:
    _alive(monkeypatch)
    requested: list[str] = []

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            requested.append(url)
            return httpx.Response(
                200,
                json={"logs": [{"message": "hi", "tab_id": "T1"}]},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(browser_trace.httpx, "AsyncClient", FakeClient)

    response = _client().get("/api/v1/browsers/Pabc23456/logs")

    assert response.status_code == 200
    assert response.json() == {"logs": [{"message": "hi", "tab_id": "T1"}]}
    assert requested == [f"http://{podman_browsers.container_host()}:51234/logs"]


def test_logs_502_when_browser_trace_is_unreachable(monkeypatch: MonkeyPatch) -> None:
    _alive(monkeypatch)

    class FailingClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FailingClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(browser_trace.httpx, "AsyncClient", FailingClient)

    response = _client().get("/api/v1/browsers/Pabc23456/logs")

    assert response.status_code == 502
