import os
from collections.abc import Generator

import httpx
import pytest

PODMANFLEET_URL = os.getenv("PODMANFLEET_URL", "http://localhost:8400")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=PODMANFLEET_URL, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
async def async_client():
    async with httpx.AsyncClient(base_url=PODMANFLEET_URL, timeout=30.0) as c:
        yield c


@pytest.mark.e2e
class TestHealthEndpoint:
    def test_health_returns_ok(self, client: httpx.Client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert "OK" in response.text


@pytest.mark.e2e
class TestBrowserLifecycle:
    @pytest.fixture(autouse=True)
    def cleanup(self, client: httpx.Client) -> Generator[None, None, None]:
        self.browser_ids: list[str] = []
        yield
        for browser_id in self.browser_ids:
            try:
                client.delete(f"/api/v1/browsers/{browser_id}")
            except Exception:
                pass

    def test_launch_browser(self, client: httpx.Client) -> None:
        response = client.post("/api/v1/browsers")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "launched"
        browser_id = data["browser_id"]
        self.browser_ids.append(browser_id)
        assert browser_id

    def test_get_browser(self, client: httpx.Client) -> None:
        create = client.post("/api/v1/browsers")
        browser_id = create.json()["browser_id"]
        self.browser_ids.append(browser_id)
        response = client.get(f"/api/v1/browsers/{browser_id}")
        assert response.status_code == 200
        data = response.json()
        assert "last_activity_timestamp" in data

    def test_get_nonexistent_browser(self, client: httpx.Client) -> None:
        response = client.get("/api/v1/browsers/nonexistent-browser")
        assert response.status_code == 404

    def test_terminate_browser(self, client: httpx.Client) -> None:
        create = client.post("/api/v1/browsers")
        browser_id = create.json()["browser_id"]
        self.browser_ids.append(browser_id)
        response = client.delete(f"/api/v1/browsers/{browser_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "terminated"
        self.browser_ids.remove(browser_id)

    def test_terminate_nonexistent_browser(self, client: httpx.Client) -> None:
        response = client.delete("/api/v1/browsers/nonexistent-browser")
        assert response.status_code == 404


@pytest.mark.e2e
class TestBrowserListing:
    def test_list_browsers(self, client: httpx.Client) -> None:
        response = client.get("/api/v1/browsers")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
