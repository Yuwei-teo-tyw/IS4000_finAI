"""
Build data/shelf_live.json from the Advised Portfolios Performance workbook.

    cd backend
    python -m app.agents.product_recommender.build_live_shelf "../[MASTER] 202610 Advised Portfolios Performance.xlsx"

Reads three tabs only:
- "Performance - Linked": per fund ISIN, currency, track-record flags, YTD/1Y/3Y/5Y/10Y
  returns, max drawdown, std dev and Sharpe (computed in the workbook from the two tabs below).
- "RHP": monthly returns; column A labels each block (SGD / USD / HK / Alts sub-strategy).
  Its rows line up with Performance - Linked, so it supplies the section of each fund.
- "RHP - MDD": NAV index per fund; used to cross-check the row alignment.
- "SGD TER": fees per share class (AMF, TER), matched on exact ISIN only.

The workbook has no asset-class column, so the class comes from the RHP section for
alternatives and from the fund name for everything else. Picks 20 equity and 20 fixed
income funds spread across style buckets (BUCKETS) and up to 10 for every other
house-view asset class: at least a 3-year track record, one share class per fund
(SGD first, then USD), ranked by Sharpe (Cash: SGD first, then 1-year return). Risk ratings are
derived from volatility, not taken from the workbook. Needs openpyxl (requirements-dev.txt).
"""
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

PER_CLASS = 10
AS_OF = date(2026, 9, 30)  # latest month in the workbook (Performance - Linked BG3)
OUT_PATH = Path(__file__).parent / "data" / "shelf_live.json"
SOURCE_NAME = "[MASTER] 202610 Advised Portfolios Performance.xlsx"

# Performance - Linked columns (0-based): BR.. onwards
C_ISIN, C_CCY, C_T1, C_T3, C_T5, C_T10, C_NAME = 69, 70, 71, 72, 73, 74, 77
C_YTD, C_R1, C_R3, C_R5, C_R10, C_MDD, C_SD, C_SHARPE = 78, 79, 80, 81, 82, 83, 84, 85
FIRST_ROW, LAST_ROW = 7, 1299   # fund block; "Portfolio" rows start at 1300
# SGD TER columns (0-based): ISIN, TER, AMF; fees are stored as fractions (0.0075 = 0.75%)
T_ISIN, T_TER, T_AMF = 5, 30, 31
ALT_LABEL_OFFSET = 1410         # RHP repeats the block without fees from row 1417; its Alts rows carry the sub-labels

ALT_SECTION = {
    "Alts (PE)": ("Private markets", "Private equity"),
    "Public/Private": ("Private markets", "Private credit"),
    "Global Macro": ("Hedge funds", "Global macro"),
    "CTAs": ("Hedge funds", "Managed futures (CTA)"),
    "FX": ("Hedge funds", "FX and credit opportunities"),
    "Absolute Return": ("Hedge funds", "Absolute return"),
    "Multi-Strat": ("Hedge funds", "Multi-strategy"),
    "Equity Long Short": ("Hedge funds", "Equity long/short"),
}
MULTI_ASSET = re.compile(r"multi-asset|multi asset|all seasons|balanced|income and growth|revolution|diversified inc|"
                         r"inflation multi|dynamic income|^franklin income|^jpm income|strategic income|bridge fund|"
                         r"commodity|^tikehau|asia pacific income", re.I)
CLASS_RULES = [  # first match wins
    ("Gold", re.compile(r"\bgold\b|precious metal", re.I)),
    ("Cash", re.compile(r"money market|money fund|global money|\bcash\b|liquidity|liquid reserves|insticash", re.I)),
    ("Real estate", re.compile(r"real estate|propert|\breits?\b", re.I)),
    ("Equities", re.compile(r"equit|stock|s&p|msci", re.I)),  # before the bond rules: "Equity Income" is equity
    ("Fixed income", re.compile(r"bond|\bbd\b|fixed income|credit|high yield|income optimiser|debt|sukuk|preferred sec|"
                                r"capital securities|senior loan|senior secured|total return|aggregate|\bglb? agg|convertible|"
                                r"low duration|short duration|short-term fund|low average duration|limited term income|"
                                r"^pimco gis (income|divers)|investment grade|inv(m|estment)? gr(a)?d|real return|"
                                r"(global|american) income|income fund|reserve|short term interest rate|"
                                r"^(uob )?united sgd( fund| plus)?\b", re.I)),
    ("Equities", re.compile(r".", re.I)),  # what is left of the long-only funds
]
REGIONS = [("US", r"\bus 500\b"), ("Global", r"\bglobal\b|world|international|thematic"), ("Emerging markets", r"emerging|frontier"),
           ("Asia", r"asia|asean|pacific"), ("China", r"china|chinese"), ("India", r"india"), ("Japan", r"japan"),
           ("US", r"\bus\b|u\.s\.|america|s&p|usa|us\$"), ("Europe", r"europe|euro"), ("Singapore", r"singapore|sgd|straits")]
ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
EXCLUDED = re.compile(r"endowus", re.I)  # Endowus-branded funds are not offered on this shelf

# Equities and fixed income are picked per style bucket, so the shelf covers the core building blocks
# rather than whatever had the best Sharpe. A fund goes in the first bucket it matches; each bucket takes
# its best funds by Sharpe, and any shortfall is filled with the best remaining funds of the class.
BUCKETS = {
    "Equities": [
        ("Emerging markets equities", 3, r"emerging|frontier"),
        ("Asia equities", 2, r"asia|asean|pacific|china|india"),
        ("Japan equities", 1, r"japan"),
        ("Europe equities", 1, r"europe"),
        ("US core equities", 2, r"\bus\b|u\.s\.|usa|s&p|america"),
        ("Value equities", 3, r"value"),
        ("Dividend equities", 1, r"dividend|equity income"),
        ("Growth equities", 3, r"growth|technology|innovation|new economy|discovery|opportunit|quality"),
        ("Global core equities", 4, r"index|core|world|developed|enhanced|global stock|global equity"),
    ],
    "Fixed income": [
        ("Emerging markets debt", 4, r"emerging|frontier|\bem\b"),
        ("High yield", 4, r"high yield|senior loan|senior secured"),
        ("Short duration bonds", 2, r"short|low duration|low average duration|limited term"),
        ("Investment grade credit", 4, r"investment grade|inv(m|estment)? gr(a)?d|credit"),
        ("Asia and Singapore bonds", 2, r"asia|singapore|china|sgd"),
        ("Global core bonds", 4, r"global bond|aggregate|\bglb? agg|core fixed income|total return|"
                                 r"bond opportunit|global quality bond|government bond|global fixed income"),
    ],
}
PER_CLASS_BY_CLASS = {ac: sum(q for _, q, _ in b) for ac, b in BUCKETS.items()}  # 20 each
BUCKET_CCYS = {"SGD", "USD"}  # one share class per fund, in the client's base currency or USD


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _clean(s) -> str:
    return re.sub(r"\s+", " ", re.sub("[�–—]", "-", str(s))).strip() if s is not None else ""


def _region(name: str) -> str | None:
    return next((r for r, rx in REGIONS if re.search(rx, name, re.I)), None)


def _classify(name: str, section: str | None) -> tuple[str | None, str]:
    if section in ALT_SECTION:
        return ALT_SECTION[section]
    if section == "Private Real Assets":
        return ("Real estate", "Private real estate") if re.search(r"real estate", name, re.I) else ("Private markets", "Private infrastructure")
    if MULTI_ASSET.search(name):
        return None, "Multi-asset"  # no house-view class for these
    ac = next(c for c, rx in CLASS_RULES if rx.search(name))
    region = _region(name)
    sub = {
        "Gold": "Gold and precious metals equities",
        "Cash": "Money market",
        "Real estate": f"{region or 'Global'} listed real estate",
        "Fixed income": f"{region or 'Global'} {'high yield' if re.search('high yield', name, re.I) else 'bonds'}",
        "Equities": f"{region or 'Global'} equities",
    }[ac]
    return ac, sub


def _risk_rating(asset_class: str, vol_pct: float) -> int:
    """1-5 from annualised volatility (SRRI-style bands). Alternatives get a floor: their reported
    volatility is smoothed by infrequent valuations and understates the risk."""
    r = 1 if vol_pct < 1 else 2 if vol_pct < 5 else 3 if vol_pct < 10 else 4 if vol_pct < 15 else 5
    floor = {"Private markets": 4, "Hedge funds": 3, "Gold": 4}.get(asset_class, 1)
    return max(r, floor)


def read_fees(wb) -> dict[str, dict]:
    """ISIN -> {"amf", "ter"} as fractions, from the SGD TER tab."""
    fees = {}
    for r in wb["SGD TER"].iter_rows(min_row=2, values_only=True):
        isin = _clean(r[T_ISIN])
        if ISIN.match(isin) and isin not in fees:
            fees[isin] = {"amf": _num(r[T_AMF]), "ter": _num(r[T_TER])}
    return fees


def read_funds(xlsx: str) -> list[dict]:
    import openpyxl  # dev-only dependency

    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    perf = list(wb["Performance - Linked"].iter_rows(values_only=True))
    rhp = list(wb["RHP"].iter_rows(values_only=True))
    mdd = list(wb["RHP - MDD"].iter_rows(values_only=True))
    fees = read_fees(wb)

    section, sections = None, {}
    for i, r in enumerate(rhp, start=1):
        if r and isinstance(r[0], str) and r[0].strip() and not r[0].startswith("Using CNY"):
            section = r[0].strip()
        sections[i] = section

    funds = []
    for i in range(FIRST_ROW, LAST_ROW + 1):
        r = perf[i - 1]
        name = _clean(r[C_NAME])
        if not name:
            continue
        sec = sections.get(i)
        if sec == "Alts":
            sec = sections.get(i + ALT_LABEL_OFFSET)
        # Row alignment check: RHP and RHP - MDD must name a fund on the same row.
        aligned = bool(_clean(rhp[i - 1][6])) and bool(_clean(mdd[i - 1][5]))
        flags = [str(r[c]) for c in (C_T1, C_T3, C_T5, C_T10)]
        funds.append(dict(
            row=i, section=sec, aligned=aligned, code=_clean(r[C_ISIN]), ccy=_clean(r[C_CCY]) or None, name=name,
            short_3y=flags[1].startswith("<"), short_5y=flags[2].startswith("<"), short_10y=flags[3].startswith("<"),
            broken="#REF!" in flags,
            ytd=_num(r[C_YTD]), r1=_num(r[C_R1]), r3=_num(r[C_R3]), r5=_num(r[C_R5]), r10=_num(r[C_R10]),
            mdd=_num(r[C_MDD]), sd=_num(r[C_SD]), sharpe=_num(r[C_SHARPE]),
            fees=fees.get(_clean(r[C_ISIN])),
        ))
    return funds


def _usable(f: dict) -> bool:
    if f["broken"] or not f["aligned"] or not f["ccy"] or f["short_3y"] or EXCLUDED.search(f["name"]):
        return False
    if None in (f["r1"], f["r3"], f["mdd"], f["sd"], f["sharpe"]):
        return False
    # Placeholder rows: the same figure for every period is the fee drag on an empty series.
    if f["r1"] == f["r3"] == f["r5"]:
        return False
    if f["asset_class"] == "Cash" and f["sd"] >= 0.01:
        return False  # not behaving like a money market fund
    return f["mdd"] <= 0


def _family(name: str) -> str:
    """One entry per fund: share-class suffixes like '(Dist)' or 'SGD' do not make a new fund."""
    n = re.sub(r"\b(dist|acc|sgd|usd|fund|i{1,3}|lionglobal|blackrock)\b|\(natixis\)", "", name, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", n.lower())


def _pick_by_bucket(ac: str, funds: list[dict]) -> list[dict]:
    funds = sorted((f for f in funds if f["ccy"] in BUCKET_CCYS), key=lambda f: f["sharpe"], reverse=True)
    for f in funds:
        f["bucket"] = next((label for label, _, rx in BUCKETS[ac] if re.search(rx, f["name"], re.I)), None)
    picked: list[dict] = []
    for label, quota, _ in BUCKETS[ac]:
        picked += [f for f in funds if f["bucket"] == label][:quota]
    rest = [f for f in funds if f not in picked]
    picked += rest[:PER_CLASS_BY_CLASS[ac] - len(picked)]
    for f in picked:
        f["sub"] = f["bucket"] or f["sub"]
    return picked


def select(funds: list[dict]) -> dict[str, list[dict]]:
    by_class: dict[str, dict[str, dict]] = defaultdict(dict)
    ccy_rank = {"SGD": 0, "USD": 1}
    for f in funds:
        ac, sub = _classify(f["name"], f["section"])
        f = {**f, "asset_class": ac, "sub": sub}
        if ac is None or not _usable(f):
            continue
        fam = _family(f["name"])
        cur = by_class[ac].get(fam)
        if cur is None or ccy_rank.get(f["ccy"], 9) < ccy_rank.get(cur["ccy"], 9):
            by_class[ac][fam] = f
    picked = {}
    for ac, fams in by_class.items():
        if ac in BUCKETS:
            picked[ac] = _pick_by_bucket(ac, list(fams.values()))
            continue
        # Cash: SGD funds first (the shelf's base currency), then by 1-year return; Sharpe means little at near-zero volatility.
        key = (lambda f: (f["ccy"] == "SGD", f["r1"])) if ac == "Cash" else (lambda f: f["sharpe"])
        picked[ac] = sorted(fams.values(), key=key, reverse=True)[:PER_CLASS]
    return picked


def _pct(v):
    return None if v is None else round(v * 100, 2)


def to_product(f: dict, alt_ids: dict) -> dict:
    alt = f["asset_class"] in ("Private markets", "Hedge funds") or f["section"] == "Private Real Assets"
    if ISIN.match(f["code"]):
        pid = f"FND-{f['code']}"
    else:
        alt_ids["n"] += 1
        pid = f"FND-ALT-{alt_ids['n']:03d}"
    vol = _pct(f["sd"])
    return {
        "product_id": pid,
        "product_name": f["name"],
        "asset_class": f["asset_class"],
        "sub_asset_class": f["sub"],
        "product_type": "Alternative fund" if alt else "Unit trust",
        "issuer": None,
        "currency": f["ccy"],
        "historical_returns": {
            "ytd": _pct(f["ytd"]), "1y": _pct(f["r1"]), "3y": _pct(f["r3"]),
            "5y": None if f["short_5y"] else _pct(f["r5"]), "10y": None if f["short_10y"] else _pct(f["r10"]),
        },
        "yield_to_maturity": None,
        "distribution_yield": None,
        "risk_rating": _risk_rating(f["asset_class"], vol),
        "volatility": vol,
        "maximum_drawdown": _pct(f["mdd"]),
        "credit_rating": None,
        "management_fee": _pct((f["fees"] or {}).get("amf")),
        "total_expense_ratio": _pct((f["fees"] or {}).get("ter")),
        "transaction_fee": None,
        "minimum_investment": None,
        # Liquid unit trusts deal daily; dealing terms for alternatives are not in the workbook.
        "liquidity": None if alt else "DAILY",
        "lock_in_period": None if alt else "none",
        "duration": None,
        "maturity_date": None,
        "geographic_exposure": None,
        "sector_exposure": None,
        "currency_hedged": None,
        "esg_compliant": None,
        "recommended_horizon": None,
        "eligibility_requirements": None,
        "product_source": SOURCE_NAME,
        "as_of_date": AS_OF.isoformat(),
        "data_completeness": "PARTIAL",
        "is_illustrative": False,
        "why_buy": None,
        "suitability_note": None,
        "rating": None,
        "sharpe_ratio": round(f["sharpe"], 2),
        "source_row": f["row"],
    }


def build(xlsx: str) -> dict:
    picked = select(read_funds(xlsx))
    order = ["Cash", "Fixed income", "Equities", "Gold", "Real estate", "Hedge funds", "Private markets"]
    alt_ids = {"n": 0}
    products = [to_product(f, alt_ids) for ac in order for f in picked.get(ac, [])]
    target = lambda ac: PER_CLASS_BY_CLASS.get(ac, PER_CLASS)
    short = {ac: len(picked.get(ac, [])) for ac in order if len(picked.get(ac, [])) < target(ac)}
    return {
        "_notice": f"Built by build_live_shelf.py from {SOURCE_NAME} (tabs: Performance - Linked, RHP, RHP - MDD, SGD TER). "
                   "Returns, drawdown, volatility and fees are from the workbook; asset class, sub-class and risk rating are derived.",
        "is_illustrative": False,
        "as_of_date": AS_OF.isoformat(),
        "base_currency": "SGD",
        "data_sources": [{"name": SOURCE_NAME, "source_type": "LIVE", "retrieved_at": f"{AS_OF.isoformat()}T00:00:00Z"}],
        "limitations": [
            "Asset class is derived from the workbook's RHP sections (alternatives) or the fund name (everything else); the workbook has no asset-class column.",
            "Risk rating (1-5) is derived from annualised volatility, with a floor of 4 for private markets and gold and 3 for hedge funds; it is not an official product risk rating.",
            "management_fee is the annual management fee (AMF) and total_expense_ratio the TER, both from the SGD TER tab by exact ISIN; "
            "funds not in that tab have no fee. Fees are for information only and are never used to rank.",
            "Yields, sector and geographic exposure, ESG status, currency hedging and eligibility are not in the source tabs and are left empty.",
            "Dealing frequency and lock-ins for alternative funds are not in the source tabs; they are left empty and must be confirmed before recommending.",
            "Returns for periods longer than a fund's track record are omitted.",
            "Equities and fixed income are picked per style bucket (shown as the sub-asset class), best Sharpe within each bucket, SGD or USD share classes only.",
            *(["Fewer qualifying funds than targeted for: " + ", ".join(f"{k} ({v})" for k, v in short.items()) + "."] if short else []),
        ],
        "products": products,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    shelf = build(sys.argv[1])
    OUT_PATH.write_text(json.dumps(shelf, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = defaultdict(int)
    for p in shelf["products"]:
        counts[p["asset_class"]] += 1
    print(f"Wrote {len(shelf['products'])} products to {OUT_PATH}")
    for ac, n in counts.items():
        print(f"  {ac}: {n}")
