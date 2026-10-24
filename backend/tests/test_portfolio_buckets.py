"""
3L buckets: each bucket's SAA follows its own purpose, horizon and risk level, and the combined
review checks the three together. No network, no LLM.
"""
import pytest

from portfolio_helpers import BASE, GENERATE, make_client, request_with

OFFERED = ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS")
GROWTH = {"Equities", "Hedge funds", "Private markets"}
COMBINED = f"{BASE}/portfolio/combined"


@pytest.fixture
def client():
    return make_client()


def gen(client, rid, bucket, amount, horizon=None, risk=None, total=1_000_000, goals=None, **profile):
    req = request_with(rid, **profile)
    if goals is not None:
        req["client_profile"]["financial_goals"] = goals
    req["bucket"] = {"bucket": bucket, "amount": amount, "horizon_years": horizon,
                     "risk_tolerance_score": risk, "total_3l_amount": total}
    r = client.post(GENERATE, json=req)
    assert r.status_code == 200, r.text
    return r.json()


def offered(p):
    return [o for o in p["portfolio_options"] if o["suitability_status"] in OFFERED]


def classes(o):
    return {a["asset_class"] for a in o["asset_allocation"]}


def growth(o):
    return o["metrics"]["growth_asset_share_pct"]


HIGH_RISK = dict(risk_appetite="Growth", risk_tolerance_score=4, risk_capacity="High", maximum_acceptable_drawdown=30)


# --- Liquidity ----------------------------------------------------------------------

def test_liquidity_bucket_holds_only_cash_and_short_bonds(client):
    p = gen(client, "LIQ-1", "liquidity", 150_000, horizon=1, goals=[], **HIGH_RISK)
    assert p["bucket"]["bucket"] == "liquidity"
    assert [t.split(" · ")[1] for t in p["bucket"]["templates_considered"]] == ["Cash reserve", "Cash and short bonds", "Short-term income"]
    assert offered(p)
    for o in offered(p):
        assert classes(o) <= {"Cash", "Fixed income"}
        assert growth(o) == 0
        for s in o["product_selections"]:
            assert s["details"]["recommended_horizon"] is None or s["details"]["recommended_horizon"] <= 1


def test_liquidity_bucket_excludes_products_it_could_not_get_back_in_time(client):
    p = gen(client, "LIQ-2", "liquidity", 150_000, horizon=1, goals=[])
    reasons = {e["product_id"]: e["reason"] for e in p["excluded_products"]}
    assert "Liquidity bucket" in reasons["MOCK-GOVT-001"]  # 3-year recommended holding period
    assert "Liquidity bucket" in reasons["MOCK-EQ-002"]


def test_liquidity_horizon_is_capped_at_three_years(client):
    p = gen(client, "LIQ-3", "liquidity", 150_000, horizon=10, goals=[])
    assert p["bucket"]["horizon_years"] == 3
    assert any("3 is used" in n["statement"] for n in p["bucket"]["notes"])


def test_whole_bucket_amount_is_invested_with_no_second_reserve_carve_out(client):
    p = gen(client, "LIQ-4", "liquidity", 150_000, horizon=2, goals=[])
    assert p["liquidity_plan"]["eligible_portfolio_value"] == 150_000
    assert p["liquidity_plan"]["reserve_carved_out"] == 0
    for o in offered(p):
        assert round(sum(a["investment_amount"] for a in o["asset_allocation"])) == 150_000


# --- Longevity / Legacy: horizon and risk drive the options -----------------------------

def test_long_horizon_retirement_bucket_gets_growth_options(client):
    p = gen(client, "LON-1", "longevity", 600_000, horizon=20, **HIGH_RISK)
    ids = {o["option_id"] for o in offered(p)}
    assert ids & {"D", "E"}, ids
    assert max(growth(o) for o in offered(p)) > 50


def test_legacy_is_not_automatically_the_riskiest(client):
    near = gen(client, "LEG-1", "legacy", 300_000, horizon=4, goals=[], **HIGH_RISK)
    far = gen(client, "LEG-2", "legacy", 300_000, horizon=25, goals=[], **HIGH_RISK)
    assert max(growth(o) for o in offered(near)) <= 30  # medium-horizon cap
    assert max(growth(o) for o in offered(far)) > max(growth(o) for o in offered(near))


def test_legacy_without_horizon_is_cautious_and_says_why(client):
    p = gen(client, "LEG-3", "legacy", 300_000, horizon=None, goals=[], **HIGH_RISK)
    assert p["bucket"]["horizon_years"] is None
    assert "Not set" in p["bucket"]["horizon_basis"]
    assert all(growth(o) <= 30 for o in offered(p))
    not_offered = [o for o in p["portfolio_options"] if o["suitability_status"] not in OFFERED]
    assert any("Legacy bucket's horizon" in o["suitability_explanation"] for o in not_offered)


def test_risk_level_can_differ_by_objective(client):
    cautious = gen(client, "RISK-1", "longevity", 600_000, horizon=20, risk=2, **HIGH_RISK)
    bold = gen(client, "RISK-2", "legacy", 600_000, horizon=20, risk=4, **HIGH_RISK)
    assert cautious["bucket"]["risk_level"] == 2 and bold["bucket"]["risk_level"] == 4
    assert max(growth(o) for o in offered(cautious)) < max(growth(o) for o in offered(bold))


def test_bucket_risk_is_capped_by_capacity_and_flagged_above_appetite(client):
    p = gen(client, "RISK-3", "legacy", 300_000, horizon=25, risk=5)  # sample client: Moderate capacity
    assert p["bucket"]["risk_level"] == 3
    assert "caps it" in p["bucket"]["risk_basis"]
    assert any("above the client's overall risk appetite" in c["description"] for c in p["conflicts"])


def test_missing_information_still_blocks_a_bucket(client):
    p = gen(client, "MISS-1", "longevity", 300_000, horizon=10, risk_capacity=None)
    assert p["status"] == "INSUFFICIENT_INFORMATION"
    assert offered(p) == []


def test_rationale_names_the_bucket_and_its_objective(client):
    p = gen(client, "WHY-1", "longevity", 600_000, horizon=15)
    for o in offered(p):
        assert o["rationale"][0]["statement"].startswith("Built for the Longevity bucket")


def test_templates_endpoint_lists_bucket_templates(client):
    assert [t["name"] for t in client.get(f"{BASE}/templates?bucket=liquidity").json()] == [
        "Cash reserve", "Cash and short bonds", "Short-term income"]
    assert len(client.get(f"{BASE}/templates").json()) == 6


# --- Combined review and isolation -------------------------------------------------------

def three(client, prefix="C", amounts=(100_000, 250_000, 150_000)):
    total = sum(amounts)
    liq = gen(client, f"{prefix}-L", "liquidity", amounts[0], horizon=2, goals=[], total=total, **HIGH_RISK)
    lon = gen(client, f"{prefix}-O", "longevity", amounts[1], horizon=15, total=total, **HIGH_RISK)
    leg = gen(client, f"{prefix}-G", "legacy", amounts[2], horizon=20, goals=[], total=total, **HIGH_RISK)
    return total, [("liquidity", liq), ("longevity", lon), ("legacy", leg)]


def choice(bucket, p, weights=None):
    o = p["preferred_option"] or offered(p)[0]["option_id"]
    return {"bucket": bucket, "request_id": p["request_id"], "option_id": o, "weights": weights}


def test_combined_review_reconciles_and_aggregates(client):
    total, ps = three(client)
    r = client.post(COMBINED, json={"client_total": total, "buckets": [choice(b, p) for b, p in ps]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_amount"] == total
    assert round(sum(c["amount"] for c in body["classes"])) == total
    assert abs(sum(c["pct"] for c in body["classes"]) - 100) < 0.05
    assert [b["bucket"] for b in body["buckets"]] == ["liquidity", "longevity", "legacy"]
    assert body["checks"][0]["status"] == "PASS"
    assert body["execution_status"] == "NOT_EXECUTED"


def test_combined_review_fails_when_buckets_do_not_add_up(client):
    total, ps = three(client, "D")
    body = client.post(COMBINED, json={"client_total": total + 50_000, "buckets": [choice(b, p) for b, p in ps]}).json()
    assert body["checks"][0]["status"] == "FAIL" and body["valid"] is False


def test_editing_one_bucket_does_not_change_the_others(client):
    total, ps = three(client, "E")
    plain = client.post(COMBINED, json={"buckets": [choice(b, p) for b, p in ps]}).json()
    _, lon = ps[1]
    c = choice("longevity", lon)
    o = next(x for x in lon["portfolio_options"] if x["option_id"] == c["option_id"])
    w = {a["asset_class"]: a["allocation_percentage"] for a in o["asset_allocation"]}
    top, low = sorted(w, key=w.get, reverse=True)[:2]
    w[top] -= 3
    w[low] += 3
    edited = client.post(COMBINED, json={"buckets": [choice(*ps[0]), {**c, "weights": w}, choice(*ps[2])]}).json()
    by = lambda body, b: next(x for x in body["buckets"] if x["bucket"] == b)  # noqa: E731
    assert by(edited, "liquidity") == by(plain, "liquidity")
    assert by(edited, "legacy") == by(plain, "legacy")
    assert by(edited, "longevity")["point"] != by(plain, "longevity")["point"]
    # the stored proposals are untouched
    assert client.get(f"{BASE}/portfolio/{lon['request_id']}").json() == lon


def test_combined_review_rejects_mismatches(client):
    total, ps = three(client, "F")
    (_, liq), (_, lon) = ps[0], ps[1]
    dup = client.post(COMBINED, json={"buckets": [choice("liquidity", liq), choice("liquidity", lon)]})
    assert dup.status_code == 422
    wrong = client.post(COMBINED, json={"buckets": [choice("legacy", liq)]})
    assert wrong.status_code == 409 and "Liquidity" in wrong.json()["detail"]
    missing = client.post(COMBINED, json={"buckets": [{"bucket": "legacy", "request_id": "NOPE", "option_id": "A"}]})
    assert missing.status_code == 404
    whole = client.post(GENERATE, json=request_with("WHOLE-1")).json()
    not_bucket = client.post(COMBINED, json={"buckets": [choice("longevity", whole)]})
    assert not_bucket.status_code == 409


def test_combined_review_flags_a_bucket_failing_its_own_checks(client):
    total, ps = three(client, "G")
    _, lon = ps[1]
    c = choice("longevity", lon)
    o = next(x for x in lon["portfolio_options"] if x["option_id"] == c["option_id"])
    w = {a["asset_class"]: a["allocation_percentage"] for a in o["asset_allocation"]}
    w[next(iter(w))] += 20  # breaks 100% and the 5-point band
    body = client.post(COMBINED, json={"buckets": [choice(*ps[0]), {**c, "weights": w}, choice(*ps[2])]}).json()
    assert body["valid"] is False
    assert any(ch["constraint"] == "Every bucket passes its own checks" and ch["status"] == "FAIL" for ch in body["checks"])


def test_liquidity_bucket_carries_no_unhedged_currency_risk(client):
    p = gen(client, "LIQ-FX", "liquidity", 300_000, horizon=1, goals=[])
    for o in offered(p):
        assert o["metrics"]["foreign_currency_exposure_pct"] == 0
    reasons = {e["product_id"]: e["reason"] for e in p["excluded_products"]}
    assert "currency risk" in reasons["MOCK-CASH-003"]  # USD money market fund


def test_single_product_limit_scales_with_the_bucket_share(client):
    small = gen(client, "CAP-1", "liquidity", 100_000, horizon=1, goals=[], total=1_000_000)  # 10% of the 3L
    assert any("single-product limit" in n["statement"] for n in small["bucket"]["notes"])
    assert offered(small)
    whole = gen(client, "CAP-2", "liquidity", 100_000, horizon=1, goals=[], total=None)  # share unknown: client's 30% applies
    assert not any("single-product limit" in n["statement"] for n in whole["bucket"]["notes"])


AGGRESSIVE = dict(risk_appetite="Aggressive", risk_tolerance_score=5, risk_capacity="High", maximum_acceptable_drawdown=40,
                  preferred_asset_classes=None)  # no class restriction, like the clients in the app


def defensive(o):
    return sum(a["allocation_percentage"] for a in o["asset_allocation"] if a["asset_class"] in ("Cash", "Fixed income"))


@pytest.mark.parametrize("bucket", ["longevity", "legacy"])
def test_aggressive_client_gets_no_cash_heavy_long_term_options(client, bucket):
    p = gen(client, f"AGG-{bucket}", bucket, 600_000, horizon=20, **AGGRESSIVE)
    ids = {o["option_id"] for o in offered(p)}
    assert not ids & {"A", "B"}, ids
    assert all(defensive(o) <= 40 for o in offered(p))
    too_cautious = [o for o in p["portfolio_options"] if "Too cautious" in o["suitability_explanation"]]
    assert {o["option_id"] for o in too_cautious} >= {"A", "B"}
    assert all(o["asset_allocation"] == [] for o in too_cautious)


def test_long_term_buckets_hold_little_cash(client):
    p = gen(client, "CASH-1", "longevity", 600_000, horizon=20, **HIGH_RISK)
    for o in offered(p):
        cash = sum(a["allocation_percentage"] for a in o["asset_allocation"] if a["asset_class"] == "Cash")
        assert cash <= 5.01, (o["option_id"], cash)


def test_cautious_client_keeps_cautious_long_term_options(client):
    p = gen(client, "CAUT-1", "longevity", 600_000, horizon=20, risk_appetite="Conservative", risk_tolerance_score=1,
            risk_capacity="Low")
    assert {o["option_id"] for o in offered(p)} & {"A", "B"}
    assert not any("Too cautious" in o["suitability_explanation"] for o in p["portfolio_options"])


def test_short_horizon_legacy_is_not_forced_into_growth(client):
    p = gen(client, "LEG-SHORT", "legacy", 300_000, horizon=4, goals=[], **AGGRESSIVE)
    assert offered(p)
    assert not any("Too cautious" in o["suitability_explanation"] for o in p["portfolio_options"])
