import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS requests (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    device               TEXT    NOT NULL DEFAULT 'default',
    endpoint             TEXT    NOT NULL,
    model                TEXT    NOT NULL,
    prompt_eval_count    INTEGER DEFAULT 0,
    eval_count           INTEGER DEFAULT 0,
    total_duration       INTEGER DEFAULT 0,
    load_duration        INTEGER DEFAULT 0,
    prompt_eval_duration INTEGER DEFAULT 0,
    eval_duration        INTEGER DEFAULT 0,
    prompt_length        INTEGER DEFAULT 0,
    temperature          REAL,
    top_p                REAL,
    top_k                INTEGER,
    num_predict          INTEGER,
    response_latency_ms  REAL    NOT NULL DEFAULT 0,
    is_streaming         INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(model)",
    "CREATE INDEX IF NOT EXISTS idx_requests_model_ts ON requests(model, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_requests_device ON requests(device)",
    "CREATE INDEX IF NOT EXISTS idx_requests_device_ts ON requests(device, timestamp)",
]


def _db_path() -> str:
    return str(settings.resolved_db_path)


async def init_db() -> None:
    settings.resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(_CREATE_TABLE)

        # Migrate existing databases: add device column if missing
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "device" not in columns:
            await db.execute(
                "ALTER TABLE requests ADD COLUMN device TEXT NOT NULL DEFAULT 'default'"
            )
            logger.info("Migrated database: added 'device' column")

        for idx in _CREATE_INDEXES:
            await db.execute(idx)
        await db.commit()
    logger.info("Database initialized at %s", _db_path())


async def insert_request(
    endpoint: str,
    model: str,
    device: str = "default",
    prompt_eval_count: int = 0,
    eval_count: int = 0,
    total_duration: int = 0,
    load_duration: int = 0,
    prompt_eval_duration: int = 0,
    eval_duration: int = 0,
    prompt_length: int = 0,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    num_predict: int | None = None,
    response_latency_ms: float = 0,
    is_streaming: bool = True,
) -> None:
    async with aiosqlite.connect(_db_path()) as db:
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
                device, endpoint, model, prompt_eval_count, eval_count,
                total_duration, load_duration, prompt_eval_duration, eval_duration,
                prompt_length, temperature, top_p, top_k, num_predict,
                response_latency_ms, int(is_streaming),
            ),
        )
        await db.commit()


def _build_filters(
    model: str | None = None, device: str | None = None
) -> tuple[str, list[Any]]:
    """Build WHERE clause fragments and params for model/device filtering."""
    clauses: list[str] = []
    params: list[Any] = []
    if model:
        clauses.append("model = ?")
        params.append(model)
    if device:
        clauses.append("device = ?")
        params.append(device)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


async def query_stats(
    model: str | None = None,
    device: str | None = None,
    lookback: str | None = None,
    tz_offset: str | None = None,
) -> dict[str, Any]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        where, params = _build_filters(model, device)

        if lookback:
            offset_mod = f", '{tz_offset}'" if tz_offset else ""
            time_clause = f"datetime(timestamp{offset_mod}) >= datetime('now'{offset_mod}, '{lookback}')"
            where = f"{where} AND {time_clause}" if where else f"WHERE {time_clause}"

        row = await db.execute_fetchall(
            f"""
            SELECT
                COUNT(*) as total_requests,
                COALESCE(SUM(prompt_eval_count), 0) as total_input_tokens,
                COALESCE(SUM(eval_count), 0) as total_output_tokens,
                COALESCE(AVG(response_latency_ms), 0) as avg_latency_ms
            FROM requests {where}
            """,
            params,
        )
        summary = dict(row[0])

        models = await db.execute_fetchall(
            f"""
            SELECT
                model,
                COUNT(*) as requests,
                COALESCE(SUM(prompt_eval_count), 0) as input_tokens,
                COALESCE(SUM(eval_count), 0) as output_tokens
            FROM requests {where}
            GROUP BY model ORDER BY requests DESC
            """,
            params,
        )
        summary["models"] = [dict(m) for m in models]
        return summary


def _period_expr(
    bucket: str, bucket_hours: int | None = None, tz_offset: str | None = None,
) -> str:
    """Build a SQL expression for the time period grouping.

    When bucket_hours is set, hours are floored to the nearest multiple
    (e.g. bucket_hours=6 gives 00:00, 06:00, 12:00, 18:00).
    When tz_offset is set (e.g. '-7 hours'), timestamps are converted from UTC
    before bucketing.
    """
    ts = f"datetime(timestamp, '{tz_offset}')" if tz_offset else "timestamp"
    if bucket_hours and bucket_hours > 1:
        return (
            f"strftime('%Y-%m-%d ', {ts}) || "
            f"printf('%02d', (CAST(strftime('%H', {ts}) AS INTEGER) / {bucket_hours}) * {bucket_hours}) || ':00'"
        )
    return f"strftime('{bucket}', {ts})"


def _parse_tz_offset(tz_offset: str | None) -> timedelta:
    """Parse a SQLite-style offset like '-7 hours' or '+5:30 hours' into a timedelta."""
    if not tz_offset:
        return timedelta(0)
    m = re.match(r"([+-]?)(\d+)(?::(\d+))?\s*hours?", tz_offset)
    if not m:
        return timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    hours = int(m.group(2))
    minutes = int(m.group(3)) if m.group(3) else 0
    return timedelta(hours=sign * hours, minutes=sign * minutes)


def _parse_lookback(lookback: str) -> timedelta:
    """Parse a SQLite-style lookback like '-7 days' or '-1 day' into a timedelta."""
    m = re.match(r"(-?\d+)\s*(days?)", lookback)
    if m:
        return timedelta(days=int(m.group(1)))
    return timedelta(0)


def _format_period(dt: datetime, bucket: str, bucket_hours: int | None) -> str:
    """Format a datetime into a period string matching the SQL output."""
    if bucket_hours and bucket_hours > 1:
        floored = (dt.hour // bucket_hours) * bucket_hours
        return dt.strftime("%Y-%m-%d ") + f"{floored:02d}:00"
    return dt.strftime(bucket)


def _fill_gaps(
    results: list[dict[str, Any]],
    bucket: str,
    lookback: str | None,
    bucket_hours: int | None,
    tz_offset: str | None,
) -> list[dict[str, Any]]:
    """Fill missing time slots with zero-valued entries for continuous charts."""
    offset = _parse_tz_offset(tz_offset)
    now_local = datetime.now(timezone.utc) + offset

    if lookback is not None:
        lb = _parse_lookback(lookback)
        start = now_local + lb
    else:
        if not results:
            return []
        periods = [r["period"] for r in results]
        start_str, end_str = min(periods), max(periods)
        fmt = "%Y-%m-%d %H:%M" if " " in start_str else bucket
        if bucket == "%Y-W%W":
            start = datetime.strptime(start_str + "-1", "%Y-W%W-%w")
            end_parsed = datetime.strptime(end_str + "-1", "%Y-W%W-%w")
        elif bucket == "%Y-%m":
            start = datetime.strptime(start_str, "%Y-%m")
            end_parsed = datetime.strptime(end_str, "%Y-%m")
        else:
            start = datetime.strptime(start_str, fmt)
            end_parsed = datetime.strptime(end_str, fmt)
        now_local = end_parsed

    # Determine step size
    if bucket_hours and bucket_hours > 1:
        step = timedelta(hours=bucket_hours)
        start = start.replace(hour=(start.hour // bucket_hours) * bucket_hours, minute=0, second=0, microsecond=0)
    elif "%H" in bucket:
        step = timedelta(hours=1)
        start = start.replace(minute=0, second=0, microsecond=0)
    elif bucket == "%Y-W%W":
        step = timedelta(weeks=1)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    elif bucket == "%Y-%m":
        step = None  # handled via month iteration
        start = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        step = timedelta(days=1)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)

    # Generate all period strings
    all_periods: list[str] = []
    if step is not None:
        current = start
        while current <= now_local:
            all_periods.append(_format_period(current, bucket, bucket_hours))
            current += step
    else:
        # Monthly iteration
        year, month = start.year, start.month
        end_year, end_month = now_local.year, now_local.month
        while (year, month) <= (end_year, end_month):
            all_periods.append(f"{year:04d}-{month:02d}")
            month += 1
            if month > 12:
                month = 1
                year += 1

    # Merge with actual results
    existing = {r["period"]: r for r in results}
    zero_entry = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "avg_latency_ms": 0, "models": []}
    merged = []
    for p in all_periods:
        if p in existing:
            merged.append(existing[p])
        else:
            merged.append({"period": p, **zero_entry})

    # Return descending to match original API contract
    merged.reverse()
    return merged


async def query_time_stats(
    bucket: str,
    lookback: str | None = None,
    model: str | None = None,
    device: str | None = None,
    bucket_hours: int | None = None,
    tz_offset: str | None = None,
) -> list[dict[str, Any]]:
    """Query stats grouped by time bucket.

    bucket: SQLite strftime format, e.g. '%Y-%m-%d' for daily
    lookback: SQLite date modifier, e.g. '-30 days'. None = all time.
    bucket_hours: if set, floor hours to this interval (e.g. 6 for 6-hour blocks).
    tz_offset: SQLite modifier for timezone conversion, e.g. '-7 hours'.
    """
    period_sql = _period_expr(bucket, bucket_hours, tz_offset)

    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row

        extra_filters: list[str] = []
        extra_params: list[Any] = []
        if model:
            extra_filters.append("AND model = ?")
            extra_params.append(model)
        if device:
            extra_filters.append("AND device = ?")
            extra_params.append(device)
        filter_sql = " ".join(extra_filters)

        if lookback is not None:
            time_clause = "WHERE timestamp >= datetime('now', ?)" if not tz_offset else f"WHERE datetime(timestamp, '{tz_offset}') >= datetime('now', '{tz_offset}', ?)"
            time_params: list[Any] = [lookback]
        else:
            time_clause = "WHERE 1=1"
            time_params = []

        rows = await db.execute_fetchall(
            f"""
            SELECT
                {period_sql} as period,
                COUNT(*) as requests,
                COALESCE(SUM(prompt_eval_count), 0) as input_tokens,
                COALESCE(SUM(eval_count), 0) as output_tokens,
                COALESCE(AVG(response_latency_ms), 0) as avg_latency_ms
            FROM requests
            {time_clause}
                {filter_sql}
            GROUP BY period
            ORDER BY period DESC
            """,
            [*time_params, *extra_params],
        )
        results = [dict(r) for r in rows]

        for item in results:
            model_rows = await db.execute_fetchall(
                f"""
                SELECT
                    model,
                    COUNT(*) as requests,
                    COALESCE(SUM(prompt_eval_count), 0) as input_tokens,
                    COALESCE(SUM(eval_count), 0) as output_tokens
                FROM requests
                WHERE {period_sql} = ?
                    {filter_sql}
                GROUP BY model ORDER BY requests DESC
                """,
                [item["period"], *extra_params],
            )
            item["models"] = [dict(m) for m in model_rows]

        return _fill_gaps(results, bucket, lookback, bucket_hours, tz_offset)


async def query_earliest_timestamp(
    model: str | None = None, device: str | None = None,
) -> "datetime | None":
    """Return the earliest request timestamp, or None if no data."""
    from datetime import datetime, timezone

    async with aiosqlite.connect(_db_path()) as db:
        where, params = _build_filters(model, device)
        row = await db.execute_fetchall(
            f"SELECT MIN(timestamp) FROM requests {where}", params
        )
        val = row[0][0] if row and row[0][0] else None
        if val is None:
            return None
        return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)


async def query_devices() -> list[str]:
    async with aiosqlite.connect(_db_path()) as db:
        rows = await db.execute_fetchall(
            "SELECT DISTINCT device FROM requests ORDER BY device"
        )
        return [row[0] for row in rows]
