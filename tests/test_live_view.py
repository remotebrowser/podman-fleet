from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from starlette.websockets import WebSocketDisconnect

from podmanfleet import live_view, podman_browsers
from podmanfleet.live_view import router as live_view_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(live_view_router)
    return TestClient(app)


@pytest.mark.asyncio
async def test_resolve_vnc_port_none_when_container_missing(monkeypatch: MonkeyPatch) -> None:
    """A stale cached port must not be trusted once the container is gone."""
    calls: list[str] = []

    async def fake_container_exists(container_name: str) -> bool:
        calls.append(container_name)
        return False

    async def fake_get_host_port(container_name: str, container_port: int) -> int | None:
        raise AssertionError("get_host_port must not be called when the container is missing")

    monkeypatch.setattr(podman_browsers, "container_exists", fake_container_exists)
    monkeypatch.setattr(podman_browsers, "get_host_port", fake_get_host_port)

    port = await live_view._resolve_vnc_port("dead1234")

    assert port is None
    assert calls == ["chromium-dead1234"]


@pytest.mark.asyncio
async def test_resolve_vnc_port_delegates_when_container_alive(monkeypatch: MonkeyPatch) -> None:
    async def fake_container_exists(container_name: str) -> bool:
        return True

    async def fake_get_host_port(container_name: str, container_port: int) -> int | None:
        assert container_name == "chromium-live1234"
        assert container_port == 5900
        return 54321

    monkeypatch.setattr(podman_browsers, "container_exists", fake_container_exists)
    monkeypatch.setattr(podman_browsers, "get_host_port", fake_get_host_port)

    port = await live_view._resolve_vnc_port("live1234")

    assert port == 54321


def test_live_view_rejects_xss_payload_without_reflecting_it() -> None:
    payload = '"><svg onload=alert(document.domain)>'

    response = _client().get(f"/live/{quote(payload, safe='')}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Browser not found"}
    assert "<svg" not in response.text
    assert payload not in response.text


def test_live_view_rejects_oversized_browser_id() -> None:
    response = _client().get(f"/live/{'a' * 21}")

    assert response.status_code == 404


def test_live_view_shows_placeholder_for_valid_but_unknown_browser_id(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_container_exists(container_name: str) -> bool:
        return False

    monkeypatch.setattr(podman_browsers, "container_exists", fake_container_exists)

    response = _client().get("/live/Pabc23456")

    assert response.status_code == 200
    assert "Live view unavailable" in response.text


def test_websockify_rejects_malformed_browser_id() -> None:
    payload = quote('"><svg onload=alert(1)>', safe="")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with _client().websocket_connect(f"/websockify/{payload}"):
            pass

    assert exc_info.value.code == 4404
    assert exc_info.value.reason == "Browser not found"
