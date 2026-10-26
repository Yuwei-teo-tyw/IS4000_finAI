"""Semantic note search: chunking, build_context with a fake store, and real-Postgres integration
(graceful degradation without pgvector; full path skipped when the extension is unavailable)."""
import os
import uuid

import psycopg
import pytest
from psycopg import sql

from app.agents.client_profiling import embeddings
from app.agents.client_profiling.answer import build_context
from app.agents.client_profiling.retrieval import read_meeting_note
from app.agents.client_profiling.schemas import ClientProfile
from app.agents.client_profiling.store import DocumentStore, MeetingNoteDoc
from app.agents.client_profiling.store_pg import PostgresStore

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")


def test_chunking():
    assert embeddings.chunk_text("") == []
    short = "Para one.\n\nPara two."
    assert embeddings.chunk_text(short) == ["Para one.\n\nPara two."]
    long = " ".join(f"Sentence number {i} is here." for i in range(60))
    cs = embeddings.chunk_text(long)
    assert len(cs) > 3 and all(len(c) <= 400 for c in cs)
    assert " ".join(cs).split() == long.split()


def test_embed_failure_returns_none(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_LLM_URL", "http://127.0.0.1:9/v1")
    assert embeddings.embed_query("x") is None


class _Fake:
    def __init__(self, base, hits):
        self.base, self.hits = base, hits

    def __getattr__(self, n):
        return getattr(self.base, n)

    def search_notes(self, client_id, query, k=6):
        return self.hits


def _profile(store):
    c = next(x for x in store.list_clients() if store.get_notes(x.id))
    return ClientProfile(client_id=c.id, client_name=c.name, facts=[]), c


def test_build_context_uses_chunks_and_falls_back(monkeypatch):
    base = DocumentStore()
    profile, c = _profile(base)
    notes = base.get_notes(c.id)
    n = notes[-1]
    hit = {"note_id": n.id, "date": n.date, "title": n.title, "text": "UNIQUE-CHUNK-TEXT", "chunk_idx": 0, "score": 0.9}
    full = build_context(base, profile)[0]
    # notes fit the budget -> full notes, semantic search not used (no question-pattern heuristics)
    assert "UNIQUE-CHUNK-TEXT" not in build_context(_Fake(base, [hit]), profile, None, "What is the retirement goal?")[0]
    monkeypatch.setattr("app.agents.client_profiling.answer.MAX_CONTEXT_CHARS", len(full) // 2)
    ctx, refs = build_context(_Fake(base, [hit]), profile, None, "What is the retirement goal?")
    assert "UNIQUE-CHUNK-TEXT" in ctx and n.id in ctx and "Meeting" in ctx and n.id in refs
    assert len(ctx) < len(full)
    # search returns None -> unchanged
    assert build_context(_Fake(base, None), profile, None, "retirement?") == build_context(base, profile)
    # hit for a foreign note id is ignored
    bad = {**hit, "note_id": "nope"}
    assert build_context(_Fake(base, [bad]), profile, None, "retirement?")[0] == build_context(base, profile)[0]


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def pg():
    if not _reachable():
        pytest.skip("Postgres not reachable")
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    st = PostgresStore(dsn=DSN, schema=name)
    yield st
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def test_pg_degrades_without_vector(pg):
    if pg.vector_enabled:
        pytest.skip("pgvector is enabled; degradation path not applicable")
    c = pg.list_clients()[0]
    n = pg.add_note(MeetingNoteDoc(id="X-1", client_id=c.id, date="2030-01-01", title="t", text="Hello world."))
    assert pg.update_note(c.id, n.id, text="Changed.").text == "Changed."
    assert pg.search_notes(c.id, "hello") is None
    assert read_meeting_note(c.id, n.id, "changed", store=pg).status in ("ok", "insufficient_information")
    profile = ClientProfile(client_id=c.id, client_name=c.name, facts=[])
    assert n.id in build_context(pg, profile, None, "what changed?")[0]


def test_pg_semantic_isolation_and_replace(pg, monkeypatch):
    if not pg.vector_enabled:
        pytest.skip("pgvector extension not available on this Postgres (use the pgvector/pgvector:pg16 image)")
    if embeddings.embed_query("probe") is None:
        pytest.skip("embedding server not reachable")
    clients = pg.list_clients()
    a, b = clients[0], clients[1]
    pg.add_note(MeetingNoteDoc(id="S-A", client_id=a.id, date="2030-01-01", title="a", text="Wants to buy a sailing yacht."))
    pg.add_note(MeetingNoteDoc(id="S-B", client_id=b.id, date="2030-01-02", title="b", text="Wants to buy a sailing yacht."))
    hits = pg.search_notes(a.id, "yacht purchase", 20)
    assert hits and {h["note_id"] for h in hits} <= {x.id for x in pg.get_notes(a.id)}
    assert "S-B" not in {h["note_id"] for h in hits}
    pg.update_note(a.id, "S-A", text="Now prefers gardening and orchids.")
    with pg._connect() as conn:
        texts = [r["text"] for r in conn.execute("SELECT text FROM cp_note_chunks WHERE note_id='S-A'").fetchall()]
    assert texts == ["Now prefers gardening and orchids."]
