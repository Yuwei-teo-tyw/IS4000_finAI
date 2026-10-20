"""
Portfolio Manager HTTP contract: health, generate, retrieval, request
validation and error handling.
"""
from portfolio_helpers import BASE, GENERATE, assert_reconciles, make_client, mock_products, offered, request_with, sample_request


def test_health():
    r = make_client().get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_generate_sample_request_returns_reconciled_options():
    r = make_client().post(GENERATE, json=sample_request())
    assert r.status_code == 200
    body = r.json()
    assert body["request_id"] == "PM-REQ-001"
    assert body["client_id"] == "CLIENT_001"
    assert body["requires_rm_review"] is True
    assert body["execution_status"] == "NOT_EXECUTED"
    # 400k investable - 30k reserve - 20k near-term withdrawals; emergency
    # fund and minimum reserve are the same money, not double-counted.
    assert body["liquidity_plan"]["eligible_portfolio_value"] == 350000
    assert offered(body)
    for opt in offered(body):
        assert opt["eligible_portfolio_value"] == 350000
        assert_reconciles(opt)
    assert {row["criterion"] for row in body["comparison_matrix"]} >= {
        "Expected return potential (p.a., illustrative)", "Liquidity (share in daily-dealing products)",
        "Alignment with risk appetite", "Alignment with risk capacity", "Expansion / slowdown / recession sensitivity",
    }


def test_generated_proposal_can_be_retrieved():
    client = make_client()
    created = client.post(GENERATE, json=request_with("PM-GET-1")).json()
    r = client.get(f"{BASE}/portfolio/PM-GET-1")
    assert r.status_code == 200
    assert r.json() == created


def test_unknown_request_id_returns_404():
    r = make_client().get(f"{BASE}/portfolio/DOES-NOT-EXIST")
    assert r.status_code == 404


def test_malformed_request_id_in_path_rejected():
    r = make_client().get(f"{BASE}/portfolio/bad id!")
    assert r.status_code in (404, 422)


def test_duplicate_request_id_conflicts():
    client = make_client()
    assert client.post(GENERATE, json=request_with("PM-DUP")).status_code == 200
    assert client.post(GENERATE, json=request_with("PM-DUP")).status_code == 409


def test_request_id_generated_when_omitted():
    req = sample_request()
    req.pop("request_id")
    body = make_client().post(GENERATE, json=req).json()
    assert body["request_id"].startswith("PM-")


def test_client_id_mismatch_rejected():
    req = sample_request()
    req["client_id"] = "CLIENT_999"
    r = make_client().post(GENERATE, json=req)
    assert r.status_code == 422


def test_negative_amount_rejected():
    r = make_client().post(GENERATE, json=request_with(investable_assets=-1))
    assert r.status_code == 422


def test_unknown_field_rejected():
    r = make_client().post(GENERATE, json=request_with(risk_apetite="High"))
    assert r.status_code == 422


def test_out_of_range_score_rejected():
    r = make_client().post(GENERATE, json=request_with(risk_tolerance_score=9))
    assert r.status_code == 422


def test_malformed_json_rejected():
    r = make_client().post(GENERATE, content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_validation_errors_do_not_echo_client_values():
    r = make_client().post(GENERATE, json=request_with(investable_assets=-123456.78))
    assert r.status_code == 422
    assert "123456" not in r.text


def test_response_includes_candidate_shelf_with_screening_outcomes():
    body = make_client().post(GENERATE, json=request_with("PM-CAND")).json()
    cands = {c["product_id"]: c for c in body["candidate_products"]}
    assert len(cands) == len(mock_products()["products"])  # every product on the shared shelf
    assert cands["MOCK-CORP-003"]["screening_status"] == "EXCLUDED"
    assert "accredited" in cands["MOCK-CORP-003"]["exclusion_reason"]
    selected = {s["product_id"] for o in offered(body) for s in o["product_selections"]}
    for pid, c in cands.items():
        assert (c["screening_status"] == "SELECTED") == (pid in selected)
        assert c["data_provenance"] == "ILLUSTRATIVE_MOCK"
    # Product details are passed through as supplied, with null for unknowns.
    assert cands["MOCK-REIT-002"]["details"]["volatility"] is None
    assert cands["MOCK-EQ-001"]["details"]["historical_returns"]["5y"] == 9.4


def test_look_through_exposures_sum_to_100():
    body = make_client().post(GENERATE, json=request_with("PM-LOOK")).json()
    for o in offered(body):
        for key in ("geographic_exposure_pct", "sector_exposure_pct"):
            exposure = o["metrics"][key]
            assert exposure is not None
            assert abs(sum(exposure.values()) - 100) < 0.1


def test_market_summary_follows_market_researcher_output():
    m = make_client().post(GENERATE, json=request_with("PM-MKT")).json()["market_context_summary"]
    assert "illustrative mock" in m["data_source_label"]
    assert m["run_id"].startswith("mr_mock_")
    assert m["regime"]["phase"] == "late_expansion"
    assert m["regime"]["recession_prob_12m"] == 0.1281
    assert {e["id"] for e in m["events"]} >= {"core_inflation_reaccelerating", "fed_raised"}
    assert any(i["id"] == "DGS10" and i["source_url"].startswith("https://fred") for i in m["indicators"])
    assert m["implications"]["duration"]
    # Scenario returns are house assumptions; only recession carries a probability (the researcher's estimate).
    probs = {s["name"]: s["probability"] for s in m["scenario_details"]}
    assert probs == {"Expansion": None, "Slowdown (base)": None, "Recession": 0.1281}
    assert all(s["basis"] == "ASSUMPTION" for s in m["scenario_details"])
    assert "house assumptions" in m["assumptions_label"]
    assert any("publishes no return forecasts" in x for x in m["limitations"])


def test_six_saa_templates_are_exposed_and_evaluated():
    client = make_client()
    templates = client.get(f"{BASE}/templates").json()
    assert [t["option_id"] for t in templates] == list("ABCDEF")
    assert templates[0]["weights"] == {"Cash": 30.0, "Fixed income": 40.0, "Equities": 10.0, "Hedge funds": 5.0,
                                       "Real estate": 5.0, "Gold": 10.0}
    for t in templates:
        assert abs(sum(t["weights"].values()) - 100) < 1e-9
    body = client.post(GENERATE, json=request_with("PM-SIX")).json()
    assert [o["option_id"] for o in body["portfolio_options"]] == list("ABCDEF")
    for row in body["comparison_matrix"]:
        assert set(row["values"]) == set("ABCDEF")