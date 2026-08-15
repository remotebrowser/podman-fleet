import asyncio
import json
from typing import Any, cast

import websockets
import websockets.asyncio.client

# WebSocket open timeout, sized to cover a browser that is still cold-starting.
_CDP_OPEN_TIMEOUT_SECONDS = 120.0


async def open_cdp_url(ws_url: str, timeout: float | None = None) -> "CDPClient":
    """Open a CDP client against a direct wss URL Used by router helpers that
    need to enumerate page targets on backends that have no /json/list HTTP endpoint."""
    ws = await websockets.connect(
        ws_url,
        open_timeout=timeout if timeout is not None else _CDP_OPEN_TIMEOUT_SECONDS,
    )
    return CDPClient(ws)


class CDPClient:
    def __init__(self, ws: websockets.asyncio.client.ClientConnection) -> None:
        self._ws: Any = ws
        self._id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            while True:
                raw = await self._ws.recv()
                if not isinstance(raw, str):
                    continue
                try:
                    loaded: Any = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(loaded, dict):
                    continue
                data: dict[str, Any] = cast(dict[str, Any], loaded)
                msg_id: Any = data.get("id")
                if isinstance(msg_id, int) and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if future.done():
                        continue
                    if "error" in data:
                        error_info: Any = data["error"]
                        if isinstance(error_info, dict):
                            message = str(error_info.get("message", "CDP error"))
                        else:
                            message = f"CDP error: {error_info}"
                        future.set_exception(Exception(message))
                    else:
                        result: Any = data.get("result", {})
                        if isinstance(result, dict):
                            future.set_result(result)
                        else:
                            future.set_result({})
        except Exception:
            pass
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(Exception("CDP connection closed"))
        self._pending.clear()

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._id += 1
        msg_id = self._id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        msg: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id
        await self._ws.send(json.dumps(msg))
        return await future

    async def aclose(self) -> None:
        if not self._reader_task.done():
            self._reader_task.cancel()
        try:
            await self._reader_task
        except (asyncio.CancelledError, Exception):
            pass
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(Exception("CDP client closed"))
        self._pending.clear()
        try:
            await self._ws.close()
        except Exception:
            pass
