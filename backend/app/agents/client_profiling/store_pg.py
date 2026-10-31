"""Postgres-backed document store for the Client Profiling Agent.

Tables (prefix cp_) live in the README's database (DATABASE_URL, same as app/core/db.py):
cp_clients (incl. the in_book / progress columns), cp_ips_versions, cp_meeting_notes. Schema creation and seeding are idempotent and run once per
process on first use: seed rows use INSERT ... ON CONFLICT DO NOTHING, so user edits/uploads are never
overwritten or deleted. Sync psycopg, one short-lived connection per call (callers are sync).
Tests may isolate in a throwaway schema via PostgresStore(schema=...) or CLIENT_PROFILING_PG_SCHEMA.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import embeddings, hybrid
from .store import (DEFAULT_DATA_DIR, DEFAULT_RM, IPS_CHAT_CAP, UPLOADS_FILE, BaseStore, Client, DocumentStore, IpsPartDoc, IpsVersion,
                    SENT_STATUS, MeetingNoteDoc, StoreUnavailableError, _check_chat, _check_progress)

_SEEDED: set[tuple[str, str, str]] = set()
_LOCK = threading.Lock()
_VECTOR: dict[tuple[str, str], bool] = {}  # (dsn, schema) -> pgvector usable
_BACKFILLED: set[tuple[str, str]] = set()

_CHUNK_DDL = """CREATE TABLE IF NOT EXISTS cp_note_chunks (
    id BIGSERIAL PRIMARY KEY, note_id TEXT NOT NULL, client_id TEXT NOT NULL, chunk_idx INTEGER NOT NULL,
    text TEXT NOT NULL, embedding vector(768), UNIQUE (note_id, chunk_idx))"""

_IPS_CHUNK_DDL = """CREATE TABLE IF NOT EXISTS cp_ips_chunks (
    id BIGSERIAL PRIMARY KEY, client_id TEXT NOT NULL, version INTEGER NOT NULL, part_n INTEGER NOT NULL,
    chunk_idx INTEGER NOT NULL, text TEXT NOT NULL, embedding vector(768),
    UNIQUE (client_id, version, part_n, chunk_idx))"""

_GUIDE_DDL = """CREATE TABLE IF NOT EXISTS cp_guide_chunks (
    id BIGSERIAL PRIMARY KEY, chunk_idx INTEGER NOT NULL UNIQUE, heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL, embedding vector(768))"""

# Read-only convenience views: client_name is joined live from cp_clients (never copied), falling back to the
# client id when the name is empty. Chunk views omit the 768-dim embedding so table viewers stay readable.
_CN = "COALESCE(NULLIF(BTRIM(c.name), ''), x.client_id)"
_VIEW_DDL = [
    f"""CREATE OR REPLACE VIEW v_meeting_notes AS
        SELECT x.id, x.client_id, {_CN} AS client_name, x.note_date, x.title, x.source_file, x.text, x.origin,
               x.created_at FROM cp_meeting_notes x LEFT JOIN cp_clients c ON c.id = x.client_id""",
    f"""CREATE OR REPLACE VIEW v_ips_versions AS
        SELECT x.client_id, {_CN} AS client_name, x.version, x.status, x.issued_on, x.author, x.summary, x.parts
        FROM cp_ips_versions x LEFT JOIN cp_clients c ON c.id = x.client_id""",
]
_CHUNK_VIEW_DDL = [
    f"""CREATE OR REPLACE VIEW v_note_chunks AS
        SELECT x.id, x.note_id, x.client_id, {_CN} AS client_name, x.chunk_idx, x.text
        FROM cp_note_chunks x LEFT JOIN cp_clients c ON c.id = x.client_id""",
    f"""CREATE OR REPLACE VIEW v_ips_chunks AS
        SELECT x.id, x.client_id, {_CN} AS client_name, x.version, x.part_n, x.chunk_idx, x.text
        FROM cp_ips_chunks x LEFT JOIN cp_clients c ON c.id = x.client_id""",
]

_DDL = [
    """CREATE TABLE IF NOT EXISTS cp_clients (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, surname TEXT NOT NULL DEFAULT '',
        risk_category TEXT, risk_cap INTEGER, aum_sgd DOUBLE PRECISION, status TEXT,
        in_book BOOLEAN NOT NULL DEFAULT FALSE,
        onboarding_progress INTEGER NOT NULL DEFAULT 0 CHECK (onboarding_progress BETWEEN 0 AND 5),
        monitoring_progress INTEGER NOT NULL DEFAULT 0 CHECK (monitoring_progress BETWEEN 0 AND 100))""",
    "ALTER TABLE cp_clients ADD COLUMN IF NOT EXISTS in_book BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE cp_clients ADD COLUMN IF NOT EXISTS onboarding_progress INTEGER NOT NULL DEFAULT 0 "
    "CHECK (onboarding_progress BETWEEN 0 AND 5)",
    "ALTER TABLE cp_clients ADD COLUMN IF NOT EXISTS monitoring_progress INTEGER NOT NULL DEFAULT 0 "
    "CHECK (monitoring_progress BETWEEN 0 AND 100)",
    """CREATE TABLE IF NOT EXISTS cp_ips_versions (
        client_id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, issued_on TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '', parts JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY (client_id, version))""",
    """CREATE TABLE IF NOT EXISTS cp_meeting_notes (
        id TEXT PRIMARY KEY, client_id TEXT NOT NULL, note_date TEXT NOT NULL, title TEXT NOT NULL,
        source_file TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, origin TEXT NOT NULL DEFAULT 'seed',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS cp_meeting_notes_client_idx ON cp_meeting_notes (client_id, note_date)",
    # The old per-RM book table is replaced by cp_clients.in_book (single RM); drop it only if it exists.
    "DROP TABLE IF EXISTS cp_client_book",
    """CREATE TABLE IF NOT EXISTS cp_strategies (
        code TEXT PRIMARY KEY, name TEXT NOT NULL, risk_label TEXT NOT NULL DEFAULT '',
        expected_return_pct DOUBLE PRECISION, volatility_pct DOUBLE PRECISION, max_drawdown_pct DOUBLE PRECISION,
        longest_drawdown_years DOUBLE PRECISION, stress JSONB NOT NULL DEFAULT '{}'::jsonb)""",
    """CREATE TABLE IF NOT EXISTS cp_strategy_allocations (
        strategy_code TEXT NOT NULL REFERENCES cp_strategies(code) ON DELETE CASCADE,
        asset_class TEXT NOT NULL, weight_pct DOUBLE PRECISION NOT NULL, PRIMARY KEY (strategy_code, asset_class))""",
    """CREATE TABLE IF NOT EXISTS cp_ips_chat (
        id TEXT PRIMARY KEY, client_id TEXT NOT NULL, seq BIGSERIAL, role TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'chat',
        text TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL DEFAULT now(), meta JSONB)""",
    "ALTER TABLE cp_ips_chat ADD COLUMN IF NOT EXISTS rm_id TEXT NOT NULL DEFAULT 'rm_default'",
    "CREATE INDEX IF NOT EXISTS cp_ips_chat_client_idx ON cp_ips_chat (client_id, rm_id, seq)",
    "ALTER TABLE cp_ips_versions ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb",
    """CREATE TABLE IF NOT EXISTS cp_strategy_overrides (
        id BIGSERIAL PRIMARY KEY, client_id TEXT NOT NULL, portfolio TEXT NOT NULL, from_strategy TEXT NOT NULL DEFAULT '',
        to_strategy TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', rm_id TEXT NOT NULL DEFAULT 'rm_default',
        ts TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS cp_ips_sends (
        client_id TEXT PRIMARY KEY, version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Sent to PM',
        sent_at TEXT NOT NULL, rm_id TEXT NOT NULL DEFAULT 'rm_default', snapshot JSONB NOT NULL)""",
    # PM working copy of the sent IPS: one jsonb per client; working.snapshotVersion says which send it was seeded from.
    """CREATE TABLE IF NOT EXISTS cp_pm_working (
        client_id TEXT PRIMARY KEY, working JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    # Review Pack state (RM <-> PM shared, whole-document, last write wins). state is opaque JSON.
    """CREATE TABLE IF NOT EXISTS cp_review_pack_state (
        client_id TEXT PRIMARY KEY, state JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL)""",
    *_VIEW_DDL,
]


class PostgresStore(BaseStore):
    def __init__(self, dsn: Optional[str] = None, schema: Optional[str] = None, data_dir=None, seed: bool = True):
        self.dsn = dsn or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
        self.schema = schema or os.getenv("CLIENT_PROFILING_PG_SCHEMA") or ""
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.vector_enabled = False
        self._init(seed)

    # ---- connection ----
    def _connect(self) -> psycopg.Connection:
        try:
            conn = psycopg.connect(self.dsn, connect_timeout=3, row_factory=dict_row)
        except psycopg.OperationalError as e:
            host = psycopg.conninfo.conninfo_to_dict(self.dsn).get("host", "localhost")
            raise StoreUnavailableError(
                f"Postgres is not reachable at {host}; start docker compose up postgres ({str(e).strip()[:120]})") from e
        if self.schema:
            conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self.schema)))
        return conn

    def _init(self, seed: bool) -> None:
        key = (self.dsn, self.schema, str(self.data_dir))
        with _LOCK:
            if key in _SEEDED:
                return
            with self._connect() as conn:
                if self.schema:
                    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                for ddl in _DDL:
                    conn.execute(ddl)
                if seed:
                    self._seed(conn)
            self._init_vector()
            _SEEDED.add(key)

    def _init_vector(self) -> None:
        """Try to enable pgvector; never raises. Sets self.vector_enabled."""
        vkey = (self.dsn, self.schema)
        if vkey not in _VECTOR:
            ok = False
            try:
                with self._connect() as conn:  # needs superuser; own transaction so failure is harmless
                    conn.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
                    conn.execute(_CHUNK_DDL)
                    conn.execute(_IPS_CHUNK_DDL)
                    conn.execute(_GUIDE_DDL)
                    ok = True
                    try:
                        with conn.transaction():
                            for ddl in _CHUNK_VIEW_DDL:
                                conn.execute(ddl)
                    except Exception:
                        pass  # views are convenience only
                    try:
                        with conn.transaction():
                            conn.execute("CREATE INDEX IF NOT EXISTS cp_note_chunks_hnsw ON cp_note_chunks "
                                         "USING hnsw (embedding vector_cosine_ops)")
                    except Exception:
                        pass  # hnsw unsupported: exact scan still works
                    try:
                        with conn.transaction():
                            conn.execute("CREATE INDEX IF NOT EXISTS cp_ips_chunks_hnsw ON cp_ips_chunks "
                                         "USING hnsw (embedding vector_cosine_ops)")
                    except Exception:
                        pass
            except Exception:
                ok = False
            _VECTOR[vkey] = ok
        self.vector_enabled = _VECTOR[vkey]

    # ---- semantic chunks (all best-effort) ----
    def _reindex_note(self, client_id: str, note_id: str, text: str) -> bool:
        """Replace this note's chunks. On embedding/DB failure the note is left un-chunked (retried later)."""
        if not self.vector_enabled:
            return False
        try:
            chunks = embeddings.chunk_text(text)
            vecs = embeddings.embed_documents(chunks) if chunks else []
            with self._connect() as conn:
                conn.execute("DELETE FROM cp_note_chunks WHERE note_id = %s AND client_id = %s", (note_id, client_id))
                if vecs is None:
                    return False
                for i, (c, v) in enumerate(zip(chunks, vecs)):
                    conn.execute("INSERT INTO cp_note_chunks (note_id, client_id, chunk_idx, text, embedding) "
                                 "VALUES (%s,%s,%s,%s,%s::vector)", (note_id, client_id, i, c, embeddings.vector_literal(v)))
            return True
        except Exception:
            try:  # never leave stale chunks of the old text behind; the note is re-indexed lazily
                with self._connect() as conn:
                    conn.execute("DELETE FROM cp_note_chunks WHERE note_id = %s AND client_id = %s", (note_id, client_id))
            except Exception:
                pass
            return False

    def note_indexing(self, client_id: str, note_id: str) -> dict:
        """{"status": "indexed"|"pending", "chunks": N}. A note with no chunks gets one retry here; if embeddings are
        still down it stays "pending" and is re-indexed lazily by the next question (search_notes -> _backfill)."""
        def count() -> int:
            with self._connect() as conn:
                return conn.execute("SELECT count(*) AS n FROM cp_note_chunks WHERE note_id = %s AND client_id = %s",
                                    (note_id, client_id)).fetchone()["n"]
        try:
            n = count()
            if n == 0 and self.vector_enabled:
                note = self.get_note(client_id, note_id)
                if note is not None and note.text.strip() and self._reindex_note(client_id, note_id, note.text):
                    n = count()
            return {"status": "indexed" if n > 0 else "pending", "chunks": n}
        except Exception:
            return {"status": "pending", "chunks": 0}

    def _backfill(self, client_id: str) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT n.id, n.text FROM cp_meeting_notes n WHERE n.client_id = %s AND NOT EXISTS "
                "(SELECT 1 FROM cp_note_chunks c WHERE c.note_id = n.id)", (client_id,)).fetchall()
        for r in rows:
            self._reindex_note(client_id, r["id"], r["text"])

    def search_notes(self, client_id: str, query: str, k: int = 6, note_id: Optional[str] = None) -> Optional[list[dict]]:
        """Top-k chunks for this client by cosine similarity, or None when pgvector/embeddings are unavailable."""
        if not self.vector_enabled or not (query or "").strip():
            return None
        try:
            qv = embeddings.embed_query(query)
            if qv is None:
                return None
            self._backfill(client_id)
            lit = embeddings.vector_literal(qv)
            extra, params = ("AND c.note_id = %s ", [note_id]) if note_id else ("", [])
            with self._connect() as conn:
                dense = conn.execute(
                    "SELECT c.note_id, n.note_date AS date, n.title, c.text, c.chunk_idx, "
                    "1 - (c.embedding <=> %s::vector) AS score "
                    "FROM cp_note_chunks c JOIN cp_meeting_notes n ON n.id = c.note_id AND n.client_id = c.client_id "
                    "WHERE c.client_id = %s " + extra +
                    "ORDER BY c.embedding <=> %s::vector LIMIT %s",
                    [lit, client_id, *params, lit, k * 3]).fetchall()
                every = conn.execute(
                    "SELECT c.note_id, n.note_date AS date, n.title, c.text, c.chunk_idx "
                    "FROM cp_note_chunks c JOIN cp_meeting_notes n ON n.id = c.note_id AND n.client_id = c.client_id "
                    "WHERE c.client_id = %s " + extra, [client_id, *params]).fetchall()
            # Hybrid: dense (meaning) + lexical (exact names and figures), fused with RRF.
            by_key = {(r["note_id"], r["chunk_idx"]): dict(r, score=0.0) for r in every}
            for r in dense:
                by_key[(r["note_id"], r["chunk_idx"])] = dict(r)
            lexical = hybrid.lexical_rank(query, [(key, r["text"]) for key, r in by_key.items()])
            fused = [key for key, _ in hybrid.rrf_fuse([[(r["note_id"], r["chunk_idx"]) for r in dense], lexical], top=k)]
            rows = [by_key[key] for key in fused]
            return rows or None
        except Exception:
            return None

    def _seed(self, conn: psycopg.Connection) -> None:
        d = self.data_dir
        load = DocumentStore._load
        sfile = d / "strategies.json"
        if sfile.exists():
            for s in json.loads(sfile.read_text(encoding="utf-8"))["strategies"]:
                conn.execute(
                    "INSERT INTO cp_strategies (code, name, risk_label, expected_return_pct, volatility_pct, max_drawdown_pct, "
                    "longest_drawdown_years, stress) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (s["code"], s["name"], s.get("risk_label", ""), s.get("expected_return_pct"), s.get("volatility_pct"),
                     s.get("max_drawdown_pct"), s.get("longest_drawdown_years"), Jsonb(s.get("stress") or {})))
                for ac, w in (s.get("allocation") or {}).items():
                    conn.execute("INSERT INTO cp_strategy_allocations (strategy_code, asset_class, weight_pct) "
                                 "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (s["code"], ac, w))
        for c in load(d / "clients.json", "clients"):
            c = Client(**c)
            conn.execute(
                "INSERT INTO cp_clients (id, name, surname, risk_category, risk_cap, aum_sgd, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (c.id, c.name, c.surname, c.risk_category, c.risk_cap, c.aum_sgd, c.status))  # book columns: defaults
        # Single RM: the seeded book is the test client jft. Only ever turns jft ON; other clients are never flipped.
        conn.execute("UPDATE cp_clients SET in_book = TRUE WHERE id = 'jft'")
        for i in load(d / "ips.json", "ips_versions"):
            i = IpsVersion(**i)
            conn.execute(
                "INSERT INTO cp_ips_versions (client_id, version, status, issued_on, author, summary, parts) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (i.client_id, i.version, i.status, i.issued_on, i.author, i.summary,
                 Jsonb([p.model_dump() for p in i.parts])))
        notes = [(MeetingNoteDoc(**n), "seed") for n in load(d / "meeting_notes.json", "meeting_notes")]
        if (d / UPLOADS_FILE).exists():  # one-time migration of the old JSON uploads
            notes += [(MeetingNoteDoc(**n), "upload") for n in load(d / UPLOADS_FILE, "meeting_notes")]
        for n, origin in notes:
            conn.execute(
                "INSERT INTO cp_meeting_notes (id, client_id, note_date, title, source_file, text, origin) "
                "SELECT %s,%s,%s,%s,%s,%s,%s WHERE EXISTS (SELECT 1 FROM cp_clients WHERE id = %s) "
                "ON CONFLICT DO NOTHING",
                (n.id, n.client_id, n.date, n.title, n.source_file, n.text, origin, n.client_id))

    # ---- row mapping ----
    @staticmethod
    def _note(r: dict) -> MeetingNoteDoc:
        return MeetingNoteDoc(id=r["id"], client_id=r["client_id"], date=r["note_date"], title=r["title"],
                              source_file=r["source_file"], text=r["text"])

    # ---- clients ----
    def list_clients(self) -> list[Client]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name, surname, risk_category, risk_cap, aum_sgd, status, in_book, onboarding_progress, monitoring_progress "
                                "FROM cp_clients ORDER BY id").fetchall()
        return [Client(**r) for r in rows]

    def get_client(self, client_id: str) -> Optional[Client]:
        with self._connect() as conn:
            r = conn.execute("SELECT id, name, surname, risk_category, risk_cap, aum_sgd, status, in_book, onboarding_progress, monitoring_progress "
                             "FROM cp_clients WHERE id = %s", (client_id,)).fetchone()
        return Client(**r) if r else None

    # ---- documents ----
    def get_ips_versions(self, client_id: str) -> list[IpsVersion]:
        with self._connect() as conn:
            rows = conn.execute("SELECT client_id, version, status, issued_on, author, summary, parts, data "
                                "FROM cp_ips_versions WHERE client_id = %s ORDER BY version DESC",
                                (client_id,)).fetchall()
        return [IpsVersion(**{**r, "parts": [IpsPartDoc(**p) for p in r["parts"]]}) for r in rows]

    def get_notes(self, client_id: str) -> list[MeetingNoteDoc]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, client_id, note_date, title, source_file, text FROM cp_meeting_notes "
                                "WHERE client_id = %s ORDER BY note_date DESC, id DESC", (client_id,)).fetchall()
        return [self._note(r) for r in rows]

    def get_note(self, client_id: str, note_id: str) -> Optional[MeetingNoteDoc]:
        with self._connect() as conn:
            r = conn.execute("SELECT id, client_id, note_date, title, source_file, text FROM cp_meeting_notes "
                             "WHERE client_id = %s AND id = %s", (client_id, note_id)).fetchone()
        return self._note(r) if r else None

    def add_note(self, note: MeetingNoteDoc) -> MeetingNoteDoc:
        """Insert an uploaded note. The client must exist; ids are unique."""
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM cp_clients WHERE id = %s", (note.client_id,)).fetchone() is None:
                raise ValueError(f"unknown client {note.client_id!r}")
            r = conn.execute(
                "INSERT INTO cp_meeting_notes (id, client_id, note_date, title, source_file, text, origin) "
                "VALUES (%s,%s,%s,%s,%s,%s,'upload') ON CONFLICT DO NOTHING RETURNING id",
                (note.id, note.client_id, note.date, note.title, note.source_file, note.text)).fetchone()
            if r is None:
                raise ValueError(f"note id {note.id!r} already exists")
        self._reindex_note(note.client_id, note.id, note.text)
        return note.model_copy(deep=True)

    def update_note(self, client_id: str, note_id: str, title: Optional[str] = None,
                    text: Optional[str] = None, date: Optional[str] = None) -> Optional[MeetingNoteDoc]:
        """Edit title/date/text of one of this client's notes only; None if no such note for that client."""
        with self._connect() as conn:
            r = conn.execute(
                "UPDATE cp_meeting_notes SET title = COALESCE(%s, title), text = COALESCE(%s, text), "
                "note_date = COALESCE(%s, note_date) WHERE client_id = %s AND id = %s "
                "RETURNING id, client_id, note_date, title, source_file, text",
                (title, text, date, client_id, note_id)).fetchone()
        if r and text is not None:
            self._reindex_note(client_id, note_id, r["text"])
        return self._note(r) if r else None

    # ---- client book ----
    def list_book(self) -> list[Client]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name, surname, risk_category, risk_cap, aum_sgd, status, in_book, onboarding_progress, monitoring_progress FROM cp_clients WHERE in_book ORDER BY id").fetchall()
        return [Client(**r) for r in rows]

    def book_ids(self) -> list[str]:
        with self._connect() as conn:
            return [r["id"] for r in conn.execute("SELECT id FROM cp_clients WHERE in_book ORDER BY id").fetchall()]

    def set_in_book(self, client_id: str, flag: bool) -> bool:
        with self._connect() as conn:
            r = conn.execute("UPDATE cp_clients SET in_book = %s WHERE id = %s RETURNING id",
                             (bool(flag), client_id)).fetchone()
        return r is not None

    def set_progress(self, client_id: str, onboarding: Optional[int] = None, monitoring: Optional[int] = None) -> bool:
        _check_progress(onboarding, monitoring)
        with self._connect() as conn:
            r = conn.execute(
                "UPDATE cp_clients SET onboarding_progress = COALESCE(%s, onboarding_progress), "
                "monitoring_progress = COALESCE(%s, monitoring_progress) WHERE id = %s RETURNING id",
                (onboarding, monitoring, client_id)).fetchone()
        return r is not None

    def save_ips(self, client_id: str, parts: list[IpsPartDoc], version: Optional[int] = None, summary: Optional[str] = None,
                 author: Optional[str] = None, status: str = "Active", data: Optional[dict] = None) -> Optional[IpsVersion]:
        from datetime import date
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM cp_clients WHERE id = %s", (client_id,)).fetchone() is None:
                raise ValueError(f"unknown client {client_id!r}")
            pj = Jsonb([p.model_dump() for p in parts])
            if version is not None:
                r = conn.execute("UPDATE cp_ips_versions SET parts = %s, summary = COALESCE(%s, summary), "
                                 "author = COALESCE(%s, author), data = COALESCE(%s, data) WHERE client_id = %s AND version = %s RETURNING version",
                                 (pj, summary, author, Jsonb(data) if data is not None else None, client_id, version)).fetchone()
                if r is None:
                    return None
            else:
                version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM cp_ips_versions WHERE client_id = %s",
                                       (client_id,)).fetchone()["v"]
                if status == "Active":
                    conn.execute("UPDATE cp_ips_versions SET status = 'Superseded' WHERE client_id = %s AND status = 'Active'",
                                 (client_id,))
                conn.execute("INSERT INTO cp_ips_versions (client_id, version, status, issued_on, author, summary, parts, data) "
                             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                             (client_id, version, status, date.today().isoformat(), author or "", summary or "", pj,
                              Jsonb(data or {})))
        return next((v for v in self.get_ips_versions(client_id) if v.version == version), None)

    def delete_ips(self, client_id: str, version: int) -> bool:
        """Remove one IPS version and its chunks. If it was Active, the newest remaining version becomes Active."""
        with self._connect() as conn:
            r = conn.execute("DELETE FROM cp_ips_versions WHERE client_id = %s AND version = %s RETURNING status",
                             (client_id, version)).fetchone()
            if r is None:
                return False
            if r["status"] == "Active" and conn.execute("SELECT 1 FROM cp_ips_versions WHERE client_id = %s AND status = 'Active'",
                                                        (client_id,)).fetchone() is None:
                conn.execute("UPDATE cp_ips_versions SET status = 'Active' WHERE client_id = %s AND version = "
                             "(SELECT MAX(version) FROM cp_ips_versions WHERE client_id = %s)", (client_id, client_id))
        if self.vector_enabled:
            try:
                with self._connect() as conn:
                    conn.execute("DELETE FROM cp_ips_chunks WHERE client_id = %s AND version = %s", (client_id, version))
            except Exception:
                pass
        return True

    def drop_stale_ips_chunks(self, client_id: str, keep_version: Optional[int]) -> None:
        if not self.vector_enabled:
            return
        try:
            with self._connect() as conn:
                if keep_version is None:
                    conn.execute("DELETE FROM cp_ips_chunks WHERE client_id = %s", (client_id,))
                else:
                    conn.execute("DELETE FROM cp_ips_chunks WHERE client_id = %s AND version <> %s", (client_id, keep_version))
        except Exception:
            pass

    def count_ips_chunks(self, client_id: str, version: int) -> int:
        if not self.vector_enabled:
            return 0
        try:
            with self._connect() as conn:
                return conn.execute("SELECT count(*) AS n FROM cp_ips_chunks WHERE client_id = %s AND version = %s",
                                    (client_id, version)).fetchone()["n"]
        except Exception:
            return 0

    # ---- IPS semantic chunks (separate from cp_note_chunks) ----
    def _current_ips(self, client_id: str) -> Optional[IpsVersion]:
        return self.latest_ips(client_id)[0]

    def index_ips(self, client_id: str, version: int) -> Optional[bool]:
        """Replace this IPS version's chunks. On embedding/DB failure the version is left un-chunked; never raises."""
        if not self.vector_enabled:
            return None
        try:
            ips = next((v for v in self.get_ips_versions(client_id) if v.version == version), None)
            if ips is None:
                return False
            items = [(p.part, i, c) for p in ips.parts for i, c in enumerate(embeddings.chunk_text(f"{p.title}. {p.body}"))]
            vecs = embeddings.embed_documents([t for _, _, t in items]) if items else []
            with self._connect() as conn:
                conn.execute("DELETE FROM cp_ips_chunks WHERE client_id = %s AND version = %s", (client_id, version))
                if vecs is None:
                    return False
                for (part_n, idx, text), v in zip(items, vecs):
                    conn.execute("INSERT INTO cp_ips_chunks (client_id, version, part_n, chunk_idx, text, embedding) "
                                 "VALUES (%s,%s,%s,%s,%s,%s::vector)",
                                 (client_id, version, part_n, idx, text, embeddings.vector_literal(v)))
            return True
        except Exception:
            return False

    def search_ips(self, client_id: str, query: str, k: int = 4) -> Optional[list[dict]]:
        """Top-k chunks of the client's CURRENT IPS version only, or None when semantic search is unavailable."""
        if not self.vector_enabled or not (query or "").strip():
            return None
        try:
            qv = embeddings.embed_query(query)
            if qv is None:
                return None
            ips = self._current_ips(client_id)
            if ips is None:
                return None
            with self._connect() as conn:
                has = conn.execute("SELECT 1 FROM cp_ips_chunks WHERE client_id = %s AND version = %s LIMIT 1",
                                   (client_id, ips.version)).fetchone()
            if has is None:
                self.index_ips(client_id, ips.version)  # lazy backfill
            lit = embeddings.vector_literal(qv)
            with self._connect() as conn:
                dense = conn.execute(
                    "SELECT part_n, chunk_idx, version, text, 1 - (embedding <=> %s::vector) AS score FROM cp_ips_chunks "
                    "WHERE client_id = %s AND version = %s ORDER BY embedding <=> %s::vector LIMIT %s",
                    [lit, client_id, ips.version, lit, k * 3]).fetchall()
                every = conn.execute("SELECT part_n, chunk_idx, version, text FROM cp_ips_chunks WHERE client_id = %s AND version = %s",
                                     (client_id, ips.version)).fetchall()
            # Hybrid: dense (meaning) + lexical (exact names and figures), fused with RRF.
            by_key = {(r["part_n"], r["chunk_idx"]): dict(r, score=0.0) for r in every}
            for r in dense:
                by_key[(r["part_n"], r["chunk_idx"])] = dict(r)
            lexical = hybrid.lexical_rank(query, [(key, r["text"]) for key, r in by_key.items()])
            fused = [key for key, _ in hybrid.rrf_fuse([[(r["part_n"], r["chunk_idx"]) for r in dense], lexical], top=k)]
            return [{k_: v for k_, v in by_key[key].items() if k_ != "chunk_idx"} for key in fused] or None  # same shape as before
        except Exception:
            return None

    # ---- model strategies (cp_strategies + cp_strategy_allocations), same shape as data/strategies.json ----
    def list_strategies(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM cp_strategies ORDER BY code").fetchall()
            allocs = conn.execute("SELECT strategy_code, asset_class, weight_pct FROM cp_strategy_allocations").fetchall()
        if not rows:  # table empty (e.g. seed=False): same data from the JSON file
            return super().list_strategies()
        order = ("Bonds", "Liquidity", "Alternative Investments", "Equities", "Other")
        out = []
        for r in rows:
            a = {x["asset_class"]: _num(x["weight_pct"]) for x in allocs if x["strategy_code"] == r["code"]}
            a = {**{k: a[k] for k in order if k in a}, **{k: v for k, v in a.items() if k not in order}}
            out.append({"code": r["code"], "name": r["name"], "risk_label": r["risk_label"], "allocation": a,
                        "expected_return_pct": _num(r["expected_return_pct"]), "volatility_pct": _num(r["volatility_pct"]),
                        "max_drawdown_pct": _num(r["max_drawdown_pct"]),
                        "longest_drawdown_years": _num(r["longest_drawdown_years"]), "stress": r["stress"] or {}})
        return out

    # ---- investor-profile guide chunks (cp_guide_chunks, pgvector) ----
    def index_guide(self) -> Optional[bool]:
        """Replace all guide chunks with freshly embedded ones. Never raises; None = no pgvector."""
        if not self.vector_enabled:
            return None
        try:
            from .guide import guide_chunks
            items = guide_chunks()
            vecs = embeddings.embed_documents([f"{h}. {t}" for h, t in items]) if items else []
            if vecs is None:
                return False
            with self._connect() as conn:
                conn.execute("DELETE FROM cp_guide_chunks")
                for i, ((h, t), v) in enumerate(zip(items, vecs)):
                    conn.execute("INSERT INTO cp_guide_chunks (chunk_idx, heading, text, embedding) VALUES (%s,%s,%s,%s::vector)",
                                 (i, h, t, embeddings.vector_literal(v)))
            return True
        except Exception:
            return False

    def search_guide(self, query: str, k: int = 4) -> Optional[list[dict]]:
        if not self.vector_enabled or not (query or "").strip():
            return None
        try:
            qv = embeddings.embed_query(query)
            if qv is None:
                return None
            from .guide import guide_chunks
            with self._connect() as conn:
                n = conn.execute("SELECT count(*) AS n FROM cp_guide_chunks").fetchone()["n"]
            if n != len(guide_chunks()):  # missing or stale (guide file changed): lazy (re)index
                if not self.index_guide():
                    return None
            lit = embeddings.vector_literal(qv)
            with self._connect() as conn:
                rows = conn.execute("SELECT heading, text, 1 - (embedding <=> %s::vector) AS score FROM cp_guide_chunks "
                                    "ORDER BY embedding <=> %s::vector LIMIT %s", [lit, lit, k]).fetchall()
            return [dict(r) for r in rows] or None
        except Exception:
            return None

    # ---- send-to-PM (cp_ips_sends): snapshot + sent state in ONE row / transaction ----
    def send_ips_to_pm(self, client_id: str, version: int, rm_id: str, sent_at: str, snapshot: dict,
                       before_commit=None) -> dict:
        rec = {"clientId": client_id, "version": version, "status": SENT_STATUS, "sentAt": sent_at, "rmId": rm_id or DEFAULT_RM,
               "snapshot": json.loads(json.dumps(snapshot))}
        with self._connect() as conn:  # commits on clean exit, rolls back if before_commit (notification) or the write raises
            conn.execute("INSERT INTO cp_ips_sends (client_id, version, status, sent_at, rm_id, snapshot) VALUES (%s,%s,%s,%s,%s,%s) "
                         "ON CONFLICT (client_id) DO UPDATE SET version = EXCLUDED.version, status = EXCLUDED.status, "
                         "sent_at = EXCLUDED.sent_at, rm_id = EXCLUDED.rm_id, snapshot = EXCLUDED.snapshot",
                         (client_id, version, SENT_STATUS, sent_at, rec["rmId"], Jsonb(rec["snapshot"])))
            if before_commit is not None:
                before_commit(json.loads(json.dumps(rec)))
        return rec

    def get_ips_send(self, client_id: str) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute("SELECT client_id, version, status, sent_at, rm_id, snapshot FROM cp_ips_sends WHERE client_id = %s",
                             (client_id,)).fetchone()
        if r is None:
            return None
        return {"clientId": r["client_id"], "version": r["version"], "status": r["status"], "sentAt": r["sent_at"],
                "rmId": r["rm_id"], "snapshot": r["snapshot"]}

    def withdraw_ips_send(self, client_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM cp_ips_sends WHERE client_id = %s", (client_id,)).rowcount > 0

    def update_ips_send(self, client_id: str, status: str, snapshot: dict) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute("UPDATE cp_ips_sends SET status = %s, snapshot = %s WHERE client_id = %s "
                             "RETURNING client_id, version, status, sent_at, rm_id, snapshot",
                             (status, Jsonb(json.loads(json.dumps(snapshot))), client_id)).fetchone()
        if r is None:
            return None
        return {"clientId": r["client_id"], "version": r["version"], "status": r["status"], "sentAt": r["sent_at"],
                "rmId": r["rm_id"], "snapshot": r["snapshot"]}

    # ---- PM working copy of the sent IPS (cp_pm_working) ----
    def get_pm_working(self, client_id: str) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute("SELECT working FROM cp_pm_working WHERE client_id = %s", (client_id,)).fetchone()
        return r["working"] if r else None

    def put_pm_working(self, client_id: str, working: dict) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO cp_pm_working (client_id, working, updated_at) VALUES (%s, %s, now()) "
                         "ON CONFLICT (client_id) DO UPDATE SET working = EXCLUDED.working, updated_at = now()",
                         (client_id, Jsonb(json.loads(json.dumps(working)))))

    # ---- Review Pack state (cp_review_pack_state) ----
    def get_review_pack_state(self, client_id: str) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute("SELECT state FROM cp_review_pack_state WHERE client_id = %s", (client_id,)).fetchone()
        return r["state"] if r else None

    def put_review_pack_state(self, client_id: str, state: dict) -> str:
        with self._connect() as conn:
            r = conn.execute("INSERT INTO cp_review_pack_state (client_id, state, updated_at) VALUES (%s, %s, now()) "
                             "ON CONFLICT (client_id) DO UPDATE SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at "
                             "RETURNING updated_at",
                             (client_id, Jsonb(state))).fetchone()
        return r["updated_at"].isoformat()

    def list_review_pack_states(self) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT client_id, state FROM cp_review_pack_state").fetchall()
        return {r["client_id"]: r["state"] for r in rows}

    def delete_review_pack_state(self, client_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM cp_review_pack_state WHERE client_id = %s", (client_id,)).rowcount > 0

    # ---- activation and client status ----
    def activate_ips(self, client_id: str, version: int) -> bool:
        """One transaction: the other Active versions of the client become Superseded, this one becomes Active."""
        with self._connect() as conn:
            conn.execute("UPDATE cp_ips_versions SET status = 'Superseded' WHERE client_id = %s AND status = 'Active' AND version <> %s",
                         (client_id, version))
            return conn.execute("UPDATE cp_ips_versions SET status = 'Active' WHERE client_id = %s AND version = %s",
                                (client_id, version)).rowcount > 0

    def deactivate_ips(self, client_id: str, version: int) -> bool:
        """The Active version becomes Superseded. False if it is missing or not Active."""
        with self._connect() as conn:
            return conn.execute("UPDATE cp_ips_versions SET status = 'Superseded' WHERE client_id = %s AND version = %s AND status = 'Active'",
                                (client_id, version)).rowcount > 0

    def set_client_status(self, client_id: str, status: str) -> bool:
        with self._connect() as conn:
            return conn.execute("UPDATE cp_clients SET status = %s WHERE id = %s", (status, client_id)).rowcount > 0

    # ---- IPS chat history (cp_ips_chat) ----
    @staticmethod
    def _chat(r: dict) -> dict:
        return {"id": r["id"], "role": r["role"], "kind": r["kind"], "text": r["text"],
                "ts": r["ts"].isoformat(), "meta": r["meta"]}

    def list_ips_chat(self, client_id: str, limit: int = IPS_CHAT_CAP, rm_id: str = DEFAULT_RM) -> list[dict]:
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute("SELECT id, role, kind, text, ts, meta FROM (SELECT * FROM cp_ips_chat WHERE client_id = %s "
                                "AND rm_id = %s ORDER BY seq DESC LIMIT %s) t ORDER BY seq",
                                (client_id, rm_id or DEFAULT_RM, limit)).fetchall()
        return [self._chat(r) for r in rows]

    def append_ips_chat(self, client_id: str, role: str, text: str, kind: str = "chat", meta: Optional[dict] = None,
                        rm_id: str = DEFAULT_RM) -> dict:
        _check_chat(role, kind)
        import uuid
        rm = rm_id or DEFAULT_RM
        with self._connect() as conn:
            r = conn.execute("INSERT INTO cp_ips_chat (id, client_id, rm_id, role, kind, text, meta) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                             "RETURNING id, role, kind, text, ts, meta",
                             (f"ipsc_{uuid.uuid4().hex[:12]}", client_id, rm, role, kind, text,
                              Jsonb(meta) if meta is not None else None)).fetchone()
            dropped = conn.execute("DELETE FROM cp_ips_chat WHERE client_id = %s AND rm_id = %s AND seq NOT IN "
                                   "(SELECT seq FROM cp_ips_chat WHERE client_id = %s AND rm_id = %s ORDER BY seq DESC LIMIT %s)",
                                   (client_id, rm, client_id, rm, IPS_CHAT_CAP)).rowcount
        return {**self._chat(r), "truncated": dropped > 0}

    def clear_ips_chat(self, client_id: str, rm_id: str = DEFAULT_RM) -> int:
        with self._connect() as conn:
            return conn.execute("DELETE FROM cp_ips_chat WHERE client_id = %s AND rm_id = %s", (client_id, rm_id or DEFAULT_RM)).rowcount

    # ---- audit log of manual 3L strategy overrides ----
    def log_strategy_override(self, client_id: str, portfolio: str, from_strategy: str, to_strategy: str, reason: str = "",
                              rm_id: str = DEFAULT_RM) -> dict:
        with self._connect() as conn:
            r = conn.execute("INSERT INTO cp_strategy_overrides (client_id, portfolio, from_strategy, to_strategy, reason, rm_id) "
                             "VALUES (%s,%s,%s,%s,%s,%s) RETURNING ts", (client_id, portfolio, from_strategy, to_strategy, reason,
                                                                         rm_id or DEFAULT_RM)).fetchone()
        return {"clientId": client_id, "portfolio": portfolio, "from": from_strategy, "to": to_strategy, "reason": reason,
                "rmId": rm_id or DEFAULT_RM, "ts": r["ts"].isoformat()}

    def list_strategy_overrides(self, client_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT client_id, portfolio, from_strategy, to_strategy, reason, rm_id, ts FROM cp_strategy_overrides "
                                "WHERE client_id = %s ORDER BY id", (client_id,)).fetchall()
        return [{"clientId": r["client_id"], "portfolio": r["portfolio"], "from": r["from_strategy"], "to": r["to_strategy"],
                 "reason": r["reason"], "rmId": r["rm_id"], "ts": r["ts"].isoformat()} for r in rows]


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f == int(f) else f
