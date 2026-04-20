import logging

from fastapi import APIRouter

from app.database import insert_request
from app.models import IngestPayload, IngestResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_metrics(payload: IngestPayload):
    """Receive token usage metrics from device proxies."""
    import aiosqlite
    from app.config import settings

    db_path = str(settings.resolved_db_path)
    async with aiosqlite.connect(db_path) as db:
        for record in payload.records:
            await db.execute(
                """
                INSERT INTO requests (
                    device, endpoint, model, prompt_eval_count, eval_count,
                    total_duration, load_duration, prompt_eval_duration, eval_duration,
                    prompt_length, temperature, top_p, top_k, num_predict,
                    response_latency_ms, is_streaming
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.device, record.endpoint, record.model,
                    record.prompt_eval_count, record.eval_count,
                    record.total_duration, record.load_duration,
                    record.prompt_eval_duration, record.eval_duration,
                    record.prompt_length, record.temperature, record.top_p,
                    record.top_k, record.num_predict,
                    record.response_latency_ms, int(record.is_streaming),
                ),
            )
        await db.commit()

    logger.info("Ingested %d records", len(payload.records))
    return IngestResponse(accepted=len(payload.records))
