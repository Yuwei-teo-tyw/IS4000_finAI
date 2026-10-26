"""3L allocation generation + discussion + new REST endpoints (offline, fake LLM)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.ips_generate import generate_ips_section, third_person
from app.agents.client_profiling.store import DocumentStore, MeetingNoteDoc
from app.agents.client_profiling.threel import discuss_allocation, rule_based_strategy
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling"
NOTE = ("Jane is 45. Jane: I am very risk averse. A fall of more than 10% in a single year would make me very uncomfortable. "
        "She needs S$2m in cash over the next 2 years for expenses. Her goal is to reach 700M within 8 years. "
        "She wants to leave a legacy for her children. She holds a long-term view of at least ten years.")


class St:
    def __init__(self, risk="Conservative", notes=None):
        self.notes = notes if notes is not None else [MeetingNoteDoc(id="n1", client_id="x", date="2026-10-01", title="First", text=NOTE)]
        self.risk = risk

    def get_notes(self, cid):
        return self.notes

    def get_client(self, cid):
        return type("C", (), {"risk_category": self.risk})()


def fake(out):
    def chat(system, user):
        chat.calls.append((system, user))
        return json.dumps(out)
    chat.calls = []
    return chat


def bucket(i, s, j, q="A fall of more than 10% in a single year would make me very uncomfortable."):
    return {"id": i, "strategy": s, "justification": j, "cite": "N1", "quote": q}


GOOD = {"riskCategory": "Conservative", "summary": "The client is conservative.", "buckets": [
    bucket("liquidity", "A", "The client needs S$2m in cash over 2 years, so Strategy A with a 15% maximum drawdown fits."),
    bucket("longevity", "B", "The client is very risk averse and has a horizon of 10 years; Strategy B has a 4 years longest drawdown.", "She holds a long-term view of at least ten years."),
    bucket("legacy", "C", "The client wants to leave a legacy for her children; Strategy C has a 25% maximum drawdown.", "She wants to leave a legacy for her children.")]}


def test_third_person_conversion():
    assert third_person("I am very risk averse") == "The client is very risk averse"
    assert third_person("Keeping my capital safe") == "Keeping the client's capital safe"
    assert third_person("We like bonds") == ""
    assert third_person("The client prefers bonds") == "The client prefers bonds"


def test_sections_use_third_person_and_model():
    risk = {"fields": [], "bullets": [{"text": "I am very risk averse", "cite": "N1"}]}
    r = generate_ips_section(St(), "x", "risk", fake(risk))
    assert r["bullets"] == ["The client is very risk averse"] and r["model"]
    # verbatim evidence keeps the client's own words
    assert "I am very risk averse" in r["evidence"][0]["passage"]
    assert generate_ips_section(St(), "x", "risk", fake({"fields": [], "bullets": [{"text": "We like bonds", "cite": "N1"}]}))["bullets"] == []


def test_model_present_on_every_status():
    assert generate_ips_section(St(notes=[]), "x", "goals")["model"] is None  # no model produced anything (IS-92)
    assert generate_ips_section(St(), "x", "allocation")["model"] is None  # unavailable (model off)


def test_allocation_ok():
    r = generate_ips_section(St(), "x", "allocation", fake(GOOD))
    a = r["allocation"]
    assert r["status"] == "ok" and r["section"] == "allocation" and r["model"]
    assert [b["id"] for b in a["buckets"]] == ["liquidity", "longevity", "legacy"]
    assert [b["strategy"] for b in a["buckets"]] == ["A", "B", "C"] and a["fallback"] is False
    assert [b["strategyName"] for b in a["buckets"]] == ["Fixed Income", "Income", "Yield"]
    assert a["riskCategory"] == "Conservative"
    for b in a["buckets"]:
        assert b["justification"] and b["evidence"] and not b["fallback"]
        assert b["evidence"][0]["passage"] in NOTE
    assert len(r["evidence"]) == 3


def test_allocation_liquidity_forced_ab_and_invented_figures_fallback():
    bad = json.loads(json.dumps(GOOD))
    bad["buckets"][0]["strategy"] = "E"               # liquidity C-F is not allowed
    bad["buckets"][1]["justification"] = "The client will earn 99% a year."  # invented figure
    r = generate_ips_section(St(), "x", "allocation", fake(bad))
    a = r["allocation"]
    assert a["fallback"] is True
    by = {b["id"]: b for b in a["buckets"]}
    assert by["liquidity"]["strategy"] in ("A", "B") and by["liquidity"]["fallback"]
    assert by["longevity"]["fallback"] and "99" not in by["longevity"]["justification"]
    assert not by["legacy"]["fallback"] and by["legacy"]["strategy"] == "C"
    assert "rule-based" in r["message"]


def test_allocation_first_person_justification_rewritten_and_we_rejected():
    g = json.loads(json.dumps(GOOD))
    g["buckets"][0]["justification"] = "I need cash within 2 years so Strategy A."
    g["buckets"][1]["justification"] = "We want growth; Strategy B."
    a = generate_ips_section(St(), "x", "allocation", fake(g))["allocation"]
    by = {b["id"]: b for b in a["buckets"]}
    assert by["liquidity"]["justification"].startswith("The client needs cash") and not by["liquidity"]["fallback"]
    assert by["longevity"]["fallback"]


@pytest.mark.parametrize("risk,exp", [("Conservative", ("A", "B", "C")), ("Balanced", ("B", "D", "E")), ("Growth", ("B", "E", "F"))])
def test_rule_based_fallback_by_risk(risk, exp):
    r = generate_ips_section(St(risk=risk), "x", "allocation", fake({"riskCategory": "", "summary": "", "buckets": []}))
    assert tuple(b["strategy"] for b in r["allocation"]["buckets"]) == exp and r["allocation"]["fallback"]
    assert tuple(rule_based_strategy(i, risk) for i in ("liquidity", "longevity", "legacy")) == exp


def test_allocation_unavailable_and_no_notes():
    assert generate_ips_section(St(), "x", "allocation", lambda s, u: "nope")["status"] == "unavailable"
    r = generate_ips_section(St(notes=[]), "x", "allocation", fake(GOOD))
    assert r["status"] == "no_notes" and r["allocation"]["buckets"] == []


# --- discuss ---
CUR = {"buckets": [{"id": "liquidity", "strategy": "A"}, {"id": "longevity", "strategy": "B"}, {"id": "legacy", "strategy": "C"}]}


def d(stance, answer, liq="A", lon="B", leg="C", cites=("N1",)):
    j = lambda t: f"The client {t}."  # noqa: E731
    return {"stance": stance, "answer": answer, "cites": list(cites), "buckets": [
        {"id": "liquidity", "strategy": liq, "justification": j("needs cash soon")},
        {"id": "longevity", "strategy": lon, "justification": j("has a long horizon")},
        {"id": "legacy", "strategy": leg, "justification": j("wants a legacy")}]}


def test_discuss_agree_updates_bucket():
    c = fake(d("agree", "Agreed, the client can take more risk for legacy.", leg="D"))
    r = discuss_allocation(St(), "x", "Legacy can be Balanced.", [], CUR, c)
    assert r["stance"] == "agree" and {b["id"]: b["strategy"] for b in r["allocation"]["buckets"]}["legacy"] == "D"
    assert r["allocation"]["buckets"][2]["strategyName"] == "Balanced" and r["model"]


def test_discuss_liquidity_limit_enforced_even_if_model_agrees():
    c = fake(d("agree", "Sure, switching liquidity to Growth.", liq="E"))
    r = discuss_allocation(St(), "x", "For Liquidity I am sure she wants more growth than pure fixed income. Justify.", [], CUR, c)
    liq = r["allocation"]["buckets"][0]
    assert liq["strategy"] in ("A", "B") and liq["strategy"] == "A"
    assert r["stance"] in ("disagree", "partial") and "A (Fixed Income) or B" in r["answer"]
    assert r["citations"] and r["citations"][0]["noteId"] == "n1"


def test_discuss_sees_history_and_drops_invented_figures():
    c = fake(d("disagree", "Strategy A keeps the maximum drawdown at 15%. The client will gain 88% anyway."))
    hist = [{"role": "user", "text": "Why A for liquidity?"}, {"role": "assistant", "text": "Because of cash needs."}]
    r = discuss_allocation(St(), "x", "Justify again", hist, CUR, c)
    assert "Why A for liquidity?" in c.calls[0][1] and "Because of cash needs." in c.calls[0][1]
    assert "15%" in r["answer"] and "88" not in r["answer"] and r["stance"] == "disagree"


def test_discuss_unavailable_keeps_allocation():
    r = discuss_allocation(St(), "x", "hi", [], CUR, lambda s, u: "bad")
    assert r["stance"] == "info" and [b["strategy"] for b in r["allocation"]["buckets"]] == ["A", "B", "C"]


# --- endpoints ---
@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(store_mod, "_default", DocumentStore())
    return TestClient(app)


def test_strategies_endpoint(api):
    j = api.get(f"{U}/strategies").json()
    assert j["liquidityAllowed"] == ["A", "B"] and [s["code"] for s in j["strategies"]] == list("ABCDEF")
    assert set(j["strategies"][0]) == {"code", "name", "riskLabel", "allocation", "expectedReturnPct", "volatilityPct", "maxDrawdownPct", "longestDrawdownYears"}
    assert j["strategies"][0]["maxDrawdownPct"] == 15 and j["source"]


def test_sections_five_and_generate_validates(api):
    assert [s["id"] for s in api.get(f"{U}/ips-generate/sections").json()][-1] == "allocation" and len(api.get(f"{U}/ips-generate/sections").json()) == 5
    assert api.post(f"{U}/ips-generate", json={"client_id": "jft", "section": "bad"}).status_code == 422
    assert api.post(f"{U}/ips-generate", json={"clientId": "ser", "section": "allocation"}).status_code == 403
    j = api.post(f"{U}/ips-generate", json={"clientId": "jft", "section": "allocation"}).json()  # model off
    assert j["status"] == "unavailable" and j["model"] is None and j["modelMessage"]


def test_discuss_endpoint(api):
    body = {"clientId": "jft", "message": "justify", "history": [], "allocation": CUR}
    assert api.post(f"{U}/ips-allocation/discuss", json={**body, "clientId": "ser"}).status_code == 403
    assert api.post(f"{U}/ips-allocation/discuss", json={**body, "message": "  "}).status_code == 422
    assert api.post(f"{U}/ips-allocation/discuss", json={**body, "history": [{"role": "system", "text": "x"}]}).status_code == 422
    j = api.post(f"{U}/ips-allocation/discuss", json=body).json()
    assert set(j) >= {"answer", "stance", "model", "allocation", "citations"} and len(j["allocation"]["buckets"]) == 3


def test_ips_chat_endpoints(api):
    assert api.get(f"{U}/ips-chat/jft").json()["messages"] == []
    m = api.post(f"{U}/ips-chat/jft", json={"role": "user", "text": "hello", "kind": "discuss", "meta": {"a": 1}}).json()
    assert set(m) >= {"id", "role", "kind", "text", "ts", "meta", "truncated"} and m["kind"] == "discuss" and m["meta"] == {"a": 1}
    api.post(f"{U}/ips-chat/jft", json={"role": "assistant", "text": "hi"})
    msgs = api.get(f"{U}/ips-chat/jft").json()["messages"]
    assert [x["text"] for x in msgs] == ["hello", "hi"] and msgs[1]["kind"] == "chat"
    assert api.post(f"{U}/ips-chat/jft", json={"role": "bot", "text": "x"}).status_code == 422
    assert api.post(f"{U}/ips-chat/jft", json={"role": "user", "text": ""}).status_code == 422
    assert api.get(f"{U}/ips-chat/ser").status_code == 403
    assert api.delete(f"{U}/ips-chat/jft").status_code == 200
    assert api.get(f"{U}/ips-chat/jft").json()["messages"] == []
