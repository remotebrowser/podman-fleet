import asyncio
from typing import Any

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from loguru import logger
from websockets.exceptions import ConnectionClosed

from podmanfleet import podman_browsers
from podmanfleet.cdp_client import CDPClient, open_cdp_url
from podmanfleet.podman_browsers import BROWSER_NAME_PREFIX

router = APIRouter()


async def _open_browser_cdp_client(browser_id: str) -> CDPClient:
    cdp_base_url = await podman_browsers.get_cdp_url(browser_id)
    ws_url = await podman_browsers.get_browser_websocket_debugger_url(cdp_base_url)
    return await open_cdp_url(ws_url, timeout=10.0)


async def _get_page_list(browser_id: str) -> list[str]:
    # Enumerate browser-level pages via Target.getTargets; pages only.
    try:
        client = await _open_browser_cdp_client(browser_id)
    except Exception as e:
        logger.warning(f"[CDP] Could not open CDP client for {browser_id}: {type(e).__name__}: {e}")
        return []
    try:
        result = await client.send("Target.getTargets")
    except Exception as e:
        logger.warning(f"[CDP] Target.getTargets failed for {browser_id}: {type(e).__name__}: {e}")
        return []
    finally:
        await client.aclose()
    target_infos: list[dict[str, Any]] = result.get("targetInfos", [])
    return [str(info["targetId"]) for info in target_infos if info.get("type") == "page"]


async def _find_browser_id(page_id: str) -> str | None:
    containers = await podman_browsers.list_containers()
    browser_ids = [
        c[len(BROWSER_NAME_PREFIX) :] for c in containers if c.startswith(BROWSER_NAME_PREFIX)
    ]
    logger.debug(f"[CDP] scanning {len(browser_ids)} browser(s) for page_id={page_id}")

    async def _browser_has_page(browser_id: str) -> str | None:
        try:
            page_ids = await _get_page_list(browser_id)
        except Exception as e:
            logger.warning(f"[CDP] Could not check pages for {browser_id}: {type(e).__name__}: {e}")
            return None
        return browser_id if page_id in page_ids else None

    # Scan every browser concurrently instead of one at a time.
    tasks = [asyncio.create_task(_browser_has_page(browser_id)) for browser_id in browser_ids]
    try:
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                return result
        return None
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _websocket_bridge(client_ws: WebSocket, remote_url: str, browser_id: str) -> None:
    try:
        async with websockets.connect(
            remote_url,
            ping_interval=60,
            ping_timeout=30,
            close_timeout=10,
            max_size=10 * 1024 * 1024,
        ) as remote_ws:
            logger.info("[CDP] Connected to remote WebSocket")

            async def client_to_remote() -> None:
                try:
                    while True:
                        message = await client_ws.receive_text()
                        logger.debug(f"[CDP] Client -> Remote: {message[:100]}")
                        await remote_ws.send(message)
                except (WebSocketDisconnect, RuntimeError):
                    logger.info("[CDP] Client disconnected")
                except Exception as e:
                    logger.error(f"[CDP] client_to_remote error: {type(e).__name__}: {e}")

            async def remote_to_client() -> None:
                try:
                    async for message in remote_ws:
                        msg_text = message if isinstance(message, str) else message.decode()
                        logger.debug(f"[CDP] Remote -> Client: {msg_text[:100]}")
                        if client_ws.client_state == WebSocketState.CONNECTED:
                            await client_ws.send_text(msg_text)
                        else:
                            logger.debug("[CDP] Client not connected, breaking")
                            break
                except ConnectionClosed as e:
                    logger.info(f"[CDP] Remote disconnected: code={e.code} reason={e.reason}")
                except Exception as e:
                    logger.error(f"[CDP] remote_to_client error: {type(e).__name__}: {e}")

            tasks = [
                asyncio.create_task(client_to_remote()),
                asyncio.create_task(remote_to_client()),
            ]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    except OSError as e:
        logger.error(f"[CDP] Could not connect to remote: {e}")
        if client_ws.client_state == WebSocketState.CONNECTED:
            await client_ws.close(code=4502, reason="Remote server unreachable")
    except Exception as e:
        logger.error(f"[CDP] Unexpected error: {type(e).__name__}: {e}")
        if client_ws.client_state == WebSocketState.CONNECTED:
            await client_ws.close(code=4500, reason="Internal bridge error")
    finally:
        if client_ws.client_state == WebSocketState.CONNECTED:
            await client_ws.close()


async def _relay_browser_cdp(client_ws: WebSocket, browser_id: str) -> None:
    await client_ws.accept()
    logger.debug("[CDP] WebSocket accepted")

    if not await podman_browsers.container_exists(f"{BROWSER_NAME_PREFIX}{browser_id}"):
        logger.warning(f"[CDP] Browser {browser_id} not found")
        await client_ws.close(code=4404, reason="Browser not found")
        return

    # Retry resolving the browser's remote wss URL up to 10 times; first success wins.
    remote_url: str | None = None
    for attempt in range(10):
        try:
            cdp_base_url = await podman_browsers.get_cdp_url(browser_id)
            remote_url = await podman_browsers.get_browser_websocket_debugger_url(cdp_base_url)
        except Exception as e:
            logger.warning(
                f"[CDP] Attempt {attempt + 1}/10 failed to get debugger URL from {browser_id}: {e}"
            )
        if remote_url is not None:
            logger.info(f"[CDP] Got remote URL: {remote_url}")
            break
        if attempt < 9:
            logger.debug("[CDP] Retrying in 3 seconds...")
            await asyncio.sleep(3)
    else:
        logger.error("[CDP] All retry attempts exhausted")
        await client_ws.close(code=4502, reason="Failed to get debugger URL")
        return

    logger.info(f"[CDP] Client connected, bridging to {remote_url}")
    await _websocket_bridge(client_ws, remote_url, browser_id)


@router.websocket("/api/v1/browsers/{browser_id}/cdp")
async def cdp_browser_websocket_bridge_raw(client_ws: WebSocket, browser_id: str) -> None:
    logger.debug(f"[CDP] Entered cdp_browser_websocket_bridge_raw for browser_id={browser_id}")
    await _relay_browser_cdp(client_ws, browser_id)
    logger.debug("[CDP] cdp_browser_websocket_bridge_raw exiting")


@router.websocket("/devtools/{path:path}")
async def cdp_devtools_websocket_bridge(client_ws: WebSocket, path: str) -> None:
    logger.debug(f"[CDP] Entered cdp_devtools_websocket_bridge for path={path}")
    await client_ws.accept()
    logger.debug("[CDP] WebSocket accepted")

    # Resolve the page id from the path's last segment; scan browsers via Target.getTargets.
    parts = path.split("/")
    page_id = parts[-1] if parts else None
    if not page_id:
        logger.error("[CDP] No page_id in path")
        await client_ws.close(code=4000, reason="No page_id in path")
        return

    logger.debug(f"[CDP] Looking for page_id={page_id}")
    browser_id = await _find_browser_id(page_id)
    if browser_id:
        logger.debug(f"[CDP] Found page {page_id} in browser {browser_id}")
    else:
        logger.error(f"[CDP] Page {page_id} not found in any browser")
        await client_ws.close(code=4000, reason="Page not found in any browser")
        return

    # Retry resolving the per-page remote wss URL up to 10 times; first success wins.
    remote_url: str | None = None
    for attempt in range(10):
        try:
            cdp_base_url = await podman_browsers.get_cdp_url(browser_id)
            remote_url = await podman_browsers.get_page_websocket_debugger_url(
                cdp_base_url, page_id
            )
        except Exception as e:
            logger.warning(
                f"[CDP] Attempt {attempt + 1}/10 failed to get page URL for "
                f"{browser_id}/{page_id}: {e}"
            )
        if remote_url is not None:
            logger.info(f"[CDP] Got page remote URL: {remote_url}")
            break
        if attempt < 9:
            logger.debug("[CDP] Retrying in 3 seconds...")
            await asyncio.sleep(3)
    else:
        logger.error(f"[CDP] Could not get websocket URL for page {page_id}")
        await client_ws.close(code=4502, reason="Failed to get page websocket URL")
        return

    logger.info(f"[CDP] Connecting to {remote_url}")
    await _websocket_bridge(client_ws, remote_url, browser_id)
    logger.debug("[CDP] cdp_devtools_websocket_bridge exiting")
