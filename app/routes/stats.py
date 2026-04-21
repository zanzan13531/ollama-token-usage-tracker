from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.config import settings
from app.database import query_devices, query_earliest_timestamp, query_stats, query_time_stats
from app.models import StatsResponse, TimeBucketStats

router = APIRouter(prefix="/stats", tags=["stats"])


def _tz_offset() -> str:
    """Compute the current UTC offset for the configured timezone as a SQLite modifier."""
    tz = ZoneInfo(settings.timezone)
    offset = datetime.now(tz).utcoffset()
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    hours, remainder = divmod(abs(total_seconds), 3600)
    minutes = remainder // 60
    if minutes:
        return f"{sign}{hours}:{minutes:02d} hours"
    return f"{sign}{hours} hours"


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
    return await query_time_stats(bucket="%Y-%m-%d %H:00", lookback="-1 day", model=model, device=device, tz_offset=_tz_offset())


@router.get("/weekly", response_model=list[TimeBucketStats])
async def get_weekly_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    return await query_time_stats(bucket="%Y-%m-%d %H:00", lookback="-7 days", model=model, device=device, bucket_hours=6, tz_offset=_tz_offset())


@router.get("/monthly", response_model=list[TimeBucketStats])
async def get_monthly_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    return await query_time_stats(bucket="%Y-%m-%d", lookback="-30 days", model=model, device=device, tz_offset=_tz_offset())


@router.get("/lifetime", response_model=list[TimeBucketStats])
async def get_lifetime_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    bucket = await get_lifetime_bucket(model=model, device=device)
    return await query_time_stats(bucket=bucket, lookback=None, model=model, device=device, tz_offset=_tz_offset())


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
