"""IS-98: multiple named Geneva chats - list/create/title/replay/isolation/DB-down. Real Postgres where reachable."""
import os
import uuid
from contextlib import asynccontextmanager

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import db, geneva_chats
from app.core.geneva_chats import derive_title, has_clear_topic
from app.endpoints.geneva_chats import router

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
U = "/geneva/chats"


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


needs_pg = pytest.mark.skipif(not _reachable(), reason="Postgres not reachable")


@asynccontextmanager
async def _lifespan(app):
    await db.init_pool()
    yield
    await db.close_pool()


def _app(lifespan=None) -> FastAPI:
    a = FastAPI(lifespan=lifespan)
    a.include_router(router)
    return a


@pytest.fixture
def client():
    with TestClient(_app(_lifespan)) as c:
        yield c


@pytest.fixture
def rm():
    rid = f"rm_t_{uuid.uuid4().hex[:8]}"
    yield rid
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DELETE FROM geneva_chats WHERE rm_id = %s", (rid,))


def H(rid):
    return {"X-RM-Id": rid}


def cid():
    return f"t-{uuid.uuid4().hex[:10]}"


def turn(c, rid, chat, q, a="Answer."):
    c.post(f"{U}/{chat}/messages", json={"role": "user", "text": q}, headers=H(rid))
    return c.post(f"{U}/{chat}/messages", json={"role": "assistant", "text": a}, headers=H(rid)).json()


# ---- title heuristic (no DB) ----
def test_title_short_and_readable():
    assert derive_title("Why Strategy D for Longevity?") == "Why Strategy D for Longevity?"
    t = derive_title("can you please explain why we chose Strategy D for the Longevity bucket given the client's risk tolerance and horizon?")
    assert t and len(t) <= 41 and t != "New chat" and "please" not in t.lower()


@pytest.mark.parametrize("p", ["hi", "Hello!", "ok", "thanks", "", "  hey  "])
def test_unclear_prompts_have_no_title(p):
    assert not has_clear_topic(p) and derive_title(p) is None


# ---- API against Postgres ----
@needs_pg
def test_empty_list_then_newest_first_with_names(client, rm):
    r = client.get(U, headers=H(rm))
    assert r.status_code == 200 and r.json() == {"chats": [], "historyAvailable": True}
    a, b = cid(), cid()
    turn(client, rm, a, "What is the outlook for US equities?")
    turn(client, rm, b, "Why Strategy D for Longevity?")
    chats = client.get(U, headers=H(rm)).json()["chats"]
    assert [c["id"] for c in chats] == [b, a]
    assert chats[0]["title"] == "Why Strategy D for Longevity?"
    assert chats[1]["title"] == "What is the Outlook for US Equities?"


@needs_pg
def test_create_empty_chat_leaves_others_unchanged(client, rm):
    a = cid()
    turn(client, rm, a, "Show gold exposure for the portfolio")
    before = client.get(f"{U}/{a}/messages", headers=H(rm)).json()
    n = cid()
    r = client.post(U, json={"id": n}, headers=H(rm))
    assert r.status_code == 200 and r.json()["title"] == "New chat"
    assert client.post(U, json={"id": n}, headers=H(rm)).json()["id"] == n  # idempotent
    assert client.get(f"{U}/{n}/messages", headers=H(rm)).json()["messages"] == []
    assert client.get(f"{U}/{a}/messages", headers=H(rm)).json() == before


@needs_pg
def test_title_set_only_after_reply_and_unclear_prompt_stays_new_chat(client, rm):
    c = cid()
    r = client.post(f"{U}/{c}/messages", json={"role": "user", "text": "hi"}, headers=H(rm))
    assert r.json()["title"] == "New chat"
    r = client.post(f"{U}/{c}/messages", json={"role": "assistant", "text": "Hello, how can I help?"}, headers=H(rm))
    assert r.json()["title"] == "New chat"
    client.post(f"{U}/{c}/messages", json={"role": "user", "text": "Why Strategy D for Longevity?"}, headers=H(rm))
    assert client.get(U, headers=H(rm)).json()["chats"][0]["title"] == "New chat"  # not named until Geneva replies
    r = client.post(f"{U}/{c}/messages", json={"role": "assistant", "text": "Because..."}, headers=H(rm))
    assert r.json()["title"] == "Why Strategy D for Longevity?"
    # title is stable afterwards
    assert turn(client, rm, c, "Something entirely different about bonds")["title"] == "Why Strategy D for Longevity?"


@needs_pg
def test_messages_replayed_in_order(client, rm):
    c = cid()
    turn(client, rm, c, "first question about bonds", "first answer")
    turn(client, rm, c, "second question about gold", "second answer")
    msgs = client.get(f"{U}/{c}/messages", headers=H(rm)).json()["messages"]
    assert [(m["role"], m["text"]) for m in msgs] == [
        ("user", "first question about bonds"), ("assistant", "first answer"),
        ("user", "second question about gold"), ("assistant", "second answer")]


@needs_pg
def test_duplicate_titles_both_listed_with_distinct_ids_and_dates(client, rm):
    a, b = cid(), cid()
    turn(client, rm, a, "Why Strategy D for Longevity?")
    turn(client, rm, b, "Why Strategy D for Longevity?")
    chats = client.get(U, headers=H(rm)).json()["chats"]
    assert len(chats) == 2 and chats[0]["title"] == chats[1]["title"]
    assert chats[0]["id"] != chats[1]["id"] and all(c["createdAt"] and c["updatedAt"] for c in chats)


@needs_pg
def test_another_rm_cannot_see_or_touch_my_chats(client, rm):
    other = rm + "_other"
    c = cid()
    turn(client, rm, c, "Why Strategy D for Longevity?")
    assert client.get(U, headers=H(other)).json()["chats"] == []
    assert client.get(f"{U}/{c}/messages", headers=H(other)).status_code == 404
    assert client.post(f"{U}/{c}/messages", json={"role": "user", "text": "x y z"}, headers=H(other)).status_code == 404
    assert client.post(U, json={"id": c}, headers=H(other)).status_code == 404
    assert len(client.get(f"{U}/{c}/messages", headers=H(rm)).json()["messages"]) == 2


@needs_pg
def test_missing_header_uses_default_rm(client):
    c = cid()
    try:
        client.post(f"{U}/{c}/messages", json={"role": "user", "text": "hello there"})
        assert c in [x["id"] for x in client.get(U).json()["chats"]]
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute("DELETE FROM geneva_chats WHERE id = %s", (c,))


# ---- DB unreachable (no Postgres needed) ----
def test_db_down_reports_history_unavailable():
    with TestClient(_app()) as c:  # pool never initialised
        for r in (c.get(U), c.post(U, json={"id": "x"}), c.get(f"{U}/x/messages"),
                  c.post(f"{U}/x/messages", json={"role": "user", "text": "hello there"})):
            assert r.status_code == 503
            assert r.json()["historyAvailable"] is False and "unavailable" in r.json()["detail"].lower()


def test_db_error_mid_request_is_503(monkeypatch):
    class Boom:
        def connection(self):
            raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(db, "_pool", Boom())
    geneva_chats.reset_ready()
    with TestClient(_app()) as c:
        assert c.get(U).status_code == 503
