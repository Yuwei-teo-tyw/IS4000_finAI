"""IS-98: named, persisted Geneva chats (list / create / append / replay), scoped per RM.

Stored in Postgres next to the LangGraph checkpoint tables, using the pool from
`app.core.db`. A chat's id doubles as the LangGraph session id, so the agent's
own memory of the conversation survives restarts too. `geneva_chat_messages`
keeps the rendered text of each turn so a chat can be replayed in order.

These are global per RM (not per client) and separate from IS-94's per-client
IPS chat.
"""
import re
from typing import Optional

from psycopg.rows import dict_row

from app.core import db

DEFAULT_TITLE = "New chat"
TITLE_MAX_LEN = 40
MESSAGE_MAX_LEN = 20_000
DEFAULT_RM = "rm_default"

_ready = False


class HistoryUnavailableError(Exception):
    """The chat-history database cannot be reached."""


class ChatNotFoundError(Exception):
    """No such chat for this RM (also raised for another RM's chat, so ids never leak)."""


# ---- title generation (heuristic, no model call) -------------------------------------------------

_GREETING = re.compile(r"^(hi+|hello+|hey+|yo|hola|thanks?|thank you|ok(ay)?|test(ing)?|help|sup|good (morning|afternoon|evening))\W*$", re.I)
_LEAD = re.compile(
    r"^(?:(?:hi|hello|hey)\b[,!\s]*)?(?:geneva[,\s]+)?(?:please\s+)?"
    r"(?:(?:can|could|would|will) you(?: please)?\s+|i (?:want|need|would like|'d like) (?:you )?to\s+|i'd like to\s+|"
    r"tell me (?:about\s+)?|let me know\s+|show me\s+|explain\s+(?=why|how|what)|help me (?:to\s+)?|i want to know\s+|i would like to know\s+)?",
    re.I,
)
_STOP = {"a", "an", "the", "is", "are", "was", "to", "of", "it", "me", "my", "i", "you", "this", "that", "do", "does", "please", "ok", "okay", "hi", "hello", "hey", "geneva", "and", "or", "for", "in", "on", "with"}
_SMALL = {"a", "an", "the", "and", "or", "for", "of", "to", "in", "on", "at", "vs", "with", "is", "by"}


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-/&.%]*", text)


def has_clear_topic(prompt: str) -> bool:
    """True when the prompt names something to talk about (not a greeting / filler)."""
    text = " ".join((prompt or "").split())
    if not text or _GREETING.match(text):
        return False
    meaningful = [w for w in _words(text) if w.lower() not in _STOP and not _GREETING.match(w)]
    return len(meaningful) >= 2


def derive_title(prompt: str) -> Optional[str]:
    """A short readable title for a chat from its first clear prompt, or None when the prompt is unclear."""
    if not has_clear_topic(prompt):
        return None
    text = " ".join(prompt.split())
    text = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text, maxsplit=1)[0]  # first sentence only
    text = _LEAD.sub("", text).strip(" ,;:-")
    q = "?" if text.endswith("?") else ""
    text = text.rstrip(".?! ")
    if not text:
        return None
    words = text.split()
    out: list[str] = []
    for i, w in enumerate(words):
        if w.isupper() or any(c.isdigit() for c in w) or (w[1:] != w[1:].lower()):
            out.append(w)  # keep acronyms / IDs / mixed case as typed
        elif i > 0 and w.lower() in _SMALL:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    title = " ".join(out)
    if len(title) + len(q) > TITLE_MAX_LEN:
        cut = title[: TITLE_MAX_LEN - 1]
        cut = cut.rsplit(" ", 1)[0] if " " in cut and title[TITLE_MAX_LEN - 1 : TITLE_MAX_LEN] != " " else cut
        ws = cut.rstrip(" ,;:-").split()
        while len(ws) > 2 and ws[-1].lower() in _SMALL:
            ws.pop()
        title = " ".join(ws) + "…"
        q = ""
    return title + q


# ---- storage -----------------------------------------------------------------------------------

async def _conn_ctx():
    try:
        return db.get_pool().connection()
    except Exception as e:  # pool not initialised
        raise HistoryUnavailableError(str(e)) from e


async def _ensure(conn) -> None:
    global _ready
    if _ready:
        return
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geneva_chats (
            id TEXT PRIMARY KEY,
            rm_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT 'New chat',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS geneva_chats_rm_updated ON geneva_chats (rm_id, updated_at DESC)")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geneva_chat_messages (
            id BIGSERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL REFERENCES geneva_chats(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS geneva_chat_messages_chat ON geneva_chat_messages (chat_id, id)")
    _ready = True


def reset_ready() -> None:
    """Tests that drop the tables / swap databases call this so `_ensure` runs again."""
    global _ready
    _ready = False


def _row(r: dict) -> dict:
    return {"id": r["id"], "title": r["title"], "createdAt": r["created_at"].isoformat(), "updatedAt": r["updated_at"].isoformat()}


async def _run(fn):
    """Run `fn(conn)` on a pooled connection; any database failure becomes HistoryUnavailableError."""
    try:
        async with db.get_pool().connection() as conn:
            await _ensure(conn)
            return await fn(conn)
    except (HistoryUnavailableError, ChatNotFoundError):
        raise
    except Exception as e:
        raise HistoryUnavailableError(str(e)) from e


async def list_chats(rm_id: str) -> list[dict]:
    async def go(conn):
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, title, created_at, updated_at FROM geneva_chats WHERE rm_id = %s ORDER BY updated_at DESC, created_at DESC",
                (rm_id,),
            )
            return [_row(r) for r in await cur.fetchall()]
    return await _run(go)


async def create_chat(rm_id: str, chat_id: str) -> dict:
    """Idempotent: re-creating your own chat returns it; another RM's id is treated as not found."""
    async def go(conn):
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "INSERT INTO geneva_chats (id, rm_id) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (chat_id, rm_id)
            )
            await cur.execute("SELECT id, rm_id, title, created_at, updated_at FROM geneva_chats WHERE id = %s", (chat_id,))
            r = await cur.fetchone()
            if r is None or r["rm_id"] != rm_id:
                raise ChatNotFoundError(chat_id)
            return _row(r)
    return await _run(go)


async def get_messages(rm_id: str, chat_id: str) -> dict:
    async def go(conn):
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, title, created_at, updated_at FROM geneva_chats WHERE id = %s AND rm_id = %s", (chat_id, rm_id))
            c = await cur.fetchone()
            if c is None:
                raise ChatNotFoundError(chat_id)
            await cur.execute("SELECT role, text, created_at FROM geneva_chat_messages WHERE chat_id = %s ORDER BY id", (chat_id,))
            msgs = [{"role": m["role"], "text": m["text"], "createdAt": m["created_at"].isoformat()} for m in await cur.fetchall()]
            return {**_row(c), "messages": msgs}
    return await _run(go)


async def append_message(rm_id: str, chat_id: str, role: str, text: str) -> dict:
    """Store a turn (creating the chat on first use). After an assistant reply, a chat still called
    "New chat" is named from its first clear user prompt. Returns the chat row (with the current title)."""
    text = text[:MESSAGE_MAX_LEN]

    async def go(conn):
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("INSERT INTO geneva_chats (id, rm_id) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (chat_id, rm_id))
            await cur.execute("SELECT rm_id, title FROM geneva_chats WHERE id = %s FOR UPDATE", (chat_id,))
            c = await cur.fetchone()
            if c is None or c["rm_id"] != rm_id:
                raise ChatNotFoundError(chat_id)
            await cur.execute("INSERT INTO geneva_chat_messages (chat_id, role, text) VALUES (%s, %s, %s)", (chat_id, role, text))
            title = c["title"]
            if role == "assistant" and title == DEFAULT_TITLE:
                await cur.execute("SELECT text FROM geneva_chat_messages WHERE chat_id = %s AND role = 'user' ORDER BY id", (chat_id,))
                for m in await cur.fetchall():
                    t = derive_title(m["text"])
                    if t:
                        title = t
                        break
            await cur.execute("UPDATE geneva_chats SET title = %s, updated_at = now() WHERE id = %s", (title, chat_id))
            await cur.execute("SELECT id, title, created_at, updated_at FROM geneva_chats WHERE id = %s", (chat_id,))
            return _row(await cur.fetchone())
    return await _run(go)
