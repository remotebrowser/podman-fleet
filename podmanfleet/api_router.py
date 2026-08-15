from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from podmanfleet import podman_browsers
from podmanfleet.cdp_bridge import router as cdp_router
from podmanfleet.live_view import router as vnc_router
from podmanfleet.podman_browsers import ProxyVerificationError

router = APIRouter()


@router.post("/api/v1/browsers")
async def launch_browser(request: Request) -> dict[str, Any]:
    logger.info("Launching browser (server-assigned id)...")
    try:
        origin_ip = request.headers.get("x-origin-ip")
        browser_id = await podman_browsers.launch_container()
        try:
            ip = await podman_browsers.configure_browser(browser_id, origin_ip)
        except ProxyVerificationError:
            logger.warning(f"Terminating browser {browser_id} after proxy verification failure")
            await podman_browsers.terminate_browser(browser_id)
            raise
        logger.info(f"Browser {browser_id} is launched.")
        return {
            "browser_id": browser_id,
            "status": "launched",
            "ip": ip,
        }
    except Exception as e:
        detail = "Unable to launch browser!"
        logger.error(f"{detail} Exception={e}")
        raise HTTPException(status_code=500, detail=detail)


@router.delete("/api/v1/browsers/{browser_id}")
async def terminate_browser(browser_id: str) -> dict[str, Any]:
    logger.info(f"Terminating browser {browser_id}...")
    if not await podman_browsers.browser_exists(browser_id):
        detail = f"Browser {browser_id} not found!"
        logger.warning(detail)
        raise HTTPException(status_code=404, detail=detail)
    try:
        await podman_browsers.terminate_browser(browser_id)
        logger.info(f"Browser {browser_id} is terminated.")
        return {"browser_id": browser_id, "status": "terminated"}
    except Exception as e:
        detail = f"Unable to terminate browser {browser_id}!"
        logger.error(f"{detail} Exception={e}")
        raise HTTPException(status_code=500, detail=detail)


@router.get("/api/v1/browsers/{browser_id}")
async def get_browser(browser_id: str) -> dict[str, Any]:
    logger.info(f"Querying browser {browser_id}...")
    if not await podman_browsers.browser_is_running(browser_id):
        detail = f"Browser {browser_id} not found!"
        logger.warning(detail)
        raise HTTPException(status_code=404, detail=detail)
    last_activity_timestamp, ip = await podman_browsers.query_browser_info(browser_id)
    logger.debug(f"Browser {browser_id}: last_activity_timestamp={last_activity_timestamp}.")
    return {
        "browser_id": browser_id,
        "last_activity_timestamp": last_activity_timestamp,
        "ip": ip,
    }


@router.get("/api/v1/browsers")
async def list_browsers() -> JSONResponse:
    logger.info("Enumerating all browsers...")
    try:
        return JSONResponse(await podman_browsers.list_browser_ids())
    except Exception as e:
        detail = "Unable to list all browsers"
        logger.error(f"{detail} Exception={e}")
        raise HTTPException(status_code=500, detail=detail)


router.include_router(cdp_router)
router.include_router(vnc_router)
