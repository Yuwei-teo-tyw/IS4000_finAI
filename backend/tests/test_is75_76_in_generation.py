"""IS-75 (3L proportion) + IS-76 (strategy A-F) applied AUTOMATICALLY in IPS generation, with `reasoning` on every section."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.ips_generate import SECTION_IDS, generate_ips_section
from app.agents.client_profiling.ips_model import merge_section, new_ips_data, normalize_data, render_parts
from app.agents.client_profiling.store import Client, DocumentStore, IpsPartDoc, MeetingNoteDoc
from app.endpoints import client_profiling as ep
from ips_helpers import Chat, alloc_payload

BUCKETS = ["liquidity", "longevity", "legacy"]
FULL = ("Anna is {age} years old. She has investable assets of S$4,000,000. She wants to leave a legacy for her two children and set up "
        "a family foundation. She keeps a cash reserve of S$400,000 and spends S$20,000 a month. She plans to invest for at least 15 years. "
        "She is comfortable with a balanced approach.")
NO_AGE = "She has investable assets of S$4,000,000. She plans to invest for at least 15 years. She is comfortable with a balanced approach."


class St:
    def __init__(self, text=FULL.format(age=52), cap=3, aum=4_000_000):
        self.c = Client(id="x", name="Anna", risk_category="Balanced", risk_cap=cap, aum_sgd=aum, in_book=True)
        self.notes = [MeetingNoteDoc(id="n1", client_id="x", date="2026-10-01", title="Review", text=text)]

    def get_client(self, cid):
        return self.c

    def get_notes(self, cid):
        return self.notes

    def get_ips_versions(self, cid):
        return []


def down(system, user):
    raise ConnectionError("LM Studio down")


def alloc(store, payload=None, chat=None):
    return generate_ips_section(store, "x", "allocation", chat or Chat(payload or alloc_payload()))


def pcts(r):
    return {b: r["proportion"][b]["pct"] for b in BUCKETS}


def test_allocation_has_proportion_summing_to_100_and_strategies():
    r = alloc(St())
    assert r["status"] == "ok" and r["proportionTotal"] == 100 and r["proportionMissing"] == []
    p = pcts(r)
    assert sum(p.values()) == 100 and all(isinstance(v, int) and 0 <= v <= 100 for v in p.values())
    assert all(r["proportion"][b]["reason"] for b in BUCKETS)
    assert [b["portfolio"] for b in r["threeL"]] == ["Liquidity", "Longevity", "Legacy"]
    assert r["threeL"][0]["strategy"] in ("A", "B")  # IS-76 Liquidity A/B only


@pytest.mark.parametrize("age", [18, 100])
def test_extreme_ages(age):
    r = alloc(St(FULL.format(age=age)))
    assert r["status"] == "ok" and r["proportion"] is not None
    p = pcts(r)
    assert sum(p.values()) == 100 and all(0 <= v <= 100 for v in p.values())
    assert any(str(age) in line for line in r["reasoning"])


def test_missing_section_lists_missing_and_no_proportion_but_generation_works():
    r = alloc(St(NO_AGE))
    assert r["proportion"] is None and r["proportionTotal"] == 100
    assert any("age" in m.lower() for m in r["proportionMissing"])
    assert r["status"] == "ok" and len(r["threeL"]) == 3  # strategies still proposed
    assert any("not proposed" in line and "IS-75" in line for line in r["reasoning"])
    data = merge_section(normalize_data(new_ips_data()), r)
    assert data["threeLProportion"] is None and "Missing information" in data["threeLProportionMessage"]


def test_small_portfolio_is_not_given_a_high_risk_strategy():
    from app.agents.client_profiling.ips_reasoning import _harmonise
    res = alloc(St(cap=5), alloc_payload(("B", "F", "F")))
    assert res["status"] == "ok"
    prop = {"liquidity": {"pct": 90}, "longevity": {"pct": 4}, "legacy": {"pct": 6}}
    assert _harmonise(res, prop) == ["longevity"]
    lng = res["threeL"][1]
    assert lng["strategy"] == "D" and "only 4%" in lng["reason"] and res["threeL"][2]["strategy"] == "F"
    assert res["allocation"]["buckets"][1]["strategy"] == "D" and res["allocation"]["proportionAdjusted"] == ["longevity"]


def test_reasoning_on_every_section_mentions_rules():
    payloads = {"demographics": {"fields": [{"label": "Occupation", "value": "banker", "cite": "N1"}]},
                "philosophy": {k: {"value": "", "cite": ""} for k in ("approach", "believes", "avoids")},
                "goals": {"bullets": []}, "risk": {"fields": [], "bullets": []}, "allocation": alloc_payload()}
    for sec in SECTION_IDS:
        r = generate_ips_section(St(FULL.format(age=52) + " She is a banker."), "x", sec, Chat(payloads[sec]))
        assert 2 <= len(r["reasoning"]) <= 6 and all(isinstance(x, str) and x for x in r["reasoning"]), sec
        text = " ".join(r["reasoning"])
        assert "meeting note" in text, sec
    r = alloc(St())
    text = " ".join(r["reasoning"])
    assert "Risk score 3 of 5" in text and "Strategy A or B" in text and "Strategies picked" in text
    assert "adds up to 100%" in text and "52" in text


def test_reasoning_boundary_conflict_and_default():
    st = St(cap=1)
    st.notes = [MeetingNoteDoc(id="n1", client_id="x", date="2026-10-20", title="b", text="Jane: My risk appetite is between conservative and moderate. She is 52 years old with S$4,000,000 of assets and a 15 year horizon."),
                MeetingNoteDoc(id="n2", client_id="x", date="2026-09-01", title="a", text="Jane: I am an aggressive investor.")]
    text = " ".join(alloc(st, alloc_payload(("A", "C", "D")))["reasoning"])
    assert "2026-10-20" in text and "2026-09-01" in text and "latest" in text and "more conservative" in text
    d = alloc(St(), {"riskCategory": "", "summary": "", "buckets": []})
    assert "rule-based Default" in " ".join(d["reasoning"])


def test_model_down_never_crashes_and_keeps_rule_baseline():
    r = alloc(St(), chat=down)
    assert r["status"] == "unavailable" and r["proportion"] is not None and sum(pcts(r).values()) == 100
    assert any("not available" in line for line in r["reasoning"])
    assert len(r["reasoning"]) >= 2


def test_no_notes_still_has_reasoning():
    st = St()
    st.notes = []
    r = alloc(st)
    assert r["status"] == "no_notes" and r["proportion"] is None and len(r["reasoning"]) == 2


def test_merge_persists_proportion_and_renders():
    r = alloc(St())
    data = merge_section(normalize_data(new_ips_data()), r)
    assert data["threeLProportion"] == r["proportion"] and data["threeLProportionMessage"] == ""
    body = render_parts(data)[1]["body"]
    assert "3L proportion (adds up to 100%)" in body and f"Liquidity {pcts(r)['liquidity']}%" in body
    d0 = normalize_data({})
    assert d0["threeLProportion"] is None and d0["threeLProportionMessage"] == ""


def test_get_ips_returns_proportion(monkeypatch):
    st = DocumentStore()
    monkeypatch.setattr(store_mod, "_default", st)
    r = alloc(St())
    data = merge_section(normalize_data(new_ips_data()), r)
    st.save_ips("jft", [IpsPartDoc(**p) for p in render_parts(data)], summary="t", author="AI draft", status="Draft", data=data)
    app = FastAPI()
    app.include_router(ep.router)
    got = TestClient(app).get("/agents/client-profiling/ips/jft").json()["versions"][0]["data"]
    assert got["threeLProportion"] == r["proportion"] and "threeLProportionMessage" in got


def test_generate_all_events_carry_reasoning(monkeypatch):
    st = DocumentStore()
    monkeypatch.setattr(store_mod, "_default", st)
    monkeypatch.setattr(ep, "generate_ips_section", lambda s, c, sec: {"section": sec, "status": "ok", "message": "m", "model": "x", "reasoning": ["a", "b"]})
    monkeypatch.setattr(ep, "_autosave", lambda *a, **k: None)
    out = TestClient(_app()).post("/agents/client-profiling/ips-generate/all", json={"client_id": "jft"}).json()
    assert all(e["reasoning"] == ["a", "b"] for e in out["events"])


def _app():
    app = FastAPI()
    app.include_router(ep.router)
    return app


def test_allocation_makes_one_llm_call_and_no_proportion_refine():
    chat = Chat(alloc_payload())
    r = alloc(St(), chat=chat)
    assert chat.calls == 1  # strategy pick only: the proportion reasons are rule-based (no refine call)
    assert r["status"] == "ok" and sum(pcts(r).values()) == 100
    assert all(r["proportion"][b]["reason"] for b in BUCKETS) and r["reasoning"]


def test_gen_chat_sends_reasoning_effort_none_and_env_can_disable(monkeypatch):
    from app.agents.client_profiling import threel
    seen = []

    def fake(body, timeout):
        seen.append(body)
        return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    monkeypatch.setattr(threel, "post_chat", fake)
    monkeypatch.delenv("CLIENT_PROFILING_IPS_ALLOC_REASONING_EFFORT", raising=False)
    threel._gen_chat()("s", "u")
    monkeypatch.setenv("CLIENT_PROFILING_IPS_ALLOC_REASONING_EFFORT", "off")
    threel._gen_chat()("s", "u")
    assert seen[0]["reasoning_effort"] == "none" and "reasoning_effort" not in seen[1]
