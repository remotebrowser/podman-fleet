import asyncio
import os
import subprocess
import sys
from typing import Any, cast

import httpx
from async_lru import alru_cache
from loguru import logger
from nanoid import generate

from podmanfleet.config import settings
from podmanfleet.residential_proxy import get_proxy_config

_DOCKER_INTERNAL_HOST = "172.17.0.1"

# Shared name prefix: a browser with id `abc` is a podman container named `chromium-abc`.
BROWSER_NAME_PREFIX = "chromium-"

# Charset for server-assigned browser ids (no ambiguous 0/O, 1/l or vowels that spell words).
_FRIENDLY_CHARS = "23456789abcdefghijkmnpqrstuvwxyz"


# uvloop's child process watcher can cause asyncio.create_subprocess_exec to hang
# indefinitely. When uvloop is the active event loop, fall back to running the
# subprocess in a thread via asyncio.to_thread to avoid the deadlock.
def _is_uvloop() -> bool:
    return type(asyncio.get_event_loop()).__module__.startswith("uvloop")


def _run_podman_sync(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )


async def _run_podman(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["podman"]
    if settings.CONTAINER_HOST:
        cmd.append("--remote")
    cmd.extend(args)

    if _is_uvloop():
        return await asyncio.to_thread(_run_podman_sync, cmd)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    assert proc.returncode is not None
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(
        args=cmd, returncode=proc.returncode, stdout=stdout, stderr=stderr
    )


# Cache port mappings since they are fixed a container's lifetime.
@alru_cache(maxsize=128)
async def _get_host_port_cached(container_name: str, container_port: int) -> int | None:
    try:
        result = await _run_podman(["port", container_name, str(container_port)])
        port_mapping = result.stdout.strip()
        if not port_mapping:
            return None
        return int(port_mapping.split(":")[-1])
    except subprocess.CalledProcessError:
        return None


async def get_host_port(container_name: str, container_port: int) -> int | None:
    host_port = await _get_host_port_cached(container_name, container_port)
    if host_port is None:
        _get_host_port_cached.cache_invalidate(container_name, container_port)
    return host_port


def _evict_host_port_cache(container_name: str) -> None:
    for port in (9222, 5900):
        _get_host_port_cached.cache_invalidate(container_name, port)


async def launch_container(image_name: str | None = None) -> str:
    browser_id = "P" + generate(_FRIENDLY_CHARS, 8)
    container_name = f"{BROWSER_NAME_PREFIX}{browser_id}"
    image = image_name or settings.CONTAINER_IMAGE
    logger.info(f"Launching Chromium container as {container_name}...")
    cmd = [
        "run",
        "-d",
        "--rm",
        "--name",
        container_name,
    ]
    if settings.CONTAINER_HOST:
        cmd.extend(["--cpus", "1", "--memory", "2048m"])
    if sys.platform == "darwin":
        cmd.append("--privileged")

    cmd.extend([
        "-p",
        "9222",
        "-p",
        "5900",
        image,
    ])
    try:
        result = await _run_podman(cmd)
        if result.returncode == 0 and result.stdout:
            container_id = result.stdout.strip()
            cdp_port = await get_host_port(container_name, 9222)
            vnc_port = await get_host_port(container_name, 5900)
            logger.info(
                f"Container started: name={container_name} id={container_id} cdp_port={cdp_port} vnc_port={vnc_port}"
            )
            return browser_id
        raise Exception(f"Unable to launch Chromium for {container_name}")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Unable to launch Chromium for {container_name}: {e}")


async def container_exists(container_name: str) -> bool:
    try:
        result = await _run_podman(["container", "exists", container_name])
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False


async def browser_exists(browser_id: str) -> bool:
    """Check whether the container backing `browser_id` exists."""
    return await container_exists(f"{BROWSER_NAME_PREFIX}{browser_id}")


async def _container_is_running(container_name: str) -> bool:
    try:
        result = await _run_podman([
            "inspect",
            "--format",
            "{{.State.Running}}",
            container_name,
        ])
        return result.stdout.strip() == "true"
    except subprocess.CalledProcessError:
        return False


async def browser_is_running(browser_id: str) -> bool:
    """Check whether the container backing `browser_id` is running."""
    return await _container_is_running(f"{BROWSER_NAME_PREFIX}{browser_id}")


async def kill_container(container_name: str) -> None:
    logger.info(f"Killing Chromium container {container_name}...")
    try:
        result = await _run_podman(["kill", container_name])
        if result.returncode == 0 and result.stdout:
            logger.info(f"Container killed: name={container_name}")
        else:
            raise Exception(f"Unable to kill container {container_name}")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Unable to kill container {container_name}: {e}")
    finally:
        _evict_host_port_cache(container_name)


async def terminate_browser(browser_id: str) -> None:
    """Terminate the container backing `browser_id`."""
    container_name = f"{BROWSER_NAME_PREFIX}{browser_id}"
    await kill_container(container_name)


async def list_containers() -> list[str]:
    logger.debug("Retrieving the list of all containers...")
    try:
        result = await _run_podman(["container", "ls", "--format", "{{.Names}}"])
        if result.returncode == 0:
            containers = result.stdout.splitlines() if result.stdout else []
            logger.debug(f"All containers obtained. Total={len(containers)}")
            return containers
        else:
            raise Exception("Unable to list all containers")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Unable to list all containers: {e}")


async def list_browser_ids() -> list[str]:
    containers = await list_containers()
    return [c[len(BROWSER_NAME_PREFIX) :] for c in containers if c.startswith(BROWSER_NAME_PREFIX)]


async def _get_container_last_activity(container_name: str) -> float | None:
    try:
        await _run_podman([
            "exec",
            container_name,
            "sh",
            "-c",
            "cp /home/user/chrome-profile/Default/History db",
        ])

        result = await _run_podman([
            "exec",
            container_name,
            "sqlite3",
            "db",
            "select MAX(last_visit_time) from urls;",
        ])

        if result.returncode == 0 and result.stdout:
            chromium_time = float(result.stdout.strip())
            unix_epoch = (chromium_time / 1_000_000) - 11644473600
            return unix_epoch
        return None
    except subprocess.CalledProcessError:
        return None
    except Exception:
        return None


async def configure_container(container_name: str, proxy_url: str | None) -> bool:
    """Apply `proxy_url` (an http://... upstream) to the container's tinyproxy.

    Returns True if the proxy was applied (or `proxy_url` was None, a no-op success). Returns False
    if any `podman exec` step failed, so the caller (`configure_browser`) can raise a
    `ProxyVerificationError`."""
    if not proxy_url:
        return True
    logger.info(f"Configuring container {container_name} with proxy_url={proxy_url}...")
    try:
        upstream = proxy_url.removeprefix("http://")
        logger.debug(f"Configuring proxy with upstream: {upstream}")
        logger.info(f"Modifying tinyproxy.conf in {container_name}...")
        await _run_podman([
            "exec",
            container_name,
            "sed",
            "-i",
            "/^Upstream http/d",
            "/app/tinyproxy.conf",
        ])
        await _run_podman([
            "exec",
            container_name,
            "sed",
            "-i",
            f"$ a\\Upstream http {upstream}",
            "/app/tinyproxy.conf",
        ])
        logger.info(f"Restarting tinyproxy in {container_name}...")
        await _run_podman([
            "exec",
            container_name,
            "sh",
            "-c",
            "pkill tinyproxy || true",
        ])
        await _run_podman([
            "exec",
            container_name,
            "sh",
            "-c",
            "tinyproxy -d -c /app/tinyproxy.conf &",
        ])
        logger.info(f"Proxy configured successfully in {container_name}.")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(
            f"Proxy config failed on {container_name}: {type(e).__name__}: {e.stderr.strip()!r}"
        )
        return False
    except Exception as e:
        logger.warning(f"Proxy config failed on {container_name}: {type(e).__name__}: {e}")
        return False


def container_host() -> str:
    return _DOCKER_INTERNAL_HOST if os.path.exists("/.dockerenv") else "127.0.0.1"


async def get_container_public_ip(
    container_name: str, *, retries: int = 5, retry_delay: float = 2.0
) -> str | None:
    for attempt in range(1, retries + 1):
        try:
            result = await _run_podman([
                "exec",
                container_name,
                "curl",
                "-s",
                "--max-time",
                "10",
                "--proxy",
                "http://127.0.0.1:8119",
                "https://ip.fly.dev",
            ])
            ip = result.stdout.strip() or None
            if ip:
                return ip
            logger.debug(
                f"IP check attempt {attempt}/{retries} in {container_name}: empty response (stderr: {result.stderr.strip()!r})"
            )
        except subprocess.CalledProcessError as e:
            logger.debug(
                f"IP check attempt {attempt}/{retries} in {container_name} failed (exit {e.returncode}): {e.stderr.strip()!r}"
            )
        except Exception as e:
            logger.debug(f"IP check attempt {attempt}/{retries} in {container_name} failed: {e}")
        if attempt < retries:
            await asyncio.sleep(retry_delay)
    logger.warning(f"IP check in {container_name} failed after {retries} attempts")
    return None


async def query_browser_info(browser_id: str) -> tuple[float | None, str | None]:
    """Return the last-activity timestamp and public IP for `browser_id`."""
    container_name = f"{BROWSER_NAME_PREFIX}{browser_id}"
    last_activity_timestamp = await _get_container_last_activity(container_name)
    ip = await get_container_public_ip(container_name)
    return last_activity_timestamp, ip


async def configure_browser(
    browser_id: str,
    origin_ip: str | None,
) -> str | None:
    """Apply the residential proxy to the container and verify the egress IP changed.

    The proxy is mandatory when one is configured: it MUST apply and change the egress IP,
    otherwise this raises `ProxyVerificationError` (the endpoint maps it to 500, so the client can
    retry rather than get an unproxied browser). If no proxy is configured, this is a no-op (proxy
    is not required) and the current egress IP is returned."""
    container_name = f"{BROWSER_NAME_PREFIX}{browser_id}"
    proxy_config = await get_proxy_config(origin_ip, settings)
    proxy_url = proxy_config.get_proxy_url(browser_id) if proxy_config else None

    ip_before = await get_container_public_ip(container_name)
    logger.debug(f"Browser {browser_id} IP before applying config: {ip_before}")

    if not proxy_url:
        return ip_before  # no proxy configured; proxy is not required for this browser

    ok = await configure_container(container_name, proxy_url)
    if not ok:
        raise ProxyVerificationError(f"Proxy failed to apply on {container_name}")

    ip_after = await get_container_public_ip(container_name)
    if ip_after is None:
        raise ProxyVerificationError(
            f"Could not verify egress IP on {container_name} (IP check failed)"
        )
    if ip_before is not None and ip_before == ip_after:
        raise ProxyVerificationError(f"Browser {browser_id} IP unchanged after proxy: {ip_before}")
    logger.info(f"Browser {browser_id} IP changed: {ip_before} -> {ip_after}")
    return ip_after


async def get_cdp_url(browser_id: str) -> str:
    container_name = f"{BROWSER_NAME_PREFIX}{browser_id}"
    host_port = await get_host_port(container_name, 9222)
    if not host_port:
        raise Exception(f"CDP port not found for {container_name}")
    return f"http://{container_host()}:{host_port}"


def _rewrite_ws_url(ws_url: str, cdp_base_url: str) -> str:
    """Rewrite a CDP webSocketDebuggerUrl to use the cdp_base_url's scheme/host/port.

    Chrome reports webSocketDebuggerUrl against the Host it saw (e.g. ws://localhost:9222/...).
    This points the websocket at the same scheme+host+port we reached CDP on (https -> wss),
    keeping the path/query. For local containers the host already matches, so it is a no-op.
    """
    base = httpx.URL(cdp_base_url)
    scheme = "wss" if base.scheme == "https" else "ws"
    return str(httpx.URL(ws_url).copy_with(scheme=scheme, host=base.host, port=base.port))


async def get_browser_websocket_debugger_url(cdp_base_url: str) -> str:
    """Discover the browser-level `webSocketDebuggerUrl` from a CDP endpoint's
    `/json/version`, rewritten to ride over the same scheme/host/port as `cdp_base_url`.

    The local container exposes a per-browser HTTP CDP endpoint but no pre-baked wss connect
    URL: callers resolve the cdp base URL (per browser, see `get_cdp_url`) and then this helper
    does the standard /json/version probe. May raise on a missed boot race (chrome not ready
    yet) — the caller in cdp_bridge retries 10x before giving up.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{cdp_base_url}/json/version")
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        logger.debug(f"[CDP] CDP json version gives {data}")
        return _rewrite_ws_url(str(data["webSocketDebuggerUrl"]), cdp_base_url)


async def get_page_websocket_debugger_url(cdp_base_url: str, page_id: str) -> str | None:
    """Discover the per-page `webSocketDebuggerUrl` for `page_id` from a CDP endpoint's
    `/json/list`, rewritten to ride over the same scheme/host/port as `cdp_base_url`.

    The local container exposes per-page webSocketDebuggerUrls over HTTP — callers resolve the
    cdp base URL (per browser, see `get_cdp_url`) and then this helper does the standard
    /json/list probe. Returns None when the page id is not present in the listing (page already
    closed or not yet registered).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{cdp_base_url}/json/list")
        response.raise_for_status()
        raw: Any = response.json()
        if not isinstance(raw, list):
            return None
        for item in cast(list[dict[str, Any]], raw):
            if item.get("id") == page_id:
                ws_url = item.get("webSocketDebuggerUrl")
                return _rewrite_ws_url(str(ws_url), cdp_base_url) if ws_url else None
        return None


class ProxyVerificationError(Exception):
    """Raised when a configured (mandatory) proxy fails to apply or the egress IP is unchanged.

    The launch endpoint maps it to HTTP 500 so the client can retry rather than receive an
    unproxied browser."""
