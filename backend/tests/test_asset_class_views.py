"""
Asset-class views: the agent's own Buy/Hold/Sell view beside the CIO's.

Offline: the market data is the PM's illustrative Market Researcher mock
(optionally edited per test), run through the real validation.
"""
import asyncio
import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from portfolio_helpers import market_fetcher_from, mock_market
from test_product_recommender import FIXED_NOW, profile, service

from app.agents.portfolio_agent.engine.profile_assessment import assess_profile
from app.agents.portfolio_agent.schemas.client import ClientProfile
from app.agents.portfolio_agent.taxonomy import ASSET_CLASS_ORDER, AssetClass
from app.agents.product_recommender.asset_views import config as cfg
from app.agents.product_recommender.asset_views.scoring import combine
from app.agents.product_recommender.asset_views.shelf_lens import in_class
from app.agents.product_recommender.house_view import load_house_view
from app.agents.product_recommender.shelf import load_shelf
from app.agents.product_recommender.suitability import gate
from app.endpoints.portfolio_agent import install_validation_handler
from app.endpoints.product_recommender import PREFIX, router

CLASSES = [ac.value for ac in ASSET_CLASS_ORDER]


def view(ac: str, market: dict | None = None, **kw):
    svc = service(market_fetcher=market_fetcher_from(market if market is not None else mock_market()), **kw)
    return asyncio.run(svc.asset_class_view(ac))


def recompute(v) -> float:
    regime_w = cfg.REGIME_WEIGHT * cfg.REGIME_CONFIDENCE[v.agent_view.regime.confidence] if v.agent_view.regime.tilt is not None else 0.0
    num = sum(s.weight * s.contribution for s in v.snapshot) + regime_w * (v.agent_view.regime.tilt or 0.0)
    den = sum(s.weight for s in v.snapshot) + regime_w
    return num / den


@pytest.mark.parametrize("ac", CLASSES)
def test_cio_view_is_reported_exactly_as_curated(ac):
    assert view(ac).cio_view == load_house_view().for_class(ac)


@pytest.mark.parametrize("ac", CLASSES)
def test_agent_stance_can_be_recomputed_from_the_snapshot(ac):
    v = view(ac)
    assert v.agent_view.label == "Agent view (analysis, not the CIO house view)"
    a = v.agent_view
    assert recompute(v) == pytest.approx(a.data_score, abs=0.002)
    assert a.cio_anchor == cfg.CIO_ANCHOR[v.cio_view.view]
    if not a.insufficient_evidence:
        assert a.score == pytest.approx(a.cio_share * a.cio_anchor + (1 - a.cio_share) * a.data_score, abs=0.002)
        assert a.view == combine(a.data_score, v.cio_view.view)[1]


@pytest.mark.parametrize("ac", CLASSES)
def test_a_supportive_move_never_lowers_the_score(ac):
    base = view(ac)
    spec = cfg.SPECS[AssetClass(ac)]
    sig = next((s for s in spec.signals if s.basis == "change" and s.vs is None), None)
    if sig is None:
        pytest.skip("no change-based signal for this class")
    market = mock_market()
    for group in ("indicators", "market_snapshot"):
        for ind in market[group]:
            if ind["id"] == sig.id:
                ind["changes"]["3m"] = ind["changes"].get("3m", 0) + sig.direction * sig.scale / 2
    assert view(ac, market).agent_view.score >= base.agent_view.score


@pytest.mark.parametrize("cio", ["Buy", "Hold", "Sell"])
@pytest.mark.parametrize("ac", ["Cash", "Fixed income", "Real estate"])  # agent reads Buy, Hold and Sell on the mock
def test_agreement_covers_every_combination(ac, cio):
    hv = load_house_view()
    for entry in hv.views:
        if entry.asset_class == ac:
            entry.view = cio
    v = view(ac, house_view_loader=lambda: hv)
    order = {"Sell": 0, "Hold": 1, "Buy": 2}
    gap = abs(order[cio] - order[v.agent_view.view])
    assert v.agreement.status == {0: "aligned", 1: "differs", 2: "opposed"}[gap]
    if gap:
        assert v.agreement.explanation and hv.for_class(ac).citation_id in v.agreement.explanation
        assert any(hv.for_class(ac).citation_id in r.refs for r in v.risks)
    else:
        assert v.agreement.explanation is None


@pytest.mark.parametrize("ac", CLASSES)
def test_segments_are_consistent_and_honest_about_missing_data(ac):
    v = view(ac)
    scored = [s for s in v.segments if s.score is not None]
    if v.agent_view.view == "Sell" and scored:
        assert not all(s.view == "Most preferred" for s in scored)
    if v.agent_view.view == "Buy" and scored:
        assert not all(s.view == "Least preferred" for s in scored)
    for s in v.segments:
        if s.score is None:
            assert s.view == "Neutral" and s.reason
        if "SGD" in s.segment or "Singapore" in s.segment:
            assert s.view == "Neutral" and "No SGD/Asia data" in s.reason


def test_low_coverage_classes_are_capped_at_low_confidence():
    for ac in ("Hedge funds", "Private markets"):
        v = view(ac)
        assert v.agent_view.confidence == "Low"
        assert any("capped at Low" in c for c in v.caveats)


def test_too_little_data_keeps_the_cio_view_one_step_less_sure():
    market = mock_market()
    keep = {"DGS10"}
    market["indicators"] = [i for i in market["indicators"] if i["id"] in keep]
    market["market_snapshot"] = []
    v = view("Fixed income", market)
    a, cio = v.agent_view, v.cio_view
    assert (a.view, a.insufficient_evidence, a.basis, a.cio_adjustment) == (cio.view, True, "cio_only", "unchanged")
    assert a.confidence == {"High": "Medium", "Medium": "Low", "Low": "Low"}[cio.confidence]
    assert any("Insufficient evidence" in c for c in v.caveats)


def test_market_researcher_unavailable_gives_the_cio_view_as_the_agent_view():
    v = asyncio.run(service(market_fetcher=market_fetcher_from(RuntimeError("down"))).asset_class_view("Equities"))
    a = v.agent_view
    assert (a.view, a.basis, a.insufficient_evidence) == (v.cio_view.view, "cio_only", True)
    assert v.agent_view_unavailable_reason and v.agreement.status == "aligned"
    assert v.narrative_source == "deterministic"
    assert v.cio_view.asset_class == "Equities"
    assert v.implementation.products


@pytest.mark.parametrize("cio", ["Buy", "Hold", "Sell"])
@pytest.mark.parametrize("data", [-1.0, -0.6, -0.3, 0.0, 0.3, 0.6, 1.0])
def test_agent_view_never_moves_more_than_one_step_from_the_cio(cio, data):
    order = ["Sell", "Hold", "Buy"]
    _, agent = combine(data, cio)
    assert abs(order.index(agent) - order.index(cio)) <= 1


def test_market_data_softens_or_moves_the_cio_view():
    assert combine(-1.0, "Buy")[1] == "Hold"   # softened, never flipped to Sell
    assert combine(1.0, "Sell")[1] == "Hold"
    assert combine(0.0, "Buy")[1] == "Buy"     # neutral data keeps the CIO view
    assert combine(0.6, "Hold")[1] == "Buy"    # strong data can move a Hold
    assert combine(-0.6, "Hold")[1] == "Sell"
    assert combine(0.2, "Hold")[1] == "Hold"   # weak data cannot


@pytest.mark.parametrize("cio", ["Buy", "Hold", "Sell"])
@pytest.mark.parametrize("ac", CLASSES)
def test_agent_view_is_anchored_on_the_cio_view_end_to_end(ac, cio):
    hv = load_house_view()
    for entry in hv.views:
        if entry.asset_class == ac:
            entry.view = cio
    a = view(ac, house_view_loader=lambda: hv).agent_view
    order = ["Sell", "Hold", "Buy"]
    assert abs(order.index(a.view) - order.index(cio)) <= 1
    assert a.cio_adjustment == ("unchanged" if a.view == cio else "softened" if cio != "Hold"
                                else "upgraded" if a.view == "Buy" else "downgraded")
    assert "CIO" in a.thesis


@pytest.mark.parametrize("ac", CLASSES)
def test_scenarios_watch_items_and_caveats_are_grounded(ac):
    v = view(ac)
    ids = {s.id for s in v.snapshot}
    for sc in v.scenarios:
        if sc.trigger:
            assert sc.trigger.indicator in ids
    for ref in [*v.drivers, *v.risks, *v.watch_items, *v.agent_view.thesis_points]:
        assert ref.refs
    assert any("US-only" in c for c in v.caveats)
    assert any("mock" in c for c in v.caveats)
    assert v.implementation.fees.display_only is True


@pytest.mark.parametrize("ac", CLASSES)
def test_every_shelf_product_in_the_class_maps_to_one_segment(ac):
    v = view(ac)
    shelf = load_shelf().data.products
    expected = sorted(p.product_id for p in in_class(AssetClass(ac), shelf))
    assert sorted(p.product_id for p in v.implementation.products) == expected
    assert all(p.segment for p in v.implementation.products)


def test_client_lens_matches_the_suitability_gate():
    p = ClientProfile.model_validate(profile("dso"))
    svc = service(market_fetcher=market_fetcher_from(mock_market()))
    v = asyncio.run(svc.asset_class_view("equities", "dso", p))
    products = in_class(AssetClass.EQUITIES, load_shelf().data.products)
    a = assess_profile(p, None, FIXED_NOW.date())
    result = gate(products, p, a, a.reference_date, 90)
    assert v.client_lens.eligible == len(result.eligible)
    assert sum(v.client_lens.excluded.values()) == len(result.excluded)
    assert v.client_lens.risk_level == a.effective_level


# --- Endpoints ---------------------------------------------------------------

def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    install_validation_handler(app, extra_prefixes=(PREFIX,))
    app.state.product_recommender = service(market_fetcher=market_fetcher_from(mock_market()))
    return TestClient(app)


def test_list_endpoint_returns_seven_headlines():
    rows = client().get(f"{PREFIX}/asset-class-views").json()
    assert [r["asset_class"] for r in rows] == CLASSES
    assert all(r["agent_view"] in {"Buy", "Hold", "Sell"} for r in rows)


def test_view_endpoints_accept_slugs_and_add_a_client_lens():
    c = client()
    v = c.get(f"{PREFIX}/asset-class-views/fixed-income").json()
    assert v["asset_class"] == "Fixed income" and v["client_lens"] is None
    body = {"client_id": "teo", "client_profile": profile("teo")}
    v2 = c.post(f"{PREFIX}/asset-class-views/Equities", json=body).json()
    assert v2["client_lens"]["client_id"] == "teo"


def test_unknown_asset_class_is_404_and_bad_profile_is_not_echoed():
    c = client()
    assert c.get(f"{PREFIX}/asset-class-views/crypto").status_code == 404
    body = {"client_id": "teo", "client_profile": {**profile("teo"), "total_aum": -4242}}
    r = c.post(f"{PREFIX}/asset-class-views/equities", json=body)
    assert r.status_code == 422 and "4242" not in r.text


def test_market_mock_is_still_valid_for_the_pm():
    raw = copy.deepcopy(mock_market())
    assert json.loads(json.dumps(raw))["region"] == "US"
