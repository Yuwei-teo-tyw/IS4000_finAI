"""
Construction behaviour across client types, missing/contradictory
information, liquidity needs and constraint conflicts.
"""
from portfolio_helpers import GENERATE, assert_reconciles, make_client, offered, option, request_with


def _post(**kw):
    r = make_client().post(GENERATE, json=request_with(**kw))
    assert r.status_code == 200, r.text
    return r.json()


CONSERVATIVE = dict(risk_appetite="Conservative", risk_capacity="Low", risk_tolerance_score=1,
                    maximum_acceptable_drawdown=8)
GROWTH = dict(
    risk_appetite="Aggressive", risk_capacity="High", risk_tolerance_score=5, maximum_acceptable_drawdown=35,
    preferred_asset_classes=[], emergency_fund=60000, minimum_cash_reserve=60000,
    financial_goals=[{"goal": "Wealth accumulation", "target_amount": 900000, "years_to_goal": 20, "priority": "High"}],
)


# --- Client types ------------------------------------------------------------

def test_conservative_client_gets_no_growth_option():
    body = _post(**CONSERVATIVE)
    assert option(body, "C")["suitability_status"] == "NOT_SUITABLE"
    assert body["client_profile_summary"]["effective_risk_level"] == 1
    for opt in offered(body):
        assert opt["metrics"]["growth_asset_share_pct"] <= 20.01
        assert opt["metrics"]["estimated_stress_drawdown_pct"] <= 8.01
        assert_reconciles(opt)
    for oid in "CDEF":
        assert option(body, oid)["suitability_status"] == "NOT_SUITABLE"
    assert body["preferred_option"] in ("A", "B")


def test_balanced_client_respects_drawdown_and_concentration():
    body = _post(risk_appetite="Balanced")
    assert body["client_profile_summary"]["effective_risk_level"] == 3
    assert body["preferred_option"] is not None
    # Templates needing a higher risk level are not offered.
    for oid in "DEF":
        assert option(body, oid)["suitability_status"] == "NOT_SUITABLE"
    for opt in offered(body):
        assert opt["metrics"]["estimated_stress_drawdown_pct"] <= 15.01
        assert max(s["allocation_percentage"] for s in opt["product_selections"]) <= 30.0
        assert opt["metrics"]["growth_asset_share_pct"] <= 50.01
        assert_reconciles(opt)


def test_moderate_and_balanced_are_the_same_level():
    # Both "Moderate" and "Balanced" clients carry risk limit 3 in the frontend data.
    body = _post()
    assert body["client_profile_summary"]["effective_risk_level"] == 3
    assert not any("risk_tolerance_score" in c["fields"] for c in body["conflicts"])


def test_growth_client_gets_growth_options_and_matching_template_is_preferred():
    body = _post(**GROWTH)
    e = option(body, "E")
    assert e["suitability_status"] in ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS")
    assert e["metrics"]["growth_asset_share_pct"] > option(body, "C")["metrics"]["growth_asset_share_pct"]
    # Risk level 5 maps to template E (Aggressive growth).
    assert body["preferred_option"] == "E"
    for opt in offered(body):
        assert_reconciles(opt)
        assert opt["metrics"]["estimated_stress_drawdown_pct"] <= 35.01
    assert any("Significant short-term losses" in d for d in e["disadvantages"])


def test_opportunistic_kept_distinct_from_aggressive_growth():
    # E and F have similar growth shares but different alternatives mixes; F must not be
    # discarded as a near-duplicate when the client can hold alternatives.
    body = _post(**{**GROWTH, "accredited_investor": True})
    f = option(body, "F")
    assert f["suitability_status"] in ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS"), f["suitability_explanation"]


def test_capital_preservation_option_is_never_described_as_risk_free():
    a = option(_post(), "A")
    text = " ".join(a["disadvantages"]).lower()
    assert "not risk-free" in text and "inflation" in text and "reinvestment" in text


def test_preferred_asset_classes_are_respected():
    body = _post()
    for opt in offered(body):
        classes = {x["asset_class"] for x in opt["asset_allocation"]}
        assert not classes & {"REITs", "Gold & Commodities", "Multi-Asset"}


# --- Missing / contradictory information ------------------------------------

def test_missing_risk_capacity_blocks_construction():
    body = _post(remove=["risk_capacity"])
    assert body["status"] == "INSUFFICIENT_INFORMATION"
    assert body["portfolio_options"] == []
    assert body["preferred_option"] is None
    assert any(m["field"] == "risk_capacity" and m["severity"] == "BLOCKING" for m in body["missing_information"])
    assert body["data_status"]["client_profile"] == "INCOMPLETE"


def test_missing_investable_assets_blocks_construction():
    body = _post(remove=["investable_assets"])
    assert body["status"] == "INSUFFICIENT_INFORMATION"
    assert body["portfolio_options"] == []


def test_missing_reserve_inputs_block_construction():
    body = _post(remove=["minimum_cash_reserve", "monthly_expenses"])
    assert body["status"] == "INSUFFICIENT_INFORMATION"


def test_missing_reserve_uses_flagged_assumption():
    body = _post(remove=["minimum_cash_reserve"])
    assert body["liquidity_plan"]["minimum_cash_reserve_required"] == 30000  # 6 x 5000
    assert any("6 months of expenses" in s for s in body["assumptions"])
    assert body["preferred_option"] is None  # material missing info


def test_contradictory_appetite_and_score_flagged_and_lower_used():
    body = _post(risk_appetite="Aggressive", risk_tolerance_score=1)
    conflict = next(c for c in body["conflicts"] if "risk_tolerance_score" in c["fields"])
    assert conflict["severity"] == "MATERIAL"
    assert body["client_profile_summary"]["effective_risk_level"] == 1
    assert body["preferred_option"] is None


def test_investable_above_total_aum_is_invalid():
    body = _post(investable_assets=600000)
    assert body["status"] == "CONSTRAINT_CONFLICT"
    assert body["data_status"]["client_profile"] == "INVALID"
    assert body["portfolio_options"] == []


def test_high_capacity_with_thin_reserves_is_capped():
    body = _post(risk_appetite="Aggressive", risk_tolerance_score=5, risk_capacity="High",
                 emergency_fund=5000, minimum_cash_reserve=5000)
    assert any("reserves cover only" in c["description"] for c in body["conflicts"])
    assert body["client_profile_summary"]["effective_risk_level"] == 3


def test_missing_goals_means_no_long_term_option():
    body = _post(remove=["financial_goals"])
    assert option(body, "C")["suitability_status"] == "NOT_SUITABLE"
    assert any(m["field"] == "financial_goals" for m in body["missing_information"])


def test_goal_dated_in_the_past_flagged():
    body = _post(financial_goals=[{"goal": "Old goal", "target_amount": 1000, "target_date": "2020-01-01",
                                   "priority": "High"}])
    assert any("on or before the review date" in c["description"] for c in body["conflicts"])


# --- Liquidity ---------------------------------------------------------------

def test_withdrawals_exceeding_investable_assets_produce_no_portfolio():
    body = _post(planned_withdrawals=390000)
    assert body["status"] == "CONSTRAINT_CONFLICT"
    assert body["portfolio_options"] == []
    assert any(c["severity"] == "BLOCKING" and "consume all investable assets" in c["description"]
               for c in body["conflicts"])


def test_large_withdrawals_shrink_eligible_value():
    body = _post(planned_withdrawals=250000)
    assert body["liquidity_plan"]["eligible_portfolio_value"] == 120000
    for opt in offered(body):
        assert_reconciles(opt)


def test_dated_withdrawals_split_near_and_later():
    body = _post(planned_withdrawals=[
        {"amount": 20000, "months_from_now": 6},
        {"amount": 50000, "months_from_now": 60},
    ])
    plan = body["liquidity_plan"]
    assert plan["near_term_withdrawals_carved_out"] == 20000
    assert plan["later_withdrawals_not_carved_out"] == 50000
    assert plan["eligible_portfolio_value"] == 350000


def test_emergency_fund_held_outside_is_not_carved_out_twice():
    body = _post(emergency_fund_included_in_investable_assets=False)
    plan = body["liquidity_plan"]
    assert plan["reserve_already_held_outside_investable_assets"] == 30000
    assert plan["reserve_carved_out"] == 0
    assert plan["eligible_portfolio_value"] == 380000


# --- Constraint conflicts ----------------------------------------------------

def test_impossible_concentration_limit_explained_not_violated():
    body = _post(maximum_single_asset_allocation=5)
    assert body["status"] == "CONSTRAINT_CONFLICT"
    assert not offered(body)
    assert all(o["suitability_status"] in ("INFEASIBLE", "NOT_SUITABLE") for o in body["portfolio_options"])
    assert any("per-product limit" in o["suitability_explanation"] for o in body["portfolio_options"])


def test_very_tight_drawdown_limit_never_breached():
    body = _post(maximum_acceptable_drawdown=2)
    for opt in offered(body):
        assert opt["metrics"]["estimated_stress_drawdown_pct"] <= 2.01
        assert_reconciles(opt)


def test_zero_currency_exposure_excludes_unhedged_foreign_products():
    body = _post(**{**GROWTH, "maximum_currency_exposure": 0})
    for opt in offered(body):
        assert opt["metrics"]["foreign_currency_exposure_pct"] == 0
    excluded = {e["product_id"] for e in body["excluded_products"]}
    assert {"MOCK-EQ-001", "MOCK-GOLD-001", "MOCK-CORP-002"} <= excluded


def test_currency_limit_respected_by_swapping_products():
    body = _post(**{**GROWTH, "maximum_currency_exposure": 10})
    for opt in offered(body):
        assert opt["metrics"]["foreign_currency_exposure_pct"] <= 10.01


def test_excluded_sector_above_tolerance_removes_product():
    body = _post(**{**GROWTH, "excluded_sectors": ["Energy"]})
    reasons = {e["product_id"]: e["reason"] for e in body["excluded_products"]}
    assert "MOCK-DIV-001" in reasons and "MOCK-CORP-001" in reasons
    assert "MOCK-EQ-001" not in reasons  # 4.5% incidental exposure is disclosed, not excluded


def test_esg_required_only_selects_esg_products():
    body = _post(**{**GROWTH, "esg_preferences": {"level": "Required"}})
    for opt in offered(body):
        for s in opt["product_selections"]:
            assert s["product_id"] in {"MOCK-EQ-003", "MOCK-DIV-002", "MOCK-CORP-002"}


def test_restricted_products_never_selected():
    body = _post(restricted_products=["MOCK-GOVT-001", "Fixed Deposit"])
    selected = {s["product_id"] for o in offered(body) for s in o["product_selections"]}
    assert "MOCK-GOVT-001" not in selected and "MOCK-CASH-002" not in selected


def test_accredited_product_only_for_accredited_clients():
    body = _post(**{**GROWTH, "accredited_investor": True,
                    "financial_goals": [{"goal": "Long-term", "target_amount": 1, "years_to_goal": 10}]})
    assert "MOCK-CORP-003" not in {e["product_id"] for e in body["excluded_products"]}
    body = _post()
    assert "MOCK-CORP-003" in {e["product_id"] for e in body["excluded_products"]}


def test_template_cut_too_far_is_not_offered_under_its_name():
    # A 12% drawdown limit would force the Growth template (52% growth assets) down to
    # under 30%; offering that as "Growth" would mislead, so it is withdrawn with the reason.
    from app.agents.portfolio_agent.engine.construction import TEMPLATES, template_growth
    body = _post(risk_appetite="Balanced", maximum_acceptable_drawdown=12, preferred_asset_classes=[])
    d = option(body, "D")
    assert d["suitability_status"] == "NOT_SUITABLE"
    assert "would no longer be a Growth portfolio" in d["suitability_explanation"]
    for o in offered(body):
        tpl = next(t for t in TEMPLATES if t.option_id == o["option_id"])
        assert template_growth(tpl) - o["metrics"]["growth_asset_share_pct"] <= 10.01
