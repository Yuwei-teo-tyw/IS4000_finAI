"""
Regime classifier backtest vs NBER recession dates (guide §4.5).

    cd backend && python -m app.agents.market_researcher.backtest [--start 1980-01-01] [--out PATH]

Runs `classify_regime` monthly (with hysteresis, as live) and compares the
calls to FRED's USREC. Writes a Markdown report (default:
backtest_report.md next to this file).

Look-ahead bias: uses *revised* FRED data, not ALFRED vintages (a vintage
fetch per month would be ~10k API calls). To limit the bias each series is
only visible after a per-frequency publication lag (PUBLICATION_LAG_DAYS),
so e.g. September CPI is first used in mid-October. Revisions to activity
data (payrolls, GDP, IP) still make this somewhat optimistic.

Before 1982 FRED has no daily T10Y3M, so the monthly GS10 - TB3MS spread
fills that gap.

Tune weights/thresholds in config.RegimeConfig, never in code.
"""
import argparse
import asyncio
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from app.agents.market_researcher import features as f
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.adapters.fred import FredClient
from app.agents.market_researcher.config import PHASES, REGIME_CONFIG, RegimeConfig
from app.agents.market_researcher.regime import classify_regime

BACKTEST_SERIES = {
    # id: frequency
    "INDPRO": "M", "RSAFS": "M", "CPIAUCSL": "M", "PAYEMS": "M", "GDPC1": "Q",
    "UNRATE": "M", "ICSA": "W", "CPILFESL": "M", "PCEPILFE": "M", "T5YIE": "D",
    "DFF": "D", "T10Y3M": "D", "GS10": "M", "TB3MS": "M", "BAMLH0A0HYM2": "D",
    "NFCI": "W", "SAHMREALTIME": "M", "PERMIT": "M", "UMCSENT": "M", "USREC": "M",
}
PUBLICATION_LAG_DAYS = {"D": 1, "W": 7, "M": 45, "Q": 90}
FETCH_START = date(1965, 1, 1)

DEFAULT_REPORT_PATH = Path(__file__).parent / "backtest_report.md"

# Acceptance (guide §4.5): catch most NBER recessions, few sustained false calls.
MIN_CATCH_SHARE = 0.6
MAX_FALSE_CALLS = 3
CATCH_WINDOW_MONTHS = 3        # a recession call within [start-3m, end+3m] counts
FALSE_CALL_BUFFER_MONTHS = 6   # recession runs this far outside NBER dates are false
FALSE_CALL_MIN_MONTHS = 3      # ...if they last at least this long


@dataclass
class Recession:
    start: date
    end: date
    caught: bool = False
    lead_months: Optional[int] = None       # first recession call relative to start (negative = early)
    late_expansion_before: bool = False     # late_expansion within 12m before start
    early_expansion_after: bool = False     # early_expansion within 12m after end


@dataclass
class BacktestResult:
    start: date
    end: date
    calls: list[tuple[date, Optional[str], int]] = field(default_factory=list)  # (month, phase, usrec)
    recessions: list[Recession] = field(default_factory=list)
    false_calls: list[tuple[date, date]] = field(default_factory=list)
    confusion: dict[str, dict[int, int]] = field(default_factory=dict)

    @property
    def caught(self) -> int:
        return sum(r.caught for r in self.recessions)

    @property
    def passed(self) -> bool:
        if not self.recessions:
            return False
        return self.caught >= math.ceil(MIN_CATCH_SHARE * len(self.recessions)) and len(self.false_calls) <= MAX_FALSE_CALLS


async def fetch_history(fred: FredClient, end: date) -> dict[str, list[SeriesPoint]]:
    ids = list(BACKTEST_SERIES)
    results = await asyncio.gather(*(fred.get_series(s, FETCH_START, end) for s in ids), return_exceptions=True)
    history = {}
    for sid, res in zip(ids, results):
        if isinstance(res, Exception):
            print(f"backtest: could not fetch {sid}: {res}")
            continue
        history[sid] = res
    return history


def splice_curve(history: dict[str, list[SeriesPoint]]) -> list[SeriesPoint]:
    """Daily T10Y3M where it exists, monthly GS10 - TB3MS before that."""
    daily = history.get("T10Y3M") or []
    first = daily[0].date if daily else date.max
    tb = {p.date: p.value for p in history.get("TB3MS") or []}
    monthly = [SeriesPoint(p.date, p.value - tb[p.date]) for p in history.get("GS10") or [] if p.date in tb and p.date < first]
    return monthly + daily


def visible_as_of(history: dict[str, list[SeriesPoint]], as_of: date) -> dict[str, list[SeriesPoint]]:
    out = {}
    for sid, pts in history.items():
        freq = BACKTEST_SERIES.get(sid, "D")
        out[sid] = f.truncate(pts, as_of - timedelta(days=PUBLICATION_LAG_DAYS[freq]))
    return out


def _months(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = f.shift_months(d, 1)
    return out


def nber_recessions(usrec: list[SeriesPoint], start: date, end: date) -> list[Recession]:
    recessions, current = [], None
    for p in usrec:
        if p.date < start or p.date > end:
            continue
        if p.value >= 0.5 and current is None:
            current = p.date
        elif p.value < 0.5 and current is not None:
            recessions.append(Recession(current, f.shift_months(p.date, -1)))
            current = None
    if current is not None:
        recessions.append(Recession(current, end))
    return recessions


def _month_diff(a: date, b: date) -> int:
    return (a.year - b.year) * 12 + (a.month - b.month)


def run_backtest(history: dict[str, list[SeriesPoint]], start: date, end: date,
                 cfg: RegimeConfig = REGIME_CONFIG) -> BacktestResult:
    history = dict(history)
    history["T10Y3M"] = splice_curve(history)
    usrec = history.pop("USREC", [])
    for sid in ("GS10", "TB3MS"):
        history.pop(sid, None)
    usrec_by_month = {p.date: int(p.value) for p in usrec}

    result = BacktestResult(start, end)
    previous: Optional[dict] = None
    for month in _months(start, end):
        # Classify at the end of each month using only data published by then.
        as_of = f.shift_months(month, 1) - timedelta(days=1)
        regime = classify_regime(visible_as_of(history, as_of), as_of, previous=previous, cfg=cfg)
        if regime.phase:
            previous = {"phase": regime.phase, "probabilities": regime.probabilities}
        result.calls.append((month, regime.phase, usrec_by_month.get(month, 0)))

    result.recessions = nber_recessions(usrec, start, end)
    _score(result)
    return result


def _score(result: BacktestResult) -> None:
    calls = {m: phase for m, phase, _ in result.calls}
    result.confusion = {phase: {0: 0, 1: 0} for phase in (*PHASES, "none")}
    for _, phase, rec in result.calls:
        result.confusion[phase or "none"][rec] += 1

    for r in result.recessions:
        lo, hi = f.shift_months(r.start, -CATCH_WINDOW_MONTHS), f.shift_months(r.end, CATCH_WINDOW_MONTHS)
        hits = sorted(m for m, phase in calls.items() if lo <= m <= hi and phase == "recession")
        r.caught = bool(hits)
        r.lead_months = _month_diff(hits[0], r.start) if hits else None
        r.late_expansion_before = any(
            phase == "late_expansion" for m, phase in calls.items() if f.shift_months(r.start, -12) <= m < r.start
        )
        r.early_expansion_after = any(
            phase == "early_expansion" for m, phase in calls.items() if r.end < m <= f.shift_months(r.end, 12)
        )

    def near_recession(m: date) -> bool:
        return any(
            f.shift_months(r.start, -FALSE_CALL_BUFFER_MONTHS) <= m <= f.shift_months(r.end, FALSE_CALL_BUFFER_MONTHS)
            for r in result.recessions
        )

    run: list[date] = []
    for m, phase, _ in result.calls + [(date.max, None, 0)]:
        if phase == "recession" and not near_recession(m):
            run.append(m)
            continue
        if len(run) >= FALSE_CALL_MIN_MONTHS:
            result.false_calls.append((run[0], run[-1]))
        run = []


def render_report(result: BacktestResult) -> str:
    lines = [
        "# Regime classifier backtest",
        "",
        f"Window: {result.start} to {result.end}, monthly ({len(result.calls)} months). "
        "Generated by `python -m app.agents.market_researcher.backtest`.",
        "",
        "Caveat: this uses revised FRED data with publication lags, not ALFRED vintages, so there is some "
        "look-ahead bias from data revisions.",
        "",
        f"**Result: {'PASS' if result.passed else 'FAIL'}.** {result.caught}/{len(result.recessions)} NBER recessions "
        f"caught (need at least {math.ceil(MIN_CATCH_SHARE * len(result.recessions))}). "
        f"{len(result.false_calls)} sustained false recession calls (max {MAX_FALSE_CALLS}).",
        "",
        "## NBER recessions",
        "",
        "| Recession | Caught | First `recession` call vs start (months) | `late_expansion` in prior 12m | `early_expansion` within 12m after |",
        "|---|---|---|---|---|",
    ]
    for r in result.recessions:
        lead = "n/a" if r.lead_months is None else f"{r.lead_months:+d}"
        lines.append(
            f"| {r.start:%Y-%m} to {r.end:%Y-%m} | {'yes' if r.caught else 'no'} | {lead} | "
            f"{'yes' if r.late_expansion_before else 'no'} | {'yes' if r.early_expansion_after else 'no'} |"
        )
    lines += ["", "## Sustained false recession calls", ""]
    lines += [f"- {a:%Y-%m} to {b:%Y-%m}" for a, b in result.false_calls] or ["- none"]
    lines += ["", "## Phase vs NBER (months)", "", "| Phase | Expansion (USREC=0) | Recession (USREC=1) |", "|---|---|---|"]
    for phase, counts in result.confusion.items():
        lines.append(f"| {phase} | {counts[0]} | {counts[1]} |")
    lines += ["", "## Calls by year", "", "Each character is one month: E = early_expansion, L = late_expansion, "
              "R = recession, T = late_recession (trough), . = no call. Uppercase marks an NBER recession month.", "", "```"]
    codes = {"early_expansion": "e", "late_expansion": "l", "recession": "r", "late_recession": "t", None: "."}
    by_year: dict[int, str] = {}
    for m, phase, rec in result.calls:
        c = codes[phase]
        by_year[m.year] = by_year.get(m.year, "") + (c.upper() if rec else c)
    lines += [f"{year} {row}" for year, row in by_year.items()]
    lines += ["```", ""]
    return "\n".join(lines)


async def _main(start: date, out: Path) -> BacktestResult:
    from app.agents.market_researcher.config import load_settings

    settings = load_settings()
    fred = FredClient(settings.fred_api_key or "", timeout=30)
    try:
        end = date.today()
        history = await fetch_history(fred, end)
    finally:
        await fred.aclose()
    result = run_backtest(history, start, f.shift_months(date(end.year, end.month, 1), -2))
    out.write_text(render_report(result), encoding="utf-8")
    return result


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", type=date.fromisoformat, default=date(1980, 1, 1))
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    result = asyncio.run(_main(args.start, args.out))
    print(f"{'PASS' if result.passed else 'FAIL'}: {result.caught}/{len(result.recessions)} recessions caught, "
          f"{len(result.false_calls)} false calls -> {args.out}")


if __name__ == "__main__":
    main()
