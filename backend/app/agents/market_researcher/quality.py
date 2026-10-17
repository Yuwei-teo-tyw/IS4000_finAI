"""
Final quality gate - the last stage before a run's JSON is written, so both
consumers (the HTTP orchestrator and the chat) get the same verdict.

Two parts, both deterministic (no LLM):

1. **Advice-language screen.** The number validators check figures, not tone.
   This screens every LLM-written text (event explanations, narrative,
   themes, risks, implications) for recommendation/guarantee wording. A
   flagged explanation becomes `unavailable` (its code-derived decomposition
   is kept); a flagged narrative is replaced by the deterministic template.
   Explanations are screened before the narrative is written, so the
   narrative never builds on a flagged explanation.

2. **Assessment** -> `output.quality`:
   - consistency: probabilities sum to 1, event evidence ids exist in the
     output, explanations link to real events, cited URLs match their sources;
   - completeness: key indicators / symbols and the regime phase present,
     news present when it was expected;
   - freshness: key indicators not stale;
   - sources: no core source failed (`planned:` extras don't count);
   - advice_language: nothing had to be screened out.
   status = `unusable` (no FRED indicators or no regime phase), `degraded`
   (any check failed), else `ok`.
"""
import re
from typing import Iterable

from app.agents.market_researcher import config as cfg
from app.agents.market_researcher.schemas import EventExplanation, MarketResearchOutput, QualityReport

# Recommendation / guarantee wording. Kept narrow so descriptive market
# language ("selloff", "buyers", "the risk-free rate") is not flagged.
ADVICE_PATTERNS: dict[str, re.Pattern] = {
    "direct instruction": re.compile(r"\byou (?:should|must|need to|ought to)\b", re.IGNORECASE),
    "recommendation": re.compile(r"\b(?:we|i) (?:recommend|suggest|advise)\b", re.IGNORECASE),
    "trade suggestion": re.compile(
        r"\b(?:should|consider|worth|time to)\s+(?:buying|selling|shorting|adding|trimming|reducing|"
        r"rotating|overweighting|underweighting|accumulating)\b", re.IGNORECASE),
    "positioning call": re.compile(r"\b(?:overweight|underweight)\b", re.IGNORECASE),
    "buy/sell call": re.compile(r"\b(?:buy|sell)\s+(?:now|signal|rating|the dip)\b", re.IGNORECASE),
    "guarantee": re.compile(r"\bguarantee(?:d|s)?\b|\brisk[- ]free\b(?!\s+(?:rate|yield|asset))|\bcan(?:not|'t) lose\b",
                            re.IGNORECASE),
}


def advice_problems(texts: Iterable[str]) -> list[str]:
    """Labels of the advice patterns found in `texts` (empty = clean)."""
    joined = " ".join(t for t in texts if t)
    return [label for label, pattern in ADVICE_PATTERNS.items() if pattern.search(joined)]


def screen_explanations(explanations: list[EventExplanation]) -> tuple[list[EventExplanation], list[str]]:
    """Explanations with advice wording become `unavailable` (decomposition kept)."""
    out, notes = [], []
    for x in explanations:
        found = advice_problems([x.explanation or "", *x.likely_drivers]) if x.status == "explained" else []
        if found:
            out.append(EventExplanation(event_id=x.event_id, status="unavailable", decomposition=x.decomposition,
                                        queries_run=x.queries_run))
            notes.append(f"Event explanation for {x.event_id} withheld: advice-like wording ({', '.join(found)}).")
        else:
            out.append(x)
    return out, notes


def narrative_texts(output: MarketResearchOutput) -> list[str]:
    return [output.narrative or "", *(output.key_themes or []), *(output.risks or []),
            *(output.implications or {}).values()]


def screen_narrative(output: MarketResearchOutput) -> list[str]:
    """Replace a narrative with advice wording by the deterministic template.
    Returns the patterns found (empty = clean or no narrative)."""
    if output.narrative is None:
        return []
    found = advice_problems(narrative_texts(output))
    if found:
        from app.agents.market_researcher.synthesis import use_template

        use_template(output, f"the LLM draft had advice-like wording ({', '.join(found)})")
    return found


def assess(output: MarketResearchOutput, news_expected: bool, screened: list[str]) -> QualityReport:
    """Build the run's QualityReport. `screened` lists what the advice screen removed."""
    issues: dict[str, list[str]] = {k: [] for k in ("consistency", "completeness", "freshness", "sources",
                                                    "advice_language")}
    r = output.regime
    indicators = {i.id: i for i in output.indicators}
    symbols = {m.id for m in output.market_snapshot}

    # consistency
    if r.probabilities and abs(sum(r.probabilities.values()) - 1) > cfg.QUALITY_PROBABILITY_TOLERANCE:
        issues["consistency"].append(f"regime probabilities sum to {sum(r.probabilities.values()):.3f}, not 1")
    known_ids = set(indicators) | symbols
    for e in output.events:
        missing = [sid for sid in e.evidence if sid not in known_ids]
        if missing:
            issues["consistency"].append(f"event {e.id} cites evidence not in the output: {', '.join(missing)}")
    event_ids = {e.id for e in output.events}
    for x in output.event_explanations:
        if x.event_id not in event_ids:
            issues["consistency"].append(f"explanation for unknown event {x.event_id}")
        if x.status == "explained" and (not x.cited_urls or x.cited_urls != [s.url for s in x.cited_sources]):
            issues["consistency"].append(f"explanation for {x.event_id} has cited URLs without matching sources")

    # completeness
    if not output.indicators:
        issues["completeness"].append("no FRED indicators")
    if r.phase is None:
        issues["completeness"].append("no regime phase")
    missing_key = [sid for sid in cfg.QUALITY_KEY_INDICATORS if sid not in indicators]
    missing_key += [sym for sym in cfg.QUALITY_KEY_SYMBOLS if sym not in symbols]
    if missing_key and output.indicators:
        issues["completeness"].append(f"key series missing: {', '.join(missing_key)}")
    if news_expected and not output.news:
        issues["completeness"].append("no news items")

    # freshness
    stale = [sid for sid in cfg.QUALITY_KEY_INDICATORS if sid in indicators and indicators[sid].stale]
    if stale:
        issues["freshness"].append(f"key indicators stale: {', '.join(stale)}")

    # sources (planner extras failing doesn't degrade the core output)
    core_failed = [s for s in output.data_quality.failed_sources if not s.startswith("planned:")]
    if core_failed:
        issues["sources"].append(f"failed sources: {', '.join(core_failed)}")

    # advice language
    issues["advice_language"] += screened

    checks = {name: not found for name, found in issues.items()}
    all_issues = [f"{name}: {msg}" for name, found in issues.items() for msg in found]
    if not output.indicators or r.phase is None:
        status = "unusable"
    elif all_issues:
        status = "degraded"
    else:
        status = "ok"
    return QualityReport(status=status, checks=checks, issues=all_issues)
