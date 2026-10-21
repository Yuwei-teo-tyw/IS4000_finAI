"""
Risk & Compliance checks: readiness (step 4), the final review-pack check
(before G4), the policy, fail-closed behaviour and the endpoints.

Offline and deterministic: fixed clock, no LLM, no network. The client is
the Portfolio Manager's sample profile (Moderate/Balanced, 8-year goal),
and products come from the shared illustrative shelf.
"""
import copy
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from portfolio_helpers import sample_request

from app.agents.portfolio_manager.schemas.upstream import UpstreamResult
from app.agents.product_recommender import shelf as shelf_mod
from app.agents.product_recommender.schemas import Shelf
from app.agents.risk_compliance import pack_checks
from app.agents.risk_compliance import service as service_mod
from app.agents.risk_compliance.config import Settings
from app.agents.risk_compliance.policy import (
    POLICY_PATH,
    RULE_IDS,
    PolicyError,
    field_matches,
    load_policy,
)
from app.agents.risk_compliance.schemas import ReadinessRequest, ReviewPackCheckRequest
from app.agents.risk_compliance.service import RiskComplianceService
from app.endpoints.portfolio_manager import install_validation_handler
from app.endpoints.risk_compliance import PREFIX, router

FIXED_NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
TODAY = FIXED_NOW.date()
PROFILE_AS_OF = date(2026, 9, 20)
MARKET_AS_OF = date(2026, 10, 14)

CLEAN_ALLOCATION = [
    {"asset_class": "Cash", "saa": 10, "current": 12, "old_taa": 10, "new_taa": 10, "band": 5},
    {"asset_class": "Fixed income", "saa": 50, "current": 48, "old_taa": 50, "new_taa": 50, "band": 5},
    {"asset_class": "Equities", "saa": 40, "current": 40, "old_taa": 40, "new_taa": 40, "band": 5},
]
CLEAN_PRODUCTS = [
    {"product_id": "MOCK-GOVT-001", "product_name": "Illustrative Singapore Government Bond ETF", "weight_pct": 25},
    {"product_id": "MOCK-CORP-001", "product_name": "Illustrative Asia Investment-Grade Bond Fund (SGD-Hedged)", "weight_pct": 25},
    {"product_id": "MOCK-DIV-002", "product_name": "Illustrative Global Quality Dividend ETF (SGD-Hedged)", "weight_pct": 20},
    {"product_id": "MOCK-CASH-001", "product_name": "Illustrative SGD Money Market Fund", "weight_pct": 10},
]
CLEAN_SECTIONS = [
    {"n": 1, "title": "Client profile and goals", "owner": "rm", "gate": "G4", "status": "ready",
     "text": "Balanced client with a retirement goal in 8 years."},
    {"n": 5, "title": "Old vs new TAA", "owner": "ic", "gate": "G2", "status": "approved",
     "text": "Fixed income 50%, equities 40%, cash 10%. Returns are not guaranteed."},
    {"n": 6, "title": "Product recommendations", "owner": "ps", "gate": "G3", "status": "approved",
     "text": "Four products from the shelf."},
    {"n": 7, "title": "Sign-off", "owner": "rm", "status": "draft", "text": "", "kind": "signoff"},
]
APPROVED_GATES = {"G1": "approved", "G2": "approved", "G3": "approved", "G4": "pending"}


def profile(remove=(), **overrides) -> dict:
    p = copy.deepcopy(sample_request()["client_profile"])
    p.update(copy.deepcopy(overrides))
    for f in remove:
        p.pop(f, None)
    return p


def readiness_request(profile_as_of=PROFILE_AS_OF, policy_version=None, **profile_overrides) -> ReadinessRequest:
    return ReadinessRequest.model_validate({
        "request_id": "RC-TEST", "client_id": "CLIENT_001", "client_profile": profile(**profile_overrides),
        "reference_date": TODAY.isoformat(), "policy_version": policy_version,
        "profile_as_of": profile_as_of.isoformat() if profile_as_of else None,
        "objective": {"type": "quarterly_review", "confirmed_by": "RM"},
    })


def pack_request(profile_overrides=None, **fields) -> ReviewPackCheckRequest:
    body = {
        "request_id": "PACK-TEST", "client_id": "CLIENT_001", "pack_version": "v1",
        "client_profile": profile(**(profile_overrides or {})), "reference_date": TODAY.isoformat(),
        "allocation": copy.deepcopy(CLEAN_ALLOCATION), "products": copy.deepcopy(CLEAN_PRODUCTS),
        "sections": copy.deepcopy(CLEAN_SECTIONS), "gates": dict(APPROVED_GATES),
        "data_as_of": {"profile": PROFILE_AS_OF.isoformat(), "market": MARKET_AS_OF.isoformat()},
    }
    body.update(copy.deepcopy(fields))
    return ReviewPackCheckRequest.model_validate(body)


def shelf_with(**changes_by_id) -> callable:
    """A shelf loader where product fields are overridden by product_id."""
    products = []
    for prod in shelf_mod.load_shelf().data.products:
        if prod.product_id in changes_by_id:
            prod = prod.model_copy(update=changes_by_id[prod.product_id])
        products.append(prod)

    def load() -> UpstreamResult:
        return UpstreamResult(source="MOCK", status="OK", data=Shelf(products=products, is_illustrative=True))
    return load


def unavailable_shelf() -> UpstreamResult:
    return UpstreamResult(source="MOCK", status="UNAVAILABLE", issues=["down"])


def service(**kw) -> RiskComplianceService:
    return RiskComplianceService(settings=Settings(policy_path=None), clock=lambda: FIXED_NOW, **kw)


def policy_file(tmp_path, mutate) -> callable:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return lambda: load_policy(path)


def rules(report) -> set[str]:
    return {f.rule_id for f in report.findings}


def check(req: ReviewPackCheckRequest, **svc_kw):
    return service(**svc_kw).check_pack(req)


def with_row(asset_class: str, **values) -> list[dict]:
    rows = copy.deepcopy(CLEAN_ALLOCATION)
    for r in rows:
        if r["asset_class"] == asset_class:
            r.update(values)
    return rows


# --- Policy -----------------------------------------------------------------------

def test_policy_defines_every_rule_and_is_marked_placeholder():
    loaded = load_policy()
    assert set(RULE_IDS) <= set(loaded.policy.rules)
    assert "PLACEHOLDER" in loaded.policy.notice and "TODO" in loaded.policy.notice


def test_policy_missing_a_rule_is_refused(tmp_path):
    loader = policy_file(tmp_path, lambda raw: raw["rules"].pop("ALLOC.SUM"))
    with pytest.raises(PolicyError):
        loader()


def test_field_patterns_match_goal_fields():
    assert field_matches("financial_goals[*].years_to_goal", "financial_goals[Retirement income].years_to_goal")
    assert field_matches("financial_goals", "financial_goals")
    assert not field_matches("financial_goals", "financial_goals[Retirement income].target_amount")


# --- Readiness: golden cases ----------------------------------------------------------

def test_complete_balanced_client_passes():
    r = service().readiness(readiness_request())
    assert r.status == "PASS" and r.next_step == "ADVISORY"
    assert r.effective_risk.effective_level == 3 and r.effective_risk.governed_by == "agree"
    assert r.eligible_value == 350_000  # 400,000 - 30,000 reserve - 20,000 withdrawals
    c = r.constraints
    assert c.max_growth_pct == 50.0 and c.max_single_product_pct == 30 and c.max_lock_in_months == 96
    assert c.preferred_asset_classes == ["Cash", "Fixed income", "Equities"]
    assert all(f.effect == "NOTE" for f in r.findings)


def test_high_appetite_with_low_reserves_is_capacity_limited():
    r = service().readiness(readiness_request(
        risk_appetite="Aggressive", risk_tolerance_score=5, risk_capacity="High", emergency_fund=5000,
    ))
    assert r.effective_risk.governed_by == "capacity"
    assert r.effective_risk.effective_level == 3 and r.effective_risk.appetite_level == 5
    assert any("reserves cover only 1.0 months" in c.description for c in r.conflicts)
    assert r.status == "PASS_WITH_CONDITIONS" and r.next_step == "ADVISORY"


def test_missing_goal_horizon_needs_info():
    goals = [{"goal": "Retirement income", "target_amount": 250000, "currency": "SGD", "priority": "High"}]
    r = service().readiness(readiness_request(financial_goals=goals))
    assert r.status == "NEEDS_INFO" and r.next_step == "CLARIFY"
    f = next(f for f in r.findings if f.rule_id == "READY.REQUIRED_FIELD")
    assert f.fields == ["financial_goals[Retirement income].years_to_goal"]


def test_no_goals_at_all_needs_info():
    r = service().readiness(readiness_request(financial_goals=None))
    assert r.status == "NEEDS_INFO"
    assert any(f.fields == ["financial_goals"] for f in r.findings)


def test_missing_risk_capacity_needs_info():
    r = service().readiness(readiness_request(risk_capacity=None))
    assert r.status == "NEEDS_INFO" and r.effective_risk.effective_level is None
    assert r.constraints.max_growth_pct is None


def test_reserve_consuming_all_assets_is_blocked():
    r = service().readiness(readiness_request(investable_assets=40000, total_aum=40000))
    assert r.status == "BLOCKED" and r.next_step == "BLOCK"
    assert r.eligible_value is None


# --- Readiness: boundaries -------------------------------------------------------------

@pytest.mark.parametrize("years, flagged", [(3, False), (2.9, True)])
def test_horizon_vs_risk_level_boundary(years, flagged):
    goals = [{"goal": "Retirement income", "target_amount": 250000, "years_to_goal": years, "priority": "High"}]
    r = service().readiness(readiness_request(financial_goals=goals))
    assert ("READY.HORIZON_VS_RISK" in rules(r)) is flagged
    assert r.status == ("PASS_WITH_CONDITIONS" if flagged else "PASS")


@pytest.mark.parametrize("age_days, stale", [(365, False), (366, True)])
def test_profile_staleness_boundary(age_days, stale):
    r = service().readiness(readiness_request(profile_as_of=TODAY - timedelta(days=age_days)))
    assert ("DATA.PROFILE_STALE" in rules(r)) is stale
    assert r.status == ("NEEDS_INFO" if stale else "PASS")


def test_unknown_profile_date_is_treated_as_stale():
    r = service().readiness(readiness_request(profile_as_of=None))
    assert r.status == "NEEDS_INFO"
    assert next(f for f in r.findings if f.rule_id == "DATA.PROFILE_STALE").code == "PROFILE_AS_OF_UNKNOWN"


# --- Fail closed -----------------------------------------------------------------------

def test_internal_error_in_readiness_is_blocked_not_passed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("client data in the message")
    monkeypatch.setattr(service_mod, "check_readiness", boom)
    r = service().readiness(readiness_request())
    assert r.status == "BLOCKED" and r.next_step == "BLOCK"
    assert [f.rule_id for f in r.findings] == ["SYS.INTERNAL"]
    assert "client data" not in r.findings[0].message


def test_internal_error_in_pack_check_is_blocked_not_passed(monkeypatch):
    def boom(*a, **k):
        raise KeyError("x")
    monkeypatch.setattr(pack_checks, "check_allocation", boom)
    r = check(pack_request())
    assert r.status == "BLOCKED" and r.rm_signoff_allowed is False
    assert [f.code for f in r.findings] == ["INTERNAL_ERROR"]


def test_broken_policy_file_blocks(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text("{not json", encoding="utf-8")
    svc = service(policy_loader=lambda: load_policy(path))
    assert svc.readiness(readiness_request()).status == "BLOCKED"
    r = svc.check_pack(pack_request())
    assert r.status == "BLOCKED" and r.findings[0].rule_id == "SYS.POLICY" and r.policy_version is None


def test_policy_version_mismatch_blocks():
    r = service().readiness(readiness_request(policy_version="2025.01"))
    assert r.status == "BLOCKED" and r.findings[0].code == "POLICY_UNAVAILABLE"


# --- Determinism -----------------------------------------------------------------------

def test_same_input_gives_identical_report_and_fingerprint():
    a = service().check_pack(pack_request(sections=CLEAN_SECTIONS + [
        {"n": 9, "title": "Extra", "owner": "rm", "status": "draft", "text": "Guaranteed 12% returns."}]))
    b = service().check_pack(pack_request(sections=CLEAN_SECTIONS + [
        {"n": 9, "title": "Extra", "owner": "rm", "status": "draft", "text": "Guaranteed 12% returns."}]))
    assert a.model_dump() == b.model_dump()
    assert service().readiness(readiness_request()).model_dump() == service().readiness(readiness_request()).model_dump()


def test_fingerprint_changes_with_input_and_policy(tmp_path):
    base = service().readiness(readiness_request()).inputs_fingerprint
    assert service().readiness(readiness_request(investable_assets=400001)).inputs_fingerprint != base
    other = service(policy_loader=policy_file(tmp_path, lambda raw: raw["thresholds"].update(band_tolerance_pct=1.0)))
    assert other.readiness(readiness_request()).inputs_fingerprint != base


def test_every_finding_cites_a_policy_rule_and_version():
    r = check(pack_request(
        allocation=with_row("Equities", new_taa=60, saa=60) + [
            {"asset_class": "Hedge funds", "saa": 0, "current": 0, "old_taa": 0, "new_taa": 5, "band": 5}],
        products=CLEAN_PRODUCTS + [{"product_id": "MOCK-EQ-002", "product_name": "x", "weight_pct": 40}],
        gates={"G1": "approved"},
        data_as_of={},
    ))
    version = load_policy().version
    assert r.findings and all(f.rule_id in RULE_IDS and f.policy_version == version for f in r.findings)


# --- Review pack: golden cases ----------------------------------------------------------

def test_clean_pack_passes_and_allows_signoff():
    r = check(pack_request())
    assert r.status == "PASS" and r.rm_signoff_allowed is True
    assert r.findings == [] and r.constraints.max_growth_pct == 50.0


def test_product_above_client_risk_limit_blocks():
    r = check(pack_request(products=CLEAN_PRODUCTS + [
        {"product_id": "MOCK-EQ-002", "product_name": "Illustrative Singapore Equity Index ETF", "weight_pct": 10}]))
    assert r.status == "BLOCKED" and r.rm_signoff_allowed is False
    f = next(f for f in r.findings if f.rule_id == "PROD.SUITABILITY")
    assert f.code == "SUITABILITY_RISK_ABOVE_LIMIT" and "MOCK-EQ-002" in f.message


def test_concentrated_product_is_flagged():
    products = copy.deepcopy(CLEAN_PRODUCTS)
    products[0]["weight_pct"] = 60
    r = check(pack_request(products=products))
    f = next(f for f in r.findings if f.rule_id == "PROD.SINGLE_CAP")
    assert f.observed == 60 and f.threshold == 30 and r.status == "BLOCKED"


def test_taa_above_growth_ceiling_blocks():
    rows = [
        {"asset_class": "Cash", "saa": 10, "current": 10, "old_taa": 10, "new_taa": 10, "band": 5},
        {"asset_class": "Fixed income", "saa": 35, "current": 35, "old_taa": 35, "new_taa": 35, "band": 5},
        {"asset_class": "Equities", "saa": 55, "current": 55, "old_taa": 55, "new_taa": 55, "band": 5},
    ]
    r = check(pack_request(allocation=rows))
    assert r.status == "BLOCKED"
    f = next(f for f in r.findings if f.rule_id == "ALLOC.GROWTH_CEILING")
    assert f.observed == 55 and f.threshold == 50


def test_guarantee_in_pack_text_blocks_but_negated_caveat_does_not():
    sections = copy.deepcopy(CLEAN_SECTIONS)
    sections[0]["text"] = "This portfolio offers guaranteed returns."
    r = check(pack_request(sections=sections))
    assert r.status == "BLOCKED" and "TEXT.CLAIM" in rules(r)
    assert "TEXT.CLAIM" not in rules(check(pack_request()))  # "Returns are not guaranteed." is allowed


def test_flagged_section_blocks_and_draft_section_needs_info():
    flagged = copy.deepcopy(CLEAN_SECTIONS)
    flagged[0]["status"] = "flagged"
    assert check(pack_request(sections=flagged)).status == "BLOCKED"
    draft = copy.deepcopy(CLEAN_SECTIONS)
    draft[0]["status"] = "draft"
    r = check(pack_request(sections=draft))
    assert r.status == "NEEDS_INFO" and "PACK.SECTION_INCOMPLETE" in rules(r)


def test_signoff_section_is_not_checked_for_completeness():
    r = check(pack_request())
    assert not any("sections[7]" in f.fields for f in r.findings)


def test_empty_section_text_is_incomplete():
    sections = copy.deepcopy(CLEAN_SECTIONS)
    sections[2]["text"] = "   "
    assert "PACK.SECTION_INCOMPLETE" in rules(check(pack_request(sections=sections)))


def test_prior_gate_not_approved_blocks():
    r = check(pack_request(gates={"G1": "approved", "G2": "pending", "G3": "approved"}))
    assert r.status == "BLOCKED"
    assert [f.fields for f in r.findings if f.rule_id == "PACK.PRIOR_GATE"] == [["gates.G2"]]


def test_stale_product_data_needs_info():
    r = check(pack_request(), shelf_loader=shelf_with(**{"MOCK-GOVT-001": {"as_of_date": TODAY - timedelta(days=91)}}))
    assert r.status == "NEEDS_INFO" and "DATA.PRODUCTS_STALE" in rules(r)
    ok = check(pack_request(), shelf_loader=shelf_with(**{"MOCK-GOVT-001": {"as_of_date": TODAY - timedelta(days=90)}}))
    assert "DATA.PRODUCTS_STALE" not in rules(ok)


@pytest.mark.parametrize("market, status", [
    (MARKET_AS_OF.isoformat(), "PASS"),
    ((TODAY - timedelta(days=30)).isoformat(), "PASS"),
    ((TODAY - timedelta(days=31)).isoformat(), "NEEDS_INFO"),
    (None, "NEEDS_INFO"),
])
def test_market_data_staleness_boundary(market, status):
    r = check(pack_request(data_as_of={"profile": PROFILE_AS_OF.isoformat(), "market": market}))
    assert r.status == status


def test_pack_carries_readiness_problems():
    goals = [{"goal": "Retirement income", "target_amount": 250000, "priority": "High"}]
    r = check(pack_request(profile_overrides={"financial_goals": goals}))
    assert "READY.REQUIRED_FIELD" in rules(r) and not r.rm_signoff_allowed
    # An unknown horizon also caps growth at the PM's 30%, so the 40% equity TAA is blocked too.
    assert r.constraints.max_growth_pct == 30.0 and r.status == "BLOCKED"


# --- Review pack: allocation boundaries ------------------------------------------------------

@pytest.mark.parametrize("cash, flagged", [(10.5, False), (10.6, True), (9.5, False), (9.4, True)])
def test_taa_sum_tolerance_boundary(cash, flagged):
    r = check(pack_request(allocation=with_row("Cash", new_taa=cash)))
    assert ("ALLOC.SUM" in rules(r)) is flagged


@pytest.mark.parametrize("fixed_income, flagged", [(55, False), (55.1, True), (45, False), (44.9, True)])
def test_saa_band_boundary(fixed_income, flagged):
    r = check(pack_request(allocation=with_row("Fixed income", new_taa=fixed_income)))
    assert ("ALLOC.BAND" in rules(r)) is flagged


@pytest.mark.parametrize("equities, flagged", [(50, False), (50.1, True)])
def test_growth_ceiling_boundary(equities, flagged):
    rows = [
        {"asset_class": "Cash", "saa": 10, "current": 10, "old_taa": 10, "new_taa": 10, "band": 5},
        {"asset_class": "Fixed income", "saa": 40, "current": 40, "old_taa": 40, "new_taa": 90 - equities, "band": 5},
        {"asset_class": "Equities", "saa": 50, "current": 50, "old_taa": 50, "new_taa": equities, "band": 5},
    ]
    assert ("ALLOC.GROWTH_CEILING" in rules(check(pack_request(allocation=rows)))) is flagged


def test_short_horizon_tightens_the_growth_ceiling():
    goals = [{"goal": "House", "target_amount": 250000, "years_to_goal": 4, "priority": "High"}]
    r = check(pack_request(profile_overrides={"financial_goals": goals}))
    # Risk level 3 allows 50%, but a horizon under 5 years caps growth at the PM's 30%.
    assert r.constraints.max_growth_pct == 30.0 and "ALLOC.GROWTH_CEILING" in rules(r)


def test_weight_in_non_preferred_class_blocks():
    rows = copy.deepcopy(CLEAN_ALLOCATION)
    rows[1]["new_taa"] = 45
    rows.append({"asset_class": "Hedge funds", "saa": 0, "current": 0, "old_taa": 0, "new_taa": 5, "band": 5})
    r = check(pack_request(allocation=rows))
    assert r.status == "BLOCKED" and "ALLOC.NOT_PREFERRED" in rules(r)


def test_unknown_asset_class_and_missing_allocation_need_info():
    rows = CLEAN_ALLOCATION + [{"asset_class": "Crypto", "saa": 0, "current": 0, "old_taa": 0, "new_taa": 0, "band": 0}]
    assert check(pack_request(allocation=rows)).status == "NEEDS_INFO"
    r = check(pack_request(allocation=[]))
    assert r.status == "NEEDS_INFO" and "ALLOC.MISSING" in rules(r)


# --- Review pack: products ---------------------------------------------------------------------

@pytest.mark.parametrize("weight, flagged", [(30, False), (30.01, True)])
def test_single_product_cap_boundary(weight, flagged):
    products = copy.deepcopy(CLEAN_PRODUCTS)
    products[0]["weight_pct"] = weight
    assert ("PROD.SINGLE_CAP" in rules(check(pack_request(products=products)))) is flagged


def test_single_product_cap_falls_back_to_policy_default():
    products = copy.deepcopy(CLEAN_PRODUCTS)
    products[0]["weight_pct"] = 26
    r = check(pack_request(products=products, profile_overrides={"maximum_single_asset_allocation": None}))
    assert r.constraints.max_single_product_pct == 25.0 and "PROD.SINGLE_CAP" in rules(r)


@pytest.mark.parametrize("weight, flagged", [(20, False), (20.5, True)])
def test_currency_exposure_cap_boundary(weight, flagged):
    products = CLEAN_PRODUCTS[1:] + [{"product_id": "MOCK-CORP-002", "product_name": "x", "weight_pct": weight}]
    r = check(pack_request(products=products, profile_overrides={"maximum_currency_exposure": 20}))
    assert ("PROD.FX_CAP" in rules(r)) is flagged


def test_hedged_foreign_products_do_not_count_as_currency_exposure():
    products = CLEAN_PRODUCTS + [{"product_id": "MOCK-GOVT-003", "product_name": "x", "weight_pct": 25}]
    r = check(pack_request(products=products, profile_overrides={"maximum_currency_exposure": 0}))
    assert "PROD.FX_CAP" not in rules(r)


def test_product_not_on_shelf_needs_info():
    r = check(pack_request(products=CLEAN_PRODUCTS + [{"product_name": "SGD Investment Grade Bond Fund"}]))
    assert r.status == "NEEDS_INFO" and "PROD.UNVERIFIED" in rules(r)


def test_shelf_unavailable_makes_every_product_unverified():
    r = check(pack_request(), shelf_loader=unavailable_shelf)
    assert r.status == "NEEDS_INFO"
    assert sum(f.rule_id == "PROD.UNVERIFIED" for f in r.findings) == len(CLEAN_PRODUCTS)


def test_product_resolves_by_exact_name_when_id_missing():
    products = [{k: v for k, v in p.items() if k != "product_id"} for p in CLEAN_PRODUCTS]
    assert check(pack_request(products=products)).status == "PASS"


def test_missing_weights_are_noted_without_failing():
    products = [{k: v for k, v in p.items() if k != "weight_pct"} for p in CLEAN_PRODUCTS]
    r = check(pack_request(products=products))
    assert r.status == "PASS" and "PROD.WEIGHTS_MISSING" in rules(r)


def test_product_in_unallocated_class_is_a_condition():
    rows = [
        {"asset_class": "Fixed income", "saa": 60, "current": 60, "old_taa": 60, "new_taa": 60, "band": 5},
        {"asset_class": "Equities", "saa": 40, "current": 40, "old_taa": 40, "new_taa": 40, "band": 5},
    ]
    r = check(pack_request(allocation=rows))
    assert r.status == "PASS_WITH_CONDITIONS" and r.rm_signoff_allowed
    assert [f.fields[0] for f in r.findings if f.rule_id == "PROD.CLASS_NOT_ALLOCATED"] == ["products[MOCK-CASH-001]"]


# --- Review pack: wording ------------------------------------------------------------------------

def test_missing_disclaimer_is_a_condition():
    sections = copy.deepcopy(CLEAN_SECTIONS)
    sections[1]["text"] = "Fixed income 50%, equities 40%, cash 10%."
    r = check(pack_request(sections=sections))
    assert r.status == "PASS_WITH_CONDITIONS" and r.rm_signoff_allowed and "TEXT.DISCLAIMER" in rules(r)


def test_unreconciled_figure_is_noted_only():
    sections = copy.deepcopy(CLEAN_SECTIONS)
    sections[0]["text"] = "Tech concentration of 31% looks high."
    r = check(pack_request(sections=sections))
    assert r.status == "PASS" and "TEXT.NUMBERS" in rules(r)


# --- Endpoints ------------------------------------------------------------------------------------

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    install_validation_handler(app, extra_prefixes=(PREFIX,))
    app.state.risk_compliance = service()
    return TestClient(app)


def test_health_and_policy_endpoints(client):
    assert client.get(f"{PREFIX}/health").json()["policy_version"] == load_policy().version
    body = client.get(f"{PREFIX}/policy").json()
    assert "_notice" in body and set(RULE_IDS) <= set(body["rules"])


def test_readiness_and_pack_endpoints_return_reports(client):
    r = client.post(f"{PREFIX}/readiness", json=json.loads(readiness_request().model_dump_json()))
    assert r.status_code == 200 and r.json()["status"] == "PASS"
    r = client.post(f"{PREFIX}/review-pack/check", json=json.loads(pack_request().model_dump_json()))
    assert r.status_code == 200 and r.json()["rm_signoff_allowed"] is True


def test_blocked_report_is_a_200_not_an_error(client):
    body = json.loads(pack_request(gates={}).model_dump_json())
    r = client.post(f"{PREFIX}/review-pack/check", json=body)
    assert r.status_code == 200 and r.json()["status"] == "BLOCKED"


def test_validation_error_does_not_echo_client_data(client):
    body = json.loads(pack_request().model_dump_json())
    body["client_profile"]["investable_assets"] = "SECRET-AMOUNT-123"
    r = client.post(f"{PREFIX}/review-pack/check", json=body)
    assert r.status_code == 422 and "SECRET-AMOUNT-123" not in r.text
