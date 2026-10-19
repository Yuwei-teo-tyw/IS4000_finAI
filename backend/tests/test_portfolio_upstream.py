"""
Upstream data handling: unavailable/incomplete market analysis, missing
product data, malformed products, and making sure mock data is never
presented as verified information.
"""
import copy

from portfolio_helpers import (
    GENERATE,
    make_client,
    make_service,
    market_fetcher_from,
    mock_market,
    mock_products,
    offered,
    option,
    product_fetcher_from,
    request_with,
)


def _post(service, **kw):
    r = make_client(service).post(GENERATE, json=request_with(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def test_market_unavailable_still_builds_but_nominates_nothing():
    body = _post(make_service(market_fetcher=market_fetcher_from(ConnectionError("down"))))
    assert body["data_status"]["market_analysis"] == "UNAVAILABLE"
    assert body["preferred_option"] is None
    assert body["market_context_summary"]["regime"] is None
    # Expected returns come from house assumptions, so they survive; the recession
    # scenario simply has no probability without the Market Researcher.
    b = option(body, "B")
    assert b["expected_portfolio_return"] is not None
    assert all(s["probability"] is None for s in b["scenario_analysis"])
    assert any("Market research unavailable" in w for w in body["warnings"])


def test_degraded_market_research_flagged():
    raw = mock_market()
    raw["regime"]["phase"] = None
    raw["quality"] = {"status": "degraded", "checks": {"completeness": False}, "issues": ["Only 1 growth component available"]}
    raw["data_quality"]["stale_series"] = ["PAYEMS"]
    body = _post(make_service(market_fetcher=market_fetcher_from(raw)))
    assert body["data_status"]["market_analysis"] == "MOCK_INCOMPLETE"
    assert any("degraded" in w and "growth component" in w for w in body["warnings"])
    assert any("could not classify the economic cycle" in w for w in body["warnings"])
    assert any("Stale market series: PAYEMS" in w for w in body["warnings"])


def test_unusable_market_research_is_not_used():
    raw = mock_market()
    raw["quality"] = {"status": "unusable", "checks": {"consistency": False}, "issues": ["Regime inconsistent"]}
    body = _post(make_service(market_fetcher=market_fetcher_from(raw)))
    assert body["data_status"]["market_analysis"] == "UNAVAILABLE"
    assert body["market_context_summary"]["regime"] is None
    assert any("unusable" in w for w in body["warnings"])


def test_recession_signal_trims_growth_ceiling():
    raw = mock_market()
    raw["regime"]["recession_prob_12m"] = 0.62
    base = _post(make_service(), request_id="PM-BASE", risk_appetite="Balanced")
    stressed = _post(make_service(market_fetcher=market_fetcher_from(raw)), request_id="PM-REC", risk_appetite="Balanced")
    def ceiling(body):
        return next(c["limit"] for o in offered(body) for c in o["constraint_checks"]
                    if c["constraint"].startswith("Growth-asset ceiling"))

    assert ceiling(base) - ceiling(stressed) == 10
    assert any("recession probability is 62%" in a for a in stressed["assumptions"])
    for o in offered(stressed):
        assert o["metrics"]["growth_asset_share_pct"] <= ceiling(stressed) + 0.01


def test_market_schema_failure_treated_as_unavailable():
    body = _post(make_service(market_fetcher=market_fetcher_from({"macroeconomic_indicators": "nonsense"})))
    assert body["data_status"]["market_analysis"] == "UNAVAILABLE"


def test_stale_market_data_flagged():
    raw = mock_market()
    raw["as_of"] = "2026-01-01"
    body = _post(make_service(market_fetcher=market_fetcher_from(raw)))
    assert any("Market research is stale" in w for w in body["warnings"])


def test_product_service_unavailable_blocks_construction():
    body = _post(make_service(product_fetcher=product_fetcher_from(TimeoutError())))
    assert body["status"] == "INSUFFICIENT_INFORMATION"
    assert body["data_status"]["product_candidates"] == "UNAVAILABLE"
    assert body["portfolio_options"] == []


def test_malformed_product_dropped_and_reported():
    raw = mock_products()
    raw["products"].append({"product_id": "BROKEN", "volatility": -5})
    body = _post(make_service(product_fetcher=product_fetcher_from(raw)))
    assert any("BROKEN dropped" in w for w in body["warnings"])
    assert offered(body)


def test_missing_product_risk_data_yields_null_metrics_not_guesses():
    raw = mock_products()
    for p in raw["products"]:
        p["maximum_drawdown"] = None
        p["volatility"] = None
    body = _post(make_service(product_fetcher=product_fetcher_from(raw)))
    for o in offered(body):
        assert o["metrics"]["estimated_stress_drawdown_pct"] is None
        assert o["metrics"]["estimated_volatility_pct"] is None
        dd = next(c for c in o["constraint_checks"] if c["constraint"] == "Maximum acceptable drawdown")
        assert dd["status"] == "UNVERIFIED"
    assert body["preferred_option"] is None


def test_missing_fees_yield_null_expected_return():
    raw = mock_products()
    for p in raw["products"]:
        p["management_fee"] = None
    body = _post(make_service(product_fetcher=product_fetcher_from(raw)))
    for o in offered(body):
        assert o["expected_portfolio_return"] is None
        assert o["metrics"]["estimated_annual_fee_pct"] is None


def test_mock_data_never_labelled_as_verified():
    # Even if a mock payload claims to be real/verified, the integration
    # layer's MOCK label wins.
    market = mock_market()
    market["data_quality"]["notes"] = []
    for i in market["indicators"]:
        i["source"] = "FRED (verified)"
    products = mock_products()
    products["is_illustrative"] = False
    for p in products["products"]:
        p["is_illustrative"] = False
        p["product_source"] = "VERIFIED"
    body = _post(make_service(market_fetcher=market_fetcher_from(market),
                              product_fetcher=product_fetcher_from(products)))
    assert body["data_status"]["market_analysis"].startswith("MOCK")
    assert body["data_status"]["product_candidates"].startswith("MOCK")
    assert any("MOCK data, not verified" in w for w in body["warnings"])
    for o in offered(body):
        assert all(s["data_provenance"] == "ILLUSTRATIVE_MOCK" for s in o["product_selections"])
    assert "illustrative mock data" in body["disclaimer"].lower()


def test_default_mock_data_labelled_illustrative_everywhere():
    body = _post(make_service())
    assert body["data_status"]["market_analysis"] == "MOCK"
    assert body["market_context_summary"]["limitations"][0].startswith("Market information is illustrative mock data")
    observed = body["market_context_summary"]["key_observations"]
    assert observed and all(s["basis"] == "OBSERVED_FACT" for s in observed)
    assert all(s["basis"] == "FORECAST" for s in body["market_context_summary"]["forecasts"])


def test_upstream_raw_data_not_mutated_between_requests():
    raw = mock_products()
    snapshot = copy.deepcopy(raw)
    service = make_service(product_fetcher=product_fetcher_from(raw))
    _post(service, request_id="PM-U1")
    _post(service, request_id="PM-U2")
    assert raw == snapshot
