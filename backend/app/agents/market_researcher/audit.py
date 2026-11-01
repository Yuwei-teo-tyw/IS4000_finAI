"""
Append-only audit log for market research runs, covering chat and HTTP alike
(chat runs don't pass through the run registry). Each event ties a run id to
SHA-256 hashes of what was produced, so a stored output or a rendered chat
answer can be checked later. Nothing here updates or deletes a row.

Two interchangeable implementations, as in cache.py: `PostgresAuditLog`
(table `market_audit_events`, created by cache.init_market_tables) and
`InMemoryAuditLog` for tests, the CLI and anything without Postgres.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, Protocol


class AuditLog(Protocol):
    async def record(self, run_id: str, event: str, details: dict) -> None: ...
    async def events(self, run_id: str) -> list[dict]: ...


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InMemoryAuditLog:
    def __init__(self):
        self._events: list[dict] = []

    async def record(self, run_id: str, event: str, details: dict) -> None:
        self._events.append({"run_id": run_id, "event": event, "details": details,
                             "at": datetime.now(timezone.utc).isoformat()})

    async def events(self, run_id: str) -> list[dict]:
        return [e for e in self._events if e["run_id"] == run_id]


class PostgresAuditLog:
    def __init__(self, pool):
        self._pool = pool

    async def record(self, run_id: str, event: str, details: dict) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO market_audit_events (run_id, event, details) VALUES (%s, %s, %s)",
                (run_id, event, json.dumps(details)),
            )

    async def events(self, run_id: str) -> list[dict]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT run_id, event, details, at FROM market_audit_events WHERE run_id = %s ORDER BY id", (run_id,)
            )
            rows = await cur.fetchall()
        return [{"run_id": r, "event": e, "details": json.loads(d), "at": at.isoformat()} for r, e, d, at in rows]


_memory_audit: Optional[InMemoryAuditLog] = None


def default_audit() -> AuditLog:
    """Postgres when the app's pool is open, otherwise a process-wide in-memory log."""
    global _memory_audit
    from app.core import db

    if db._pool is not None:
        return PostgresAuditLog(db.get_pool())
    if _memory_audit is None:
        _memory_audit = InMemoryAuditLog()
    return _memory_audit
