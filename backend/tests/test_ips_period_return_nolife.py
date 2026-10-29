"""IPS changes: Life Events removed, Investment Period in the philosophy, per-strategy rate of return, new section order."""
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling import strategies as strat
from app.agents.client_profiling.alloc_dialogue import _bucket
from app.agents.client_profiling.ips_generate import PHIL_KEYS, SECTION_IDS, generate_ips_section
from app.agents.client_profiling.ips_model import merge_section, new_ips_data, normalize_data, render_parts
from app.agents.client_profiling.strategies import INFLATION_ASSUMPTION_PCT, load_strategies, rate_of_return
from app.agents.client_profiling.store import DocumentStore
from app.endpoints import client_profiling as ep
from ips_helpers import Chat, FakeStore, alloc_payload, note

U = "/agents/client-profiling"
app = FastAPI()
app.include_router(ep.router)
TEMPLATE = re.compile(r"^This portfolio recommendation is designed to generate an average, expected rate of return of "
                      r"(-?\d+\.\d)%–(-?\d+\.\d)% above inflation, net of fees and costs\. Based on current projections, "
                      r"this equates to a current nominal return of (\d+\.\d)%–(\d+\.\d)%\.$")


# --- 3. rate of return -------------------------------------------------------
def test_inflation_constant_documented():
    assert INFLATION_ASSUMPTION_PCT == 2.0


@pytest.mark.parametrize("s", load_strategies(), ids=lambda s: s["code"])
def test_rate_of_return_every_strategy(s):
    r = rate_of_return(s["code"])
    er = s["expected_return_pct"]
    assert set(r) == {"nominalLowPct", "nominalHighPct", "realLowPct", "realHighPct", "inflationPct", "text"}
    assert (r["nominalLowPct"], r["nominalHighPct"]) == (round(er - 0.5, 1), round(er + 0.5, 1))
    assert (r["realLowPct"], r["realHighPct"]) == (round(er - 0.5 - 2.0, 1), round(er + 0.5 - 2.0, 1)) and r["inflationPct"] == 2.0
    if r["realLowPct"] > 0:
        m = TEMPLATE.match(r["text"])
        assert m and m.groups() == (f"{r['realLowPct']:.1f}", f"{r['realHighPct']:.1f}", f"{r['nominalLowPct']:.1f}", f"{r['nominalHighPct']:.1f}")
    assert f"nominal return of {r['nominalLowPct']:.1f}%–{r['nominalHighPct']:.1f}%." in r["text"]


def test_exact_text_strategy_c_and_unknown():
    assert rate_of_return("c")["text"] == (
        "This portfolio recommendation is designed to generate an average, expected rate of return of 1.0%–2.0% above inflation, "
        "net of fees and costs. Based on current projections, this equates to a current nominal return of 3.0%–4.0%.")
    assert rate_of_return("Z") is None and rate_of_return("") is None


def test_wording_when_real_range_not_positive(monkeypatch):
    a = rate_of_return("A")  # nominal 1.5-2.5 -> real -0.5..0.5 straddles 0
    assert "in line with inflation" in a["text"] and "nominal return of 1.5%–2.5%" in a["text"]
    monkeypatch.setattr(strat, "INFLATION_ASSUMPTION_PCT", 5.0)
    lo = strat.rate_of_return("A")
    assert "below inflation" in lo["text"] and "nominal return of 1.5%–2.5%" in lo["text"]


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(store_mod, "_default", DocumentStore())
    return TestClient(app)


def test_strategies_endpoint_rows(api):
    rows = api.get(f"{U}/strategies").json()["strategies"]
    for row in rows:
        r = rate_of_return(row["code"])
        assert row["rateOfReturnText"] == r["text"] and row["nominalLowPct"] == r["nominalLowPct"]
        assert row["realHighPct"] == r["realHighPct"] and row["inflationPct"] == 2.0


def test_generated_allocation_buckets_and_saved_threel_have_rate_of_return():
    res = generate_ips_section(FakeStore([note(1, "2026-10-20", "She is conservative with a long horizon.")], category="Conservative"),
                               "x", "allocation", Chat(alloc_payload(("A", "B", "C"))))
    for b in res["allocation"]["buckets"] + res["threeL"]:
        assert b["rateOfReturn"] == rate_of_return(b["strategy"])["text"]
    d = merge_section(new_ips_data(), res)
    assert all(b["rateOfReturn"] for b in d["threeL"])
    body = {p["part"]: p["body"] for p in render_parts(d)}[2]
    assert all(b["rateOfReturn"] in body for b in d["threeL"])


def test_normalize_recomputes_stale_rate_of_return():
    d = normalize_data({"threeL": [{"portfolio": "Longevity", "strategy": "E", "strategyName": "Growth", "rateOfReturn": "stale"},
                                   {"portfolio": "Legacy", "strategy": "D"}]})
    assert d["threeL"][0]["rateOfReturn"] == rate_of_return("E")["text"] and d["threeL"][1]["rateOfReturn"] == rate_of_return("D")["text"]


def test_discuss_bucket_recomputed_on_strategy_change():
    cur = {"longevity": {"strategy": "C", "justification": ""}}
    assert _bucket("longevity", cur)["rateOfReturn"] == rate_of_return("C")["text"]
    cur["longevity"]["strategy"] = "F"
    assert _bucket("longevity", cur)["rateOfReturn"] == rate_of_return("F")["text"]


def test_override_returns_recomputed_rate_of_return(api):
    r = api.post(f"{U}/ips-allocation/override", json={"clientId": "jft", "portfolio": "Longevity", "from": "C", "to": "F",
                                                       "reason": "client asked"}, headers={"X-RM-Id": "isabel"})
    assert r.status_code == 200, r.text
    assert r.json()["rateOfReturn"] == rate_of_return("F")["text"]


def test_rate_figures_are_allow_listed_for_validators():
    from app.agents.client_profiling.answer import _numbers
    from app.agents.client_profiling.threel import _table_numbers
    assert _numbers(" ".join(rate_of_return(c)["text"] for c in "ABCDEF")) <= _table_numbers()


# --- 1. life events gone -----------------------------------------------------
def test_life_events_removed_everywhere():
    assert "lifeEvents" not in new_ips_data() and "lifeEvents" not in normalize_data({})
    g = generate_ips_section(FakeStore([note(1, "2026-10-20", "She will retire in 2041. Daughter starts university in September 2029.")]),
                             "x", "goals", Chat({"bullets": []}))
    assert "lifeEvents" not in g
    d = merge_section(new_ips_data(), {"section": "goals", "status": "ok", "goals": g["goals"], "lifeEvents": [{"label": "x"}]})
    assert "lifeEvents" not in d
    old = normalize_data({"lifeEvents": [{"id": "m1", "year": 2035, "label": "Sabbatical", "manual": True}]})
    assert "lifeEvents" not in old
    assert "Sabbatical" not in " ".join(p["body"] for p in render_parts({"lifeEvents": [{"year": 2035, "label": "Sabbatical"}]}))


def test_old_saved_ips_with_life_events_loads(api):
    r = api.post(f"{U}/ips/jft", json={"data": {"lifeEvents": [{"id": "m1", "year": 2035, "label": "Sabbatical", "manual": True}]},
                                       "status": "Draft"})
    assert r.status_code == 200
    got = api.get(f"{U}/ips/jft").json()["versions"][0]["data"]
    assert "lifeEvents" not in got
    assert all("life events" not in p["body"].lower() for p in api.get(f"{U}/ips/jft").json()["versions"][0]["parts"])


def test_life_events_not_in_schema_or_sections():
    from app.agents.client_profiling.ips_generate import _SCHEMAS, _TASK
    assert "lifeEvents" not in str(_SCHEMAS) and "life event" not in " ".join(_TASK.values()).lower()
    assert SECTION_IDS == ["demographics", "philosophy", "goals", "risk", "allocation"]


# --- 2. investment period ----------------------------------------------------
NOTE = note(1, "2026-10-20", "Tom prefers a long-term diversified approach. He plans to invest for at least 10 years.")


def _phil(payload):
    return generate_ips_section(FakeStore([NOTE]), "x", "philosophy", Chat(payload))


def test_investment_period_generated_and_persisted():
    assert "investmentPeriod" in PHIL_KEYS
    item = {"value": "", "cite": ""}
    r = _phil({"approach": {"value": "long-term, diversified", "cite": "N1"}, "believes": item, "avoids": item,
               "investmentPeriod": {"value": "At least 10 years", "cite": "N1"}})
    assert r["philosophy"]["investmentPeriod"] == "At least 10 years" and r["philosophy"]["approach"] == "long-term, diversified"
    d = merge_section(new_ips_data(), r)
    assert d["philosophy"]["investmentPeriod"] == "At least 10 years"
    body = {p["part"]: p["body"] for p in render_parts(d)}[7]
    assert "Investment period: At least 10 years" in body


def test_investment_period_invented_figure_rejected_and_blank_when_not_stated():
    item = {"value": "", "cite": ""}
    r = _phil({"approach": item, "believes": item, "avoids": item, "investmentPeriod": {"value": "At least 25 years", "cite": "N1"}})
    assert r["philosophy"]["investmentPeriod"] == ""
    r = _phil({"approach": item, "believes": item, "avoids": item, "investmentPeriod": item})
    assert r["philosophy"]["investmentPeriod"] == ""


def test_investment_period_third_person_enforced():
    item = {"value": "", "cite": ""}
    r = _phil({"approach": item, "believes": item, "avoids": item, "investmentPeriod": {"value": "I will invest at least 10 years", "cite": "N1"}})
    assert not re.search(r"\b(I|my|we)\b", r["philosophy"]["investmentPeriod"], re.I)


def test_old_philosophy_without_period_loads_and_get_ips_camel_case(api):
    assert normalize_data({"philosophy": {"approach": "x"}})["philosophy"]["investmentPeriod"] == ""
    api.post(f"{U}/ips/jft", json={"data": {"philosophy": {"approach": "x", "investmentPeriod": "At least 10 years"}}, "status": "Draft"})
    got = api.get(f"{U}/ips/jft").json()["versions"][0]["data"]
    assert got["philosophy"]["investmentPeriod"] == "At least 10 years" and got["philosophy"]["approach"] == "x"


# --- 4. order ----------------------------------------------------------------
def test_render_parts_keep_stable_numbers_and_never_include_life_events():
    parts = render_parts(new_ips_data())
    assert [p["part"] for p in parts] == [1, 2, 3, 4, 5, 6]  # legacy numbers are a contract with the frontend
    assert [p["title"] for p in parts] == ["Client goals and objectives", "3L buckets and explanation", "Client risk profile",
                                           "Strategic Asset Allocation", "Review rules", "Signature line"]
    assert not any("life event" in p["title"].lower() or "life events:" in p["body"].lower() for p in parts)
