import asyncio

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from loguru import logger
from websockets.exceptions import ConnectionClosed

from podmanfleet import podman_browsers
from podmanfleet.podman_browsers import BROWSER_NAME_PREFIX

router = APIRouter()


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
                        logger.opt(lazy=True).debug(
                            "[CDP] Client -> Remote: {}", lambda: message[:100]
                        )
                        await remote_ws.send(message)
                except (WebSocketDisconnect, RuntimeError):
                    logger.info("[CDP] Client disconnected")
                except Exception as e:
                    logger.error(f"[CDP] client_to_remote error: {type(e).__name__}: {e}")

            async def remote_to_client() -> None:
                try:
                    async for message in remote_ws:
                        msg_text = message if isinstance(message, str) else message.decode()
                        logger.opt(lazy=True).debug(
                            "[CDP] Remote -> Client: {}", lambda: msg_text[:100]
                        )
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
