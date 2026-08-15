from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from podmanfleet import podman_browsers
from podmanfleet.index_view import router as index_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(index_router)
    return TestClient(app)


def test_index_renders_thumbnails_for_running_browsers(monkeypatch: MonkeyPatch) -> None:
    async def fake_list_browser_ids() -> list[str]:
        return ["Pabc12345", "Pdef67890"]

    monkeypatch.setattr(podman_browsers, "list_browser_ids", fake_list_browser_ids)

    response = _client().get("/")
    assert response.status_code == 200
    html = response.text
    assert "2 browser(s) running:" in html
    for browser_id in ("Pabc12345", "Pdef67890"):
        # Server-rendered thumbnail: live-view link, live-view iframe, activity placeholder.
        assert f'href="/live/{browser_id}"' in html
        assert f'src="/live/{browser_id}"' in html
        assert f'id="{browser_id}-activity"' in html
    # Ids are embedded so the JS can fetch activity stamps asynchronously.
    assert 'const browserIds = ["Pabc12345", "Pdef67890"];' in html


def test_index_uses_vendored_assets_only(monkeypatch: MonkeyPatch) -> None:
    async def fake_list_browser_ids() -> list[str]:
        return []

    monkeypatch.setattr(podman_browsers, "list_browser_ids", fake_list_browser_ids)

    html = _client().get("/").text
    assert '<link rel="stylesheet" href="/style.css" />' in html
    assert "formatRelativeTime" in html
    for external in ("cdn.jsdelivr.net", "unpkg.com", "oat.min.css", "timeago"):
        assert external not in html


def test_index_without_browsers(monkeypatch: MonkeyPatch) -> None:
    async def fake_list_browser_ids() -> list[str]:
        return []

    monkeypatch.setattr(podman_browsers, "list_browser_ids", fake_list_browser_ids)

    response = _client().get("/")
    assert response.status_code == 200
    assert "No browsers running!" in response.text
    assert "const browserIds = [];" in response.text


def test_index_shows_error_when_enumeration_fails(monkeypatch: MonkeyPatch) -> None:
    async def fake_list_browser_ids() -> list[str]:
        raise Exception("podman unreachable")

    monkeypatch.setattr(podman_browsers, "list_browser_ids", fake_list_browser_ids)

    response = _client().get("/")
    assert response.status_code == 200
    assert "Error loading browsers" in response.text
    assert "const browserIds = [];" in response.text
