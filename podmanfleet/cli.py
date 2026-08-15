import os
import sys

_frozen = getattr(sys, "frozen", False)
if _frozen:
    os.environ["PYDANTIC_DISABLE_PLUGINS"] = "1"

import uvicorn

from podmanfleet.main import app


def main():
    port = int(os.getenv("PORT", 8400))
    uvicorn.run(
        app if _frozen else "podmanfleet.main:app",
        host="127.0.0.1",
        port=port,
        reload=not _frozen,
    )
