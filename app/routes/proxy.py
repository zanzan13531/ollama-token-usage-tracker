import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import settings
from app.services.proxy_service import TRACKED_ENDPOINTS, handle_passthrough, handle_tracked_request

logger = logging.getLogger(__name__)

router = APIRouter()


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

    try:
        if request.method == "POST" and endpoint in TRACKED_ENDPOINTS:
            body = await request.json()
            return await handle_tracked_request(client, path, body, tracker_client)
        return await handle_passthrough(client, request, path)
    except httpx.ConnectError:
        logger.error("Cannot connect to Ollama at %s", request.app.state.ollama_host)
        return JSONResponse(
            status_code=502,
            content={"error": f"Cannot reach Ollama at {request.app.state.ollama_host}"},
        )
    except Exception:
        logger.exception("Proxy error for %s %s", request.method, path)
        return JSONResponse(status_code=502, content={"error": "Proxy error"})
