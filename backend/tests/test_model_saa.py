"""
Model SAA libraries and the Portfolio Agent's best-fit recommendation (Longevity, Legacy), the weight check,
and the PM save through /pm-ips. No network, no LLM, no Postgres.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import embeddings
from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.store import Client, DocumentStore, IpsVersion
from app.agents.portfolio_agent.explain.llm_client import LLMUnavailable
from app.agents.portfolio_agent.model_saa import llm_pick as llm_mod
from app.agents.portfolio_agent.model_saa.context import build_context, parse_loss_pct, parse_years
from app.agents.portfolio_agent.model_saa.library import LibraryError, load_library, parse_library
from app.agents.portfolio_agent.model_saa.schemas import WeightCheckRequest
from app.agents.portfolio_agent.model_saa.service import check_saa, recommend_saa
from app.agents.portfolio_agent.model_saa.sources import live_market
from app.endpoints import client_profiling as cp_ep
from app.endpoints import ips_handover
from app.endpoints import portfolio_agent as pa_ep
from conftest import run_async

NO_HOLDINGS = lambda _c: {"available": True, "status": "no_holdings", "holdings": []}  # noqa: E731


def NO_LLM(_settings):
    raise LLMUnavailable("tests never call Groq")


class FakeLLM:
    """Stands in for ChatGroq: with_structured_output(schema).ainvoke(...) returns the queued PickOut."""
    def __init__(self, out):
        self.out, self.calls = out, []

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, msgs):
        self.calls.append(msgs)
        return self.out


def ips(score=2, tolerance="A fall of more than 10% in a single year would make her uncomfortable", horizon="At least ten years",
        approach="safety and steady income", avoids="tobacco", goals=None, targets=None, split=(20, 60, 20)):
    return {
        "riskScore": score,
        "risk": {"fields": {"Risk tolerance (willingness)": tolerance, "Time horizon": horizon, "Liquidity needs": "Keeps a cash reserve",
                            "Risk capacity (ability)": "Large asset base"}},
        "philosophy": {"approach": approach, "avoids": avoids, "investmentPeriod": horizon},
        "goals": [{"key": "returnRequirements", "title": "Return Requirements", "bullets": goals or ["Keep capital safe and earn steady income"]}],
        "targets": targets or [],
        "demographics": {"fields": {"Date of birth / age": "Born on 14 March 1981"}},
        "threeLProportion": {"liquidity": {"pct": split[0]}, "longevity": {"pct": split[1]}, "legacy": {"pct": split[2]}},
    }


class FakeStore:
    def __init__(self, data, aum=10_000_000, risk_cap=None, sent=False):
        self.client = Client(id="c1", name="Test", surname="Client", aum_sgd=aum, risk_cap=risk_cap)
        self.v = IpsVersion(client_id="c1", version=1, status="Draft", issued_on="2026-10-01", data=data)
        self.sent = sent

    def get_client(self, cid):
        return self.client if cid == "c1" else None

    def get_ips_send(self, cid):
        return {"version": 1, "status": "Sent to PM", "snapshot": {"data": self.v.data}} if self.sent else None

    def get_ips_versions(self, cid):
        return [self.v]

    def latest_ips(self, cid):
        return self.v, False

    def get_pm_working(self, cid):
        return None


def rec(store, bucket="longevity", registry=None, llm_factory=NO_LLM):
    return run_async(recommend_saa("c1", bucket, market_registry=registry, store=store, portfolio_loader=NO_HOLDINGS, llm_factory=llm_factory))


# --- library ------------------------------------------------------------------------------------------------------

def test_library_is_valid_and_separate_per_bucket():
    lib = load_library()
    lon, leg = lib.bucket("longevity").models, lib.bucket("legacy").models
    assert lon and leg
    assert not {m.id for m in lon} & {m.id for m in leg}
    for m in lon + leg:
        assert abs(sum(m.weights.values()) - 100) < 0.01
        assert set(m.weights) <= set(lib.asset_classes)


def test_library_rejects_bad_weights():
    raw = json.loads(load_library.__wrapped__().model_dump_json())
    raw["buckets"]["longevity"]["models"][0]["weights"]["Cash"] += 1
    with pytest.raises(LibraryError, match="add to"):
        parse_library(raw)


def test_library_rejects_model_above_its_growth_cap():
    raw = json.loads(load_library.__wrapped__().model_dump_json())
    m = raw["buckets"]["legacy"]["models"][0]
    m["weights"] = {"Equities": 90, "Cash": 10}
    with pytest.raises(LibraryError, match="growth cap"):
        parse_library(raw)


# --- parsing --------------------------------------------------------------------------------------------------------

def test_parsers_read_only_explicit_numbers():
    assert parse_years("At least ten years") == 10
    assert parse_years("8 years") == 8
    assert parse_years("long term") is None
    assert parse_loss_pct("A fall of more than 10% in a single year") == 10
    assert parse_loss_pct("Wants 10% income") is None


def test_context_comes_from_the_ips_and_lists_missing_fields():
    ctx = build_context("c1", store=FakeStore(ips(tolerance="", approach="")), portfolio_loader=NO_HOLDINGS)
    assert ctx.risk_level == 2 and ctx.horizon_years == 10 and ctx.total_wealth == 10_000_000
    assert ctx.three_l["longevity"].amount == 6_000_000
    assert "Risk tolerance (willingness)" in ctx.missing and "Investment approach" in ctx.missing
    assert all(f.source for f in ctx.facts)


def test_product_risk_limit_caps_the_risk_level():
    ctx = build_context("c1", store=FakeStore(ips(score=5), risk_cap=3), portfolio_loader=NO_HOLDINGS)
    assert ctx.risk_level == 3 and "capped" in ctx.risk_level_basis


def test_unknown_client_raises():
    with pytest.raises(LookupError):
        build_context("nobody", store=FakeStore(ips()), portfolio_loader=NO_HOLDINGS)


# --- recommendation -------------------------------------------------------------------------------------------------

def test_conservative_client_gets_a_low_risk_model_with_reasons():
    r = rec(FakeStore(ips(score=2)))
    assert r.recommendation is not None
    best = r.recommendation
    assert next(e for e in r.evaluations if e.model_id == best.model_id).risk_level <= 2
    assert best.reasons and best.client_factors and best.risks
    assert all(not e.suitable for e in r.evaluations if e.risk_level > 2)
    assert all(e.unsuitable_reasons for e in r.evaluations if not e.suitable)


def test_recommendations_differ_by_client_profile():
    cautious = rec(FakeStore(ips(score=1, horizon="5 years", tolerance="A fall of more than 5% would worry her")))
    bold = rec(FakeStore(ips(score=5, horizon="25 years", tolerance="Can accept a fall of 30%", approach="long-term growth",
                             goals=["Grow wealth aggressively for retirement"])))
    assert cautious.recommendation.model_id != bold.recommendation.model_id
    risk = {e.model_id: e.risk_level for e in bold.evaluations}
    assert risk[bold.recommendation.model_id] > risk[cautious.recommendation.model_id]


def test_longevity_and_legacy_are_evaluated_separately():
    s = FakeStore(ips(score=3, horizon="12 years"))
    lon, leg = rec(s, "longevity"), rec(s, "legacy")
    assert {e.model_id[:3] for e in lon.evaluations} == {"LON"}
    assert {e.model_id[:3] for e in leg.evaluations} == {"LEG"}
    assert "transfer" in leg.objectives and "transfer" not in lon.objectives


def test_legacy_is_not_assumed_more_aggressive():
    s = FakeStore(ips(score=2, horizon="30 years"))
    leg = rec(s, "legacy")
    assert next(e for e in leg.evaluations if e.model_id == leg.recommendation.model_id).risk_level <= 2


def test_no_model_suits_short_horizon_legacy():
    r = rec(FakeStore(ips(score=1, horizon="2 years")), "legacy")
    assert r.recommendation is None and "No model" in r.no_recommendation_reason


def test_no_ips_means_no_recommendation_even_with_a_book_risk_limit():
    s = FakeStore({}, risk_cap=3)
    s.latest_ips = lambda cid: (None, False)
    r = rec(s)
    assert r.recommendation is None and "no completed IPS" in r.no_recommendation_reason
    assert "IPS (no IPS saved for this client)" in r.client.missing


def test_alternatives_explain_why_they_rank_lower():
    r = rec(FakeStore(ips(score=4, horizon="15 years")))
    assert r.recommendation.alternatives
    assert all(a.why_not and a.score <= r.recommendation.score for a in r.recommendation.alternatives)


def test_excluded_asset_class_is_removed_from_the_agent_weights():
    r = rec(FakeStore(ips(score=5, horizon="25 years", avoids="hedge funds and private equity", approach="growth")))
    w = r.recommendation.recommended_weights
    assert "Hedge funds" not in w and "Private markets" not in w
    assert abs(sum(w.values()) - 100) < 0.01
    assert r.recommendation.weight_adjustments


def test_market_is_unavailable_without_a_run_and_never_mocked():
    r = rec(FakeStore(ips()))
    assert r.market.status == "UNAVAILABLE" and r.market.issues
    assert r.data_status["market"] == "UNAVAILABLE"
    assert any("unavailable" in x.lower() for x in r.recommendation.market_considerations)


def test_market_reads_the_latest_finished_run(tmp_path):
    from app.agents.portfolio_agent.upstream.market_analysis import _MOCK_PATH
    out = json.loads(_MOCK_PATH.read_text(encoding="utf-8"))
    p = tmp_path / "run.json"
    p.write_text(json.dumps(out), encoding="utf-8")

    class Reg:
        async def latest_success(self, region, since):
            return SimpleNamespace(run_id="mr_test", json_path=str(p), finished_at=datetime.now(timezone.utc))
    m = run_async(live_market(Reg()))
    assert m.status == "OK" and m.run_id == "mr_test" and m.regime_phase and m.as_of and m.retrieved_at
    r = rec(FakeStore(ips()), registry=Reg())
    assert any("did not change the ranking" in x for x in r.recommendation.market_considerations)


def test_products_come_from_the_shelf_within_the_risk_level():
    r = rec(FakeStore(ips(score=2)))
    assert r.products.source == "Product Specialist Agent"
    for items in r.products.by_asset_class.values():
        assert all(p.risk_rating is None or p.risk_rating <= 2 for p in items)


# --- weight check ---------------------------------------------------------------------------------------------------

def test_check_flags_total_growth_cap_and_exclusions():
    s = FakeStore(ips(score=2, avoids="gold"))
    ok = check_saa("c1", WeightCheckRequest(bucket="longevity", model_id="LON-2", weights={"Cash": 5, "Fixed income": 67, "Equities": 23, "Real estate": 5}), store=s)
    assert ok.valid and ok.amounts["Equities"] == pytest.approx(6_000_000 * 0.23)
    bad = check_saa("c1", WeightCheckRequest(bucket="longevity", model_id="LON-2", weights={"Equities": 60, "Gold": 30, "Cash": 5}), store=s)
    fails = {c.id for c in bad.checks if c.status == "FAIL"}
    assert not bad.valid and {"total", "growth_cap", "restrictions"} <= fails


# --- endpoints and PM save ------------------------------------------------------------------------------------------

app = FastAPI()
app.include_router(pa_ep.router)
app.include_router(cp_ep.router)
app.include_router(ips_handover.router)
PA, CP = "/agents/portfolio-agent", "/agents/client-profiling"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(llm_mod, "get_llm", NO_LLM)
    monkeypatch.setattr(embeddings, "embed_documents", lambda texts: [[0.0] * 768 for _ in texts])
    monkeypatch.setattr(store_mod, "_default", DocumentStore())
    import app.agents.client_portfolio.service as cps
    monkeypatch.setattr(cps, "get_client_portfolio", NO_HOLDINGS)
    c = TestClient(app)
    r = c.post(f"{CP}/ips/jft", json={"data": ips(score=3, horizon="12 years"), "status": "Draft"})
    assert r.status_code == 200, r.text
    assert c.post(f"{CP}/ips-send/jft", json={"version": r.json()["ips"]["version"]}).status_code == 200
    return c


def test_endpoints_recommend_check_and_library(api):
    lib = api.get(f"{PA}/model-saa?bucket=legacy").json()
    assert lib["models"] and all(m["id"].startswith("LEG") for m in lib["models"])
    r = api.get(f"{PA}/clients/jft/saa-recommendation?bucket=longevity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_id"] == "jft" and body["client"]["ips_basis"].startswith("IPS v")
    assert api.get(f"{PA}/clients/nobody/saa-recommendation?bucket=longevity").status_code == 404
    assert api.get(f"{PA}/clients/jft/saa-recommendation?bucket=liquidity").status_code == 422
    chk = api.post(f"{PA}/clients/jft/saa-check", json={"bucket": "longevity", "model_id": "LON-3", "weights": {"Equities": 50}})
    assert chk.status_code == 200 and not chk.json()["valid"]


def test_pm_saves_model_saa_independently_and_it_reaches_the_ips(api):
    lon = api.get(f"{PA}/clients/jft/saa-recommendation?bucket=longevity").json()["recommendation"]
    leg = api.get(f"{PA}/clients/jft/saa-recommendation?bucket=legacy").json()["recommendation"]
    amended = dict(lon["recommended_weights"])
    k = max(amended, key=amended.get)
    amended[k] -= 2
    amended["Cash"] = amended.get("Cash", 0) + 2
    r = api.put(f"{CP}/pm-ips/jft", json={"saa": {"longevity": {"modelId": lon["model_id"], "recommendedModelId": lon["model_id"],
                                                               "recommendedWeights": lon["recommended_weights"], "weights": amended}}})
    assert r.status_code == 200, r.text
    w = r.json()["saa"]
    assert w["longevity"]["modelId"] == lon["model_id"] and w["longevity"]["weights"]["Cash"] == amended["Cash"]
    assert w["legacy"].get("modelId") is None  # Legacy untouched
    # A different model than recommended needs a reason.
    other = next(e for e in api.get(f"{PA}/clients/jft/saa-recommendation?bucket=legacy").json()["evaluations"]
                 if e["suitable"] and e["model_id"] != leg["model_id"])
    bad = api.put(f"{CP}/pm-ips/jft", json={"saa": {"legacy": {"modelId": other["model_id"], "recommendedModelId": leg["model_id"]}}})
    assert bad.status_code == 422 and "reason" in bad.json()["detail"]
    ok = api.put(f"{CP}/pm-ips/jft", json={"saa": {"legacy": {"modelId": other["model_id"], "recommendedModelId": leg["model_id"],
                                                              "overrideReason": "Client prefers more income"}}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["saa"]["longevity"]["weights"]["Cash"] == amended["Cash"]  # Longevity unchanged by the Legacy save
    # Failing weights are refused server-side.
    assert api.put(f"{CP}/pm-ips/jft", json={"saa": {"longevity": {"modelId": lon["model_id"], "weights": {"Equities": 100}}}}).status_code == 422
    ret = api.post(f"{CP}/pm-ips/jft/return")
    assert ret.status_code == 200, ret.text
    saa = ret.json()["ips"]["data"]["saa"]
    assert saa["longevity"]["modelId"] == lon["model_id"] and saa["longevity"]["weights"]["Cash"] == amended["Cash"]
    assert saa["legacy"]["overrideReason"] == "Client prefers more income"


# --- LLM pick -------------------------------------------------------------------------------------------------------

def _bold():
    return FakeStore(ips(score=4, horizon="15 years", tolerance="Can accept a fall of 25%", approach="growth and income"))


def test_llm_chooses_among_suitable_models_and_explains():
    base = rec(_bold())
    suitable = [e.model_id for e in base.evaluations if e.suitable]
    other = next(m for m in suitable if m != base.recommendation.model_id)
    out = llm_mod.PickOut(model_id=other, summary="It balances income and growth for this client.",
                          reasons=["Its objectives match the client.", "The horizon is long enough."], risks=["Equity markets can fall."],
                          alternatives=[llm_mod._AltOut(model_id=base.recommendation.model_id, why_not=["It takes more risk than needed."])])
    fake = FakeLLM(out)
    r = rec(_bold(), llm_factory=lambda _s: fake)
    assert r.recommendation.decided_by == "llm" and r.recommendation.model_id == other
    assert r.recommendation.summary.startswith("It balances")
    assert any(a.why_not == ["It takes more risk than needed."] for a in r.recommendation.alternatives)
    sent = str(fake.calls[0])
    assert "Test Client" not in sent and "<suitable_models>" in sent  # no client name; data in tags


def test_llm_choosing_an_unsuitable_model_falls_back_to_the_scored_pick():
    base = rec(_bold())
    bad = next(e.model_id for e in base.evaluations if not e.suitable)
    r = rec(_bold(), llm_factory=lambda _s: FakeLLM(llm_mod.PickOut(model_id=bad, summary="x", reasons=["y"])))
    assert r.recommendation.decided_by == "rules" and r.recommendation.model_id == base.recommendation.model_id
    assert "not a suitable model" in r.recommendation.llm_note


def test_llm_inventing_a_number_or_a_guarantee_falls_back():
    base = rec(_bold())
    mid = base.recommendation.model_id
    for txt in ("It will return 12.3% a year.", "Returns are guaranteed."):
        r = rec(_bold(), llm_factory=lambda _s, t=txt: FakeLLM(llm_mod.PickOut(model_id=mid, summary=t, reasons=["Fits the client."])))
        assert r.recommendation.decided_by == "rules" and "guardrails" in r.recommendation.llm_note


def test_llm_unavailable_keeps_the_scored_pick_and_says_why():
    r = rec(_bold())
    assert r.recommendation.decided_by == "rules" and "LLM not used" in r.recommendation.llm_note


def test_llm_may_quote_a_scaled_amount_from_the_client_profile():
    s = FakeStore(ips(score=4, horizon="15 years", approach="growth", targets=[{"text": "reach 700M within 15 years", "amount": 700_000_000, "horizonYears": 15}]))
    mid = rec(s).recommendation.model_id
    r = rec(s, llm_factory=lambda _s: FakeLLM(llm_mod.PickOut(model_id=mid, summary="It supports the target of 700 M.", reasons=["Fits the client."])))
    assert r.recommendation.decided_by == "llm", r.recommendation.llm_note


def test_llm_inventing_a_client_limit_from_the_loss_tolerance_falls_back():
    # The live failure: "a fall of more than 10%" (loss tolerance) restated as "a limit of up to 10% equities".
    s = FakeStore(ips(score=4, horizon="15 years", approach="growth"))
    mid = rec(s).recommendation.model_id
    r = rec(s, llm_factory=lambda _s: FakeLLM(llm_mod.PickOut(model_id=mid, summary="Fits.", reasons=["Equities match the client's limit of up to 10% blue-chip equities."])))
    assert r.recommendation.decided_by == "rules" and "unsupported client limit" in r.recommendation.llm_note
    assert llm_mod.unsupported_limits("within the client's cap of 20% equities", "Restrictions: no more than 20% in equities") == []


def test_stated_caps_and_goal_exclusions_are_hard_constraints():
    goal = "Prefers government bonds; up to 10% blue‑chip equities; excludes hedge funds, private markets, tobacco"
    s = FakeStore(ips(score=3, horizon="12 years", goals=[goal]))
    ctx = build_context("c1", store=s, portfolio_loader=NO_HOLDINGS)
    assert ctx.asset_class_caps == {"Equities": 10.0}
    assert {"Hedge funds", "Private markets"} <= set(ctx.excluded_asset_classes)
    r = rec(s)
    assert all(e.weights.get("Equities", 0) <= 10 for e in r.evaluations if e.suitable)
    assert any("stated maximum" in x for e in r.evaluations for x in e.unsuitable_reasons)
    bad = check_saa("c1", WeightCheckRequest(bucket="longevity", model_id="LON-1", weights={"Fixed income": 75, "Equities": 20, "Cash": 5}), store=s)
    assert not bad.valid and any(c.id == "caps" and c.status == "FAIL" for c in bad.checks)
