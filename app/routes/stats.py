from fastapi import APIRouter, Query

from app.database import query_devices, query_stats, query_time_stats
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
    return await query_time_stats(bucket="%Y-%m-%d", lookback="-30 days", model=model, device=device)


@router.get("/weekly", response_model=list[TimeBucketStats])
async def get_weekly_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    return await query_time_stats(bucket="%Y-W%W", lookback="-84 days", model=model, device=device)


@router.get("/monthly", response_model=list[TimeBucketStats])
async def get_monthly_stats(
    model: str | None = Query(None),
    device: str | None = Query(None),
):
    return await query_time_stats(bucket="%Y-%m", lookback="-365 days", model=model, device=device)


@router.get("/devices")
async def get_devices():
    devices = await query_devices()
    return {"devices": devices}
