from fastapi.staticfiles import StaticFiles

from podmanfleet.config import PROJECT_DIR

static_assets = StaticFiles(directory=str(PROJECT_DIR / "podmanfleet" / "webui"), html=True)
