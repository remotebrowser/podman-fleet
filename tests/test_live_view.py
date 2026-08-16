import pytest
from pytest import MonkeyPatch

from podmanfleet import live_view, podman_browsers


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
