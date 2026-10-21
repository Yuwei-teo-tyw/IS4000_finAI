"""
Optional LLM synthesis (guide §6) - only when the request sets
`include_narrative=True`; normally the main agent does the synthesis from
the structured JSON.

The model sees a compact JSON payload (never raw series) and must use only
numbers present in it. A number validator enforces that: every number in
the narrative/themes/risks/implications must match - within the rounding
the text used - a value in the payload (also as x100, for probabilities
written as % and pp changes written as bp). Dates, years, tenors ("10Y",
"3 months") and indicator ids are ignored. The payload includes the validated
event explanations and decompositions, so their numbers are allowed too. It also rejects wording the
data can't back ("YTD", "record high"); a label reminder follows the
payload, since that wording is the most common first-draft failure. On
failure the model gets one retry with the problems listed and its draft
quoted in the same user turn (not replayed as a plain-text assistant turn,
which led the model to answer the retry in plain JSON instead of the tool
call - Groq's 400 tool_use_failed). Each call is re-asked once if that 400
still happens. If the retry fails validation too, a deterministic template
narrative is used and `data_quality.notes` says so.
"""
import json
import logging
import re
from typing import Any, Iterable, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.market_researcher.news_tagging import with_max_tokens
from app.agents.market_researcher.schemas import MarketResearchOutput
from app.core import get_groq_model
from app.prompts.prompt_builder import get_prompt

SYNTHESIS_MAX_TOKENS = 6000

logger = logging.getLogger("market_researcher")


class Implication(BaseModel):
    area: str = Field(description="e.g. equities, duration, credit, sectors, usd, commodities")
    text: str


class SynthesisOut(BaseModel):
    key_themes: list[str] = Field(description="3-6 short bullets")
    risks: list[str] = Field(description="2-5 bullets, upside and downside")
    implications: list[Implication] = Field(description="Descriptive, not advice")
    narrative: str = Field(description="150-300 words")


# --- payload ----------------------------------------------------------------

def build_payload(output: MarketResearchOutput) -> dict:
    r = output.regime
    return {
        "as_of": output.as_of.isoformat(),
        "region": output.region,
        "query": output.request.query,
        "focus": output.request.focus,
        "regime": {
            "phase": r.phase,
            "confidence": r.confidence,
            "probabilities": r.probabilities,
            "recession_prob_12m": r.recession_prob_12m,
            "recession_prob_12m_source": "NY Fed yield-curve probit (model estimate) [T10Y3M]",
            "composites": r.composites,
            "drivers": [d.model_dump() for d in r.drivers],
            "conflicting_signals": r.conflicting_signals[:5],
            "previous_phase": r.previous_phase,
        },
        "events": [e.model_dump() for e in output.events],
        "indicators": [
            {
                "id": i.id, "name": i.name, "value": i.value, "unit": i.unit,
                "observation_date": i.observation_date.isoformat(), "changes": i.changes,
                "percentile_10y": i.percentile_10y, "signal": i.signal, "stale": i.stale,
            }
            for i in output.indicators
        ],
        "market": [
            {"id": m.id, "name": m.name, "value": m.value, "unit": m.unit, "date": m.observation_date.isoformat(),
             # explicit keys - with bare "1y" the model kept calling trailing returns "YTD"
             **{f"trailing_{k}_pct": v for k, v in m.changes.items()}}
            for m in output.market_snapshot
        ],
        "event_explanations": [
            {"event_id": x.event_id, "status": x.status, "explanation": x.explanation,
             "likely_drivers": x.likely_drivers, "decomposition": x.decomposition, "cited_urls": x.cited_urls,
             "cited_indicators": x.cited_indicators}
            for x in output.event_explanations
            if x.status in ("explained", "insufficient_evidence") or x.decomposition
        ],
        # Extras the query planner pulled for this request (code-derived numbers).
        "planned_indicators": [
            {"id": i.id, "name": i.name, "value": i.value, "unit": i.unit,
             "observation_date": i.observation_date.isoformat(), "changes": i.changes,
             "percentile_10y": i.percentile_10y, "stale": i.stale}
            for i in output.planned_indicators
        ],
        "planned_market": [
            {"id": m.id, "name": m.name, "value": m.value, "unit": m.unit, "date": m.observation_date.isoformat(),
             **{f"trailing_{k}_pct": v for k, v in m.changes.items()}}
            for m in output.planned_market
        ],
        "news": [
            {"title": n.title, "url": n.url, "summary": n.summary, "topics": n.topics,
             "sentiment": n.sentiment, "impact": n.market_impact,
             "published": n.published_at.date().isoformat() if n.published_at else None}
            for n in output.news
        ],
        "data_quality": output.data_quality.model_dump(),
    }


# --- number validator ---------------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.])[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+−]?\d+(?:\.\d+)?")
_IGNORED_SPANS = [
    re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b"),                                    # dates
    re.compile(r"\b[A-Z][A-Z0-9^=.\-]*\d[A-Z0-9^=.\-]*\b"),                      # ids: DGS10, T10Y3M, CL=F
    re.compile(r"\b\d+(?:\.\d+)?\s*-?\s*(?:y|yr|yrs|year|years|m|mo|mos|month|months|w|wk|wks|week|weeks|"
               r"d|day|days|q|quarter|quarters|h|hour|hours)\b", re.IGNORECASE),  # tenors / periods
    re.compile(r"\b\d+(?:st|nd|rd|th)\b"),                                       # ordinals
    re.compile(r"\bQ[1-4]\b"),
    re.compile(r"https?://\S+"),
    re.compile(r"\bS&P\s*500\b|\bNasdaq-100\b|\bRussell\s*2000\b", re.IGNORECASE),
]


def _parse_number(token: str) -> float:
    return float(token.replace(",", "").replace("−", "-").lstrip("+"))


def extract_numbers(text: str) -> list[str]:
    """Number tokens in `text` that must be backed by data."""
    for pattern in _IGNORED_SPANS:
        text = pattern.sub(" ", text)
    tokens = []
    for token in _NUMBER.findall(text):
        value = _parse_number(token)
        if "." not in token and "," not in token and 1900 <= value <= 2100:
            continue  # a year
        tokens.append(token)
    return tokens


def _walk(obj: Any) -> Iterable[Any]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def allowed_numbers(payload: dict) -> set[float]:
    allowed: set[float] = set()
    for leaf in _walk(payload):
        if isinstance(leaf, bool) or leaf is None:
            continue
        if isinstance(leaf, (int, float)):
            allowed.update({float(leaf), float(leaf) * 100})
        elif isinstance(leaf, str):
            for token in _NUMBER.findall(leaf):
                allowed.add(_parse_number(token))
    return {abs(v) for v in allowed}


def _tolerance(token: str) -> float:
    decimals = len(token.split(".")[1]) if "." in token else 0
    return 0.5 * 10 ** -decimals + 1e-9


def invalid_numbers(texts: Iterable[str], allowed: set[float]) -> list[str]:
    bad = []
    for text in texts:
        for token in extract_numbers(text):
            value, tol = abs(_parse_number(token)), _tolerance(token)
            if not any(abs(value - a) <= tol for a in allowed):
                bad.append(token)
    return sorted(set(bad))


# Wording the data rarely supports; flagged unless the payload itself uses it.
_UNSUPPORTED_LABELS = {
    "YTD / year-to-date (the data has trailing-window changes only)": re.compile(r"\bYTD\b|year[- ]to[- ]date", re.IGNORECASE),
    "record / all-time / near-record (the data gives 10-year percentiles and 'highest since' events)":
        re.compile(r"\ball[- ]time\b|\brecord\b|near[- ]record", re.IGNORECASE),
}


def unsupported_labels(texts: Iterable[str], payload: dict) -> list[str]:
    payload_text = json.dumps(payload, default=str)
    joined = " ".join(texts)
    return [
        label for label, pattern in _UNSUPPORTED_LABELS.items()
        if pattern.search(joined) and not pattern.search(payload_text)
    ]


def problems(texts: list[str], allowed: set[float], payload: dict) -> list[str]:
    bad = invalid_numbers(texts, allowed)
    found = [f"numbers not in the data: {', '.join(bad)}"] if bad else []
    return found + [f"unsupported wording: {label}" for label in unsupported_labels(texts, payload)]


def _texts(s: SynthesisOut) -> list[str]:
    return [s.narrative, *s.key_themes, *s.risks, *(i.text for i in s.implications)]


# --- template fallback --------------------------------------------------------

def template_synthesis(output: MarketResearchOutput) -> SynthesisOut:
    r = output.regime
    parts = [f"As of {output.as_of}, "]
    if r.phase:
        probs = ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(r.probabilities.items(), key=lambda kv: -kv[1]))
        parts.append(f"the rule-based classifier places the {output.region} cycle in {r.phase} "
                     f"with {r.confidence} confidence ({probs}).")
    else:
        parts.append("there is not enough macro data to classify the cycle phase.")
    if r.recession_prob_12m is not None:
        parts.append(f" The NY Fed yield-curve model implies a {r.recession_prob_12m * 100:.0f}% probability of "
                     "recession within 12 months [T10Y3M] (a model estimate).")
    if output.events:
        parts.append(" Notable: " + " ".join(e.description for e in output.events[:4]))
    decompositions = [x.decomposition["description"] for x in output.event_explanations
                      if x.decomposition and x.decomposition.get("description")]
    if decompositions:
        parts.append(" " + " ".join(decompositions))
    if r.conflicting_signals:
        parts.append(f" Main conflicting signal: {r.conflicting_signals[0]}.")
    dq = output.data_quality
    if dq.failed_sources or dq.stale_series:
        parts.append(" Data gaps: " + ", ".join(dq.failed_sources + [f"{s} (stale)" for s in dq.stale_series]) + ".")
    themes = [f"Cycle phase: {r.phase or 'unclassified'} ({r.confidence} confidence)."]
    themes += [e.description for e in output.events[:4]]
    risks = r.conflicting_signals[:4] or ["No conflicting signals flagged by the classifier."]
    return SynthesisOut(key_themes=themes, risks=risks, implications=[], narrative="".join(parts))


# --- entry point --------------------------------------------------------------

def _apply(output: MarketResearchOutput, s: SynthesisOut, implications: Optional[dict[str, str]]) -> None:
    output.key_themes = s.key_themes
    output.risks = s.risks
    output.implications = implications
    output.narrative = s.narrative


async def _invoke(writer, messages: list) -> SynthesisOut:
    """One structured call, re-asked once if Groq rejects the output because the
    model answered in plain text instead of the tool call (400 tool_use_failed).
    Other errors are not retried here."""
    try:
        return await writer.ainvoke(messages)
    except Exception as e:
        if "tool_use_failed" not in str(e):
            raise
        logger.info("stage=synthesis re-asking after tool_use_failed")
        return await writer.ainvoke(messages)


async def synthesize(output: MarketResearchOutput) -> None:
    """Fill the narrative fields on `output` in place."""
    payload = build_payload(output)
    allowed = allowed_numbers(payload)
    messages = [
        SystemMessage(content=get_prompt("market_researcher.synthesis_system")),
        HumanMessage(content=json.dumps(payload, default=str)
                     + "\n\n" + get_prompt("market_researcher.synthesis_label_reminder")),
    ]
    try:
        writer = with_max_tokens(get_groq_model(), SYNTHESIS_MAX_TOKENS).with_structured_output(SynthesisOut)
        draft = await _invoke(writer, messages)
        found = problems(_texts(draft), allowed, payload)
        if found:
            note = "; ".join(found)
            # The draft goes inside the user turn so the model revises it rather
            # than starting over, without a plain-JSON assistant turn to imitate.
            messages.append(HumanMessage(content=get_prompt(
                "market_researcher.synthesis_retry_note",
                problems=note, numbers=note, draft=draft.model_dump_json())))
            draft = await _invoke(writer, messages)
            found = problems(_texts(draft), allowed, payload)
        if not found:
            _apply(output, draft, {i.area: i.text for i in draft.implications})
            return
        reason = "had " + "; ".join(found)
    except Exception as e:
        reason = f"LLM call failed ({type(e).__name__})"
    use_template(output, f"the LLM draft {reason}")


def use_template(output: MarketResearchOutput, reason: str) -> None:
    """Replace the narrative fields with the deterministic template and say why."""
    _apply(output, template_synthesis(output), None)
    output.data_quality.notes.append(f"Narrative is a deterministic template: {reason}.")
