"""Real-Postgres integration tests for PostgresStore. Run in a throwaway schema (dropped at teardown);
never touch the real cp_* tables. Skipped when Postgres is unreachable."""
import os
import uuid

import psycopg
import pytest
from psycopg import sql

from app.agents.client_profiling.store import MeetingNoteDoc, StoreUnavailableError
from app.agents.client_profiling.store_pg import PostgresStore

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")


def _reachable() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="Postgres not reachable")


@pytest.fixture
def schema():
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    yield name
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def _count(schema, table):
    with psycopg.connect(DSN) as c:
        return c.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]


def _note(i="note_up_1", client="ser", title="T", text="body"):
    return MeetingNoteDoc(id=i, client_id=client, date="2026-10-20", title=title, source_file="f.txt", text=text)


def test_seed_idempotent_and_no_overwrite(schema):
    s = PostgresStore(schema=schema)
    counts = [_count(schema, t) for t in ("cp_clients", "cp_ips_versions", "cp_meeting_notes")]
    assert all(c > 0 for c in counts)
    seeded = s.get_notes("jfr")[0]
    assert s.update_note("jfr", seeded.id, title="EDITED", text="edited text").title == "EDITED"
    from app.agents.client_profiling import store_pg
    store_pg._SEEDED.clear()  # simulate a process restart
    s2 = PostgresStore(schema=schema)
    assert [_count(schema, t) for t in ("cp_clients", "cp_ips_versions", "cp_meeting_notes")] == counts
    assert s2.get_note("jfr", seeded.id).title == "EDITED"


def test_latest_ips_rules(schema):
    s = PostgresStore(schema=schema)
    ips, current = s.latest_ips("ser")
    assert (ips.version, ips.status, current) == (2, "Active", True)
    assert [v.version for v in s.get_ips_versions("ser")] == sorted([v.version for v in s.get_ips_versions("ser")], reverse=True)
    ips, current = s.latest_ips("jfr")
    assert ips.status == "Draft" and current is False
    assert all(isinstance(p.body, str) for p in ips.parts)


def test_add_and_update_persist_across_instances(schema):
    s = PostgresStore(schema=schema)
    s.add_note(_note())
    with pytest.raises(ValueError):
        s.add_note(_note())
    with pytest.raises(ValueError):
        s.add_note(_note(i="note_up_2", client="nobody"))
    assert s.update_note("ser", "note_up_1", title="New", text="new text").text == "new text"
    s2 = PostgresStore(schema=schema)
    n = s2.get_note("ser", "note_up_1")
    assert (n.title, n.text) == ("New", "new text")
    assert s2.get_notes("ser")[0].id == "note_up_1"  # newest first (2026-10-20 is latest)


def test_client_isolation(schema):
    s = PostgresStore(schema=schema)
    s.add_note(_note())
    assert s.get_note("jfr", "note_up_1") is None
    assert s.update_note("jfr", "note_up_1", title="hijack") is None
    assert s.get_note("ser", "note_up_1").title == "T"
    assert all(n.client_id == "jfr" for n in s.get_notes("jfr"))


def test_sql_injection_title_is_data(schema):
    s = PostgresStore(schema=schema)
    evil = "x'); drop table cp_meeting_notes;--"
    s.add_note(_note(title=evil))
    s.update_note("ser", "note_up_1", text=evil)
    n = PostgresStore(schema=schema).get_note("ser", "note_up_1")
    assert n.title == evil and n.text == evil
    assert _count(schema, "cp_meeting_notes") > 0


def test_unreachable_raises_clear_error():
    with pytest.raises(StoreUnavailableError, match="not reachable"):
        PostgresStore(dsn="postgresql://postgres:x@127.0.0.1:1/none", schema="cp_test_unreach")


def _rows(schema, query):
    with psycopg.connect(DSN) as c:
        c.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        return c.execute(query).fetchall()


def test_client_name_views(schema):
    s = PostgresStore(schema=schema)
    s.add_note(_note("note_v1", client="jft"))
    names = {r[0]: r[1] for r in _rows(schema, "SELECT id, name FROM cp_clients")}
    notes = _rows(schema, "SELECT client_id, client_name, title FROM v_meeting_notes")
    assert len(notes) == _count(schema, "cp_meeting_notes") and all(n[1] == names[n[0]] for n in notes)
    ips = _rows(schema, "SELECT client_id, client_name, version FROM v_ips_versions")
    assert len(ips) == _count(schema, "cp_ips_versions") and all(r[1] == names[r[0]] for r in ips)
    if s.vector_enabled:  # chunk views exist only with pgvector; they never expose the embedding
        cols = [r[0] for r in _rows(schema, "SELECT column_name FROM information_schema.columns "
                                            f"WHERE table_schema='{schema}' AND table_name='v_note_chunks'")]
        assert "client_name" in cols and "text" in cols and "embedding" not in cols
        _rows(schema, "SELECT client_id, client_name, text FROM v_ips_chunks")


def test_view_follows_rename_and_blank_name_fallback(schema):
    PostgresStore(schema=schema)
    with psycopg.connect(DSN) as c:
        c.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        cid = c.execute("SELECT client_id FROM cp_ips_versions LIMIT 1").fetchone()[0]
        q = "SELECT DISTINCT client_name FROM v_ips_versions WHERE client_id=%s"
        c.execute("UPDATE cp_clients SET name='Renamed Person' WHERE id=%s", (cid,))
        assert c.execute(q, (cid,)).fetchall() == [("Renamed Person",)]
        c.execute("UPDATE cp_clients SET name='  ' WHERE id=%s", (cid,))
        assert c.execute(q, (cid,)).fetchall() == [(cid,)]


def test_views_idempotent_on_reinit(schema):
    from app.agents.client_profiling import store_pg
    PostgresStore(schema=schema)
    store_pg._SEEDED.clear()
    store_pg._VECTOR.clear()
    PostgresStore(schema=schema)
    assert _rows(schema, "SELECT count(*) FROM v_meeting_notes")[0][0] > 0
