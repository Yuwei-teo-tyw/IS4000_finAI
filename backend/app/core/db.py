"""
Postgres persistence for chat sessions.

Two things live in Postgres:
1. LangGraph's own checkpoint tables (owned entirely by AsyncPostgresSaver -
   see agents/graph.py) - the full agent/conversation state per session,
   resumable across process restarts.
2. A small `sessions` table maintained here - just enough metadata (title,
   timestamps) to render a ChatGPT-style sidebar without having to decode
   LangGraph's checkpoint format for every list view.

DATABASE_URL defaults to the local docker-compose Postgres service (see
docker-compose.yml at the repo root) - override it for anything else.
"""
import os
from typing import Optional

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents"
)

TITLE_MAX_LEN = 60

_pool: Optional[AsyncConnectionPool] = None


async def init_pool() -> AsyncConnectionPool:
    """Open the connection pool and create the `sessions` table if it
    doesn't exist yet. Call once during app startup."""
    global _pool
    _pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False)
    await _pool.open()
    async with _pool.connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized - call init_pool() during app startup first.")
    return _pool


def _derive_title(first_message: str) -> str:
    text = " ".join(first_message.split())
    if len(text) <= TITLE_MAX_LEN:
        return text
    return text[:TITLE_MAX_LEN].rstrip() + "…"


async def touch_session(session_id: str, latest_message: Optional[str] = None) -> None:
    """Create the session row if it doesn't exist yet (titled from whatever
    message is passed in on that first call), and always bump `updated_at`
    so it sorts to the top of the sidebar. Safe to call on every turn - the
    title, once set, is never overwritten (COALESCE keeps the existing one).
    """
    title = _derive_title(latest_message) if latest_message else None
    async with get_pool().connection() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at)
            VALUES (%s, %s, now(), now())
            ON CONFLICT (id) DO UPDATE
                SET updated_at = now(),
                    title = COALESCE(sessions.title, EXCLUDED.title)
            """,
            (session_id, title),
        )


async def list_sessions() -> list[dict]:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            )
            return await cur.fetchall()


async def delete_session(session_id: str) -> None:
    async with get_pool().connection() as conn:
        await conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
