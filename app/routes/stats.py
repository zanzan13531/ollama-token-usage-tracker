from fastapi import APIRouter, Query

from app.database import query_devices, query_earliest_timestamp, query_stats, query_time_stats
from app.models import StatsResponse, TimeBucketStats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsResponse)
async def get_stats(
    model: str | None = Query(None, description="Filter by model name"),
    device: str | None = Query(None, description="Filter by device name"),
):
    return await query_stats(model=model, device=device)


@router.get("/daily", response_model=list[TimeBucketStats])
async def get_daily_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    return await query_time_stats(bucket="%Y-%m-%d %H:00", lookback="-1 day", model=model, device=device)


@router.get("/weekly", response_model=list[TimeBucketStats])
async def get_weekly_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    return await query_time_stats(bucket="%Y-%m-%d %H:00", lookback="-7 days", model=model, device=device, bucket_hours=6)


@router.get("/monthly", response_model=list[TimeBucketStats])
async def get_monthly_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    return await query_time_stats(bucket="%Y-%m-%d", lookback="-30 days", model=model, device=device)


@router.get("/lifetime", response_model=list[TimeBucketStats])
async def get_lifetime_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    bucket = await get_lifetime_bucket(model=model, device=device)
    return await query_time_stats(bucket=bucket, lookback=None, model=model, device=device)


async def get_lifetime_bucket(
    model: str | None = None, device: str | None = None,
) -> str:
    """Choose a bucket granularity based on the span of stored data."""
    from datetime import datetime, timezone

    earliest = await query_earliest_timestamp(model=model, device=device)
    if earliest is None:
        return "%Y-%m-%d"
    span_days = (datetime.now(timezone.utc) - earliest).days
    if span_days <= 7:
        return "%Y-%m-%d %H:00"
    if span_days <= 90:
        return "%Y-%m-%d"
    if span_days <= 730:
        return "%Y-W%W"
    return "%Y-%m"


@router.get("/devices")
async def get_devices():
    devices = await query_devices()
    return {"devices": devices}
