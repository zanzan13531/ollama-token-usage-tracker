import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import settings
from app.database import init_db
from app.routes import dashboard, ingest, proxy, stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    if settings.mode == "proxy":
        app.state.ollama_host = settings.ollama_host
        app.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=10.0),
        )
        logger.info(
            "Proxy mode [%s] — forwarding to %s",
            settings.device_name, settings.ollama_host,
        )
        if settings.tracker_url:
            app.state.tracker_client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0),
            )
            logger.info("Reporting metrics to tracker at %s", settings.tracker_url)
    else:
        logger.info("Tracker mode — receiving metrics from device proxies")

    yield

    if hasattr(app.state, "http_client"):
        await app.state.http_client.aclose()
    if hasattr(app.state, "tracker_client"):
        await app.state.tracker_client.aclose()


app = FastAPI(title="Ollama Token Usage Tracker", lifespan=lifespan)

# Order matters: specific routes before catch-all
app.include_router(stats.router)
app.include_router(dashboard.router)
app.include_router(ingest.router)

if settings.mode == "proxy":
    app.include_router(proxy.router)  # catch-all LAST, only in proxy mode


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.proxy_port)
