from fastapi import FastAPI

from podmanfleet.api_router import router as api_router
from podmanfleet.health_router import router as health_router
from podmanfleet.index_view import router as index_router
from podmanfleet.static_assets import static_assets
from podmanfleet.tracing import instrument_fastapi

app = FastAPI(
    title="Podman Fleet",
    description="Orchestrate containerized browsers via REST and CDP",
    version="0.1.1",
)
instrument_fastapi(app)


app.include_router(health_router)
app.include_router(api_router)
app.include_router(index_router)

app.mount("/", static_assets, name="webui")
