import asyncio
import json
from typing import Any

import pytest
import websockets
from pytest import MonkeyPatch

from podmanfleet import api_router, podman_browsers
from podmanfleet.podman_browsers import ProxyVerificationError


def _patch_proxy(monkeypatch: MonkeyPatch, *, ips: list[str | None], proxy_ok: bool = True) -> None:
    """Force a configured proxy and drive get_container_public_ip's return sequence."""

    class _Cfg:
        def get_proxy_url(self, browser_id: str) -> str:
            return "http://proxy.example:9999"

    async def fake_get_proxy_config(*args: Any, **kwargs: Any) -> Any:
        return _Cfg()

    async def fake_configure_container(*args: Any, **kwargs: Any) -> bool:
        return proxy_ok

    it = iter(ips)

    async def fake_public_ip(*args: Any, **kwargs: Any) -> str | None:
        return next(it)

    monkeypatch.setattr(podman_browsers, "get_proxy_config", fake_get_proxy_config)
    monkeypatch.setattr(podman_browsers, "configure_container", fake_configure_container)
    monkeypatch.setattr(podman_browsers, "get_container_public_ip", fake_public_ip)


@pytest.mark.asyncio
async def test_configure_browser_ok_when_ip_before_missing(monkeypatch: MonkeyPatch) -> None:
    # Regression: a failed ip_before measurement (None) must NOT fail a working proxy.
    _patch_proxy(monkeypatch, ips=[None, "9.9.9.9"])
    ip = await podman_browsers.configure_browser("b0", None)
    assert ip == "9.9.9.9"


@pytest.mark.asyncio
async def test_configure_browser_raises_on_apply_failure(monkeypatch: MonkeyPatch) -> None:
    _patch_proxy(monkeypatch, ips=["1.1.1.1"], proxy_ok=False)
    with pytest.raises(ProxyVerificationError, match="Proxy failed to apply"):
        await podman_browsers.configure_browser("b0", None)


@pytest.mark.asyncio
async def test_configure_browser_raises_on_ip_check_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    # ip_after is None (curl/exec timeout): distinct, accurate error, not "IP unchanged".
    _patch_proxy(monkeypatch, ips=["1.1.1.1", None])
    with pytest.raises(ProxyVerificationError, match="IP check failed"):
        await podman_browsers.configure_browser("b0", None)


@pytest.mark.asyncio
async def test_configure_browser_raises_when_ip_unchanged(monkeypatch: MonkeyPatch) -> None:
    _patch_proxy(monkeypatch, ips=["1.1.1.1", "1.1.1.1"])
    with pytest.raises(ProxyVerificationError, match="IP unchanged"):
        await podman_browsers.configure_browser("b0", None)


@pytest.mark.asyncio
async def test_configure_browser_noop_without_proxy(monkeypatch: MonkeyPatch) -> None:
    # No proxy configured: it's a no-op that returns the current egress IP (no verification needed).
    async def fake_get_proxy_config(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_public_ip(*args: Any, **kwargs: Any) -> str | None:
        return "1.1.1.1"

    monkeypatch.setattr(podman_browsers, "get_proxy_config", fake_get_proxy_config)
    monkeypatch.setattr(podman_browsers, "get_container_public_ip", fake_public_ip)

    ip = await podman_browsers.configure_browser("b0", None)
    assert ip == "1.1.1.1"


def test_get_browser_never_reconfigures_proxy(monkeypatch: MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    configured = False

    async def fake_configure(*args: Any, **kwargs: Any) -> str | None:
        nonlocal configured
        configured = True
        return "9.9.9.9"

    async def fake_running(browser_id: str) -> bool:
        return True

    async def fake_query_info(browser_id: str) -> tuple[Any, Any]:
        return 1.0, "9.9.9.9"

    monkeypatch.setattr(podman_browsers, "configure_browser", fake_configure)
    monkeypatch.setattr(podman_browsers, "browser_is_running", fake_running)
    monkeypatch.setattr(podman_browsers, "query_browser_info", fake_query_info)

    app = FastAPI()
    app.include_router(api_router.router)
    client = TestClient(app)

    response = client.get(
        "/api/v1/browsers/b0",
        headers={"x-origin-ip": "1.2.3.4"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "browser_id": "b0",
        "last_activity_timestamp": 1.0,
        "ip": "9.9.9.9",
    }
    assert configured is False


def test_launch_browser_propagates_proxy_verification_error(monkeypatch: MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def fake_launch(*args: Any, **kwargs: Any) -> str:
        return "P12345678"

    async def fake_configure(*args: Any, **kwargs: Any) -> str | None:
        raise ProxyVerificationError("IP unchanged after proxy")

    killed: list[str] = []

    async def fake_kill(container_name: str) -> None:
        killed.append(container_name)

    monkeypatch.setattr(podman_browsers, "launch_container", fake_launch)
    monkeypatch.setattr(podman_browsers, "configure_browser", fake_configure)
    monkeypatch.setattr(podman_browsers, "kill_container", fake_kill)

    app = FastAPI()
    app.include_router(api_router.router)
    client = TestClient(app)

    response = client.post("/api/v1/browsers")
    assert response.status_code == 500
    assert len(killed) == 1
    assert killed[0].startswith("chromium-P")


@pytest.mark.asyncio
async def test_configure_container_returns_true_without_proxy() -> None:
    # No proxy_url: a no-op success (proxy is not required for this browser).
    assert await podman_browsers.configure_container("chromium-b0", None) is True


@pytest.mark.asyncio
async def test_list_browser_ids_strips_prefix_and_filters(monkeypatch: MonkeyPatch) -> None:
    async def fake_list_containers() -> list[str]:
        return ["chromium-Pabc12345", "otel-gui", "chromium-Pdef67890"]

    monkeypatch.setattr(podman_browsers, "list_containers", fake_list_containers)

    assert await podman_browsers.list_browser_ids() == ["Pabc12345", "Pdef67890"]


def test_launch_browser_auto_name_starts_with_b(monkeypatch: MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def fake_launch_container(*args: Any, **kwargs: Any) -> str:
        return "P12345678"

    async def fake_configure_browser(*args: Any, **kwargs: Any) -> str:
        return "1.2.3.4"

    monkeypatch.setattr(podman_browsers, "launch_container", fake_launch_container)
    monkeypatch.setattr(podman_browsers, "configure_browser", fake_configure_browser)

    app = FastAPI()
    app.include_router(api_router.router)
    client = TestClient(app)

    response = client.post("/api/v1/browsers")
    assert response.status_code == 200
    data = response.json()
    assert data["browser_id"].startswith("P")
    assert data["status"] == "launched"
    assert data["ip"] == "1.2.3.4"


class _FakeRemote:
    """A stand-in for the browser's CDP socket: records what the relay forwards, and answers
    every command with a canned result carrying the browser's own (raw) target id."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._replies: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, message: str) -> None:
        self.sent.append(message)
        await self._replies.put(json.dumps({"id": 1, "result": {"targetId": "abc1234567"}}))

    def __aiter__(self) -> "_FakeRemote":
        return self

    async def __anext__(self) -> str:
        return await self._replies.get()


class _FakeConnect:
    def __init__(self, remote: _FakeRemote) -> None:
        self._remote = remote

    async def __aenter__(self) -> _FakeRemote:
        return self._remote

    async def __aexit__(self, *args: Any) -> bool:
        return False


def _relay_roundtrip(monkeypatch: MonkeyPatch, path: str, sent_target_id: str) -> tuple[str, str]:
    """Drive one command through `path` and return (what the browser saw, what the client saw)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def fake_container_exists(container_name: str) -> bool:
        return True

    async def fake_get_cdp_url(browser_id: str) -> str:
        return "http://cdp"

    async def fake_get_browser_websocket_debugger_url(cdp_base_url: str) -> str:
        return "ws://remote/devtools/browser/xyz"

    remote = _FakeRemote()
    monkeypatch.setattr(podman_browsers, "container_exists", fake_container_exists)
    monkeypatch.setattr(podman_browsers, "get_cdp_url", fake_get_cdp_url)
    monkeypatch.setattr(
        podman_browsers,
        "get_browser_websocket_debugger_url",
        fake_get_browser_websocket_debugger_url,
    )
    monkeypatch.setattr(websockets, "connect", lambda url, **kwargs: _FakeConnect(remote))

    app = FastAPI()
    app.include_router(api_router.router)
    with TestClient(app).websocket_connect(path) as ws:
        ws.send_text(
            json.dumps({
                "id": 1,
                "method": "Target.attachToTarget",
                "params": {"targetId": sent_target_id},
            })
        )
        received: str = ws.receive_text()
    return remote.sent[0], received


def test_cdp_raw_route_relays_verbatim(monkeypatch: MonkeyPatch) -> None:
    to_browser, to_client = _relay_roundtrip(monkeypatch, "/api/v1/browsers/BID/cdp", "abc1234567")
    assert json.loads(to_browser)["params"]["targetId"] == "abc1234567"
    assert json.loads(to_client)["result"]["targetId"] == "abc1234567"
