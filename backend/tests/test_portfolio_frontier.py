"""
Efficient frontier, adjusted-weight evaluation, and the per-option
sub-class breakdown and key differences.
"""
import dataclasses

import numpy as np
import pytest

from app.agents.portfolio_manager.assumptions import load_assumptions
from app.agents.portfolio_manager.engine.frontier import _model, efficient_frontier, min_variance, model_point
from portfolio_helpers import BASE, GENERATE, make_client, make_service, offered, option, request_with

CLASSES = ["Cash", "Fixed income", "Equities", "Hedge funds", "Private markets", "Real estate", "Gold"]


def _evaluate(client, request_id, option_id, weights):
    return client.post(f"{BASE}/portfolio/{request_id}/options/{option_id}/evaluate", json={"weights": weights})


def _proposal(client, request_id="PM-FR", **kw):
    body = client.post(GENERATE, json=request_with(request_id, **kw)).json()
    opt = body["portfolio_options"][[o["option_id"] for o in body["portfolio_options"]].index(body["preferred_option"])]
    return body, opt, {a["asset_class"]: a["allocation_percentage"] for a in opt["asset_allocation"]}


# --- Frontier maths ------------------------------------------------------------

def test_frontier_is_efficient_and_monotone():
    cma = load_assumptions()
    f = efficient_frontier(cma, CLASSES)
    assert len(f.points) >= 20
    vols = [p.volatility_pct for p in f.points]
    rets = [p.expected_return_pct for p in f.points]
    assert all(a <= b + 1e-9 for a, b in zip(vols, vols[1:]))
    assert all(a <= b + 1e-9 for a, b in zip(rets, rets[1:]))
    for p in f.points:
        assert abs(sum(p.weights.values()) - 100) < 0.05 and min(p.weights.values()) >= 0
    # No random long-only portfolio has lower risk at the same expected return.
    mu, cov = _model(cma, CLASSES)
    rng = np.random.default_rng(1)
    for w in rng.dirichlet(np.ones(len(CLASSES)), size=500):
        best = min_variance(mu, cov, float(w @ mu))
        assert best @ cov @ best <= w @ cov @ w + 1e-9


def test_frontier_matches_closed_form_for_two_assets():
    # Two uncorrelated assets: the minimum-variance weight on asset 1 is s2^2 / (s1^2 + s2^2).
    cma = load_assumptions()
    f = efficient_frontier(cma, ["Cash", "Equities"])
    s1, s2 = cma.volatility["Cash"], cma.volatility["Equities"]
    w_cash = s2**2 / (s1**2 + s2**2) * 100
    assert abs(f.points[0].weights["Cash"] - w_cash) < 0.05


def test_no_frontier_without_complete_assumptions():
    cma = load_assumptions()
    partial = dataclasses.replace(cma, volatility={k: v for k, v in cma.volatility.items() if k != "Gold"})
    assert efficient_frontier(partial, CLASSES) is None
    assert model_point(partial, {"Gold": 50, "Cash": 50}) is None


# --- Adjusted weights endpoint ---------------------------------------------------

def test_original_weights_reproduce_the_proposal():
    client = make_client()
    body, opt, weights = _proposal(client)
    r = _evaluate(client, body["request_id"], opt["option_id"], weights)
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["valid"] is True
    assert ev["adjusted"] == ev["original"]
    assert abs(ev["adjusted"]["product_expected_return_pct"] - opt["expected_portfolio_return"]) < 0.02
    assert abs(ev["adjusted"]["stress_drawdown_pct"] - opt["metrics"]["estimated_stress_drawdown_pct"]) < 0.02
    assert ev["frontier"] and len(ev["frontier"]["points"]) >= 20
    assert ev["frontier"]["basis"] == "ASSUMPTION"
    # Frontier only spans classes the client can hold (preferred classes exclude alternatives here).
    assert set(ev["frontier"]["asset_classes"]) <= {"Cash", "Fixed income", "Equities"}


def test_valid_shift_moves_the_portfolio_point():
    client = make_client()
    body, opt, w = _proposal(client, "PM-SHIFT")
    up, down = "Equities", "Cash"
    assert w[down] >= 3
    adjusted = {**w, up: w[up] + 3, down: w[down] - 3}
    ev = _evaluate(client, body["request_id"], opt["option_id"], adjusted).json()
    assert ev["adjusted"]["model_volatility_pct"] > ev["original"]["model_volatility_pct"]
    assert ev["adjusted"]["model_expected_return_pct"] > ev["original"]["model_expected_return_pct"]
    line = {ln["asset_class"]: ln for ln in ev["lines"]}
    assert line[up]["change_pp"] == pytest.approx(3) and line[down]["change_pp"] == pytest.approx(-3)
    assert abs(sum(ln["adjusted_amount"] for ln in ev["lines"]) - ev["eligible_portfolio_value"]) < 0.05


def test_total_must_be_100_and_other_weights_are_not_touched():
    client = make_client()
    body, opt, w = _proposal(client, "PM-TOT")
    ev = _evaluate(client, body["request_id"], opt["option_id"], {**w, "Equities": w["Equities"] + 2}).json()
    assert ev["valid"] is False
    total = next(c for c in ev["checks"] if c["constraint"] == "Weights total 100%")
    assert total["status"] == "FAIL" and total["actual"] == pytest.approx(102)
    for ln in ev["lines"]:
        if ln["asset_class"] != "Equities":
            assert ln["adjusted_pct"] == ln["original_pct"]


def test_negative_and_out_of_band_weights_fail():
    client = make_client()
    body, opt, w = _proposal(client, "PM-NEG")
    ev = _evaluate(client, body["request_id"], opt["option_id"], {**w, "Cash": -1, "Equities": w["Equities"] + w["Cash"] + 1}).json()
    status = {c["constraint"]: c["status"] for c in ev["checks"]}
    assert status["No negative weights"] == "FAIL"
    assert status["Each class within 5 points of the proposal"] == "FAIL"
    assert ev["valid"] is False


def test_drawdown_limit_breach_is_flagged():
    client = make_client()
    body, opt, w = _proposal(client, "PM-DD", risk_appetite="Balanced", maximum_acceptable_drawdown=12)
    ev = _evaluate(client, body["request_id"], opt["option_id"],
                   {**w, "Equities": w["Equities"] + 5, "Cash": w["Cash"] - 5}).json()
    # The proposal sits just inside the 12% limit; moving 5 points from cash to equities pushes it over.
    assert opt["metrics"]["estimated_stress_drawdown_pct"] <= 12.01
    assert ev["adjusted"]["stress_drawdown_pct"] > 12.01
    status = {c["constraint"]: c["status"] for c in ev["checks"]}
    assert status["Maximum acceptable drawdown"] == "FAIL" and ev["valid"] is False
    assert [k for k, v in status.items() if v == "FAIL"] == ["Maximum acceptable drawdown"]


def test_evaluate_errors():
    client = make_client()
    body, opt, w = _proposal(client, "PM-ERR")
    assert _evaluate(client, "NOPE", "A", w).status_code == 404
    assert _evaluate(client, body["request_id"], opt["option_id"], {**w, "Crypto": 0}).status_code == 409
    withdrawn = next(o for o in body["portfolio_options"] if o["suitability_status"] in ("NOT_SUITABLE", "INFEASIBLE"))
    assert _evaluate(client, body["request_id"], withdrawn["option_id"], {}).status_code == 409


def test_frontier_limitation_reported_when_assumptions_incomplete(monkeypatch):
    service = make_service()
    service.cma = dataclasses.replace(service.cma, correlation_labels=(), correlation_matrix=())
    client = make_client(service)
    body, opt, w = _proposal(client, "PM-LIM")
    ev = _evaluate(client, body["request_id"], opt["option_id"], w).json()
    assert ev["frontier"] is None and "No efficient frontier" in ev["frontier_limitation"]
    assert ev["adjusted"]["model_volatility_pct"] is None  # no invented risk figure
    assert ev["adjusted"]["product_expected_return_pct"] is not None


# --- New response fields ----------------------------------------------------------

def test_sub_asset_allocation_reconciles_to_asset_classes():
    body = make_client().post(GENERATE, json=request_with("PM-SUB", preferred_asset_classes=[])).json()
    for o in offered(body):
        by_class: dict = {}
        for s in o["sub_asset_allocation"]:
            by_class[s["asset_class"]] = by_class.get(s["asset_class"], 0) + s["allocation_percentage"]
        for a in o["asset_allocation"]:
            assert abs(by_class[a["asset_class"]] - a["allocation_percentage"]) < 0.05
        assert len({s["sub_asset_class"] for s in o["sub_asset_allocation"]}) >= len(o["asset_allocation"])


def test_key_differences_explain_each_offered_option():
    body = make_client().post(GENERATE, json=request_with("PM-KD", risk_appetite="Aggressive", risk_tolerance_score=5,
                                                          risk_capacity="High", maximum_acceptable_drawdown=35,
                                                          preferred_asset_classes=[])).json()
    offers = offered(body)
    assert len(offers) >= 2
    assert offers[0]["key_differences"][0].startswith("Most cautious portfolio proposed")
    for prev, o in zip(offers, offers[1:]):
        assert o["key_differences"][0].startswith(f"Compared with {prev['option_id']}")
    for o in body["portfolio_options"]:
        if o not in offers:
            assert o["key_differences"] == [] and o["sub_asset_allocation"] == []


def test_number_of_proposed_portfolios_varies_by_client():
    def count(**kw):
        return len(offered(make_client().post(GENERATE, json=request_with(**kw)).json()))
    cautious = count(risk_appetite="Conservative", risk_tolerance_score=1, risk_capacity="Low", maximum_acceptable_drawdown=8)
    bold = count(risk_appetite="Aggressive", risk_tolerance_score=5, risk_capacity="High", maximum_acceptable_drawdown=35,
                 preferred_asset_classes=[], accredited_investor=True,
                 financial_goals=[{"goal": "Wealth", "target_amount": 1, "years_to_goal": 20, "priority": "High"}])
    assert 1 <= cautious < bold
    low = make_client().post(GENERATE, json=request_with(risk_appetite="Conservative", risk_tolerance_score=1,
                                                         risk_capacity="Low", maximum_acceptable_drawdown=8)).json()
    for oid in "DEF":
        assert option(low, oid)["suitability_status"] == "NOT_SUITABLE"
