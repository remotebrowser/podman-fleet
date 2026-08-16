import asyncio

from fastapi import APIRouter, WebSocket
from fastapi.responses import HTMLResponse

from podmanfleet import podman_browsers
from podmanfleet.podman_browsers import BROWSER_NAME_PREFIX

router = APIRouter()


async def _resolve_vnc_port(browser_id: str) -> int | None:
    container_name = f"{BROWSER_NAME_PREFIX}{browser_id}"
    if not await podman_browsers.container_exists(container_name):
        return None
    return await podman_browsers.get_host_port(container_name, 5900)


@router.get("/live/{browser_id}", response_model=None)
async def vnc_live_viewer(browser_id: str) -> HTMLResponse:
    vnc_port = await _resolve_vnc_port(browser_id)
    if vnc_port is not None:
        page = f"""<!DOCTYPE html>
<html>
<head>
    <title>{browser_id} - Live View</title>
    <style>
        body {{ margin: 0; background: #000; }}
        #screen {{ width: 100vw; height: 100vh; }}
    </style>
</head>
<body>
    <div id="screen"></div>
    <script type="module">
        import RFB from '/rfb.min.js';

        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = wsScheme + '://' + window.location.host + '/websockify/{browser_id}';

        const rfb = new RFB(
            document.getElementById('screen'),
            wsUrl
        );
        rfb.scaleViewport = true;
    </script>
</body>
</html>"""
        return HTMLResponse(page)

    # No local VNC port: the browser is idle or stopped. Show a placeholder instead of a dead
    # noVNC screen.
    page = f"""<!DOCTYPE html>
<html>
<head>
    <title>{browser_id} - Live View</title>
    <style>
        html, body {{
            margin: 0; height: 100%;
            display: flex; align-items: center; justify-content: center;
            background: #111; color: #aaa;
            font-family: system-ui, sans-serif; text-align: center;
        }}
        .msg {{ padding: 1rem; font-size: 0.9rem; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="msg">Live view unavailable<br>The browser is idle or stopped. Use it to resume.</div>
</body>
</html>"""
    return HTMLResponse(page)


@router.websocket("/websockify/{browser_id}")
async def websockify_proxy(websocket: WebSocket, browser_id: str) -> None:
    vnc_port = await _resolve_vnc_port(browser_id)
    if vnc_port is None:
        await websocket.close()
        return
    host = podman_browsers.container_host()

    client_subprotocol = websocket.headers.get("sec-websocket-protocol")
    if client_subprotocol and "binary" in [p.strip() for p in client_subprotocol.split(",")]:
        await websocket.accept(subprotocol="binary")
    else:
        await websocket.accept()

    try:
        reader, writer = await asyncio.open_connection(host, vnc_port)
    except Exception:
        await websocket.close()
        return

    async def ws_to_vnc() -> None:
        try:
            while True:
                data = await websocket.receive_bytes()
                writer.write(data)
                await writer.drain()
        except Exception:
            pass

    async def vnc_to_ws() -> None:
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    await asyncio.gather(ws_to_vnc(), vnc_to_ws())
    writer.close()
    await writer.wait_closed()
