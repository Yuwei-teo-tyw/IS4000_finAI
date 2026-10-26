"""IPS assist tools with a fake chat (no network)."""
import json

from fastapi.testclient import TestClient

from app.agents.client_profiling.answer import answer_question
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.ips_assist import ips_assist
from app.agents.client_profiling.store import get_default_store

STORE = get_default_store()


def run(chat, mode="write", text="", section="Client goals and objectives", message="", cid="jfr"):
    return ips_assist(STORE, cid, section, mode, text, message, chat)


def seq(*outs):
    it = iter(outs)
    calls = []

    def chat(system, user):
        calls.append((system, user))
        return json.dumps(next(it))
    chat.calls = calls
    return chat


def test_professionalize_ok():
    r = run(seq({"revised": "The client seeks capital preservation over ten years.", "notes": ["Tidied wording"]}), "professionalize",
            "she wants to keep her money safe over ten years")
    assert r["status"] == "ok" and r["original"].startswith("she wants") and r["revised"].startswith("The client")


def test_professionalize_new_number_retries_then_falls_back():
    text = "keep money safe, ok with small losses"
    c = seq({"revised": "Preserve capital; tolerate losses up to 15%.", "notes": []},
            {"revised": "Preserve capital with equities.", "notes": []})
    r = run(c, "professionalize", text)
    assert len(c.calls) == 2 and "REJECTED" in c.calls[1][0]
    assert r["status"] == "insufficient_information" and r["message"] == "Could not rewrite without adding facts"
    assert r["revised"] == text and r["original"] == text


def test_professionalize_retry_can_succeed_and_empty_text():
    c = seq({"revised": "Capital preserved at S$99.", "notes": []}, {"revised": "Preserve capital.", "notes": []})
    assert run(c, "professionalize", "keep money safe")["status"] == "ok"
    r = run(seq(), "professionalize", "  ")
    assert r["status"] == "insufficient_information" and r["message"] == "Nothing to professionalise yet"


def test_write_uses_notes_and_drops_unsupported_figures():
    good = "Jane wants income and capital preservation, with a drawdown tolerance of 10%."
    bad = "She will invest S$777,000 next month."
    r = run(seq({"revised": f"{good}\n{bad}", "cites": ["N1"], "notes": []}))
    assert r["status"] == "ok" and "777" not in r["revised"] and "10%" in r["revised"]
    assert r["sources"] and any("Removed" in n for n in r["notes"]) and r["original"] == ""


def test_write_requires_valid_cites():
    for cites in ([], ["N99"]):
        assert run(seq({"revised": "Goals to be confirmed.", "cites": cites, "notes": []}))["status"] == "insufficient_information"


def test_signature_section_not_drafted_and_no_model_call():
    c = seq()
    assert run(c, section="Signature line")["status"] == "out_of_scope" and not c.calls


def test_auto_routes_by_decision():
    r = run(seq({"action": "write"}, {"revised": "Goals: income, to be confirmed.", "cites": ["N1"], "notes": []}), "auto")
    assert r["status"] == "ok" and "Goals" in r["revised"]
    r = run(seq({"action": "professionalize"}, {"revised": "Preserve capital.", "notes": []}), "auto", "keep money safe")
    assert r["status"] == "ok" and r["revised"] == "Preserve capital."
    r = run(seq({"action": "out_of_scope"}), "auto", "", message="what is the weather")
    assert r["status"] == "out_of_scope" and r["message"] == "I can only write or professionalise this IPS section."


def test_unavailable():
    def down(s, u):
        raise ConnectionError
    assert run(down)["status"] == "unavailable"


def test_prompt_isolated_to_client():
    c = seq({"revised": "x to be confirmed", "cites": ["N1"], "notes": []})
    run(c, cid="jfr")
    u = c.calls[0][1]
    assert "note_1013" in u and "Ermotti" not in u and "IPS v" not in u and "Part 1" not in u
    c2 = seq({"revised": "x to be confirmed", "cites": ["N1"], "notes": []})
    run(c2, cid="ser")  # a different client never sees jfr's notes
    assert not c2.calls or "note_1013" not in c2.calls[0][1]


def test_endpoint_404_and_validation():
    from app.app import app
    cl = TestClient(app)
    body = {"client_id": "nope", "section": "Client goals and objectives", "mode": "write", "current_text": "", "message": ""}
    assert cl.post("/agents/client-profiling/ips-assist", json=body).status_code == 404
    assert cl.post("/agents/client-profiling/ips-assist", json={**body, "client_id": "jfr", "message": "x" * 501}).status_code == 422


def _overview(text):
    p = extract_key_facts(STORE, "jfr")
    out = {"in_scope": True, "broad": True, "answerable": True, "answer": "Overview of Jane.", "cites": ["N1"], "groups": [],
           "explanation": {"risk_category": "", "text": text, "recommended_asset_classes": [], "cites": ["N1"]}}
    return answer_question("overview", STORE, p, chat=lambda s, u: json.dumps(out))


def test_income_prepended_when_missing_and_not_duplicated():
    t = _overview("Based on the meetings, Jane is very risk averse.")["explanation"]["text"]
    assert t.startswith("Annual income S$10.0m;") and "Managed assets S$500.0m" in t
    t2 = _overview("Jane earns S$10m a year and manages S$500m.")["explanation"]["text"]
    assert "Annual income" not in t2
