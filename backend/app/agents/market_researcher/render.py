"""
Deterministic Markdown rendering of a MarketResearchOutput for the chat UI
(used by the optional chat trigger, nodes/market_researcher.py). Every
number shown comes straight from the output; nothing here calls an LLM.
"""
from typing import Optional

from app.agents.market_researcher.schemas import EventExplanation, Indicator, MarketResearchOutput
from app.agents.market_researcher.synthesis import TEMPLATE_NOTE_PREFIX

# Headline rows shown in chat; the full set stays in the JSON file.
HEADLINE_INDICATORS = ("DGS10", "DGS2", "T10Y3M", "DFF", "CPILFESL", "UNRATE", "PAYEMS", "BAMLH0A0HYM2", "NFCI")
HEADLINE_PRICES = ("SPY", "^VIX", "CL=F", "DX-Y.NYB", "GLD")
_PHASE_LABELS = {
    "early_expansion": "Early expansion",
    "late_expansion": "Late expansion",
    "recession": "Recession",
    "late_recession": "Late recession (trough forming)",
}


_QUALITY_WARNINGS = {
    "unusable": "**Data warning: this run is unusable. Do not rely on the cycle call or the indicators below.**",
    "degraded": "_Data warning: some of this run's data is missing, stale or was withheld, so read it with care._",
}


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"


def _change(i: Indicator, key: str) -> str:
    v = i.changes.get(key)
    if v is None:
        return "-"
    return f"{v:+.2f}%" if i.source != "FRED" else f"{v:+.2f}"


def _area_label(area: str) -> str:
    return area.upper() if len(area) <= 3 else area.replace("_", " ").capitalize()


def _explanation_lines(x: Optional[EventExplanation]) -> list[str]:
    if x is None:
        return []
    out = []
    if x.status == "explained" and x.explanation:
        source = f" [source]({x.cited_urls[0]})" if x.cited_urls else ""
        out.append(f"  - Why: {x.explanation}{source}")
    elif x.status == "insufficient_evidence":
        out.append("  - Why: Cause unclear from recent coverage.")
    if x.decomposition and x.decomposition.get("description"):
        out.append(f"  - {x.decomposition['description']}")
    return out


def render_markdown(output: MarketResearchOutput, disclaimer: str) -> str:
    r = output.regime
    lines = [f"**Market research - {output.region}, as of {output.as_of}**", ""]
    warning = _QUALITY_WARNINGS.get(output.quality.status) if output.quality else None
    if warning:
        lines += [warning, ""]
    if r.phase:
        probs = ", ".join(f"{k.replace('_', ' ')} {v * 100:.0f}%" for k, v in sorted(r.probabilities.items(), key=lambda kv: -kv[1]))
        lines.append(f"**Cycle phase: {_PHASE_LABELS[r.phase]}** ({r.confidence} confidence; uncalibrated model scores: {probs})")
    else:
        lines.append("**Cycle phase: not classified** (insufficient macro data)")
    if r.recession_prob_12m is not None:
        lines.append(f"Yield-curve model 12-month recession probability: {r.recession_prob_12m * 100:.0f}% (NY Fed probit, model estimate)")
    if r.conflicting_signals:
        lines.append(f"Main conflicting signal: {r.conflicting_signals[0]}")

    templated = any(n.startswith(TEMPLATE_NOTE_PREFIX) for n in output.data_quality.notes)
    if output.narrative:
        lines += ["", output.narrative]
        if templated:
            lines += ["", "_This summary is generated from the data alone; the written analysis was unavailable._"]
    # The template's risks only repeat the conflicting signals shown above.
    if output.risks and not templated:
        lines += ["", "**Risks**"] + [f"- {risk}" for risk in output.risks]
    if output.implications:
        lines += ["", "**Implications**"]
        lines += [f"- **{_area_label(area)}:** {text}" for area, text in output.implications.items()]

    if output.events:
        lines += ["", "**Notable events**"]
        shown = [e for e in output.events if e.severity != "info"][:6] or output.events[:1]
        explained = {x.event_id: x for x in output.event_explanations}
        for e in shown:
            lines.append(f"- {e.description}")
            lines += _explanation_lines(explained.get(e.id))

    planned = output.planned_indicators + output.planned_market
    if planned:
        lines += ["", "**Relevant to your question**", "", "| Series | Latest | As of | 1m | 1y |", "|---|---|---|---|---|"]
        for i in planned:
            stale = " (stale)" if i.stale else ""
            lines.append(f"| {i.name} | {_fmt(i.value)} {i.unit}{stale} | {i.observation_date} | {_change(i, '1m')} | {_change(i, '1y')} |")

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

