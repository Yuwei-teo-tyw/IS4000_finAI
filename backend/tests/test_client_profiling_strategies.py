"""Strategy table (JSON + Postgres), investor-profile guide search/context, guide chat routing."""
import os
import uuid

import psycopg
import pytest
from psycopg import sql

from app.agents.client_profiling import guide
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DocumentStore
from app.agents.client_profiling.store_pg import PostgresStore
from app.agents.client_profiling.strategies import load_strategies

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


pg_only = pytest.mark.skipif(not _reachable(), reason="Postgres not reachable")


@pytest.fixture
def pg():
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    yield PostgresStore(schema=name)
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def test_json_store_strategies_match_file():
    assert DocumentStore().list_strategies() == load_strategies()


@pg_only
def test_pg_strategies_seeded_same_shape(pg):
    assert pg.list_strategies() == load_strategies()
    assert [s["code"] for s in pg.list_strategies()] == list("ABCDEF")


@pg_only
def test_pg_seed_idempotent(pg):
    PostgresStore(schema=pg.schema)
    assert len(pg.list_strategies()) == 6


def test_guide_chunks_and_keyword_search():
    assert len(guide.guide_chunks()) >= 9
    hits = guide.search_guide("what is loss capacity free assets", 2, store=DocumentStore())
    assert hits and set(hits[0]) == {"text", "heading"} and "Financial situation" in hits[0]["heading"]


def test_strategy_context_compact_and_complete():
    ctx = guide.strategy_context("strategy E drawdown", store=DocumentStore())
    assert len(ctx) <= 2500
    assert all(f"\n{c} " in ctx for c in "ABCDEF") and "[G]" in ctx


@pg_only
def test_pg_guide_index_and_search(pg):
    if not pg.vector_enabled:
        pytest.skip("pgvector unavailable")
    from app.agents.client_profiling import embeddings
    if embeddings.embed_query("x") is None:
        pytest.skip("embedding model unavailable")
    assert pg.index_guide() is True
    hits = pg.search_guide("how is loss capacity computed", 2)
    assert hits and any("loss capacity" in h["text"] for h in hits)


@pytest.mark.parametrize("q", [
    "Explain the 3L approach", "What is the max drawdown of Strategy E?", "What is risk budget?",
    "How does loss capacity work?", "Why is the Liquidity portfolio only strategy A or B?",
    "What is the strategic asset allocation of Balanced?", "difference between risk ability and risk tolerance"])
def test_guide_questions_route_to_guide(q):
    r = handle_chat(q, client_id="jfr", store=DocumentStore(), answer_chat=lambda s, u: "Strategy E has a max drawdown of 45%.")
    assert r.tool == "get_guide" and r.status == "ok"
    labels = {x["label"] for x in r.data["answer"]["sources"]}
    assert labels == {"Investor Profile guide", "Strategy table"}


@pytest.mark.parametrize("q", ["What is her risk tolerance?", "What did she say about equities?", "What is the allocation in the IPS?"])
def test_other_questions_not_hijacked(q):
    assert not guide.is_guide_question(q)


def test_invented_numbers_fall_back_to_table():
    r = handle_chat("What is the max drawdown of Strategy E?", client_id="jfr", store=DocumentStore(),
                    answer_chat=lambda s, u: "Strategy E can lose 77% at most.")
    assert "77" not in r.message and "-45%" in r.message


def test_model_down_gives_table_answer(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_LLM_ENABLED", "false")
    r = handle_chat("What is the expected return of strategy B?", client_id="jfr", store=DocumentStore())
    assert r.tool == "get_guide" and "expected return 3.0%" in r.message
