"""AI IPS generation: per-section drafts from meeting notes only, grounded + cited, read-only (fake chat, no network)."""
import json
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.ips_generate import SECTION_IDS, generate_ips_draft, generate_ips_section
from app.agents.client_profiling.store import DocumentStore, MeetingNoteDoc
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling/ips-generate"

NOTE = ("First meeting with Tom Lee. Tom is 45 years old and a surgeon at City Hospital. He earns 400k a year from salary. "
        "He has 20M with the bank. He wants to grow the portfolio to 700M within 8 years. He believes in healthcare and technology "
        "companies, prefers a long-term diversified approach, and avoids tobacco. He is a balanced investor and would accept a "
        "fall of 10% in a year. He needs 2M in cash for liquidity. Horizon is 8 years.")


class Store:
    def __init__(self, notes=None):
        self.notes = notes if notes is not None else [MeetingNoteDoc(id="note_a", client_id="x", date="2026-10-01", title="First meeting", text=NOTE)]
        self.ips_reads = 0

    def get_notes(self, cid):
        return self.notes

    def get_ips_versions(self, cid):
        self.ips_reads += 1
        raise AssertionError("IPS must not be read")

    latest_ips = get_ips_versions


def fake(out):
    calls = []

    def chat(system, user):
        calls.append((system, user))
        return json.dumps(out)
    chat.calls = calls
    return chat


GOOD = {
    "demographics": {"fields": [{"label": "Date of birth / age", "value": "45 years old", "cite": "N1"},
                                {"label": "Occupation", "value": "surgeon at City Hospital", "cite": "N1"},
                                {"label": "Annual income", "value": "400k", "cite": "N1"},
                                {"label": "AUM", "value": "20M", "cite": "N1"}]},
    "philosophy": {"approach": {"value": "long-term, diversified", "cite": "N1"},
                   "believes": {"value": "healthcare and technology", "cite": "N1"}, "avoids": {"value": "tobacco", "cite": "N1"}},
    "goals": {"bullets": [{"label": "Return requirements", "text": "Grow the portfolio to 700M within 8 years", "cite": "N1", "quote": "He wants to grow the portfolio to 700M within 8 years."}]},
    "risk": {"fields": [{"label": "Risk category", "value": "balanced", "cite": "N1"}, {"label": "Time horizon", "value": "8 years", "cite": "N1"},
                        {"label": "Risk tolerance (willingness)", "value": "would accept a fall of 10% in a year", "cite": "N1"},
                        {"label": "Risk capacity (ability)", "value": "8 years", "cite": "N1"},
                        {"label": "Liquidity needs", "value": "2M in cash", "cite": "N1"}],
             "bullets": [{"text": "Would accept a fall of 10% in a year", "cite": "N1"}]},
}


@pytest.mark.parametrize("section", [x for x in SECTION_IDS if x != "allocation"])
def test_per_section_shape(section):
    r = generate_ips_section(Store(), "x", section, fake(GOOD[section]))
    assert r["status"] == "ok" and r["section"] == section and r["message"]
    assert set(r) == {"section", "status", "message", "model", "fields", "bullets", "sources", "evidence", "notIncluded", "reasoning"} | ({"philosophy"} if section == "philosophy" else set()) | ({"goals", "targets"} if section == "goals" else set())
    assert r["sources"] == [{"id": "note_a", "date": "2026-10-01", "label": "First meeting"}]
    assert isinstance(r["fields"], dict) and isinstance(r["bullets"], list)


def test_values_kept_verbatim():
    d = generate_ips_section(Store(), "x", "demographics", fake(GOOD["demographics"]))
    assert d["fields"] == {"Date of birth / age": "45 years old", "Occupation": "surgeon at City Hospital", "Annual income": "400k", "AUM": "20M"}
    assert generate_ips_section(Store(), "x", "goals", fake(GOOD["goals"]))["bullets"] == ["Return requirements: Grow the portfolio to 700M within 8 years"]
    p = generate_ips_section(Store(), "x", "philosophy", fake(GOOD["philosophy"]))["philosophy"]
    assert p == {"approach": "long-term, diversified", "believes": "healthcare and technology", "avoids": "tobacco", "investmentPeriod": ""}
    r = generate_ips_section(Store(), "x", "risk", fake(GOOD["risk"]))
    assert r["fields"]["Risk category"] == "balanced" and r["bullets"] == ["Would accept a fall of 10% in a year"]


def test_grounding_drops_invented_facts():
    bad = {"fields": [{"label": "Annual income", "value": "S$400k", "cite": "N1"},          # invented currency
                      {"label": "AUM", "value": "50M", "cite": "N1"},                        # invented figure
                      {"label": "Occupation", "value": "astronaut at NASA", "cite": "N1"},  # invented phrase
                      {"label": "Date of birth / age", "value": "45 years old", "cite": "N9"},  # bad cite -> re-attributed
                      {"label": "Favourite colour", "value": "blue", "cite": "N1"}]}        # unknown label
    r = generate_ips_section(Store(), "x", "demographics", fake(bad))
    assert r["fields"] == {"Date of birth / age": "45 years old"}
    assert r["sources"][0]["id"] == "note_a" and "removed" in r["message"]
    g = generate_ips_section(Store(), "x", "goals", fake({"bullets": [{"label": "Return requirements", "text": "Grow the portfolio to 900M within 8 years", "cite": "N1", "quote": ""},
                                                                       {"label": "Primary goals", "text": "Retire at 55 on a yacht", "cite": "N1", "quote": ""}]}))
    # invented 900M / yacht dropped; only the safety-net target taken verbatim from the notes remains
    assert g["bullets"] == ["Return requirements: grow the portfolio to 700M within 8 years"] and "900M" not in json.dumps(g)


def test_nothing_stated_is_ok_but_empty():
    r = generate_ips_section(Store(), "x", "philosophy", fake({k: {"value": "", "cite": ""} for k in ("approach", "believes", "avoids", "investmentPeriod")}))
    assert r["status"] == "ok" and r["philosophy"] == {"approach": "", "believes": "", "avoids": "", "investmentPeriod": ""} and r["sources"] == []


def test_no_notes_and_no_model_calls():
    c = fake({})
    r = generate_ips_section(Store(notes=[]), "x", "goals", c)
    assert r["status"] == "no_notes" and r["message"].startswith("No meeting notes found.") and "pload" in r["message"] and r["fields"] == {} and r["bullets"] == [] and not c.calls


def test_unavailable_when_model_off_or_broken(monkeypatch):
    r = generate_ips_section(Store(), "x", "goals")  # autouse fixture disables the local model
    assert r["status"] == "unavailable" and r["bullets"] == [] and r["fields"] == {}

    def boom(s, u):
        raise OSError("down")
    assert generate_ips_section(Store(), "x", "goals", boom)["status"] == "unavailable"
    assert generate_ips_section(Store(), "x", "goals", lambda s, u: "not json")["status"] == "unavailable"
    assert generate_ips_section(Store(notes=[MeetingNoteDoc(id="n", client_id="x", date="2026-10-01", title="t", text="Likes tea.")]), "x", "goals",
                                lambda s, u: json.dumps({"bullets": "oops"}))["bullets"] == []


def test_never_reads_ips_and_prompt_has_only_notes():
    st, c = Store(), fake(GOOD["goals"])
    generate_ips_section(st, "x", "goals", c)
    assert st.ips_reads == 0 and "<notes>" in c.calls[0][1] and "700M" in c.calls[0][1]


def test_unknown_section_value_error():
    with pytest.raises(ValueError):
        generate_ips_section(Store(), "x", "nope", fake({}))


def test_tool_envelope():
    t = generate_ips_draft(Store(), "x", "goals", fake(GOOD["goals"]))
    assert t.tool == "generate_ips_draft" and t.status == "ok" and t.data["bullets"]
    assert generate_ips_draft(Store(notes=[]), "x", "goals").status == "not_found"
    assert generate_ips_draft(Store(), "x", "bad").status == "insufficient_information"


def test_only_this_clients_notes_are_requested():
    asked = []

    class Spy(Store):
        def get_notes(self, cid):
            asked.append(cid)
            return super().get_notes(cid)
    generate_ips_section(Spy(), "jft", "goals", fake(GOOD["goals"]))
    assert asked == ["jft"]


# --- endpoint ---
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_STORE", "json")
    monkeypatch.setattr(store_mod, "_default", DocumentStore())
    return TestClient(app)


def test_sections_endpoint(client):
    assert client.get(f"{U}/sections").json() == [
        {"id": "demographics", "label": "Demographics"}, {"id": "philosophy", "label": "Investment philosophy"},
        {"id": "goals", "label": "Goals and objectives"}, {"id": "risk", "label": "Risk profile"}, {"id": "allocation", "label": "3L allocation"}]


def test_endpoint_not_in_book_403_and_bad_section_422(client):
    r = client.post(U, json={"client_id": "ser", "section": "goals"})
    assert r.status_code == 403 and r.json()["detail"] == "Client is not in your book"
    assert client.post(U, json={"client_id": "jft", "section": "bogus"}).status_code == 422
    assert client.post(U, json={"section": "goals"}).status_code == 422


def test_endpoint_model_off_is_unavailable_and_writes_nothing(client):
    s = store_mod.get_default_store()
    before = (len(s.get_notes("jft")), len(s.get_ips_versions("jft")))
    j = client.post(U, json={"client_id": "jft", "section": "goals"}).json()
    assert j["status"] == "unavailable" and j["section"] == "goals" and j["bullets"] == []
    assert (len(s.get_notes("jft")), len(s.get_ips_versions("jft"))) == before


def test_endpoint_with_injected_chat(client, monkeypatch):
    from app.agents.client_profiling import ips_generate as g
    real = g.generate_ips_section
    monkeypatch.setattr("app.endpoints.client_profiling.generate_ips_section",
                        lambda st, cid, sec: real(st, cid, sec, fake({"bullets": [{"label": "Investment time horizon", "text": "At least ten years", "cite": "N1", "quote": ""}]})))
    j = client.post(U, json={"client_id": "jft", "section": "goals"}).json()
    assert j["status"] == "ok" and "Investment time horizon: At least ten years" in j["bullets"] and j["sources"][0]["id"].startswith("note_jft")


# --- Postgres (throwaway schema) ---
def _pg_ok():
    import psycopg
    try:
        psycopg.connect(os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents"), connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_ok(), reason="Postgres not reachable")
def test_postgres_store_generation():
    import psycopg
    from psycopg import sql
    from app.agents.client_profiling.store_pg import PostgresStore
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    try:
        s = PostgresStore(schema=name)
        s.add_note(MeetingNoteDoc(id="note_up_9", client_id="jft", date="2026-10-25", title="New", source_file="n.txt",
                                  text="Jane wants to grow the portfolio to 700M within 8 years."))
        c = fake({"bullets": [{"label": "Return requirements", "text": "Grow the portfolio to 700M within 8 years", "cite": "N1", "quote": ""}]})
        r = generate_ips_section(s, "jft", "goals", c)
        assert r["status"] == "ok" and r["sources"]
        assert "700M within 8 years" in r["bullets"][0] and r["sources"][0]["id"] == "note_up_9"
    finally:
        with psycopg.connect(os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents"), autocommit=True) as cn:
            cn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


# --- labelled goals, evidence, equivalence ---
LABELLED = {"bullets": [
    {"label": "Primary goals", "text": "Keep capital safe", "cite": "N1", "quote": "keep capital safe"},
    {"label": "Return requirements", "text": "Low risk with steady growth", "cite": "N1", "quote": "low risk but steady growth"},
    {"label": "Return requirements", "text": "Return requirements: Portfolio to hit 700M within 8 years", "cite": "N1", "quote": "hit 700 M within 8 years"},
    {"label": "Investment time horizon", "text": "8 years", "cite": "N1", "quote": "invented quote not in the note"},
    {"label": "Secondary goals", "text": "Capital preservation", "cite": "N1", "quote": ""},   # 'preservation' not in the notes
    {"label": "Made up label", "text": "Keep capital safe", "cite": "N1", "quote": ""},
]}
N2 = MeetingNoteDoc(id="note_b", client_id="x", date="2026-10-02", title="Goals chat",
                    text="Jane wants low risk but steady growth and to keep capital safe.\nShe wants the portfolio to hit 700M within 8 years")


def test_labelled_goals_target_and_evidence():
    st = Store(notes=[N2])
    r = generate_ips_section(st, "x", "goals", fake(LABELLED))
    assert r["bullets"] == ["Return requirements: Low risk with steady growth",
                            "Return requirements: Portfolio to hit 700M within 8 years",
                            "Investment time horizon: 8 years", "Primary goals: Keep capital safe",
                          "Unique circumstances & preferences: Keep capital safe"]  # unknown label -> Unique circumstances (IS-93)
    assert any(b.startswith("Return requirements:") and "700" in b and "8 years" in b for b in r["bullets"]), r["bullets"]
    assert all(b.split(":")[0] in ("Return requirements", "Investment time horizon", "Primary goals") for b in r["bullets"][:4])
    assert r["evidence"]
    for e in r["evidence"]:
        assert set(e) == {"item", "noteId", "date", "title", "passage"} and e["noteId"] == "note_b" and e["date"] == "2026-10-02"
        assert e["passage"] in N2.text and e["item"] in r["bullets"]


def test_target_safety_net_when_model_skips_it():
    r = generate_ips_section(Store(notes=[N2]), "x", "goals", fake({"bullets": [
        {"label": "Primary goals", "text": "Capital preservation", "cite": "N1", "quote": ""}]}))
    assert "Return requirements: Portfolio to hit 700M within 8 years" in r["bullets"]
    assert r["bullets"][0].startswith("Return requirements")


def test_risk_fields_and_evidence_passages_are_verbatim():
    out = {"fields": [{"label": "risk tolerance (willingness)", "value": "would accept a fall of 10% in a year", "cite": "N1",
                       "quote": "a fall of 10% in a year"},
                      {"label": "Risk capacity (ability)", "value": "8 years", "cite": "N1", "quote": "nonsense not in note"}],
           "bullets": [{"text": "Would accept a fall of 10% in a year", "cite": "N1", "quote": ""}]}
    r = generate_ips_section(Store(), "x", "risk", fake(out))
    assert set(r["fields"]) == {"Risk tolerance (willingness)", "Risk capacity (ability)"}
    assert len(r["evidence"]) == 3
    assert all(e["passage"] in NOTE and e["noteId"] == "note_a" for e in r["evidence"])
    assert r["evidence"][0]["passage"].lower() == "a fall of 10% in a year"


def test_unit_equivalence_but_not_inventions():
    from app.agents.client_profiling.ips_generate import _grounded, _numbers, _words, _CCY
    t = "He wants 700 million within 8-year, a 10% fall and low risk but steady growth. Horizon is 8 yrs."
    g = lambda x: _grounded(x, t, _numbers(t), _words(t), {c.lower() for c in _CCY.findall(t)})
    assert g("700M within 8 years") and g("steady growth with low risk") and g("700 M")
    assert not g("700B within 8 years") and not g("800M within 8 years") and not g("10 years") and not g("S$700M")


def test_long_notes_are_batched_and_merged(monkeypatch):
    from app.agents.client_profiling import ips_generate as g
    monkeypatch.setattr(g, "MAX_NOTES_CHARS", 300)
    long = MeetingNoteDoc(id="note_l", client_id="x", date="2026-10-03", title="Long", text=(
        "Filler paragraph about nothing in particular. " * 5 + "\n\nJane wants the portfolio to hit 700M within 8 years.\n\n"
        + "More filler about weather and travel plans. " * 5))
    calls = []

    def chat(system, user):
        calls.append(user)
        has = "700M" in user
        return json.dumps({"bullets": [{"label": "Return requirements", "text": "Portfolio to hit 700M within 8 years", "cite": "N1"}] if has else []})
    r = generate_ips_section(Store(notes=[long]), "x", "goals", chat)
    assert len(calls) > 1 and all(len(c) < 700 for c in calls)
    assert r["bullets"] == ["Return requirements: Portfolio to hit 700M within 8 years"] and r["evidence"][0]["passage"] in long.text


# --- speed: one model call per section for a typical note set, still batched for very long notes, truncation fails fast ---
def _two_notes(n):
    body = "He is 45 years old. " * (n // 20)
    return [MeetingNoteDoc(id=f"n{i}", client_id="x", date=f"2026-10-0{i}", title=f"Meeting {i}", text=NOTE + "\n\n" + body) for i in (1, 2)]


def test_typical_notes_are_one_call_per_section():
    chat = fake({"fields": []})
    generate_ips_section(Store(_two_notes(2000)), "x", "demographics", chat=chat)  # 2 notes of ~2.1k chars (cap 5500)
    assert len(chat.calls) == 1


def test_very_long_notes_still_batch():
    chat = fake({"fields": []})
    generate_ips_section(Store(_two_notes(12000)), "x", "demographics", chat=chat)
    assert len(chat.calls) > 1
    assert all(len(u) < 9000 + 600 for _, u in chat.calls)


def test_truncated_reply_retries_once_bigger_then_raises(monkeypatch):
    from app.agents.client_profiling import ips_generate as g
    seen = []

    def post(body, timeout):
        seen.append(body["max_tokens"])
        return {"choices": [{"finish_reason": "length", "message": {"content": '{"fields": [{"lab'}}], "usage": {}}

    monkeypatch.setattr(g, "post_chat", post)
    monkeypatch.setattr(g, "GEN_MAX_TOKENS_RETRY", 2 * g.GEN_MAX_TOKENS)  # the bigger retry is opt-in (default = same budget)
    with pytest.raises(g.TruncatedReply):
        g._gen_chat("t", {"type": "object"}, "m")("s", "u")
    assert seen == [g.GEN_MAX_TOKENS, g.GEN_MAX_TOKENS_RETRY]


def test_truncated_first_then_ok_returns_reply(monkeypatch):
    from app.agents.client_profiling import ips_generate as g
    replies = iter([("length", '{"x'), ("stop", '{"fields": []}')])
    monkeypatch.setattr(g, "GEN_MAX_TOKENS_RETRY", 2 * g.GEN_MAX_TOKENS)
    monkeypatch.setattr(g, "post_chat", lambda b, t: (lambda r: {"choices": [{"finish_reason": r[0], "message": {"content": r[1]}}]})(next(replies)))
    assert g._gen_chat("t", {}, "m")("s", "u") == '{"fields": []}'


def test_truncation_does_not_sleep_or_repeat(monkeypatch):
    from app.agents.client_profiling import ips_generate as g
    n = {"c": 0}

    def chat(system, user):
        n["c"] += 1
        raise g.TruncatedReply("cut")

    res = generate_ips_section(Store(), "x", "demographics", chat=chat)
    assert n["c"] == 1 and res["status"] == "unavailable"
