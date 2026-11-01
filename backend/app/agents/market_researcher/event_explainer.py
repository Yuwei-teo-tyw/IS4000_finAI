"""
Event explanations: for the top major/notable events, gather code-derived
context (evidence + configured context indicators, plus a decomposition
where one exists), run targeted news searches, and have the LLM write a
short, cited "why it happened" - one batched structured call for all events.

Guarantees, enforced in code:
- the model refers to articles by number; code maps numbers to URLs, so it
  cannot invent a source, and citations outside the provided set are dropped;
- every number in the explanation must appear in the event's description,
  context, decomposition or the *cited* articles' title/snippet (the same
  validator as the narrative, synthesis.problems);
- failing events get one retry with their problems listed, then become
  `unavailable` (keeping the code-derived decomposition);
- any LLM failure or timeout degrades to `unavailable`, never fails the run.
"""
import asyncio
import dataclasses
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.market_researcher import config as cfg
from app.agents.market_researcher import features as f
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.adapters.news import NewsProvider, RawNewsItem, rank_news
from app.agents.market_researcher.decompositions import DECOMPOSITIONS
from app.agents.market_researcher.news_tagging import keyword_tag, with_max_tokens
from app.agents.market_researcher.schemas import CitedSource, Event, EventExplanation
from app.agents.market_researcher.synthesis import allowed_numbers, problems
from app.agents.market_researcher.tracing import record_attempt, record_failure, trace_config
from app.core import get_groq_model
from app.prompts.prompt_builder import get_prompt

logger = logging.getLogger("market_researcher")

EXPLAINER_MAX_TOKENS = 4096
Series = dict[str, list[SeriesPoint]]

_SERIES_SPECS = {s.id: s for s in cfg.US_SERIES}
_SYMBOL_SPECS = {s.symbol: s for s in cfg.WATCHLIST}


class ExplanationDraft(BaseModel):
    event_id: str
    status: Literal["explained", "insufficient_evidence"]
    explanation: Optional[str] = Field(default=None, description="At most 70 words, own words.")
    likely_drivers: list[str] = Field(default_factory=list, description="1-3 short phrases.")
    cited_articles: list[int] = Field(default_factory=list, description="Numbers of the articles relied on.")
    cited_indicators: list[str] = Field(default_factory=list)
    confidence: Optional[Literal["low", "medium", "high"]] = None


class ExplainBatch(BaseModel):
    items: list[ExplanationDraft]


@dataclass
class _Case:
    event: Event
    spec: cfg.EventExplainSpec
    context: list[dict]
    decomposition: Optional[dict]
    queries: list[str]
    articles: list[RawNewsItem] = field(default_factory=list)


# --- selection and context (pure code) ----------------------------------------

def spec_for(event_id: str) -> Optional[cfg.EventExplainSpec]:
    """Longest matching event-id prefix in EVENT_EXPLAIN_SPECS."""
    matches = [p for p in cfg.EVENT_EXPLAIN_SPECS if event_id.startswith(p)]
    return cfg.EVENT_EXPLAIN_SPECS[max(matches, key=len)] if matches else None


def select_events(events: list[Event]) -> list[Event]:
    """Major/notable events in the existing severity order, capped."""
    return [e for e in events if e.severity in ("major", "notable")][:cfg.EXPLAIN_MAX_EVENTS]


def _points(sid: str, series: Series, prices: Series, as_of: date) -> tuple[list[SeriesPoint], bool]:
    if sid in series:
        return f.truncate(series[sid], as_of), False
    return f.truncate(prices.get(sid) or [], as_of), True


def context_for(event: Event, spec: cfg.EventExplainSpec, series: Series, prices: Series, as_of: date) -> list[dict]:
    """Latest value, date and 1w/1m change for the evidence + context ids."""
    out = []
    for sid in dict.fromkeys([*event.evidence, *spec.context_series, *spec.context_symbols]):
        pts, is_price = _points(sid, series, prices, as_of)
        if not pts:
            continue
        meta = _SYMBOL_SPECS.get(sid) if is_price else _SERIES_SPECS.get(sid)
        changes = {}
        for label, days in (("1w", 7), ("1m", 30)):
            delta = f.pct_change_over(pts, days) if is_price else f.change_over(pts, days)
            if delta is not None:
                changes[label] = round(delta, 2 if is_price else 4)
        out.append({
            "id": sid, "name": meta.name if meta else sid, "value": round(pts[-1].value, 4),
            "unit": meta.unit if meta else "", "date": pts[-1].date.isoformat(), "changes": changes,
            "change_unit": "% (price change)" if is_price else "own unit (pp for % values)",
        })
    return out


def fill_templates(event: Event, spec: cfg.EventExplainSpec, series: Series, prices: Series, as_of: date) -> list[str]:
    """{direction} from the sign of the first evidence series' 1m change;
    {month_year} from its latest observation."""
    direction, month_year = spec.direction_words[0], as_of.strftime("%B %Y")
    if event.evidence:
        pts, is_price = _points(event.evidence[0], series, prices, as_of)
        if pts:
            month_year = pts[-1].date.strftime("%B %Y")
            change = f.pct_change_over(pts, 30) if is_price else f.change_over(pts, 30)
            if change is not None and change < 0:
                direction = spec.direction_words[1]
    return [t.format(direction=direction, month_year=month_year) for t in spec.query_templates]


def reusable_news(raw_news: list[RawNewsItem], spec: cfg.EventExplainSpec) -> list[RawNewsItem]:
    """Already-fetched items whose keyword topics match the event's topics."""
    topics = set(spec.topics)
    return [dataclasses.replace(i) for i in raw_news if topics & set(keyword_tag(i).topics)]


# --- search ---------------------------------------------------------------------

async def _search(cases: list[_Case], raw_news: list[RawNewsItem], provider: Optional[NewsProvider],
                  now: datetime) -> int:
    """Fill each case's top articles; returns the number of failed searches."""
    jobs = [(case, q) for case in cases for q in case.queries] if provider is not None else []
    results = await asyncio.gather(
        *(provider.search(q, case.spec.lookback_days, cfg.NEWS_RESULTS_PER_QUERY) for case, q in jobs),
        return_exceptions=True,
    )
    found: dict[int, list[RawNewsItem]] = {id(c): [] for c in cases}
    failed = 0
    for (case, _), res in zip(jobs, results):
        if isinstance(res, Exception):
            failed += 1
        else:
            found[id(case)].extend(res)
    for case in cases:
        pool = found[id(case)] + reusable_news(raw_news, case.spec)
        case.articles = rank_news(
            pool, case.queries, case.spec.lookback_days, cfg.EXPLAIN_MAX_ARTICLES, cfg.NEWS_TITLE_SIMILARITY,
            focus_terms=[case.event.description], now=now,
        )
    return failed


# --- LLM input and validation ---------------------------------------------------

def _article(item: RawNewsItem, n: int) -> dict:
    return {
        "n": n, "title": item.title, "source": item.source,
        "published": item.published_at.date().isoformat() if item.published_at else None,
        "snippet": item.snippet[:cfg.EXPLAIN_SNIPPET_CHARS],
    }


def build_input(cases: list[_Case]) -> str:
    return json.dumps([
        {
            "event_id": c.event.id, "description": c.event.description, "context_indicators": c.context,
            "decomposition": c.decomposition,
            "articles": [_article(a, n) for n, a in enumerate(c.articles, start=1)],
        }
        for c in cases
    ], default=str)


def validate(draft: ExplanationDraft, case: _Case) -> tuple[EventExplanation, list[str]]:
    """Map article numbers to URLs, drop invalid citations, check numbers and length.
    Returns (explanation, problems); problems non-empty means the draft failed."""
    base = EventExplanation(event_id=case.event.id, status="insufficient_evidence",
                            decomposition=case.decomposition, queries_run=case.queries)
    text = (draft.explanation or "").strip()
    if draft.status == "insufficient_evidence" or not text:
        return base, []

    valid_n = range(1, len(case.articles) + 1)
    cited_n = list(dict.fromkeys(n for n in draft.cited_articles if n in valid_n))
    provided_ids = {c["id"] for c in case.context}
    cited_ids = list(dict.fromkeys(i for i in draft.cited_indicators if i in provided_ids))
    if not cited_n:
        return base, []  # an explanation must cite at least one provided article

    drivers = [d.strip() for d in draft.likely_drivers if d.strip()][:3]
    payload = {
        "description": case.event.description, "context": case.context, "decomposition": case.decomposition,
        "articles": [_article(case.articles[n - 1], n) for n in cited_n],
    }
    found = problems([text, *drivers], allowed_numbers(payload), payload)
    words = len(text.split())
    if words > cfg.EXPLAIN_MAX_WORDS:
        found.append(f"explanation is {words} words (max {cfg.EXPLAIN_MAX_WORDS})")
    if found:
        return base, found
    return base.model_copy(update={
        "status": "explained", "explanation": text, "likely_drivers": drivers,
        "cited_urls": [case.articles[n - 1].url for n in cited_n],
        "cited_sources": [_source(case.articles[n - 1]) for n in cited_n],
        "cited_indicators": cited_ids,
        "confidence": draft.confidence,
    }), []


def _source(item: RawNewsItem) -> CitedSource:
    return CitedSource(url=item.url, title=item.title, source=item.source, published_at=item.published_at,
                       snippet=item.snippet[:cfg.EXPLAIN_SNIPPET_CHARS], retrieved_at=item.retrieved_at)


def _unavailable(case: _Case) -> EventExplanation:
    return EventExplanation(event_id=case.event.id, status="unavailable",
                            decomposition=case.decomposition, queries_run=case.queries)


_PROMPT_KEYS = ("market_researcher.event_explainer_system", "market_researcher.event_explainer_retry_note")


async def _invoke(writer, messages: list, deadline: float) -> ExplainBatch:
    """One structured call, re-asked once if the provider rejects the output
    (Groq returns 400 when the model answers in prose / a bare list instead of
    the tool call). Timeouts are not retried."""
    config = trace_config("event_explainer", _PROMPT_KEYS)
    try:
        return await asyncio.wait_for(writer.ainvoke(messages, config=config),
                                      timeout=max(1.0, deadline - time.monotonic()))
    except asyncio.TimeoutError:
        raise
    except Exception as e:
        if deadline - time.monotonic() < 2.0:
            raise
        logger.debug("stage=explain_llm re-asking after %s", type(e).__name__)
        return await asyncio.wait_for(writer.ainvoke(messages, config=config),
                                      timeout=max(1.0, deadline - time.monotonic()))


async def _write(cases: list[_Case], timeout: float) -> tuple[dict[str, EventExplanation], list[str]]:
    """One batched call (+ one retry for failing events)."""
    by_id = {c.event.id: c for c in cases}
    results: dict[str, EventExplanation] = {}
    writer = with_max_tokens(get_groq_model(), EXPLAINER_MAX_TOKENS).with_structured_output(ExplainBatch)
    messages = [
        SystemMessage(content=get_prompt("market_researcher.event_explainer_system")),
        HumanMessage(content=build_input(cases)),
    ]
    deadline = time.monotonic() + timeout

    def check(batch: ExplainBatch, wanted: set[str]) -> dict[str, list[str]]:
        failing: dict[str, list[str]] = {}
        drafts = {d.event_id: d for d in batch.items if d.event_id in wanted}
        for eid in wanted:
            if eid not in drafts:
                failing[eid] = ["no item returned for this event"]
                continue
            explanation, found = validate(drafts[eid], by_id[eid])
            if found:
                failing[eid] = found
            else:
                results[eid] = explanation
        return failing

    async def attempt(wanted: set[str]) -> tuple[ExplainBatch, dict[str, list[str]]]:
        started = time.monotonic()
        try:
            batch = await _invoke(writer, messages, deadline)
        except Exception as e:
            record_failure("event_explainer", started, e)
            raise
        failing = check(batch, wanted)
        record_attempt("event_explainer", started, [f"{eid}: {', '.join(p)}" for eid, p in failing.items()],
                       batch.model_dump_json() if failing else None)
        return batch, failing

    batch, failing = await attempt(set(by_id))
    if failing:
        listing = "; ".join(f"{eid}: {', '.join(p)}" for eid, p in failing.items())
        # The draft goes inside the user turn, as in synthesis.py: a plain-JSON
        # assistant turn leads the model to skip the tool call (Groq's 400).
        messages.append(HumanMessage(content=get_prompt("market_researcher.event_explainer_retry_note",
                                                        problems=listing, draft=batch.model_dump_json())))
        batch, failing = await attempt(set(failing))
    notes = []
    for eid, found in failing.items():
        results[eid] = _unavailable(by_id[eid])
        notes.append(f"Event explanation for {eid} unavailable: draft {'; '.join(found)}.")
    return results, notes


# --- entry point ------------------------------------------------------------------

async def explain_events(
    events: list[Event],
    series: Series,
    prices: Series,
    news_items: list[RawNewsItem],
    as_of: date,
    budget_s: float,
    news_provider: Optional[NewsProvider],
    now: Optional[datetime] = None,
) -> tuple[list[EventExplanation], list[str]]:
    """Returns (one EventExplanation per selected event, data-quality notes)."""
    selected = select_events(events)
    if not selected:
        return [], []
    if budget_s < cfg.EXPLAIN_MIN_BUDGET_S:
        return (
            [EventExplanation(event_id=e.id, status="skipped") for e in selected],
            [f"Event explanations skipped: {budget_s:.0f}s of run budget left (needs {cfg.EXPLAIN_MIN_BUDGET_S:.0f}s)."],
        )

    deadline = time.monotonic() + budget_s
    now = now or datetime.now(timezone.utc)
    out: dict[str, EventExplanation] = {}
    cases: list[_Case] = []
    for event in selected:
        spec = spec_for(event.id)
        if spec is None:
            out[event.id] = EventExplanation(event_id=event.id, status="skipped")
            continue
        fn = DECOMPOSITIONS.get(spec.decomposition) if spec.decomposition else None
        cases.append(_Case(
            event=event, spec=spec, context=context_for(event, spec, series, prices, as_of),
            decomposition=fn(series, as_of, event) if fn else None,
            queries=fill_templates(event, spec, series, prices, as_of),
        ))

    notes: list[str] = []
    started = time.monotonic()
    try:
        failed = await asyncio.wait_for(_search(cases, news_items, news_provider, now),
                                        timeout=max(1.0, deadline - time.monotonic()))
        if failed:
            notes.append(f"{failed} event-explanation news searches failed.")
    except asyncio.TimeoutError:
        notes.append("Event-explanation news searches timed out; explanations use already-fetched news only.")
        for case in cases:
            case.articles = rank_news(reusable_news(news_items, case.spec), case.queries, case.spec.lookback_days,
                                      cfg.EXPLAIN_MAX_ARTICLES, cfg.NEWS_TITLE_SIMILARITY,
                                      focus_terms=[case.event.description], now=now)
    logger.debug("stage=explain_search explain_search_ms=%d", int((time.monotonic() - started) * 1000))

    # Nothing to cite -> no LLM call needed.
    for case in cases:
        if not case.articles:
            out[case.event.id] = EventExplanation(event_id=case.event.id, status="insufficient_evidence",
                                                  decomposition=case.decomposition, queries_run=case.queries)
    to_write = [c for c in cases if c.articles]

    if to_write:
        started = time.monotonic()
        try:
            written, write_notes = await _write(to_write, deadline - time.monotonic())
            out.update(written)
            notes.extend(write_notes)
        except asyncio.TimeoutError:
            out.update({c.event.id: _unavailable(c) for c in to_write})
            notes.append("Event explanations unavailable: the LLM call exceeded the budget.")
        except Exception as e:
            logger.debug("stage=explain_llm failed: %s: %.500s", type(e).__name__, e)
            out.update({c.event.id: _unavailable(c) for c in to_write})
            notes.append(f"Event explanations unavailable: the LLM call failed ({type(e).__name__}).")
        logger.debug("stage=explain_llm explain_llm_ms=%d", int((time.monotonic() - started) * 1000))

    return [out[e.id] for e in selected], notes
