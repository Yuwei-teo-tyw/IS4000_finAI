"""
Product Recommender: shelf, house view, suitability gate, ranking, endpoints.

Offline and deterministic: fixed clock, no LLM, no network. Client fixtures
mirror the five frontend clients (risk limit and IPS part 3 risk data).
"""
import copy
import json
import random
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.portfolio_manager.engine.product_screening import (
    rank_products,
    screen_products,
)
from app.agents.portfolio_manager.engine.profile_assessment import assess_profile
from app.agents.portfolio_manager.schemas.client import ClientProfile
from app.agents.portfolio_manager.schemas.upstream import (
    ProductCandidate,
    UpstreamResult,
)
from app.agents.portfolio_manager.taxonomy import ASSET_CLASS_ORDER
from app.agents.product_recommender import shelf as shelf_mod
from app.agents.product_recommender.config import Settings
from app.agents.product_recommender.house_view import HouseViewError, load_house_view
from app.agents.product_recommender.schemas import RecommendRequest, Shelf, ShelfProduct
from app.agents.product_recommender.service import ProductRecommenderService
from app.agents.product_recommender.suitability import gate
from app.endpoints.portfolio_manager import install_validation_handler
from app.endpoints.product_recommender import PREFIX, router

FIXED_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
TODAY = FIXED_NOW.date()

# riskCategory / riskCap from frontend clients, risk capacity + drawdown from ipsRiskByClient.
CLIENTS = {
    "ser": ("Balanced", 3, "Moderate", 12),
    "dso": ("Conservative", 2, "Moderately low", 6),
    "jfr": ("Aggressive", 5, "High", 30),
    "teo": ("Growth", 4, "Moderately high", 20),
    "sha": ("Moderate", 3, "Moderate", 12),
}


def profile(client_id="ser", **overrides) -> dict:
    cat, cap, capacity, dd = CLIENTS[client_id]
    p = {
        "client_id": client_id, "base_currency": "SGD", "total_aum": 5_000_000, "investable_assets": 5_000_000,
        "risk_appetite": cat, "risk_tolerance_score": cap, "risk_capacity": capacity,
        "maximum_acceptable_drawdown": dd,
        "financial_goals": [{"goal": "Grow wealth", "years_to_goal": 10, "priority": "High", "currency": "SGD"}],
    }
    p.update(overrides)
    return p


def request(client_id="ser", options=None, request_id=None, **overrides) -> RecommendRequest:
    return RecommendRequest.model_validate({"request_id": request_id, "client_id": client_id,
                                            "client_profile": profile(client_id, **overrides), "options": options or {}})


def service(**kw) -> ProductRecommenderService:
    return ProductRecommenderService(settings=Settings(), clock=lambda: FIXED_NOW, **kw)


def shelf_products() -> list[ShelfProduct]:
    return list(shelf_mod.load_shelf().data.products)


def shelf_loader_from(products: list[ShelfProduct]):
    def load() -> UpstreamResult:
        return UpstreamResult(source="MOCK", status="OK", data=Shelf(products=products, is_illustrative=True))
    return load


def gate_for(client_id="ser", products=None, **overrides):
    p = ClientProfile.model_validate(profile(client_id, **overrides))
    a = assess_profile(p, None, TODAY)
    return gate(products or shelf_products(), p, a, TODAY, 90)


def product(**fields) -> ShelfProduct:
    base = shelf_products()[0].model_dump()
    base.update(fields)
    return ShelfProduct.model_validate(base)


# --- Shelf and house view ----------------------------------------------------

def test_shelf_covers_every_asset_class_with_at_least_two_products():
    res = shelf_mod.load_shelf()
    assert res.status in {"OK", "INCOMPLETE"} and res.source == "MOCK"
    classes = [p.asset_class for p in res.data.products]
    for ac in ASSET_CLASS_ORDER:
        assert classes.count(ac.value) >= 2, ac
    assert len({p.product_id for p in res.data.products}) == len(res.data.products)


def test_shelf_drops_a_malformed_product_without_sinking_the_rest():
    raw = shelf_mod.load_raw()
    raw["products"][0]["risk_rating"] = 9
    res = shelf_mod.validate(raw, ShelfProduct, Shelf, "MOCK")
    assert res.status == "INCOMPLETE"
    assert len(res.data.products) == len(raw["products"]) - 1
    assert any(raw["products"][0]["product_id"] in i for i in res.issues)


def test_house_view_has_one_entry_per_asset_class_in_order():
    hv = load_house_view()
    assert [v.asset_class for v in hv.views] == [ac.value for ac in ASSET_CLASS_ORDER]
    assert {v.basis for v in hv.views} <= {"rated", "interpreted", "not_covered"}
    rated = {v.asset_class: v for v in hv.views if v.basis == "rated"}
    assert rated["Fixed income"].cio_term == "Attractive" and rated["Fixed income"].view == "Buy"
    assert rated["Gold"].cio_term == "Neutral" and rated["Gold"].view == "Hold"


def test_house_view_missing_a_class_is_refused(tmp_path):
    raw = json.loads(load_house_view.__globals__["HOUSE_VIEW_PATH"].read_text(encoding="utf-8"))
    raw["views"] = raw["views"][1:]
    path = tmp_path / "hv.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(HouseViewError):
        load_house_view(path)


# --- Suitability gate --------------------------------------------------------

def test_conservative_client_excludes_every_product_above_risk_2():
    result = gate_for("dso")
    for x in result.excluded:
        if x.product.risk_rating and x.product.risk_rating > 2:
            assert x.code in {"RISK_ABOVE_LIMIT", "ELIGIBILITY", "LIQUIDITY"}
    assert all(sp.product.risk_rating <= 2 for sp in result.eligible)
    assert result.eligible


def test_product_at_the_limit_passes_with_a_note():
    result = gate_for("ser", products=[product(risk_rating=3)])
    assert len(result.eligible) == 1
    assert any("at the client's limit" in n for n in result.eligible[0].notes)


def test_missing_risk_rating_is_excluded_not_passed():
    result = gate_for("jfr", products=[product(risk_rating=None)])
    assert [x.code for x in result.excluded] == ["DATA_INVALID"]


def test_unknown_client_risk_level_excludes_with_reason():
    result = gate_for("ser", risk_capacity=None)
    assert result.eligible == []
    assert {x.code for x in result.excluded} <= {"RISK_UNKNOWN", "ELIGIBILITY", "LIQUIDITY", "DATA_INVALID"}
    assert any(x.code == "RISK_UNKNOWN" for x in result.excluded)


def test_single_product_drawdown_is_a_note_by_default_and_an_exclusion_when_configured():
    p = ClientProfile.model_validate(profile("jfr", maximum_acceptable_drawdown=10))
    a = assess_profile(p, None, TODAY)
    deep = [product(risk_rating=4, maximum_drawdown=-33.9)]
    soft = gate(deep, p, a, TODAY, 90)
    assert len(soft.eligible) == 1 and any("diversified portfolio" in n for n in soft.eligible[0].notes)
    hard = gate(deep, p, a, TODAY, 90, drawdown_hard_limit=True)
    assert [x.code for x in hard.excluded] == ["DRAWDOWN"]


def test_near_term_cash_need_excludes_quarterly_dealing_and_long_lock_ins():
    need = {"planned_withdrawals": [{"amount": 100_000, "months_from_now": 6}]}
    quarterly = product(product_id="Q", risk_rating=1, liquidity="QUARTERLY", lock_in_period="none")
    locked = product(product_id="L", risk_rating=1, liquidity="AT_MATURITY", lock_in_period="1 year")
    weekly = product(product_id="W", risk_rating=1, liquidity="WEEKLY", lock_in_period="none")
    result = gate_for("jfr", products=[quarterly, locked, weekly], **need)
    codes = {x.product.product_id: x.code for x in result.excluded}
    assert codes == {"Q": "LIQUIDITY_NEED", "L": "LIQUIDITY_NEED"}
    assert any("Weekly dealing" in n for n in result.eligible[0].notes)


def test_dated_withdrawal_beyond_the_window_does_not_trigger_the_liquidity_need_check():
    far = {"planned_withdrawals": [{"amount": 100_000, "months_from_now": 30}]}
    quarterly = product(product_id="Q", risk_rating=1, liquidity="QUARTERLY", lock_in_period="none")
    assert len(gate_for("jfr", products=[quarterly], **far).eligible) == 1


def test_core_checks_report_codes():
    restricted = gate_for("jfr", restricted_products=["MOCK-EQ-001"])
    assert {x.code for x in restricted.excluded if x.product.product_id == "MOCK-EQ-001"} == {"RESTRICTED"}
    no_fx = gate_for("jfr", maximum_currency_exposure=0)
    assert {x.code for x in no_fx.excluded if x.product.product_id == "MOCK-CASH-003"} == {"CURRENCY"}
    accredited = gate_for("jfr")
    assert {x.code for x in accredited.excluded if x.product.product_id == "MOCK-CORP-003"} == {"ELIGIBILITY"}
    esg = gate_for("jfr", esg_preferences={"level": "Required"})
    assert {x.code for x in esg.excluded if x.product.product_id == "MOCK-EQ-001"} == {"ESG"}
    pref = gate_for("jfr", preferred_asset_classes=["Fixed income"])
    assert {x.code for x in pref.excluded if x.product.product_id == "MOCK-EQ-001"} == {"NOT_PREFERRED"}


def test_pm_screen_does_not_apply_the_per_product_risk_cap():
    # The PM builds diversified portfolios, so a Balanced client still has equity candidates.
    p = ClientProfile.model_validate(profile("ser"))
    a = assess_profile(p, None, TODAY)
    screened = screen_products(shelf_products(), p, a, TODAY, 90)
    assert any(sp.product.risk_rating == 4 for sps in screened.by_class.values() for sp in sps)


# --- Ranking -----------------------------------------------------------------

def _order(resp):
    return [s.product.product_id for s in resp.shortlist] + [e.product_id for e in resp.eligible_not_shortlisted]


@pytest.mark.parametrize("client_id", sorted(CLIENTS))
def test_fees_never_change_the_order(client_id):
    baseline = _order(service().recommend(request(client_id)))
    rng = random.Random(7)
    for _ in range(5):
        products = shelf_products()
        for p in products:
            p.management_fee = round(rng.uniform(0, 3), 2)
            p.transaction_fee = round(rng.uniform(0, 1), 2)
        shuffled = _order(service(shelf_loader=shelf_loader_from(products)).recommend(request(client_id)))
        assert shuffled == baseline


def test_pm_rank_products_ignores_fees():
    p = ClientProfile.model_validate(profile("jfr"))
    a = assess_profile(p, None, TODAY)
    screened = screen_products(shelf_products(), p, a, TODAY, 90)
    for sps in screened.by_class.values():
        before = [sp.product_id for sp in rank_products(sps, "SGD", 0.5, False, 5)]
        changed = copy.deepcopy(sps)
        for i, sp in enumerate(changed):
            sp.product.management_fee = 5.0 - i
        assert [sp.product_id for sp in rank_products(changed, "SGD", 0.5, False, 5)] == before


@pytest.mark.parametrize("client_id", sorted(CLIENTS))
def test_every_product_is_accounted_for_exactly_once(client_id):
    resp = service().recommend(request(client_id))
    ids = _order(resp) + [x.product_id for x in resp.excluded]
    assert sorted(ids) == sorted(p.product_id for p in shelf_products())


def test_same_request_gives_the_same_answer():
    a = service().recommend(request("teo", request_id="PR-1"))
    b = service().recommend(request("teo", request_id="PR-1"))
    assert a.model_dump() == b.model_dump()


def test_house_view_change_moves_products():
    hv = load_house_view()
    sell_fi = hv.model_copy(deep=True)
    for v in sell_fi.views:
        if v.asset_class == "Fixed income":
            v.view, v.confidence = "Sell", "High"
    base = service().recommend(request("ser"))
    moved = service(house_view_loader=lambda: sell_fi).recommend(request("ser"))
    def fi_score(resp):
        items = [(s.product.product_id, s.score.total) for s in resp.shortlist if s.product.asset_class == "Fixed income"]
        items += [(e.product_id, e.total) for e in resp.eligible_not_shortlisted if e.asset_class == "Fixed income"]
        return dict(items)
    before, after = fi_score(base), fi_score(moved)
    assert all(after[k] < before[k] for k in before)


def test_shortlist_respects_top_n_and_per_class_cap():
    resp = service().recommend(request("jfr", options={"top_n": 5, "max_per_asset_class": 1}))
    assert len(resp.shortlist) <= 5
    classes = [s.product.asset_class for s in resp.shortlist]
    assert len(classes) == len(set(classes))
    assert [s.rank for s in resp.shortlist] == list(range(1, len(resp.shortlist) + 1))


def test_shortlist_items_carry_reasons_citations_and_display_only_fees():
    resp = service().recommend(request("ser"))
    assert resp.shortlist
    for s in resp.shortlist:
        assert s.costs.display_only is True
        assert s.reason.source == "deterministic"
        assert all(line.rstrip().endswith("].") for line in s.reason.text.splitlines())
        assert s.product.product_id in s.reason.citations
        assert "fee" not in json.dumps(s.score.model_dump()).lower()


def test_income_goal_sets_the_income_objective():
    goals = [{"goal": "Retirement income", "years_to_goal": 8, "priority": "High", "currency": "SGD"}]
    resp = service().recommend(request("ser", financial_goals=goals))
    assert resp.client_summary.objective == "income"


def test_named_products_report_their_status():
    resp = service().recommend(request("dso", options={"named_products": [
        "MOCK-CASH-001", "Global Equity Index", "MOCK-CORP-003", "No such fund"]}))
    status = {n.query: n.status for n in resp.named_products}
    assert status["Global Equity Index"] == "excluded"
    assert status["MOCK-CORP-003"] == "excluded"
    assert status["No such fund"] == "not_found"
    assert status["MOCK-CASH-001"] in {"shortlisted", "eligible"}


# --- Endpoints ---------------------------------------------------------------

def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    install_validation_handler(app, extra_prefixes=(PREFIX,))
    app.state.product_recommender = service()
    return TestClient(app)


def test_health_shelf_and_house_view_endpoints():
    c = client()
    health = c.get(f"{PREFIX}/health").json()
    assert health["status"] == "ok" and health["shelf_source"] == "MOCK"
    shelf = c.get(f"{PREFIX}/shelf").json()
    assert shelf["fees_display_only"] is True and len(shelf["products"]) == len(shelf_products())
    hv = c.get(f"{PREFIX}/house-view").json()
    assert len(hv["views"]) == 7


def test_recommend_endpoint_returns_a_shortlist():
    body = {"client_id": "teo", "client_profile": profile("teo")}
    r = client().post(f"{PREFIX}/recommend", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["shortlist"] and data["client_summary"]["risk_level"] == 4
    assert data["request_id"].startswith("PR-")


def test_validation_errors_do_not_echo_client_data():
    body = {"client_id": "ser", "client_profile": {**profile("ser"), "total_aum": -987654}}
    r = client().post(f"{PREFIX}/recommend", json=body)
    assert r.status_code == 422
    assert "987654" not in r.text


def test_partial_profile_is_answered_with_missing_information_not_a_422():
    body = {"client_id": "ser", "client_profile": {"client_id": "ser", "risk_appetite": "Balanced"}}
    r = client().post(f"{PREFIX}/recommend", json=body)
    assert r.status_code == 200
    data = r.json()
    assert "risk_capacity" in data["missing_information"]
    assert data["shortlist"] == []


def test_unavailable_shelf_is_a_503():
    def down():
        return UpstreamResult(source="MOCK", status="UNAVAILABLE", issues=["Product shelf could not be read."])
    app = FastAPI()
    app.include_router(router)
    app.state.product_recommender = service(shelf_loader=down)
    r = TestClient(app).post(f"{PREFIX}/recommend", json={"client_id": "ser", "client_profile": profile("ser")})
    assert r.status_code == 503


def test_shelf_products_validate_as_pm_candidates():
    for raw in shelf_mod.load_raw()["products"]:
        ProductCandidate.model_validate(raw)
    assert date.fromisoformat(shelf_mod.load_raw()["as_of_date"]) <= TODAY
