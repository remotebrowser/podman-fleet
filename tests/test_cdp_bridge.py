import asyncio

import pytest
from pytest import MonkeyPatch

from podmanfleet import cdp_bridge, podman_browsers


@pytest.mark.asyncio
async def test_find_browser_id_returns_match_among_several(monkeypatch: MonkeyPatch) -> None:
    async def fake_list_containers() -> list[str]:
        return ["chromium-b1", "chromium-b2", "chromium-b3", "otel-gui"]

    async def fake_get_page_list(browser_id: str) -> list[str]:
        return ["pageA"] if browser_id == "b2" else ["other"]

    monkeypatch.setattr(podman_browsers, "list_containers", fake_list_containers)
    monkeypatch.setattr(cdp_bridge, "_get_page_list", fake_get_page_list)

    assert await cdp_bridge._find_browser_id("pageA") == "b2"


@pytest.mark.asyncio
async def test_find_browser_id_returns_none_when_no_match(monkeypatch: MonkeyPatch) -> None:
    async def fake_list_containers() -> list[str]:
        return ["chromium-b1", "chromium-b2"]

    async def fake_get_page_list(browser_id: str) -> list[str]:
        return ["other"]

    monkeypatch.setattr(podman_browsers, "list_containers", fake_list_containers)
    monkeypatch.setattr(cdp_bridge, "_get_page_list", fake_get_page_list)

    assert await cdp_bridge._find_browser_id("missing") is None


@pytest.mark.asyncio
async def test_find_browser_id_survives_one_browser_failing(monkeypatch: MonkeyPatch) -> None:
    """A single unreachable/booting browser must not sink the whole scan.

    Regression: the sequential version had no guard around opening the CDP client, so one bad
    browser raised past _find_browser_id and failed the request even when the target page was in
    a different, healthy browser.
    """

    async def fake_list_containers() -> list[str]:
        return ["chromium-flaky", "chromium-good"]

    async def fake_get_page_list(browser_id: str) -> list[str]:
        if browser_id == "flaky":
            raise ConnectionRefusedError("boom")
        return ["pageA"]

    monkeypatch.setattr(podman_browsers, "list_containers", fake_list_containers)
    monkeypatch.setattr(cdp_bridge, "_get_page_list", fake_get_page_list)

    assert await cdp_bridge._find_browser_id("pageA") == "good"


@pytest.mark.asyncio
async def test_find_browser_id_scans_concurrently(monkeypatch: MonkeyPatch) -> None:
    """The match should return without waiting for a slower, non-matching browser."""
    finished: list[str] = []

    async def fake_list_containers() -> list[str]:
        return ["chromium-slow", "chromium-fast"]

    async def fake_get_page_list(browser_id: str) -> list[str]:
        if browser_id == "slow":
            await asyncio.sleep(0.05)
            finished.append("slow")
            return ["other"]
        finished.append("fast")
        return ["pageA"]

    monkeypatch.setattr(podman_browsers, "list_containers", fake_list_containers)
    monkeypatch.setattr(cdp_bridge, "_get_page_list", fake_get_page_list)

    result = await cdp_bridge._find_browser_id("pageA")

    assert result == "fast"
    # Proves the scan doesn't wait for "slow" before checking "fast"'s result: if it did, this
    # would be sequential and "slow" would still finish first (it's listed first).
    assert finished[0] == "fast"
