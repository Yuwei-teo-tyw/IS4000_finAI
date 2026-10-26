"""Grounded answers: accepted only when cited, supported by this client's records, and number-safe."""
import json

from app.agents.client_profiling.service import handle_chat


def chat_returning(**kw):
    out = {"in_scope": True, "broad": False, "answerable": True, "answer": "", "cites": []}
    out.update(kw)
    return lambda system, user: json.dumps(out)


def ask(q, cid="jfr", **kw):
    return handle_chat(q, cid, answer_chat=kw.pop("chat")).data.get("answer")


def test_supported_answer_is_shown_with_sources_and_ids_stripped():
    a = ask("Is she ok with equities?", chat=chat_returning(answer="Open to up to 15% in blue-chip equities (N1).", cites=["N1"]))
    assert a["status"] == "ok" and "N1" not in a["text"] and a["sources"][0]["id"] == "note_1020"


def test_invented_number_uncited_or_unknown_cite_become_cannot_answer():
    for kw in (dict(answer="Her AUM is S$9,999m.", cites=["N1"]),
               dict(answer="Open to 15% in equities.", cites=[]),
               dict(answer="Open to 15% in equities.", cites=["N99"]),
               dict(answerable=False)):
        a = ask("q", chat=chat_returning(**kw))
        assert a["status"] == "cannot_answer" and a["sources"] == []


def test_model_unavailable_gives_routing_unavailable():
    def down(system, user):
        raise ConnectionError
    r = handle_chat("q", "jfr", answer_chat=down)
    assert r.tool == "routing_unavailable"


def test_prompt_contains_only_the_resolved_clients_notes():
    seen = {}

    def spy(system, user):
        seen["user"] = user
        return json.dumps({"in_scope": True, "broad": False, "answerable": False, "answer": "", "groups": [], "cites": []})
    handle_chat("what did we discuss", "jfr", answer_chat=spy)
    assert "Ermotti" not in seen["user"] and "IPS v" not in seen["user"] and "Part 1" not in seen["user"]
    assert "note_1013" in seen["user"]
    seen.clear()
    handle_chat("what did we discuss", "ser", answer_chat=spy)
    assert "user" not in seen  # a client with no notes: no model call at all, so no other client's notes can be in a prompt


def test_context_capped_and_keeps_newest_notes():
    from app.agents.client_profiling import answer as A
    from app.agents.client_profiling.extract import extract_key_facts
    from app.agents.client_profiling.store import get_default_store
    store = get_default_store()
    old = A.MAX_CONTEXT_CHARS
    try:
        A.MAX_CONTEXT_CHARS = 3000
        text, refs = A.build_context(store, extract_key_facts(store, "jfr"))
    finally:
        A.MAX_CONTEXT_CHARS = old
    assert len(text) <= 3000 and "N1" in refs
