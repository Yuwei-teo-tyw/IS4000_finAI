"""Out-of-scope refusal: decided by the same single model call (in_scope=false)."""
import json

from app.agents.client_profiling.service import handle_chat as hc


def _chat(**kw):
    out = {"in_scope": True, "broad": False, "answerable": True, "answer": "", "groups": [], "cites": []}
    out.update(kw)
    return lambda s, u: json.dumps(out)


def test_out_of_scope_refuses_without_data_or_sources():
    calls = []

    def chat(s, u):
        calls.append(1)
        return json.dumps({"in_scope": False, "broad": False, "answerable": True, "answer": "Sunny", "groups": [], "cites": ["N1"]})
    r = hc("what is the weather", "jfr", answer_chat=chat)
    assert len(calls) == 1
    assert r.tool == "out_of_scope" and r.status == "insufficient_information"
    assert r.message == "I can't answer that question."
    a = r.data["answer"]
    assert a["status"] == "cannot_answer" and a["sections"] == [] and a["sources"] == [] and "Sunny" not in json.dumps(r.model_dump())
    assert "sections" not in r.data and not r.sources
    assert r.data["routing"]["method"] == "local_llm"


def test_missing_in_scope_is_treated_as_out_of_scope():
    r = hc("hello", "jfr", answer_chat=lambda s, u: json.dumps({"answerable": True, "answer": "x", "cites": ["C0"]}))
    assert r.tool == "out_of_scope"


def test_model_unavailable_gives_routing_unavailable_without_data():
    r = hc("Show me the notes", "jfr")  # autouse conftest disables the real local model
    assert r.tool == "routing_unavailable" and r.status == "insufficient_information"
    assert r.message == "The local model is unavailable, so this question was not routed."
    assert r.data == {"routing": {"method": "unavailable", "model": None, "scope": None,
                                  "note": "local model off, unreachable or invalid answer"}}
    assert not r.sources
