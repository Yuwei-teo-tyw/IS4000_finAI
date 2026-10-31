"""Model investment strategies A-F (UBS Investor Profile guide). JSON-backed; Postgres mirrors it."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).parent / "data" / "strategies.json"
ASSET_CLASSES = ("Bonds", "Liquidity", "Alternative Investments", "Equities", "Other")
BUCKETS = ("liquidity", "longevity", "legacy")


@lru_cache(maxsize=1)
def _raw() -> dict:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def load_strategies() -> list[dict]:
    return list(_raw()["strategies"])


def get_strategy(code: str) -> dict | None:
    c = (code or "").strip().upper()
    return next((s for s in load_strategies() if s["code"] == c), None)


def allowed_strategies(bucket: str) -> list[str]:
    """Only Longevity and Legacy get a strategy (A-F); the Liquidity portfolio gets no SAA / strategy."""
    if bucket == "liquidity":
        return []
    return [s["code"] for s in load_strategies()]


def strategy_label(code: str) -> str:
    s = get_strategy(code)
    return f"{s['code']} - {s['name']}" if s else code


# --- IS-85: validated display of the strategy table (units, missing metrics, unknown codes) ---------------------
CODES = tuple("ABCDEF")
UNAVAILABLE_MSG = "The strategy table is currently unavailable, so I cannot give strategy figures."
UNKNOWN_CODE_MSG = "Only strategies A to F exist (A Fixed Income, B Income, C Yield, D Balanced, E Growth, F Equities)."
_WEIGHT_ORDER = ("Bonds", "Liquidity", "Alternative Investments", "Equities", "Other")


def weights_total(s: dict) -> float:
    return sum(float(v) for v in (s.get("allocation") or {}).values())


def strategy_table_error() -> str | None:
    """None when the table is readable and sound (six strategies A-F, every weight set sums to exactly 100)."""
    try:
        rows = load_strategies()
    except Exception:
        return "unreadable"
    if [r.get("code") for r in rows] != list(CODES):
        return "codes"
    for r in rows:
        if not isinstance(r.get("allocation"), dict) or abs(weights_total(r) - 100) > 1e-9:
            return f"weights {r.get('code')}"
    return None


def _num(v) -> str | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return f"{v:g}"


def metric_text(s: dict, key: str) -> str:
    """One metric with units, or '<metric> not available for Strategy X' (never an invented number)."""
    label = {"expected_return_pct": "expected return", "volatility_pct": "volatility", "max_drawdown_pct": "max drawdown",
             "longest_drawdown_years": "longest drawdown"}[key]
    v = s.get(key)
    n = _num(v)
    if n is None:
        return f"{label} not available for Strategy {s.get('code')}"
    if key in ("expected_return_pct", "volatility_pct"):
        return f"{label} {float(v):.1f}% p.a."
    if key == "max_drawdown_pct":
        return f"{label} -{n}%"
    return f"{label} {round(float(v) * 12)} months ({n} years)"


def strategy_line(s: dict) -> str:
    """'C Yield (Moderate risk tolerance): Bonds 51%, ...; expected return 3.5% p.a., ...' with every unit shown."""
    alloc = s.get("allocation") or {}
    w = ", ".join(f"{k} {alloc[k]:g}%" for k in _WEIGHT_ORDER if k in alloc)
    metrics = "; ".join(metric_text(s, k) for k in ("expected_return_pct", "volatility_pct", "max_drawdown_pct", "longest_drawdown_years"))
    st = s.get("stress") or {}
    stress = ""
    if st.get("event") and _num(st.get("loss_pct")) is not None:
        stress = f"; stress {st['event']} -{_num(st['loss_pct'])}% (under water {st.get('time_under_water', 'n/a')})"
    risk = f" ({s['risk_label']})" if s.get("risk_label") else ""
    return f"{s['code']} {s['name']}{risk}: {w}; {metrics}{stress}"


def strategy_codes_in(text: str) -> tuple[list[str], list[str]]:
    """(valid codes A-F, invalid letters) named as 'strategy X' / 'X strategy'. Lower/upper case both work for A-F."""
    t = text or ""
    found = (re.findall(r"\bstrateg(?:y|ies)\s+([A-Fa-f])\b(?![\w'-])", t, re.I) + re.findall(r"\b([A-F])\s+(?i:strategy)\b", t)
             + re.findall(r"\bstrategy\s+((?-i:[G-Z]))\b(?![\w'-])", t, re.I))
    good = [c.upper() for c in found if c.upper() in CODES]
    bad = [c.upper() for c in found if c.upper() not in CODES]
    return list(dict.fromkeys(good)), list(dict.fromkeys(bad))


# --- portfolio rate of return (nominal range from the strategy table, real = nominal - inflation) ----------------
INFLATION_ASSUMPTION_PCT = 2.0  # long-run inflation assumption (% p.a.) used to turn the nominal range into a real one. Change here only.
RETURN_RANGE_HALF_WIDTH_PP = 0.5  # nominal range = expected return +/- this many percentage points


def _r1(x: float) -> float:
    return round(x + 1e-9, 1) + 0.0  # one decimal, no -0.0


def _f(x: float) -> str:
    return f"{_r1(x):.1f}"


def rate_of_return(code: str) -> dict | None:
    """{"nominalLowPct","nominalHighPct","realLowPct","realHighPct","inflationPct","text"} for strategy `code`, or None when the
    strategy or its expected return is unknown. Nominal = expected_return_pct +/- 0.5pp; real = nominal - INFLATION_ASSUMPTION_PCT."""
    s = get_strategy(code)
    er = s.get("expected_return_pct") if s else None
    if isinstance(er, bool) or not isinstance(er, (int, float)):
        return None
    nl, nh = _r1(er - RETURN_RANGE_HALF_WIDTH_PP), _r1(er + RETURN_RANGE_HALF_WIDTH_PP)
    rl, rh = _r1(nl - INFLATION_ASSUMPTION_PCT), _r1(nh - INFLATION_ASSUMPTION_PCT)
    nominal = f"Based on current projections, this equates to a current nominal return of {_f(nl)}%\u2013{_f(nh)}%."
    if rl > 0:
        head = (f"This portfolio recommendation is designed to generate an average, expected rate of return of "
                f"{_f(rl)}%\u2013{_f(rh)}% above inflation, net of fees and costs.")
    elif rh <= 0:
        head = ("This portfolio recommendation is designed to generate an average, expected rate of return below inflation "
                f"({_f(rl)}%\u2013{_f(rh)}% in real terms), net of fees and costs." if rh < 0 else
                "This portfolio recommendation is designed to generate an average, expected rate of return in line with inflation, "
                "net of fees and costs.")
    else:  # range straddles 0
        head = ("This portfolio recommendation is designed to generate an average, expected rate of return broadly in line with "
                f"inflation ({_f(rl)}%\u2013{_f(rh)}% in real terms), net of fees and costs.")
    return {"nominalLowPct": nl, "nominalHighPct": nh, "realLowPct": rl, "realHighPct": rh,
            "inflationPct": INFLATION_ASSUMPTION_PCT, "text": f"{head} {nominal}"}


def rate_of_return_text(code: str) -> str:
    r = rate_of_return(code)
    return r["text"] if r else ""
