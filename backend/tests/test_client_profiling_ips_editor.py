"""Live IPS editor: selection rewrite, retrieve from notes, auto routing, general requests (fake chat, no network)."""
import json

import pytest

from fastapi.testclient import TestClient

from app.agents.client_profiling.ips_assist import ips_assist
from app.agents.client_profiling.store import get_default_store

STORE = get_default_store()
SEC = "Client goals and objectives"


@pytest.fixture(autouse=True)
def _all_in_book():
    """These tests exercise the endpoint, not the book gate: put every seeded client in the (JSON) book."""
    from app.agents.client_profiling.store import get_default_store
    s = get_default_store()
    for c in s.list_clients():
        s.set_in_book(c.id, True)


def seq(*outs):
    it = iter(outs)
    calls = []

    def chat(system, user):
        calls.append((system, user))
        return json.dumps(next(it))
    chat.calls = calls
    return chat


def run(chat, mode="auto", section=SEC, text="", message="", selection="", cid="jfr"):
    return ips_assist(STORE, cid, section, mode, text, message, chat, selection=selection)


def test_selection_rewrite_only_touches_selection():
    c = seq({"revised": "The client wishes to preserve capital.", "notes": []})
    r = run(c, "professionalize", text="Intro. she wants to keep money safe. Outro.", selection="she wants to keep money safe")
    assert r["status"] == "ok" and r["kind"] == "rewrite" and r["target"] == "selection"
    assert r["original"] == "she wants to keep money safe" and "Intro" not in c.calls[0][1]


def test_selection_rewrite_rejects_new_figures_and_assets():
    c = seq({"revised": "Preserve capital with 15% equities.", "notes": []}, {"revised": "Preserve capital via bonds.", "notes": []})
    r = run(c, "professionalize", text="x keep money safe y", selection="keep money safe")
    assert r["status"] == "insufficient_information" and r["revised"] == "keep money safe" and r["target"] == "selection"


def test_section_rewrite_and_neither():
    r = run(seq({"revised": "Preserve capital.", "notes": []}), "professionalize", text="keep money safe")
    assert r["target"] == "section" and r["kind"] == "rewrite" and r["original"] == "keep money safe"
    c = seq()
    r = run(c, "professionalize", section="")
    assert r["status"] == "insufficient_information" and r["message"] == "Select some text or a section first"
    assert r["target"] == "document" and not c.calls


def test_retrieve_cited_bullets_with_date_and_drops_unsupported():
    out = {"bullets": [
        {"text": "She expects to stay invested for at least ten years.", "cite": "N1"},
        {"text": "She would accept up to 15% in blue-chip equities.", "cite": "N1"},
        {"text": "She will invest S$777,000 next month.", "cite": "N1"},
        {"text": "No cite on this one.", "cite": ""},
        {"text": "Too " + "long " * 25, "cite": "N1"},
    ]}
    r = run(seq(out), "retrieve", message="what did she say about retirement or income")
    assert r["status"] == "ok" and r["kind"] == "retrieve" and r["target"] == "section"
    lines = r["revised"].split("\n")
    assert len(lines) == 2 and all(l.startswith("• ") for l in lines) and "777" not in r["revised"]
    assert r["sources"] and r["sources"][0]["type"] == "meeting_note" and r["sources"][0]["date"] and r["sources"][0]["passage"]
    assert r["notes"]


def test_retrieve_max_five_and_selection_is_topic():
    out = {"bullets": [{"text": f"Point {chr(97 + i)} about her goals.", "cite": "N1"} for i in range(8)]}
    c = seq(out)
    r = run(c, "retrieve", section="", selection="income needs")
    assert len(r["revised"].split("\n")) == 5 and r["target"] == "selection"
    assert "income needs" in c.calls[0][1]


def test_retrieve_empty():
    r = run(seq({"bullets": []}), "retrieve", message="her favourite colour")
    assert r["status"] == "insufficient_information" and r["revised"] == ""
    assert r["message"] == "I cannot find that in this client's meeting notes."
    assert run(seq(), "retrieve", cid="ser")["status"] == "insufficient_information"


def test_retrieve_isolated_notes_only():
    c = seq({"bullets": []})
    run(c, "retrieve", message="income")
    u = c.calls[0][1]
    assert "note_1013" in u and "Ermotti" not in u and "Extracted fact" not in u


def test_auto_routes_retrieve_and_general():
    c = seq({"action": "retrieve", "section": ""}, {"bullets": [{"text": "She stays invested for ten years.", "cite": "N1"}]})
    r = run(c, section="", message="what did she say about the time horizon")
    assert r["status"] == "ok" and r["kind"] == "retrieve" and r["target"] == "document"
    assert run(seq({"action": "out_of_scope", "section": ""}), section="", message="weather")["status"] == "out_of_scope"


def test_auto_general_write_needs_section():
    r = run(seq({"action": "write", "section": ""}), section="", message="write it")
    assert r["status"] == "insufficient_information" and "section" in r["message"].lower() and r["target"] == "document"
    c = seq({"action": "write", "section": "Risk profile"}, {"revised": "Very risk averse.", "cites": ["N1"], "notes": []})
    assert run(c, section="", message="draft the risk profile")["status"] == "ok"


def test_auto_selection_professionalize_and_unavailable():
    r = run(seq({"action": "professionalize", "section": ""}, {"revised": "Preserve capital.", "notes": []}),
            text="a keep money safe b", selection="keep money safe")
    assert r["status"] == "ok" and r["target"] == "selection"

    def down(s, u):
        raise ConnectionError
    r = run(down, "retrieve")
    assert r["status"] == "unavailable" and r["kind"] == "none"


def test_endpoint_fields_and_validation():
    from app.app import app
    cl = TestClient(app)
    u = "/agents/client-profiling/ips-assist"
    assert cl.post(u, json={"client_id": "nope", "mode": "retrieve"}).status_code == 404
    assert cl.post(u, json={"client_id": "jfr", "selection": "x" * 4001}).status_code == 422
    r = cl.post(u, json={"client_id": "jfr", "mode": "professionalize", "section": ""})
    assert r.status_code == 200 and r.json()["target"] == "document" and r.json()["kind"] in ("rewrite", "none")
