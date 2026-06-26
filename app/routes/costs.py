import logging
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import database
from app.services.model_matcher import resolve_openrouter_id
from app.services.pricing import fetch_and_cache_prices, get_cached_prices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/costs", tags=["costs"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PriceEntry(BaseModel):
    openrouter_id: str
    prompt_price: str
    completion_price: str
    fetched_at: str


class MappingEntry(BaseModel):
    ollama_model: str
    openrouter_id: str
    is_user_override: bool


class MappingSetRequest(BaseModel):
    openrouter_id: str


class BackfillResult(BaseModel):
    updated: int
    unmatched_models: list[str]


# ---------------------------------------------------------------------------
# Price endpoints
# ---------------------------------------------------------------------------

@router.get("/prices", response_model=list[PriceEntry])
async def list_prices():
    return await database.get_all_prices()


@router.post("/prices/refresh")
async def refresh_prices():
    count = await fetch_and_cache_prices(force=True)
    if count < 0:
        return {"status": "error", "message": "Failed to fetch OpenRouter prices"}
    return {"status": "ok", "cached": count}


# ---------------------------------------------------------------------------
# Mapping endpoints
# ---------------------------------------------------------------------------

@router.get("/mappings", response_model=list[MappingEntry])
async def list_mappings():
    return await database.get_all_mappings()


@router.put("/mappings/{ollama_model}")
async def set_mapping(ollama_model: str, body: MappingSetRequest):
    await database.upsert_mapping(ollama_model, body.openrouter_id, is_user_override=True)
    return {"status": "ok", "ollama_model": ollama_model, "openrouter_id": body.openrouter_id}


@router.delete("/mappings/{ollama_model}")
async def remove_mapping(ollama_model: str):
    deleted = await database.delete_mapping(ollama_model)
    if not deleted:
        return {"status": "not_found", "message": "No user override found for this model"}
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

@router.get("/models")
async def list_ollama_models():
    """List all distinct Ollama models from the requests table."""
    models = await database.get_distinct_models()
    return {"models": models}


@router.post("/backfill", response_model=BackfillResult)
async def trigger_backfill(
    force: bool = Query(False, description="Recalculate ALL rows, not just missing costs"),
):
    # Refresh prices if stale
    await fetch_and_cache_prices(force=False)

    prices = await get_cached_prices()
    models = await database.get_distinct_models()

    total_updated = 0
    unmatched: list[str] = []

    for model in models:
        openrouter_id = await resolve_openrouter_id(model)
        if not openrouter_id or openrouter_id not in prices:
            unmatched.append(model)
            continue

        prompt_price, completion_price = prices[openrouter_id]
        updated = await database.backfill_costs(
            model, openrouter_id,
            float(prompt_price), float(completion_price),
            force=force,
        )
        total_updated += updated

    logger.info("Backfill complete: %d rows updated, %d unmatched models", total_updated, len(unmatched))
    return BackfillResult(updated=total_updated, unmatched_models=unmatched)
