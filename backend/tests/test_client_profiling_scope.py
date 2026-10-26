"""Notes-only context: the prompt only ever carries the client's own meeting notes."""
import json

from app.agents.client_profiling.answer import answer_question
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.store import get_default_store


def prompt_for(cid):
    seen = {}

    def spy(system, user):
        seen["system"], seen["user"] = system, user
        return json.dumps({"in_scope": True, "broad": False, "answerable": False, "answer": "", "groups": [], "cites": []})
    store = get_default_store()
    answer_question("q", store, extract_key_facts(store, cid), chat=spy)
    return seen["user"], seen["system"]


def test_jfr_context_is_notes_only():
    u, s = prompt_for("jfr")
    assert "note_1013" in u and "IPS v" not in u and "Part 1" not in u and "[I" not in u
    assert "Conflict" not in u and "Staleness" not in u
    assert "meeting-note" in s


def test_ser_context_has_no_ips_mentions():
    u, _ = prompt_for("ser")
    assert "IPS" not in u and "[I" not in u


def test_clients_never_mix():
    u, _ = prompt_for("jfr")
    assert "Ermotti" not in u and "Sergio" not in u
