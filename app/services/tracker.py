import asyncio
import logging

import httpx

from app import database
from app.config import settings

logger = logging.getLogger(__name__)


def _compute_prompt_length(request_body: dict, endpoint: str) -> int:
    """Compute character count of prompt content (never stores actual text)."""
    if endpoint == "/api/generate":
        return len(request_body.get("prompt", ""))
    if endpoint == "/api/chat":
        messages = request_body.get("messages", [])
        return sum(len(m.get("content", "")) for m in messages)
    return 0


async def _report_to_tracker(
    tracker_client: httpx.AsyncClient, payload: dict
) -> None:
    """Fire-and-forget POST to central tracker."""
    try:
        await tracker_client.post(
            f"{settings.tracker_url}/api/ingest", json=payload
        )
    except Exception:
        logger.warning("Failed to report to tracker at %s", settings.tracker_url)


async def record_usage(
    response_data: dict,
    request_body: dict,
    endpoint: str,
    response_latency_ms: float,
    is_streaming: bool,
    device_name: str = "default",
    tracker_client: httpx.AsyncClient | None = None,
) -> None:
    """Extract token metrics from Ollama response and persist to database."""
    try:
        model = request_body.get("model", response_data.get("model", "unknown"))
        options = request_body.get("options", {})

        record_kwargs = dict(
            endpoint=endpoint,
            model=model,
            device=device_name,
            prompt_eval_count=response_data.get("prompt_eval_count", 0) or 0,
            eval_count=response_data.get("eval_count", 0) or 0,
            total_duration=response_data.get("total_duration", 0) or 0,
            load_duration=response_data.get("load_duration", 0) or 0,
            prompt_eval_duration=response_data.get("prompt_eval_duration", 0) or 0,
            eval_duration=response_data.get("eval_duration", 0) or 0,
            prompt_length=_compute_prompt_length(request_body, endpoint),
            temperature=options.get("temperature"),
            top_p=options.get("top_p"),
            top_k=options.get("top_k"),
            num_predict=options.get("num_predict"),
            response_latency_ms=response_latency_ms,
            is_streaming=is_streaming,
        )

        await database.insert_request(**record_kwargs)

        # Report to central tracker if configured
        if settings.tracker_url and tracker_client:
            ingest_payload = {
                "records": [{
                    "device": device_name,
                    "endpoint": endpoint,
                    "model": model,
                    "prompt_eval_count": record_kwargs["prompt_eval_count"],
                    "eval_count": record_kwargs["eval_count"],
                    "total_duration": record_kwargs["total_duration"],
                    "load_duration": record_kwargs["load_duration"],
                    "prompt_eval_duration": record_kwargs["prompt_eval_duration"],
                    "eval_duration": record_kwargs["eval_duration"],
                    "prompt_length": record_kwargs["prompt_length"],
                    "temperature": record_kwargs["temperature"],
                    "top_p": record_kwargs["top_p"],
                    "top_k": record_kwargs["top_k"],
                    "num_predict": record_kwargs["num_predict"],
                    "response_latency_ms": response_latency_ms,
                    "is_streaming": is_streaming,
                }]
            }
            asyncio.create_task(_report_to_tracker(tracker_client, ingest_payload))

        logger.debug(
            "Tracked %s tokens (in=%d, out=%d) for model=%s device=%s",
            endpoint,
            record_kwargs["prompt_eval_count"],
            record_kwargs["eval_count"],
            model,
            device_name,
        )
    except Exception:
        logger.exception("Failed to record token usage")
