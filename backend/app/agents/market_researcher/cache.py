"""
TTL cache for fetched data, plus the last regime classification per region
(for hysteresis, guide §4.4 step 5).

Two interchangeable implementations behind one protocol:
- `PostgresCache` - reuses the app's pool (app/core/db.py); survives
  restarts and is shared across workers.
- `InMemoryCache` - tests, the CLI, and anything running without Postgres.

Values must be JSON-serializable; `points_to_json`/`points_from_json`
convert SeriesPoint lists.
"""
import json
import time
from datetime import date
from typing import Any, Optional, Protocol

from app.agents.market_researcher.adapters.base import SeriesPoint


class Cache(Protocol):
    async def get(self, key: str) -> Optional[Any]: ...
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    async def get_regime(self, region: str) -> Optional[dict]: ...
    async def set_regime(self, region: str, state: dict) -> None: ...


def points_to_json(points: list[SeriesPoint]) -> list[list]:
    return [[p.date.isoformat(), p.value] for p in points]


def points_from_json(raw: list[list]) -> list[SeriesPoint]:
    return [SeriesPoint(date.fromisoformat(d), float(v)) for d, v in raw]


class InMemoryCache:
    def __init__(self):
        self._data: dict[str, tuple[float, Any]] = {}
        self._regimes: dict[str, dict] = {}

    async def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._data[key] = (time.time() + ttl_seconds, value)

    async def get_regime(self, region: str) -> Optional[dict]:
        return self._regimes.get(region)

    async def set_regime(self, region: str, state: dict) -> None:
        self._regimes[region] = state


class PostgresCache:
    def __init__(self, pool):
        self._pool = pool

    async def get(self, key: str) -> Optional[Any]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT value FROM market_cache WHERE key = %s AND expires_at > now()", (key,)
            )
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO market_cache (key, value, expires_at)
                VALUES (%s, %s, now() + %s * interval '1 second')
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, expires_at = EXCLUDED.expires_at
                """,
                (key, json.dumps(value), ttl_seconds),
            )

    async def get_regime(self, region: str) -> Optional[dict]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT state FROM market_regime_state WHERE region = %s", (region,)
            )
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def set_regime(self, region: str, state: dict) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO market_regime_state (region, state, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (region) DO UPDATE
                    SET state = EXCLUDED.state, updated_at = now()
                """,
                (region, json.dumps(state)),
            )


async def init_market_tables(pool) -> None:
    """Create the market researcher's tables. Called once from app.py's
    lifespan, right after `db.init_pool()`. JSON is stored as TEXT (not
    JSONB) so values round-trip through json.dumps/loads unchanged."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_regime_state (
                region TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_research_runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                region TEXT NOT NULL,
                request TEXT NOT NULL,
                json_path TEXT,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ,
                quality TEXT
            )
            """
        )
        await conn.execute("ALTER TABLE market_research_runs ADD COLUMN IF NOT EXISTS quality TEXT")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_audit_events (
                id BIGSERIAL PRIMARY KEY,
                run_id TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT NOT NULL,
                at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS market_audit_events_run ON market_audit_events (run_id)")
        await conn.execute("DELETE FROM market_cache WHERE expires_at < now()")


_memory_cache: Optional[InMemoryCache] = None


def default_cache() -> Cache:
    """Postgres when the app's pool is open (the FastAPI app), otherwise a
    process-wide in-memory cache (CLI, tests, scripts)."""
    global _memory_cache
    from app.core import db

    if db._pool is not None:
        return PostgresCache(db.get_pool())
    if _memory_cache is None:
        _memory_cache = InMemoryCache()
    return _memory_cache
