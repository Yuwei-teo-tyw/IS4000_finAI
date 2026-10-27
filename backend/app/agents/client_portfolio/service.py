"""Portfolio maths for IS-97: AUM, per-holding value / P&L / weight, grouping by asset class and 3L portfolio, and the
comparison of the saved IPS 3L allocation + SAA/strategy with what is actually held.

All arithmetic is Decimal. Displayed percentages are apportioned (largest remainder) to 1 dp so each list sums to exactly
100.0. A holding whose instrument has no stored price shows "Price not available" and is EXCLUDED from AUM and weights.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .store import PORTFOLIOS, PortfolioStore, PortfolioUnavailableError, get_default_store

CURRENCY = "USD"  # reporting currency of the seed dataset (see data/README.md)
NO_HOLDINGS = "No holdings yet"
NO_PRICE = "Price not available"
UNAVAILABLE_MSG = "Portfolio data is unavailable right now."
Q2, Q4, Q1 = Decimal("0.01"), Decimal("0.0001"), Decimal("0.1")


def _q(v: Decimal, q: Decimal = Q2) -> Decimal:
    return v.quantize(q, rounding=ROUND_HALF_UP)


def _f(v: Optional[Decimal]) -> Optional[float]:
    return None if v is None else float(v)


def apportion(values: list[Decimal], total: Decimal = Decimal("100.0")) -> list[Decimal]:
    """Percentages of `total` for each value, at 0.1 precision, summing to exactly `total` (largest remainder)."""
    s = sum(values, Decimal(0))
    if s <= 0:
        return [Decimal("0.0") for _ in values]
    units = int(total / Q1)
    exact = [v * units / s for v in values]
    floor = [int(e) for e in exact]
    left = units - sum(floor)
    order = sorted(range(len(values)), key=lambda i: (-(exact[i] - floor[i]), i))
    for i in order[:left]:
        floor[i] += 1
    return [Decimal(n) * Q1 for n in floor]


def _group(rows: list[dict], key: str, names: Optional[tuple] = None) -> list[dict]:
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for r in rows:
        totals[r[key]] = totals.get(r[key], Decimal(0)) + r["_mv"]
        counts[r[key]] = counts.get(r[key], 0) + 1
    keys = list(names) if names else sorted(totals, key=lambda k: (-totals[k], k))
    vals = [totals.get(k, Decimal(0)) for k in keys]
    pcts = apportion(vals) if sum(vals, Decimal(0)) > 0 else [Decimal("0.0")] * len(keys)
    return [{key: k, "value": _f(_q(v)), "weight_pct": _f(p), "holdings_count": counts.get(k, 0)}
            for k, v, p in zip(keys, vals, pcts)]


def compute_portfolio(client_id: str, rows: list[dict]) -> dict:
    """rows: joined holding+instrument dicts (see PortfolioStore.holdings). Pure; no I/O."""
    if not rows:
        return {"available": True, "client_id": client_id, "currency": CURRENCY, "status": "no_holdings", "aum": {"value": None, "label": NO_HOLDINGS},
                "holdings": [], "by_asset_class": [], "by_3l_portfolio": [], "notes": [NO_HOLDINGS + ": nothing has been calculated."]}
    holdings, priced = [], []
    for r in rows:
        qty, cost = Decimal(str(r["quantity"])), Decimal(str(r["cost_per_unit"]))
        price = None if r.get("price") is None else Decimal(str(r["price"]))
        basis = _q(qty * cost)
        h = {"ticker": r["ticker"], "name": r["name"], "instrument_type": r["instrument_type"], "sector": r["sector"],
             "asset_class": r["asset_class"], "date_bought": str(r["date_bought"]), "quantity": _f(qty),
             "cost_per_unit": _f(cost), "cost_basis": _f(basis), "portfolio": r["portfolio"],
             "price": _f(price), "price_as_at": str(r["price_as_at"]) if r.get("price_as_at") else None,
             "price_source": r.get("price_source") or None, "price_available": price is not None,
             "price_label": None if price is not None else NO_PRICE,
             "market_value": None, "pnl": None, "pnl_pct": None, "weight_pct": None, "note": None}
        if price is not None:
            mv = _q(qty * price)
            pnl = mv - basis
            h.update(market_value=_f(mv), pnl=_f(pnl), pnl_pct=_f(_q(pnl / basis * 100)) if basis > 0 else None)
            priced.append({**h, "_mv": mv})
        else:
            h["note"] = f"{NO_PRICE}: excluded from AUM and weights."
        holdings.append(h)
    notes = [f"{h['ticker']}: {h['note']}" for h in holdings if h["note"]]
    if not priced:
        return {"available": True, "client_id": client_id, "currency": CURRENCY, "status": "no_priced_holdings",
                "aum": {"value": None, "label": NO_PRICE + " for any holding"}, "holdings": holdings,
                "by_asset_class": [], "by_3l_portfolio": [], "notes": notes}
    aum = sum((p["_mv"] for p in priced), Decimal(0))
    weights = apportion([p["_mv"] for p in priced])
    wmap = {p["ticker"] + p["date_bought"]: w for p, w in zip(priced, weights)}
    for h in holdings:
        if h["price_available"]:
            h["weight_pct"] = _f(wmap[h["ticker"] + h["date_bought"]])
    return {"available": True, "client_id": client_id, "currency": CURRENCY, "status": "ok", "aum": {"value": _f(_q(aum)), "label": f"{_q(aum):,.2f}"},
            "holdings": holdings, "by_asset_class": _group(priced, "asset_class"),
            "by_3l_portfolio": _group(priced, "portfolio", PORTFOLIOS), "notes": notes}


# --- 3L / SAA comparison -----------------------------------------------------------------------------------------
def _pct(v) -> Optional[float]:
    v = v.get("pct") if isinstance(v, dict) else v
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def three_l_comparison(profiling_store, client_id: str, actual: list[dict]) -> dict:
    """Saved IPS (threeLProportion, threeL strategies) next to actual per-portfolio value/%. Never invents a target."""
    from app.agents.client_profiling.ips_model import normalize_data
    from app.agents.client_profiling.strategies import get_strategy
    ips, current = profiling_store.latest_ips(client_id)
    if ips is None:
        return {"available": False, "message": "No IPS exists for this client yet, so there is no 3L allocation to compare."}
    data = normalize_data(ips.data, ips.issued_on)
    prop = data.get("threeLProportion") if isinstance(data.get("threeLProportion"), dict) else {}
    strat = {}
    for b in data.get("threeL") or []:
        label = str(b.get("id") or b.get("portfolio") or "").strip().lower()
        if label in PORTFOLIOS:
            strat[label] = b
    if not prop and not strat:
        return {"available": False, "message": "The IPS has no 3L allocation or strategies saved yet."}
    act = {a["portfolio"]: a for a in actual}
    out = []
    for p in PORTFOLIOS:
        target = _pct(prop.get(p)) if prop else None
        s = strat.get(p) or {}
        code = s.get("strategy") or None
        meta = get_strategy(code) if code else None
        a = act.get(p) or {}
        actual_pct = a.get("weight_pct")
        out.append({"portfolio": p, "target_pct": target, "strategy": code, "strategy_name": (meta or {}).get("name") or s.get("strategyName"),
                    "saa": (meta or {}).get("allocation"), "actual_value": a.get("value"), "actual_pct": actual_pct,
                    "difference_pct": None if target is None or actual_pct is None else round(actual_pct - target, 1)})
    return {"available": True, "ips_version": ips.version, "ips_status": ips.status, "ips_is_current": current, "portfolios": out}


def get_client_portfolio(client_id: str, store: Optional[PortfolioStore] = None, profiling_store=None) -> dict:
    """Full portfolio for one client, including the 3L comparison when an IPS exists. Never raises for a down portfolio
    database: returns {"available": False, "message": ..., "holdings": []} so Geneva never uses stale or invented holdings."""
    store = store or get_default_store()
    try:
        rows = store.holdings(client_id)
    except PortfolioUnavailableError:
        return {"available": False, "client_id": client_id, "message": UNAVAILABLE_MSG, "holdings": []}
    res = compute_portfolio(client_id, rows)
    if res["status"] == "no_holdings":
        res["three_l"] = {"available": False, "message": "No holdings yet, so nothing to compare with the IPS."}
        return res
    try:
        if profiling_store is None:
            from app.agents.client_profiling.store import get_default_store as cp_store
            profiling_store = cp_store()
        res["three_l"] = three_l_comparison(profiling_store, client_id, res["by_3l_portfolio"])
    except Exception:  # client-profiling DB unavailable: holdings stay valid, comparison is just absent
        res["three_l"] = {"available": False, "message": "The IPS could not be read, so the 3L comparison is unavailable."}
    return res
