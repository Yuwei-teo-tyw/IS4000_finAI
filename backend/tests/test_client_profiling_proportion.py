"""IS-75: base 3L proportion. Happy path, sums to 100, missing sections, model down, endpoints, validate (all offline)."""
import json
import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.proportion import (BUCKET_IDS, normalise_pcts, parse_age, propose_proportion, rule_proportion,
                                                    validate_proportion)
from app.agents.client_profiling.store import Client, MeetingNoteDoc
from app.endpoints.client_profiling import router

app = FastAPI()
app.include_router(router)
U = "/agents/client-profiling/ips-proportion"

FULL = ("Anna is 52 years old. She has investable assets of S$4,000,000. She wants to leave a legacy for her two children and set up "
        "a family foundation. She keeps a cash reserve of S$400,000 and spends S$20,000 a month. She plans to invest for at least 15 years. "
        "She is comfortable with a balanced approach.")
NO_GOALS = "Anna is 52 years old. She has investable assets of S$4,000,000. She is comfortable with a balanced approach."


class St:
    def __init__(self, text=FULL, risk="Balanced", cap=3, aum=4_000_000):
        self.c = Client(id="x", name="Anna", risk_category=risk, risk_cap=cap, aum_sgd=aum, in_book=True)
        self.notes = [MeetingNoteDoc(id="n1", client_id="x", date="2026-10-01", title="Review", text=text)] if text else []

    def get_client(self, cid):
        return self.c if cid == "x" else None

    def get_notes(self, cid):
        return self.notes

    def get_ips_versions(self, cid):
        return []

    def book_ids(self):
        return ["x"]


def ok_chat(system, user):
    return json.dumps({"liquidity": "The client keeps a cash reserve of S$400,000.", "longevity": "The client is 52 with a balanced profile.",
                       "legacy": "The client wants a legacy for two children."})


def down(system, user):
    raise ConnectionError("LM Studio down")


def pcts(r):
    return {b: r["proportion"][b]["pct"] for b in BUCKET_IDS}


def base(**kw):
    d = {"age": 45, "risk_score": 3, "risk_category": "Balanced", "aum": 1_000_000, "reserve": None, "monthly": None, "goals": set(), "horizon": []}
    d.update(kw)
    return d


def test_happy_three_pcts_with_reasons():
    r = propose_proportion(St(), "x", chat=down)
    assert r["status"] == "ok" and r["missing"] == [] and r["total"] == 100
    assert set(r["proportion"]) == set(BUCKET_IDS)
    assert sum(pcts(r).values()) == 100 and all(isinstance(v, int) and 0 <= v <= 100 for v in pcts(r).values())
    assert "S$400,000" in r["proportion"]["liquidity"]["reason"] and "S$4,000,000" in r["proportion"]["liquidity"]["reason"]
    assert "52" in r["proportion"]["longevity"]["reason"]
    assert "legacy" in r["proportion"]["legacy"]["reason"].lower() and pcts(r)["legacy"] >= 20
    assert all(v["reason"] for v in r["proportion"].values())


def test_model_refines_reasons():
    r = propose_proportion(St(), "x", chat=ok_chat)
    assert r["status"] == "ok" and r["model"]
    assert r["proportion"]["legacy"]["reason"] == "The client wants a legacy for two children."
    assert sum(pcts(r).values()) == 100


def test_model_invented_figure_rejected_keeps_rule_reason():
    bad = lambda s, u: json.dumps({"liquidity": "The client needs S$9,999,999 in cash.", "longevity": "I like it.", "legacy": "The client has 77 heirs."})  # noqa: E731
    r = propose_proportion(St(), "x", chat=bad)
    assert r["status"] == "ok" and "9,999,999" not in json.dumps(r) and "77" not in json.dumps(r)
    assert "S$400,000" in r["proportion"]["liquidity"]["reason"]


@pytest.mark.parametrize("chat", [down, lambda s, u: "not json", lambda s, u: "[1,2]"])
def test_model_down_or_garbage_falls_back(chat):
    r = propose_proportion(St(), "x", chat=chat)
    assert r["status"] == "ok" and r["model"] is None and sum(pcts(r).values()) == 100


def test_model_cannot_change_pcts():
    pct_changing = lambda s, u: json.dumps({"liquidity": "The client wants 90% liquidity.", "longevity": "x", "legacy": "y"})  # noqa: E731
    r = propose_proportion(St(), "x", chat=pct_changing)
    assert sum(pcts(r).values()) == 100 and "90%" not in r["proportion"]["liquidity"]["reason"]


def test_missing_goals_lists_and_no_proportion():
    r = propose_proportion(St(NO_GOALS), "x", chat=ok_chat)
    assert r["status"] == "missing" and r["proportion"] is None and r["model"] is None
    assert any(m.startswith("Goals") for m in r["missing"]) and len(r["missing"]) == 1


def test_missing_multiple_sections():
    r = propose_proportion(St(text="", risk=None, cap=None, aum=None), "x", chat=ok_chat)
    assert r["status"] == "missing" and r["proportion"] is None
    heads = {m.split(":")[0] for m in r["missing"]}
    assert heads == {"Demographics", "Client profile", "Risk profile", "Goals"}


def test_unknown_client_unavailable():
    r = propose_proportion(St(), "nobody", chat=ok_chat)
    assert r["status"] == "unavailable" and r["proportion"] is None


@pytest.mark.parametrize("age", [18, 100])
def test_extreme_ages_valid(age):
    r = rule_proportion(base(age=age))
    assert sum(r["pcts"].values()) == 100 and all(0 <= v <= 100 for v in r["pcts"].values())
    r2 = propose_proportion(St(FULL.replace("52", str(age))), "x", chat=down)
    assert r2["status"] == "ok" and sum(pcts(r2).values()) == 100 and str(age) in r2["proportion"]["longevity"]["reason"]


def test_sums_to_100_for_many_random_inputs():
    rnd = random.Random(75)
    goals = ["legacy", "family_foundation", "retirement", "growth", "income"]
    for _ in range(600):
        p = base(age=rnd.randint(18, 100), risk_score=rnd.randint(1, 5), aum=rnd.choice([1, 1000, 5e5, 1e9]),
                 reserve=rnd.choice([None, 0, 1e3, 5e8, 1e12]), monthly=rnd.choice([None, 0, 50, 1e7]),
                 goals=set(rnd.sample(goals, rnd.randint(0, 3))))
        r = rule_proportion(p)
        assert sum(r["pcts"].values()) == 100, p
        assert set(r["pcts"]) == set(BUCKET_IDS)
        assert all(isinstance(v, int) and 0 <= v <= 100 for v in r["pcts"].values()), p
        assert all(r["reasons"][b] for b in BUCKET_IDS)


def test_normalise_pcts_edge_cases():
    rnd = random.Random(1)
    for _ in range(500):
        raw = {b: rnd.choice([0, 0.001, rnd.random() * 1000, 1e9]) for b in BUCKET_IDS}
        out = normalise_pcts(raw)
        assert sum(out.values()) == 100 and all(isinstance(v, int) and 0 <= v <= 100 for v in out.values())
    assert sum(normalise_pcts({"liquidity": 0, "longevity": 0, "legacy": 0}).values()) == 100
    assert normalise_pcts({"liquidity": 1, "longevity": 1, "legacy": 1}) == {"liquidity": 34, "longevity": 33, "legacy": 33}
    assert normalise_pcts({"liquidity": -5, "longevity": 10, "legacy": 0}) == {"liquidity": 0, "longevity": 100, "legacy": 0}


def test_rule_direction():
    hi_need = rule_proportion(base(reserve=300_000, monthly=10_000))["pcts"]["liquidity"]
    lo_need = rule_proportion(base(reserve=1_000, monthly=100))["pcts"]["liquidity"]
    assert hi_need > lo_need
    assert rule_proportion(base(goals={"legacy"}))["pcts"]["legacy"] > rule_proportion(base())["pcts"]["legacy"]


@pytest.mark.parametrize("t,age", [("Jane said she is 45 now.", 45), ("He is 62 years old.", 62), ("a 38-year-old client", 38),
                                   ("Age: 71", 71), ("The deposit is 12 months away.", None), ("It is 15 years from now", None), ("", None)])
def test_parse_age(t, age):
    assert parse_age(t) == age


# --- validate ---------------------------------------------------------------
@pytest.mark.parametrize("p,ok,total", [({"liquidity": 20, "longevity": 50, "legacy": 30}, True, 100),
                                        ({"liquidity": 20, "longevity": 50, "legacy": 25}, False, 95),
                                        ({"liquidity": 50, "longevity": 50, "legacy": 50}, False, 150),
                                        ({"liquidity": 0, "longevity": 100, "legacy": 0}, True, 100),
                                        ({"liquidity": -10, "longevity": 110, "legacy": 0}, False, 100),
                                        ({"liquidity": 101, "longevity": -1, "legacy": 0}, False, 100)])
def test_validate(p, ok, total):
    r = validate_proportion(p)
    assert r["ok"] is ok and r["total"] == total and r["message"]


def test_validate_bad_inputs():
    assert validate_proportion({"liquidity": 50, "longevity": 50})["ok"] is False
    assert validate_proportion({"liquidity": "a", "longevity": 50, "legacy": 50})["ok"] is False
    assert validate_proportion(None)["ok"] is False
    assert validate_proportion({"liquidity": {"pct": 20}, "longevity": {"pct": 50}, "legacy": {"pct": 30}})["ok"] is True


# --- endpoints --------------------------------------------------------------
@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_LLM_ENABLED", "false")
    monkeypatch.setattr(store_mod, "_default", St())
    return TestClient(app)


def test_endpoint_validate(api):
    ok = api.post(f"{U}/validate", json={"liquidity": 20, "longevity": 50, "legacy": 30}).json()
    assert ok == {"ok": True, "total": 100, "message": ok["message"]}
    bad = api.post(f"{U}/validate", json={"liquidity": 20, "longevity": 50, "legacy": 20}).json()
    assert bad["ok"] is False and bad["total"] == 90 and "90" in bad["message"]
    assert api.post(f"{U}/validate", json={"liquidity": 20}).status_code == 422


def test_propose_refine_false_makes_no_llm_call_and_keeps_rule_reasons():
    calls = []

    def chat(system, user):
        calls.append(1)
        return "{}"
    out = propose_proportion(St(), "x", chat, refine=False)
    assert calls == [] and out["status"] == "ok" and out["model"] is None
    assert sum(out["proportion"][b]["pct"] for b in BUCKET_IDS) == 100
    assert all(out["proportion"][b]["reason"] for b in BUCKET_IDS)
