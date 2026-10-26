"""IS-84: client name shown next to client_id on meeting-note / IPS records (real-Postgres views + API payloads)."""
import os
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import DocumentStore
from app.agents.client_profiling.store_pg import PostgresStore
from app.endpoints.client_profiling import router

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
VIEWS = ("v_meeting_notes", "v_note_chunks", "v_ips_versions", "v_ips_chunks")


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


pg_only = pytest.mark.skipif(not _reachable(), reason="Postgres not reachable")


@pytest.fixture
def schema():
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    yield name
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def _q(schema, query, params=()):
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else None


@pytest.fixture
def pg(schema):
    s = PostgresStore(schema=schema)
    # one chunk row per chunk table so the chunk views have data (embedding NULL is allowed)
    if s.vector_enabled:
        note = s.get_notes("jfr")[0]
        _q(schema, "INSERT INTO cp_note_chunks (note_id, client_id, chunk_idx, text) VALUES (%s,'jfr',0,'c')", (note.id,))
        _q(schema, "INSERT INTO cp_ips_chunks (client_id, version, part_n, chunk_idx, text) VALUES ('jfr',2,1,0,'c')")
    return s


def _names(schema, view, cid="jfr"):
    return {r[0] for r in _q(schema, f"SELECT client_name FROM {view} WHERE client_id = %s", (cid,))}


@pg_only
@pytest.mark.parametrize("view", VIEWS)
def test_views_show_name_next_to_id(pg, schema, view):
    if view.endswith("chunks") and not pg.vector_enabled:
        pytest.skip("pgvector unavailable: chunk tables/views not created")
    rows = _q(schema, f"SELECT client_id, client_name FROM {view}")
    assert rows
    clients = dict(_q(schema, "SELECT id, name FROM cp_clients"))
    assert all(name == clients[cid] for cid, name in rows)  # always matches cp_clients


@pg_only
def test_test_twin_name_is_shown_verbatim(pg, schema):
    twin = next((c for c in pg.list_clients() if "(test)" in c.name), None)
    if twin is None:
        pytest.skip("no test twin seeded")
    assert _names(schema, "v_meeting_notes", twin.id) == {twin.name} == {"Jane Fraser (test)"}


@pg_only
@pytest.mark.parametrize("view", VIEWS)
def test_rename_propagates_live(pg, schema, view):
    if view.endswith("chunks") and not pg.vector_enabled:
        pytest.skip("pgvector unavailable")
    assert _names(schema, view) != {"Jane Fraser (test)"}
    _q(schema, "UPDATE cp_clients SET name = 'Jane Fraser (test)' WHERE id = 'jfr'")
    assert _names(schema, view) == {"Jane Fraser (test)"}
    _q(schema, "UPDATE cp_clients SET name = 'Renamed Again' WHERE id = 'jfr'")
    assert _names(schema, view) == {"Renamed Again"}


@pg_only
@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("view", VIEWS)
def test_empty_name_falls_back_to_client_id(pg, schema, view, blank):
    if view.endswith("chunks") and not pg.vector_enabled:
        pytest.skip("pgvector unavailable")
    _q(schema, "UPDATE cp_clients SET name = %s WHERE id = 'jfr'", (blank,))
    assert _names(schema, view) == {"jfr"}


@pg_only
def test_orphan_record_without_client_row_shows_id_no_error(pg, schema):
    _q(schema, "INSERT INTO cp_meeting_notes (id, client_id, note_date, title, text) VALUES ('n_orph','ghost','2026-01-01','t','x')")
    assert _names(schema, "v_meeting_notes", "ghost") == {"ghost"}


@pg_only
def test_lookups_unchanged_and_client_id_remains_key(pg, schema):
    cols = {r[0] for r in _q(schema, "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='cp_meeting_notes'", (schema,))}
    assert "client_name" not in cols  # no denormalised copy in base tables
    assert all(c.id and pg.get_client(c.id) for c in pg.list_clients())
    assert [n.client_id for n in pg.get_notes("jfr")] == ["jfr"] * len(pg.get_notes("jfr"))
    assert pg.get_ips_versions("jfr")


@pg_only
@pytest.mark.parametrize("view", VIEWS)
def test_views_are_plain_read_only_views(pg, schema, view):
    if view.endswith("chunks") and not pg.vector_enabled:
        pytest.skip("pgvector unavailable")
    assert _q(schema, "SELECT table_type FROM information_schema.tables WHERE table_schema=%s AND table_name=%s", (schema, view)) == [("VIEW",)]
    # base tables carry no client_name column and the join is live (rename test above); embeddings are not exposed
    cols = {r[0] for r in _q(schema, "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (schema, view))}
    assert {"client_id", "client_name"} <= cols and "embedding" not in cols


@pg_only
def test_view_creation_idempotent(schema):
    from app.agents.client_profiling import store_pg
    PostgresStore(schema=schema)
    store_pg._SEEDED.clear()
    PostgresStore(schema=schema)  # re-runs CREATE OR REPLACE VIEW without error
    assert _q(schema, "SELECT count(*) FROM v_meeting_notes")[0][0] > 0


# ---- API payload parity (JSON store) ----
app = FastAPI()
app.include_router(router)
BASE = "/agents/client-profiling"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_STORE", "json")
    st = DocumentStore()
    monkeypatch.setattr(store_mod, "_default", st)
    return TestClient(app), st


def _in_book_client(st):
    cl = st.get_client("jfr")
    st.set_in_book("jfr", True)
    return cl


def test_api_notes_and_ips_include_client_name(api):
    c, st = api
    cl = _in_book_client(st)
    notes = c.get(f"{BASE}/meeting-notes/{cl.id}").json()
    assert notes and all(n["clientName"] == cl.name and n["clientId"] == cl.id for n in notes)
    j = c.get(f"{BASE}/ips/{cl.id}").json()
    assert j["clientName"] == cl.name == j["client_name"] and j["client_id"] == cl.id


def test_api_blank_name_falls_back_to_id(api):
    c, st = api
    cl = _in_book_client(st)
    st.get_client = lambda cid, _o=st.get_client: (lambda x: x.model_copy(update={"name": "  "}) if x else x)(_o(cid))
    assert c.get(f"{BASE}/ips/{cl.id}").json()["clientName"] == cl.id
    assert all(n["clientName"] == cl.id for n in c.get(f"{BASE}/meeting-notes/{cl.id}").json())
