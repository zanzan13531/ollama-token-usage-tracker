import logging
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
    model: str | None = None, device: str | None = None
) -> dict[str, Any]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        where, params = _build_filters(model, device)

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


async def query_time_stats(
    bucket: str,
    lookback: str,
    model: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """Query stats grouped by time bucket.

    bucket: SQLite strftime format, e.g. '%Y-%m-%d' for daily
    lookback: SQLite date modifier, e.g. '-30 days'
    """
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

        rows = await db.execute_fetchall(
            f"""
            SELECT
                strftime('{bucket}', timestamp) as period,
                COUNT(*) as requests,
                COALESCE(SUM(prompt_eval_count), 0) as input_tokens,
                COALESCE(SUM(eval_count), 0) as output_tokens,
                COALESCE(AVG(response_latency_ms), 0) as avg_latency_ms
            FROM requests
            WHERE timestamp >= datetime('now', ?)
                {filter_sql}
            GROUP BY period
            ORDER BY period DESC
            """,
            [lookback, *extra_params],
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
                WHERE strftime('{bucket}', timestamp) = ?
                    {filter_sql}
                GROUP BY model ORDER BY requests DESC
                """,
                [item["period"], *extra_params],
            )
            item["models"] = [dict(m) for m in model_rows]

        return results


async def query_devices() -> list[str]:
    async with aiosqlite.connect(_db_path()) as db:
        rows = await db.execute_fetchall(
            "SELECT DISTINCT device FROM requests ORDER BY device"
        )
        return [row[0] for row in rows]
