"""IS-97 client portfolio database: maths, API, loader validation (fixture data) + validation of the real seed CSVs."""
import csv
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.endpoints.client_portfolio as ep
from app.agents.client_portfolio import load as loader
from app.agents.client_portfolio import service
from app.agents.client_portfolio.store import PortfolioStore, PortfolioUnavailableError
from app.agents.client_profiling.store import IpsVersion

SEED = Path(loader.DATA_DIR)


def row(ticker, qty, cost, price, cls="Equities", portfolio="longevity", sector="Tech", d="2025-01-02"):
    return {"client_id": "c1", "ticker": ticker, "date_bought": d, "quantity": Decimal(qty), "cost_per_unit": Decimal(cost),
            "portfolio": portfolio, "name": ticker + " Inc", "instrument_type": "stock", "sector": sector, "asset_class": cls,
            "price": None if price is None else Decimal(price), "price_as_at": "2026-10-26" if price else None, "price_source": "test"}


class FakeStore:
    def __init__(self, rows=None, down=False):
        self.rows, self.down = rows or [], down

    def holdings(self, client_id):
        if self.down:
            raise PortfolioUnavailableError("down")
        return self.rows


class FakeProfiling:
    def __init__(self, ips=None):
        self.ips = ips

    def latest_ips(self, cid):
        return (self.ips, True) if self.ips else (None, False)

    def book_ids(self):
        return ["c1"]


def ips(data):
    return IpsVersion(client_id="c1", version=2, status="Active", issued_on="2026-01-01", data=data)


THREE = [row("A", "100", "10", "12", "Equities", "longevity"), row("B", "50", "100", "90", "Fixed Income", "liquidity"),
         row("C", "10", "300", "310", "Alternatives", "legacy")]


def test_weights_sum_to_exactly_100_and_values_correct():
    r = service.compute_portfolio("c1", THREE)
    assert r["status"] == "ok" and r["aum"]["value"] == 1200 + 4500 + 3100
    assert round(sum(h["weight_pct"] for h in r["holdings"]), 1) == 100.0
    a = r["holdings"][0]
    assert (a["market_value"], a["pnl"], a["pnl_pct"], a["cost_basis"]) == (1200.0, 200.0, 20.0, 1000.0)
    assert a["price_as_at"] == "2026-10-26" and a["sector"] == "Tech" and a["portfolio"] == "longevity"
    b = r["holdings"][1]
    assert b["pnl"] == -500.0 and b["pnl_pct"] == -10.0


def test_rounding_awkward_thirds_still_sum_to_100():
    rows = [row(t, "1", "1", "1") for t in "ABC"]
    r = service.compute_portfolio("c1", rows)
    ws = [Decimal(str(h["weight_pct"])) for h in r["holdings"]]
    assert sum(ws) == Decimal("100.0") and sorted(ws) == [Decimal("33.3"), Decimal("33.3"), Decimal("33.4")]
    assert sum(Decimal(str(g["weight_pct"])) for g in r["by_asset_class"]) == Decimal("100.0")


def test_no_float_drift():
    r = service.compute_portfolio("c1", [row("A", "3", "0.1", "0.1"), row("B", "3", "0.2", "0.2")])
    assert r["aum"]["value"] == 0.9 and r["holdings"][0]["pnl"] == 0.0


def test_group_by_asset_class():
    g = {x["asset_class"]: x for x in service.compute_portfolio("c1", THREE)["by_asset_class"]}
    assert g["Fixed Income"]["value"] == 4500 and g["Fixed Income"]["weight_pct"] == 51.2
    assert round(sum(x["weight_pct"] for x in g.values()), 1) == 100.0


def test_missing_price_excluded_with_note():
    r = service.compute_portfolio("c1", THREE + [row("N", "1000", "1", None, "Cash", "liquidity")])
    n = next(h for h in r["holdings"] if h["ticker"] == "N")
    assert n["price_label"] == "Price not available" and n["market_value"] is None and n["weight_pct"] is None
    assert r["aum"]["value"] == 8800  # unpriced position not counted
    assert round(sum(h["weight_pct"] for h in r["holdings"] if h["weight_pct"] is not None), 1) == 100.0
    assert all(g["asset_class"] != "Cash" for g in r["by_asset_class"])
    assert any("excluded from AUM" in x for x in r["notes"])


def test_all_unpriced():
    r = service.compute_portfolio("c1", [row("N", "1", "1", None)])
    assert r["status"] == "no_priced_holdings" and r["aum"]["value"] is None and r["holdings"][0]["price_label"]


def test_no_holdings_is_not_zero():
    r = service.get_client_portfolio("c1", FakeStore([]), FakeProfiling())
    assert r["aum"] == {"value": None, "label": "No holdings yet"} and r["holdings"] == [] and r["by_asset_class"] == []
    assert r["status"] == "no_holdings"


def test_three_l_comparison_present():
    data = {"threeLProportion": {"liquidity": {"pct": 40}, "longevity": {"pct": 40}, "legacy": {"pct": 20}},
            "threeL": [{"portfolio": "Liquidity", "strategy": "A", "strategyName": "Fixed Income"},
                       {"portfolio": "Longevity", "strategy": "D"}, {"portfolio": "Legacy", "strategy": "F"}]}
    r = service.get_client_portfolio("c1", FakeStore(THREE), FakeProfiling(ips(data)))
    t = r["three_l"]
    assert t["available"] and t["ips_version"] == 2
    p = {x["portfolio"]: x for x in t["portfolios"]}
    assert p["liquidity"]["target_pct"] == 40 and p["liquidity"]["strategy"] == "A" and p["liquidity"]["saa"]["Bonds"] == 95
    assert p["liquidity"]["actual_pct"] == 51.2 and p["liquidity"]["difference_pct"] == 11.2
    assert p["longevity"]["strategy_name"] == "Balanced"


def test_three_l_comparison_absent_without_ips():
    r = service.get_client_portfolio("c1", FakeStore(THREE), FakeProfiling(None))
    assert r["three_l"]["available"] is False and "No IPS" in r["three_l"]["message"]
    assert r["aum"]["value"] == 8800  # holdings unaffected


def test_service_down():
    r = service.get_client_portfolio("c1", FakeStore(down=True), FakeProfiling())
    assert r == {"available": False, "client_id": "c1", "message": service.UNAVAILABLE_MSG, "holdings": []}


# ---- API ----
@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    app.include_router(ep.router)
    monkeypatch.setattr(ep, "get_default_store", lambda: FakeProfiling())
    holder = {"store": FakeStore(THREE)}
    real = service.get_client_portfolio
    monkeypatch.setattr(service, "get_client_portfolio",
                        lambda cid, **k: real(cid, store=holder["store"], profiling_store=FakeProfiling()))
    return TestClient(app), holder


def test_api_ok_and_outside_book_403(api):
    c, _ = api
    r = c.get("/agents/client-portfolio/c1", headers={"X-RM-Id": "rm_default"})
    assert r.status_code == 200 and r.json()["aum"]["value"] == 8800
    assert c.get("/agents/client-portfolio/other").status_code == 403


def test_api_db_down_503(api):
    c, h = api
    h["store"] = FakeStore(down=True)
    r = c.get("/agents/client-portfolio/c1")
    assert r.status_code == 503 and r.json()["available"] is False and r.json()["holdings"] == [] and r.json()["message"]


# ---- loader validation ----
INST = [{"ticker": "AAA", "name": "A", "instrument_type": "etf", "sector": "S", "asset_class": "Equities", "price": "10",
         "price_as_at": "2026-10-26", "price_source": "x"},
        {"ticker": "NOP", "name": "N", "instrument_type": "mutual_fund", "sector": "S", "asset_class": "Cash", "price": "",
         "price_as_at": "", "price_source": ""}]
HOLD = [{"client_id": "c1", "ticker": "AAA", "date_bought": "2025-01-02", "quantity": "5", "cost_per_unit": "9", "portfolio": "legacy"}]


def test_loader_accepts_valid_and_empty_price():
    i, h = loader.validate_rows(INST, HOLD)
    assert i[1][5] is None and i[1][6] is None and len(h) == 1


def test_loader_rejects_unknown_ticker():
    with pytest.raises(loader.SeedError) as e:
        loader.validate_rows(INST, HOLD + [{**HOLD[0], "ticker": "ZZZ"}])
    assert "ZZZ" in str(e.value) and "not in instruments" in str(e.value)


@pytest.mark.parametrize("patch", [{"portfolio": "other"}, {"quantity": "0"}, {"date_bought": "02/01/2025"}, {"cost_per_unit": "x"}])
def test_loader_rejects_bad_holdings(patch):
    with pytest.raises(loader.SeedError):
        loader.validate_rows(INST, [{**HOLD[0], **patch}])


def test_loader_rejects_bad_instrument():
    with pytest.raises(loader.SeedError):
        loader.validate_rows([{**INST[0], "instrument_type": "bond"}], [])
    with pytest.raises(loader.SeedError):
        loader.validate_rows([{**INST[0], "price_as_at": ""}], [])


def test_store_unreachable_raises():
    s = PortfolioStore(dsn="postgresql://postgres:postgres@127.0.0.1:1/none", autoload=False)
    with pytest.raises(PortfolioUnavailableError):
        s.holdings("c1")


# ---- real seed CSVs ----
def _csv(name):
    with open(SEED / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def seed():
    if not (SEED / "instruments.csv").exists() or not (SEED / "holdings.csv").exists():
        pytest.skip("seed CSVs not present")
    return _csv("instruments.csv"), _csv("holdings.csv")


def test_seed_passes_loader_validation(seed):
    loader.validate_rows(*seed)


def test_seed_every_asset_class_has_two_priced(seed):
    by = {}
    for r in seed[0]:
        if r["price"]:
            by[r["asset_class"]] = by.get(r["asset_class"], 0) + 1
        by.setdefault(r["asset_class"], 0)
    assert by and all(n >= 2 for n in by.values()), by


def test_seed_priced_rows_have_as_at_date(seed):
    assert all(r["price_as_at"] for r in seed[0] if r["price"])


def test_seed_holdings_shape(seed):
    inst = {r["ticker"] for r in seed[0]}
    hs = seed[1]
    assert all(h["ticker"] in inst for h in hs)
    keys = [(h["client_id"], h["ticker"]) for h in hs]
    assert len(keys) == len(set(keys))
    per = {}
    for h in hs:
        per.setdefault(h["client_id"], set()).add(h["ticker"])
    assert all(len(v) <= 10 for v in per.values())
    sets = [frozenset(v) for v in per.values()]
    assert len(sets) == len(set(sets))  # jfr and jft currently differ; ser differs from both
    assert set(per) == {"jfr", "jft", "ser"}  # portfolio data is seeded for Jane Fraser (jfr/jft) and Sergio (ser) only


def test_seed_jane_equities_are_famous_bank_and_tech(seed):
    famous = {"JPM", "GS", "MS", "BAC", "C", "UBS", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META"}
    insts = {r["ticker"]: r for r in seed[0]}
    for cid in ("jft", "jfr"):
        stocks = {h["ticker"] for h in seed[1] if h["client_id"] == cid and insts[h["ticker"]]["instrument_type"] == "stock"}
        assert stocks and stocks <= famous, (cid, stocks)
    assert all(insts[t]["price"] for t in famous)


def test_seed_jane_actual_vs_saa_has_flagged_and_unflagged_rows(seed):
    saa = {"liquidity": {"Fixed Income": 95, "Cash": 5, "Alternatives": 0, "Equities": 0},
           "longevity": {"Fixed Income": 72, "Cash": 5, "Alternatives": 7, "Equities": 13},
           "legacy": {"Fixed Income": 51, "Cash": 5, "Alternatives": 11, "Equities": 29}}
    insts = {r["ticker"]: r for r in seed[0]}
    for cid in ("jft", "jfr"):
        deltas = []
        for p, target in saa.items():
            v = {}
            for h in seed[1]:
                if h["client_id"] == cid and h["portfolio"] == p:
                    c = insts[h["ticker"]]["asset_class"]
                    v[c] = v.get(c, 0) + float(h["quantity"]) * float(insts[h["ticker"]]["price"])
            tot = sum(v.values())
            deltas += [v.get(c, 0) / tot * 100 - w for c, w in target.items()]
        assert any(d >= 10 for d in deltas) and any(d <= -10 for d in deltas), cid  # over and under
        assert any(abs(d) < 10 for d in deltas), cid


def test_seed_computes_for_every_client(seed):
    insts = {r["ticker"]: r for r in seed[0]}
    for cid in {h["client_id"] for h in seed[1]}:
        rows = [{**h, **insts[h["ticker"]], "quantity": Decimal(h["quantity"]), "cost_per_unit": Decimal(h["cost_per_unit"]),
                 "price": Decimal(insts[h["ticker"]]["price"]) if insts[h["ticker"]]["price"] else None,
                 "price_as_at": insts[h["ticker"]]["price_as_at"] or None}
                for h in seed[1] if h["client_id"] == cid]
        r = service.compute_portfolio(cid, rows)
        assert r["status"] == "ok"
        assert round(sum(x["weight_pct"] for x in r["holdings"] if x["weight_pct"] is not None), 1) == 100.0


# ---- loader reconcile against a real (throwaway-schema) Postgres ----
def _pg_store():
    import uuid
    st = PortfolioStore(schema="t_pf_" + uuid.uuid4().hex[:8], autoload=False)
    try:
        with st.connect():
            pass
    except Exception:
        pytest.skip("local Postgres not reachable")
    return st


def _write(d, hold_rows):
    (d / "instruments.csv").write_text("ticker,name,instrument_type,sector,asset_class,price,price_as_at,price_source\n"
                                       "AAA,A,etf,S,Equities,10,2026-10-26,x\n", encoding="utf-8")
    hdr = "client_id,ticker,date_bought,quantity,cost_per_unit,portfolio\n"
    (d / "holdings.csv").write_text(hdr + "".join(f"{r}\n" for r in hold_rows), encoding="utf-8")


def test_loader_reconciles_db_to_csv_and_is_idempotent(tmp_path):
    from psycopg import sql
    st = _pg_store()
    try:
        _write(tmp_path, ["a,AAA,2025-01-02,5,9,legacy", "b,AAA,2025-01-02,7,9,legacy", "a,AAA,2025-02-03,1,9,legacy"])
        assert loader.load_seeds(st, tmp_path)["holdings"] == 3
        assert len(st.holdings("a")) == 2 and len(st.holdings("b")) == 1
        _write(tmp_path, ["a,AAA,2025-01-02,6,9,legacy"])  # b removed, one of a's positions removed, one updated
        r = loader.load_seeds(st, tmp_path)
        assert r["deleted"] == 2 and st.holdings("b") == [] and len(st.holdings("a")) == 1
        assert float(st.holdings("a")[0]["quantity"]) == 6
        r2 = loader.load_seeds(st, tmp_path)  # idempotent
        assert r2["deleted"] == 0 and len(st.holdings("a")) == 1
    finally:
        with st.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(st.schema)))


def test_unseeded_client_gets_no_holdings(api):
    c, h = api
    h["store"] = FakeStore([])
    r = c.get("/agents/client-portfolio/c1")
    assert r.status_code == 200 and r.json()["status"] == "no_holdings" and r.json()["aum"]["label"] == "No holdings yet"


def test_out_of_book_without_holdings_is_clean_no_holdings_but_with_holdings_is_403(api):
    c, h = api
    h["store"] = FakeStore([])
    r = c.get("/agents/client-portfolio/other")
    assert r.status_code == 200 and r.json()["status"] == "no_holdings" and r.json()["holdings"] == []
    h["store"] = FakeStore(THREE)
    assert c.get("/agents/client-portfolio/other").status_code == 403
