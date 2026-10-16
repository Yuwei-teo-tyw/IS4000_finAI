"""
Deterministic Markdown rendering of a MarketResearchOutput for the chat UI
(used by the optional chat trigger, nodes/market_researcher.py). Every
number shown comes straight from the output; nothing here calls an LLM.
"""
from app.agents.market_researcher.schemas import Indicator, MarketResearchOutput

# Headline rows shown in chat; the full set stays in the JSON file.
HEADLINE_INDICATORS = ("DGS10", "DGS2", "T10Y3M", "DFF", "CPILFESL", "UNRATE", "PAYEMS", "BAMLH0A0HYM2", "NFCI")
HEADLINE_PRICES = ("SPY", "^VIX", "CL=F", "DX-Y.NYB", "GLD")
_PHASE_LABELS = {
    "early_expansion": "Early expansion",
    "late_expansion": "Late expansion",
    "recession": "Recession",
    "late_recession": "Late recession (trough forming)",
}


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"


def _change(i: Indicator, key: str) -> str:
    v = i.changes.get(key)
    if v is None:
        return "-"
    return f"{v:+.2f}%" if i.source != "FRED" else f"{v:+.2f}"


def render_markdown(output: MarketResearchOutput, disclaimer: str) -> str:
    r = output.regime
    lines = [f"**Market research - {output.region}, as of {output.as_of}**", ""]
    if r.phase:
        probs = ", ".join(f"{k.replace('_', ' ')} {v * 100:.0f}%" for k, v in sorted(r.probabilities.items(), key=lambda kv: -kv[1]))
        lines.append(f"**Cycle phase: {_PHASE_LABELS[r.phase]}** ({r.confidence} confidence; {probs})")
    else:
        lines.append("**Cycle phase: not classified** (insufficient macro data)")
    if r.recession_prob_12m is not None:
        lines.append(f"Yield-curve model 12-month recession probability: {r.recession_prob_12m * 100:.0f}% (NY Fed probit, model estimate)")
    if r.conflicting_signals:
        lines.append(f"Main conflicting signal: {r.conflicting_signals[0]}")

    if output.narrative:
        lines += ["", output.narrative]

    if output.events:
        lines += ["", "**Notable events**"]
        lines += [f"- {e.description}" for e in output.events if e.severity != "info"][:6] or [f"- {output.events[0].description}"]

    by_id = {i.id: i for i in output.indicators}
    rows = [by_id[i] for i in HEADLINE_INDICATORS if i in by_id]
    if rows:
        lines += ["", "| Indicator | Latest | As of | 1m | 1y |", "|---|---|---|---|---|"]
        for i in rows:
            stale = " (stale)" if i.stale else ""
            lines.append(f"| {i.name} | {_fmt(i.value)} {i.unit}{stale} | {i.observation_date} | {_change(i, '1m')} | {_change(i, '1y')} |")

    prices = {m.id: m for m in output.market_snapshot}
    prow = [prices[s] for s in HEADLINE_PRICES if s in prices]
    if prow:
        lines += ["", "| Market | Last | 1w | 1m | 1y |", "|---|---|---|---|---|"]
        for m in prow:
            lines.append(f"| {m.name} | {_fmt(m.value)} | {_change(m, '1w')} | {_change(m, '1m')} | {_change(m, '1y')} |")

    if output.news:
        lines += ["", "**Recent news**"]
        lines += [f"- [{n.title}]({n.url}) - {n.source}" for n in output.news[:5]]

    dq = output.data_quality
    gaps = dq.failed_sources + [f"{s} stale" for s in dq.stale_series]
    if gaps:
        lines += ["", f"_Data gaps: {', '.join(gaps)}_"]
    lines += ["", f"_Sources: FRED, Yahoo Finance, Tavily news. Run `{output.run_id}`. {disclaimer}_"]
    return "\n".join(lines)

