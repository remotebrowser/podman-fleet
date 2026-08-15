import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from loguru import logger

from podmanfleet import podman_browsers

router = APIRouter()


def _thumbnail_html(browser_id: str) -> str:
    """Server-rendered thumbnail card for one browser: a live-view link, an activity-stamp
    placeholder (filled in asynchronously by the page's JS), and the noVNC iframe behind a
    click-shielding overlay."""
    return f"""<div id="{browser_id}" style="padding: 10px">
        <a href="/live/{browser_id}" target="_blank" style="font-weight: bold">{browser_id}</a>
        <span
          id="{browser_id}-activity"
          style="font-size: 0.8em; color: #666; margin-left: 16px"
        ></span>
        <div style="position: relative; width: 100%">
          <iframe
            src="/live/{browser_id}"
            style="width: 100%; aspect-ratio: 16 / 9; border: 1px solid #888; margin-top: 8px"
          ></iframe>
          <div
            style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; background-color: transparent"
          ></div>
        </div>
      </div>"""


def _index_page(browser_ids: list[str], status: str) -> str:
    thumbnails = "\n      ".join(_thumbnail_html(browser_id) for browser_id in browser_ids)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Podman Fleet</title>
    <link rel="stylesheet" href="/style.css" />
  </head>

  <body>
    <h1>Podman Fleet</h1>
    <p id="status">{status}</p>
    <div
      id="browsers-grid"
      style="display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 15px"
    >
      {thumbnails}
    </div>
    <script>
      // The browser ids and thumbnails are rendered server-side; only the activity stamps are
      // fetched here — asynchronously and in parallel, while the live-view iframes load.
      const browserIds = {json.dumps(browser_ids)};

      const MINUTE_MS = 60 * 1000;
      const HOUR_MS = 60 * MINUTE_MS;
      const DAY_MS = 24 * HOUR_MS;

      const pluralize = (count, unit) => `${{count}} ${{unit}}${{count === 1 ? "" : "s"}} ago`;

      const formatRelativeTime = (timestampMs, nowMs = Date.now()) => {{
        const elapsedMs = nowMs - timestampMs;
        if (elapsedMs < MINUTE_MS) {{
          return "just now";
        }}
        if (elapsedMs < HOUR_MS) {{
          return pluralize(Math.floor(elapsedMs / MINUTE_MS), "minute");
        }}
        if (elapsedMs < DAY_MS) {{
          return pluralize(Math.floor(elapsedMs / HOUR_MS), "hour");
        }}
        return pluralize(Math.floor(elapsedMs / DAY_MS), "day");
      }};

      const formatTimestamp = (timestamp) =>
        timestamp ? formatRelativeTime(timestamp * 1000) : "-";

      const updateActivity = async (id) => {{
        try {{
          const response = await fetch("/api/v1/browsers/" + id);
          if (!response.ok) return;
          const browser = await response.json();
          const activitySpan = document.getElementById(id + "-activity");
          if (activitySpan) {{
            activitySpan.textContent = formatTimestamp(browser.last_activity_timestamp);
          }}
        }} catch (error) {{
          console.error("Error fetching activity for " + id + ":", error);
        }}
      }};

      document.addEventListener("DOMContentLoaded", () => {{
        browserIds.forEach(updateActivity);
      }});
    </script>
  </body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    try:
        browser_ids = await podman_browsers.list_browser_ids()
    except Exception as e:
        logger.error(f"Unable to enumerate browsers for the index page: {e}")
        return HTMLResponse(_index_page([], "Error loading browsers"))
    if browser_ids:
        status = f"{len(browser_ids)} browser(s) running:"
    else:
        status = "No browsers running!"
    return HTMLResponse(_index_page(browser_ids, status))
