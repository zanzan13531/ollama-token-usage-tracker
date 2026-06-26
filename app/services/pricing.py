import logging
from decimal import Decimal

import httpx

from app import database
from app.config import settings

logger = logging.getLogger(__name__)


async def fetch_and_cache_prices(force: bool = False) -> int:
    """Fetch OpenRouter model prices and cache to DB.

    Skips fetch if cache is fresh (< TTL hours old) unless force=True.
    Returns the number of models cached, or -1 on failure.
    """
    if not force:
        age = await database.get_price_age_hours()
        if age is not None and age < settings.price_cache_ttl_hours:
            logger.debug("Price cache is %.1f hours old (TTL=%.1f), skipping fetch", age, settings.price_cache_ttl_hours)
            return 0

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(settings.openrouter_api_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Failed to fetch OpenRouter prices")
        return -1

    models = data.get("data", [])
    prices: list[tuple[str, str, str]] = []
    for m in models:
        pricing = m.get("pricing")
        if not pricing:
            continue
        prompt_price = pricing.get("prompt", "0")
        completion_price = pricing.get("completion", "0")
        prices.append((m["id"], prompt_price, completion_price))

    if prices:
        count = await database.upsert_prices(prices)
        logger.info("Cached %d OpenRouter model prices", count)
        return count
    return 0


async def get_cached_prices() -> dict[str, tuple[Decimal, Decimal]]:
    """Return {openrouter_id: (prompt_price_per_token, completion_price_per_token)}."""
    rows = await database.get_all_prices()
    result: dict[str, tuple[Decimal, Decimal]] = {}
    for r in rows:
        try:
            result[r["openrouter_id"]] = (
                Decimal(r["prompt_price"]),
                Decimal(r["completion_price"]),
            )
        except Exception:
            continue
    return result


async def compute_cost(
    request_id: int,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Compute and store cost for a single request."""
    from app.services.model_matcher import resolve_openrouter_id

    openrouter_id = await resolve_openrouter_id(model)
    if not openrouter_id:
        return

    price_row = await database.get_price_for_model(openrouter_id)
    if not price_row:
        return

    prompt_price = Decimal(price_row[0])
    completion_price = Decimal(price_row[1])
    prompt_cost = float(prompt_tokens * prompt_price)
    completion_cost = float(completion_tokens * completion_price)

    await database.update_request_cost(request_id, openrouter_id, prompt_cost, completion_cost)
