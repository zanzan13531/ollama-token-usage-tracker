import asyncio
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import settings
from app.services.proxy_service import TRACKED_ENDPOINTS, handle_passthrough, handle_tracked_request

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds between retries


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy(request: Request, path: str) -> Response:
    if settings.mode == "tracker":
        return JSONResponse(
            status_code=404,
            content={"error": "This is a tracker node. Ollama proxy is not available."},
        )

    client: httpx.AsyncClient = request.app.state.http_client
    tracker_client: httpx.AsyncClient | None = getattr(request.app.state, "tracker_client", None)
    endpoint = f"/{path}"

    # Pre-read body for tracked endpoints so it can be replayed on retry
    body = None
    if request.method == "POST" and endpoint in TRACKED_ENDPOINTS:
        body = await request.json()

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if body is not None:
                return await handle_tracked_request(client, path, body, tracker_client)
            return await handle_passthrough(client, request, path)
        except httpx.ConnectError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                logger.warning(
                    "Cannot connect to Ollama (attempt %d/%d), retrying in %.0fs...",
                    attempt, MAX_RETRIES, RETRY_DELAY,
                )
                await asyncio.sleep(RETRY_DELAY)
            else:
                logger.error("Cannot connect to Ollama at %s after %d attempts", request.app.state.ollama_host, MAX_RETRIES)
        except Exception:
            logger.exception("Proxy error for %s %s", request.method, path)
            return JSONResponse(status_code=502, content={"error": "Proxy error"})

    return JSONResponse(
        status_code=502,
        content={"error": f"Cannot reach Ollama at {request.app.state.ollama_host}"},
    )
