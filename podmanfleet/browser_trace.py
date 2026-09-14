"""Read-only access to a browser container's `browser-trace` HTTP server.

browser-trace listens on `BROWSER_TRACE_PORT` inside every browser container and
serves the session's application logs. The port is published to an ephemeral
host port, which callers cannot discover, so the fleet server passes the logs
through under the browser's own API path.
"""

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from loguru import logger

from podmanfleet import podman_browsers
from podmanfleet.podman_browsers import BROWSER_NAME_PREFIX, BROWSER_TRACE_PORT

router = APIRouter()

_TIMEOUT = 10.0


async def _trace_base_url(browser_id: str) -> str:
    if not podman_browsers.is_valid_browser_id(browser_id):
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found!")
    container_name = f"{BROWSER_NAME_PREFIX}{browser_id}"
    if not await podman_browsers.container_exists(container_name):
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found!")
    host_port = await podman_browsers.get_host_port(container_name, BROWSER_TRACE_PORT)
    if not host_port:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found!")
    return f"http://{podman_browsers.container_host()}:{host_port}"


@router.get("/api/v1/browsers/{browser_id}/logs")
async def get_browser_logs(browser_id: str) -> dict[str, Any]:
    base_url = await _trace_base_url(browser_id)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{base_url}/logs")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        detail = f"Unable to read logs for browser {browser_id}!"
        logger.error(f"{detail} Exception={e}")
        raise HTTPException(status_code=502, detail=detail)
