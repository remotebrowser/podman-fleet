from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from loguru import logger

from podmanfleet import podman_browsers
from podmanfleet.config import settings

router = APIRouter()


@router.get("/health")
def health():
    return PlainTextResponse(
        content=f"OK {int(datetime.now().timestamp())} GIT_REV: {settings.GIT_REV}"
    )


@router.get("/extended-health")
async def extended_health():
    # A fresh ephemeral browser per probe, terminated when done
    browser_id = await podman_browsers.launch_container()
    try:
        try:
            await podman_browsers.configure_browser(browser_id, None)
        except Exception:
            # A failed probe makes the browser unusable; terminate it rather than leak it.
            logger.warning(f"Terminating browser {browser_id} after probe failure")
            await podman_browsers.terminate_browser(browser_id)
            raise
        await podman_browsers.terminate_browser(browser_id)
        return PlainTextResponse(content="OK")
    except Exception as e:
        return PlainTextResponse(content=f"Error: {e}")
