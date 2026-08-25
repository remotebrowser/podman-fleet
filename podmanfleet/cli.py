import argparse
import os
import sys

_frozen = getattr(sys, "frozen", False)
if _frozen:
    os.environ["PYDANTIC_DISABLE_PLUGINS"] = "1"

import uvicorn

from podmanfleet.main import app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="podmanfleet", description="Run the Podman Fleet server via uvicorn."
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (ignored for frozen builds).",
    )
    args = parser.parse_args()

    port = int(os.getenv("PORT", 8400))
    uvicorn.run(
        app if _frozen else "podmanfleet.main:app",
        host="127.0.0.1",
        port=port,
        reload=not _frozen and args.reload,
    )
