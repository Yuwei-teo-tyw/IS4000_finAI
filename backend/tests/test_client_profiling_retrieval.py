"""Tests for the Client Profiling Agent store, retrieval tools and key-fact extraction.

Uses the FICTIONAL seed data in app/agents/client_profiling/data (no LLM, no network).
"""
import json
import shutil
from pathlib import Path

import pytest

from app.agents.client_profiling import extract_key_facts, get_meeting_note, read_meeting_note, resolve_client
from app.agents.client_profiling.schemas import ClientProfile, ToolResult
from app.agents.client_profiling.store import DEFAULT_DATA_DIR, DocumentStore

CLIENTS = ["ser", "dso", "jfr", "teo", "sha"]
OTHER_NAMES = {"ser": ["David", "Solomon", "Jane", "Fraser", "Teo", "Yuwei", "Shane"],
               "dso": ["Sergio", "Ermotti", "Jane", "Fraser", "Teo", "Yuwei", "Shane"],
               "jfr": ["Sergio", "Ermotti", "David", "Solomon", "Teo", "Yuwei", "Shane"],
               "teo": ["Sergio", "Ermotti", "David", "Solomon", "Jane", "Fraser", "Shane"],
               "sha": ["Sergio", "Ermotti", "David", "Solomon", "Jane", "Fraser", "Teo", "Yuwei"]}


@pytest.fixture(scope="module")
def store():
    return DocumentStore()


def _dump(*results: ToolResult) -> str:
    return json.dumps([r.model_dump() for r in results])


def test_only_jfr_has_meeting_notes(store):
    assert {n.id for n in store.get_notes("jfr")} == {"note_1013", "note_1020"}
    for cid in ("ser", "dso", "teo", "sha"):
        assert store.get_notes(cid) == []
        r = get_meeting_note(cid, store=store)
        assert r.status == "not_found" and r.data == {} and not r.sources
        assert get_meeting_note(cid, topic="risk", store=store).status == "not_found"
        assert read_meeting_note(cid, "note_1013", store=store).status == "not_found"     # jfr's note id


def test_get_meeting_note_by_id_date_topic(store):
    r = get_meeting_note("jfr", note_id="note_1013", store=store)
    assert r.data["notes"][0]["note_id"] == "note_1013" and "S$500m" in r.data["notes"][0]["text"]
    assert r.sources[0].type == "meeting_note" and r.sources[0].id == "note_1013"
    assert get_meeting_note("jfr", date="2026-10-20", store=store).data["notes"][0]["note_id"] == "note_1020"
    rng = get_meeting_note("jfr", date_from="2026-10-01", date_to="2026-12-31", store=store)
    assert {n["note_id"] for n in rng.data["notes"]} == {"note_1013", "note_1020"}
    t = get_meeting_note("jfr", topic="monthly living costs cash reserve", store=store)
    assert t.data["notes"][0]["note_id"] == "note_1020"
    assert t.data["notes"][0]["relevance_score"] > 0 and t.data["notes"][0]["matched_passages"]
    t2 = get_meeting_note("jfr", topic="tobacco coal exclusion", store=store)
    assert t2.data["notes"][0]["note_id"] == "note_1013"
    assert get_meeting_note("jfr", topic="zebra", store=store).status == "not_found"
    assert get_meeting_note("jfr", note_id="note_0421", store=store).status == "not_found"   # removed / other client's note
    assert get_meeting_note("jfr", store=store).data["notes"][0]["note_id"] == "note_1020"  # default: latest


def test_read_meeting_note_full_and_passages(store):
    full = read_meeting_note("jfr", "note_1020", store=store)
    assert "S$150,000 a month" in full.data["text"] and full.data["untrusted_content"] is True
    r = read_meeting_note("jfr", "note_1020", query="blue-chip equities growth", store=store)
    assert r.status == "ok" and r.data["passages"]
    assert any("15%" in p["text"] for p in r.data["passages"])
    assert all(s.passage and s.passage in full.data["text"] for s in r.sources)   # verbatim
    assert read_meeting_note("jfr", "note_1020", query="xylophone", store=store).status == "insufficient_information"
    assert read_meeting_note("jfr", "nope", store=store).status == "not_found"


# ---- extraction ----
def _passage_ok(p, store, cid, ips_version=None):
    texts = {n.id: n.text for n in store.get_notes(cid)}
    for f in p.facts:
        if f.kind == "missing":
            assert f.value is None and not f.sources
            continue
        assert f.sources, f.field
        for s in f.sources:
            assert s.passage, f.field
            assert s.passage in texts[s.id], (f.field, s.passage)   # verbatim


def test_extract_jfr_from_notes_only(store):
    p = extract_key_facts(store, "jfr")
    assert isinstance(p, ClientProfile) and p.ips_version_used is None and p.ips_status is None
    assert {f.category for f in p.facts} == {"client_financial", "objectives", "risk", "preferences"}
    _passage_ok(p, store, "jfr")
    assert p.get("aum_managed_sgd").value == 500_000_000 and p.get("aum_managed_sgd").kind == "documented"
    assert p.get("annual_income_sgd").value == 10_000_000 and p.get("annual_income_sgd").sources[0].id == "note_1013"
    assert p.get("monthly_cash_need_sgd").value == 150_000 and p.get("monthly_cash_need_sgd").sources[0].id == "note_1020"
    assert p.get("annual_cash_need_sgd").kind == "calculated" and p.get("annual_cash_need_sgd").value == 1_800_000
    assert p.get("liquidity_need_sgd").value == 30_000_000 and p.get("liquidity_need_pct_of_aum").value == 6.0
    assert p.get("drawdown_tolerance_pct").value == 10 and p.get("max_loss_at_drawdown_sgd").value == 50_000_000
    assert p.get("risk_classification") is None and p.get("risk_tolerance").kind == "inferred"
    assert all(s.type == "meeting_note" for f in p.facts for s in f.sources)
    assert p.get("investment_horizon").value == ["at least ten years"]
    assert {"capital_preservation", "income", "growth"} <= set(p.get("goals").value)
    assert set(p.get("restrictions").value) == {"tobacco", "thermal coal", "hedge funds", "private markets"}
    assert p.get("currency_preference").value == ["SGD", "USD"]
    assert "responsible investing" in p.get("sustainability_preferences").value
    assert {"cash", "bonds", "equities"} <= set(p.get("asset_class_preferences").value)
    assert p.get("knowledge_experience").kind == "documented"
    assert any("very risk averse" in v for v in p.get("risk_attitude_statements").value)
    # genuinely open items are flagged, not guessed
    assert set(p.missing) == {"other_assets_sgd", "liabilities_sgd"}
    assert p.get("other_assets_sgd").kind == "missing"
    assert not p.conflicts


def test_extract_clients_without_notes_are_all_missing(store):
    for cid in ("ser", "dso", "teo", "sha"):
        q = extract_key_facts(store, cid)
        assert q.ips_version_used is None and not q.conflicts and not q.outdated
        assert all(f.kind in ("missing", "calculated") and not f.sources for f in q.facts)
        assert "annual_income_sgd" in q.missing


def test_extract_ignores_ips_even_when_requested(store):
    assert extract_key_facts(store, "ser", ips_version=1).model_dump() == extract_key_facts(store, "ser").model_dump()


def test_extract_kinds_inferred_and_missing(store):
    p = extract_key_facts(store, "jfr")
    rt = p.get("risk_tolerance")
    assert rt.kind == "inferred" and "INFERRED" in rt.note and rt.value.startswith("low")
    # Missing items (assets outside the bank were never stated) are flagged, not guessed.
    assert p.get("other_assets_sgd").kind == "missing" and "other_assets_sgd" in p.missing


def test_extract_notes_conflicting_statements_use_latest(store):
    d = _synthetic_dir(store, extra_notes=[
        {"id": "t_ser1", "client_id": "ser", "date": "2026-10-08", "title": "Test call",
         "text": "Call with the client.\n\nHe now needs a S$1.5m deposit. A fall of more than 5% would make him uncomfortable and prompt him to sell."}])
    p = extract_key_facts(DocumentStore(d), "ser")
    assert p.get("liquidity_need_sgd").value == 1_500_000 and p.get("drawdown_tolerance_pct").value == 5
    assert all(s.type == "meeting_note" for f in p.facts for s in f.sources)


# ---- client resolution ----
def test_resolve_client_by_name_context_and_override(store):
    assert resolve_client("show Sergio's IPS", store=store).client_id == "ser"
    assert resolve_client("what is the risk profile?", "dso", store=store).client_id == "dso"
    r = resolve_client("compare with David Solomon", "ser", store=store)
    assert r.client_id == "dso" and r.data["differs_from_context"] is True
    assert resolve_client("SOLOMON please", "ser", store=store).client_id == "dso"


def test_ambiguous_or_unknown_client_returns_clarification_and_no_data(store):
    for q in ("Sergio or David, whichever", "notes for Michael Brown"):
        r = resolve_client(q, "ser", store=store)
        assert r.status in ("needs_clarification", "not_found") and r.client_id is None and r.data == {}
        assert {c["id"] for c in r.candidates}
        blob = _dump(r)
        assert "Active" not in blob and "S$" not in blob
    assert resolve_client("Sergio or David", "ser", store=store).status == "needs_clarification"
    assert resolve_client("hello", None, store=store).status == "needs_clarification"
    for r in (get_meeting_note("zzz", store=store), read_meeting_note("zzz", "note_1013", store=store)):
        assert r.status == "not_found" and r.data == {} and not r.sources


# ---- isolation ----
@pytest.mark.parametrize("cid", CLIENTS)
def test_cross_client_isolation(store, cid):
    results = [get_meeting_note(cid, store=store), get_meeting_note(cid, topic="risk portfolio", store=store),
               get_meeting_note(cid, date_from="2000-01-01", limit=50, store=store)]
    results += [read_meeting_note(cid, n.id, store=store) for n in store.get_notes(cid)]
    results += [read_meeting_note(cid, n.id, query="income retirement risk", store=store) for n in store.get_notes(cid)]
    blob = _dump(*results) + extract_key_facts(store, cid).model_dump_json()
    for name in OTHER_NAMES[cid]:
        assert name not in blob, f"{cid} output leaked '{name}'"
    for other in CLIENTS:
        if other != cid:
            assert f'"client_id": "{other}"' not in blob and f"{other}:v" not in blob
    # a note id of another client is not readable
    if cid != "jfr":
        assert read_meeting_note(cid, "note_1013", store=store).status == "not_found"
    else:
        assert read_meeting_note(cid, "note_0421", store=store).status == "not_found"


def test_store_is_read_only_copy(store):
    notes = store.get_notes("jfr")
    notes[0].text = "tampered"
    assert store.get_notes("jfr")[0].text != "tampered"


def _synthetic_dir(store, strip_ips_part3=False, extra_notes=()):
    import tempfile
    d = Path(tempfile.mkdtemp())
    for f in ("clients.json", "meeting_notes.json", "ips.json"):
        shutil.copy(DEFAULT_DATA_DIR / f, d / f)
    if extra_notes:
        data = json.loads((d / "meeting_notes.json").read_text())
        data["meeting_notes"] += [{"source_file": "", "origin": "test", "fictional": True, **n} for n in extra_notes]
        (d / "meeting_notes.json").write_text(json.dumps(data))
    if strip_ips_part3:
        data = json.loads((d / "ips.json").read_text())
        for v in data["ips_versions"]:
            for p in v["parts"]:
                if p["part"] == 3:
                    p["body"] = ""
        (d / "ips.json").write_text(json.dumps(data))
    return d
