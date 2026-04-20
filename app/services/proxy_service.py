import json
import logging
import time
from collections.abc import AsyncIterator

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.config import settings
from app.services.tracker import record_usage

logger = logging.getLogger(__name__)

TRACKED_ENDPOINTS = {"/api/chat", "/api/generate"}

# Headers that should not be forwarded between hops
HOP_BY_HOP_HEADERS = {
    "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te",
    "trailers", "upgrade",
}


def _filter_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        k: v for k, v in headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }


async def _stream_and_track(
    response: httpx.Response,
    request_body: dict,
    endpoint: str,
    start_time: float,
    tracker_client: httpx.AsyncClient | None = None,
) -> AsyncIterator[bytes]:
    """Yield streaming NDJSON chunks while capturing the final one for tracking."""
    final_chunk: dict | None = None

    async for line in response.aiter_lines():
        yield line.encode("utf-8") + b"\n"
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
            if parsed.get("done"):
                final_chunk = parsed
        except (json.JSONDecodeError, ValueError):
            pass

    elapsed_ms = (time.monotonic() - start_time) * 1000
    if final_chunk:
        await record_usage(
            final_chunk, request_body, endpoint, elapsed_ms,
            is_streaming=True, device_name=settings.device_name,
            tracker_client=tracker_client,
        )


async def handle_tracked_request(
    client: httpx.AsyncClient,
    path: str,
    request_body: dict,
    tracker_client: httpx.AsyncClient | None = None,
) -> Response:
    """Handle /api/chat and /api/generate with token tracking."""
    endpoint = f"/{path}"
    is_streaming = request_body.get("stream", True)
    start_time = time.monotonic()

    if is_streaming:
        ollama_response = await client.send(
            client.build_request(
                "POST",
                f"{settings.ollama_host}/{path}",
                json=request_body,
            ),
            stream=True,
        )
        return StreamingResponse(
            _stream_and_track(
                ollama_response, request_body, endpoint, start_time, tracker_client,
            ),
            status_code=ollama_response.status_code,
            headers=_filter_headers(ollama_response.headers),
            media_type="application/x-ndjson",
        )

    # Non-streaming
    response = await client.post(f"{settings.ollama_host}/{path}", json=request_body)
    elapsed_ms = (time.monotonic() - start_time) * 1000
    data = response.json()
    await record_usage(
        data, request_body, endpoint, elapsed_ms,
        is_streaming=False, device_name=settings.device_name,
        tracker_client=tracker_client,
    )
    return JSONResponse(content=data, status_code=response.status_code)


async def handle_passthrough(
    client: httpx.AsyncClient, request: Request, path: str,
) -> Response:
    """Passthrough proxy for non-tracked endpoints."""
    url = f"{settings.ollama_host}/{path}"
    body = await request.body()

    # Build and send the request preserving method and headers
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    ollama_req = client.build_request(
        method=request.method,
        url=url,
        headers=headers,
        content=body if body else None,
    )

    # Stream the response through for large payloads (e.g., model pulls)
    ollama_response = await client.send(ollama_req, stream=True)

    async def stream_body() -> AsyncIterator[bytes]:
        async for chunk in ollama_response.aiter_bytes():
            yield chunk

    return StreamingResponse(
        stream_body(),
        status_code=ollama_response.status_code,
        headers=_filter_headers(ollama_response.headers),
        media_type=ollama_response.headers.get("content-type", "application/json"),
    )
