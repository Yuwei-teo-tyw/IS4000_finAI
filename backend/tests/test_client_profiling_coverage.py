"""Coverage guard for summary questions + chronological meeting labels (fake chat, no network)."""
import json

from app.agents.client_profiling.answer import answer_question
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.schemas import Fact, SourceRef
from app.agents.client_profiling.store import get_default_store


def ref(t, i):
    return SourceRef(type=t, id=i, client_id="jfr", label="x", passage="p")


def setup(scope_src="meeting_note"):
    store = get_default_store()
    profile = extract_key_facts(store, "jfr").model_copy(deep=True)
    notes = store.get_notes("jfr")
    profile.facts = [
        Fact(field="annual_income_sgd", category="client_financial", value=10000000, kind="documented",
             sources=[ref(scope_src, notes[0].id if scope_src == "meeting_note" else "jfr:v1")]),
        Fact(field="risk_tolerance", category="risk", value="moderate", kind="documented",
             sources=[ref("meeting_note", notes[0].id)]),
    ]
    return store, profile


def fake(answer, calls, broad=False, **extra):
    def chat(system, user):
        calls.append(user)
        return json.dumps({"in_scope": True, "broad": broad, "answerable": True, "answer": answer, "cites": ["N1"], **extra})
    return chat


def test_deterministic_append_without_retry():
    store, profile = setup()
    calls = []
    r = answer_question("Summarize the meeting notes", store, profile,
                        chat=fake("She has a moderate risk tolerance.", calls, broad=True))
    assert len(calls) == 1
    sec = r["sections"][-1]
    assert sec["heading"] == "Also on record" and sec["lines"][0]["text"] == "Annual income: S$10.0m"
    assert sec["sources"] and sec["lines"][0]["kind"] == "documented"
    assert all("risk" not in l["text"].lower() for l in sec["lines"])


def test_complete_answer_no_append():
    store, profile = setup()
    calls = []
    r = answer_question("Give me an overview", store, profile,
                        chat=fake("Annual income is 10000000 and risk tolerance is moderate.", calls, broad=True))
    assert len(calls) == 1 and all(s["heading"] != "Also on record" for s in r["sections"])


def test_not_broad_is_not_guarded():
    store, profile = setup()
    calls = []
    r = answer_question("Is she ok with equities?", store, profile, chat=fake("Yes, open to equities.", calls))
    assert len(calls) == 1 and r["sections"] == []


def test_ips_only_facts_never_appended():
    store, profile = setup(scope_src="ips")
    calls = []
    r = answer_question("Summarize", store, profile, chat=fake("Moderate risk tolerance.", calls, broad=True))
    assert len(calls) == 1 and r["sections"] == []


def test_ordinal_labels_in_prompt():
    store, profile = setup()
    seen = {}

    def spy(system, user):
        seen["u"], seen["s"] = user, system
        return json.dumps({"in_scope": True, "broad": False, "answerable": False, "answer": "", "groups": [], "cites": []})
    answer_question("What did she say in the 2nd meeting?", store, profile, chat=spy)
    n = len(store.get_notes("jfr"))
    assert f"Meeting {n} of {n} (" in seen["u"] and f"Meeting 1 of {n}" in seen["u"]
    assert "the first meeting is the oldest" in seen["s"]


def test_identity_question_c0_only_ok_without_sources():
    store, profile = setup()
    seen = {}

    def chat(system, user):
        seen["u"], seen["s"] = user, system
        return json.dumps({"in_scope": True, "broad": False, "answerable": True, "answer": "The current client is Jane Fraser.", "cites": ["C0"]})
    r = answer_question("who is the current client?", store, profile, chat=chat)
    assert r["status"] == "ok" and r["sources"] == [] and "Jane Fraser" in r["text"]
    assert "[C0] Client in focus: Jane Fraser (id jfr)" in seen["u"] and "Sergio" not in seen["u"]
    assert "C0" in seen["s"]


def _expl(**kw):
    e = {"risk_category": "Conservative / very risk averse", "text": "Based on the meetings, Jane is conservative; consider cash.",
         "recommended_asset_classes": ["cash"], "cites": ["N1"]}
    e.update(kw)
    return e


def test_explanation_valid_is_returned_as_suggestion():
    store, profile = setup()
    ctx = " ".join(n.text for n in store.get_notes("jfr")).lower()
    e = _expl(risk_category="", recommended_asset_classes=["cash"] if "cash" in ctx else [])
    r = answer_question("overview", store, profile, chat=fake("Annual income is 10000000 and risk tolerance is moderate.", [], broad=True, explanation=e))
    x = r["explanation"]
    assert x["title"] == "Client overview" and x["status"] == "suggestion" and x["sources"] and x["text"]


def test_explanation_dropped_for_unsupported_asset_class_but_answer_kept():
    store, profile = setup()
    e = _expl(risk_category="", recommended_asset_classes=["cryptocurrency futures"])
    r = answer_question("overview", store, profile, chat=fake("Annual income is 10000000 and risk tolerance is moderate.", [], broad=True, explanation=e))
    assert r["status"] == "ok" and "explanation" not in r


def test_explanation_dropped_for_invented_figure_or_risk_category():
    store, profile = setup()
    for e in (_expl(risk_category="", text="She will invest 98765 in cash.", recommended_asset_classes=[]),
              _expl(risk_category="Hyperaggressive speculator", recommended_asset_classes=[])):
        r = answer_question("overview", store, profile, chat=fake("Annual income is 10000000 and risk tolerance is moderate.", [], broad=True, explanation=e))
        assert r["status"] == "ok" and "explanation" not in r


def test_no_explanation_when_not_broad():
    store, profile = setup()
    r = answer_question("income?", store, profile, chat=fake("Income is 10000000.", [], broad=False, explanation=_expl(risk_category="", recommended_asset_classes=[])))
    assert "explanation" not in r
