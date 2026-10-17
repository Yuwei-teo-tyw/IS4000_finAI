"""
Query planner: before fetching, an LLM reads the request and picks extra
FRED series, symbols and news queries - from the curated catalogs in
config.py only. It never invents ids: anything outside the catalogs (or
duplicating the core set, or over the caps) is dropped and listed in
`PlanRecord.dropped`.

One structured call under a short budget; on any failure, timeout or a plan
that validates to nothing, a keyword heuristic picks a few catalog entries
by tag instead. The extras land in planned_indicators / planned_market and
never feed the regime classifier or the event rules.
"""
import asyncio
import re
import time
from typing import Optional, get_args

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.market_researcher import config as cfg
from app.agents.market_researcher.news_tagging import with_max_tokens
from app.agents.market_researcher.schemas import MarketResearchRequest, PlanArea, PlanRecord, QueryPlan
from app.core import get_groq_model
from app.prompts.prompt_builder import get_prompt

PLANNER_MAX_TOKENS = 4096

_OPERATOR = re.compile(r"\b\w+:")
_URLISH = re.compile(r"https?://|www\.|\.com\b|\.org\b", re.IGNORECASE)


def default_news_queries(request: MarketResearchRequest) -> list[str]:
    """Today's caller-specific news queries (also the `planning="off"` behavior)."""
    return [f"{term} market news" for term in request.focus] + ([request.query] if request.query else [])


def _catalog_lines(series: tuple[cfg.SeriesSpec, ...], symbols: tuple[cfg.SymbolSpec, ...]) -> str:
    s_lines = [f"{s.id} | {s.name} | {','.join(s.tags)} | {s.description}" for s in series]
    m_lines = [f"{s.symbol} | {s.name} | {','.join(s.tags)} | {s.description}" for s in symbols]
    return "SERIES CATALOG (FRED):\n" + "\n".join(s_lines) + "\n\nSYMBOL CATALOG:\n" + "\n".join(m_lines)


def build_prompt_input(request: MarketResearchRequest, series: tuple[cfg.SeriesSpec, ...],
                       symbols: tuple[cfg.SymbolSpec, ...]) -> str:
    core_series = ", ".join(s.id for s in cfg.US_SERIES if not s.backtest_only)
    core_symbols = ", ".join(s.symbol for s in cfg.WATCHLIST)
    return (
        f"REQUEST\nquery: {request.query or '(none)'}\nfocus: {', '.join(request.focus) or '(none)'}\n"
        f"news lookback days: {request.lookback_days_news}\n\n"
        f"ALREADY COVERED - core series: {core_series}\nALREADY COVERED - core symbols: {core_symbols}\n"
        f"ALREADY COVERED - core news queries: {' | '.join(cfg.NEWS_QUERIES)}\n\n"
        + _catalog_lines(series, symbols)
    )


def _query_problem(query: str) -> Optional[str]:
    words = query.split()
    if not 3 <= len(words) <= 12:
        return "must be 3-12 words"
    if len(query) > 120:
        return "over 120 chars"
    if _URLISH.search(query):
        return "contains a URL"
    if _OPERATOR.search(query):
        return "uses a search operator"
    return None


def validate_plan(plan: QueryPlan, series: tuple[cfg.SeriesSpec, ...],
                  symbols: tuple[cfg.SymbolSpec, ...]) -> tuple[QueryPlan, list[str]]:
    """Keep only catalog ids and well-formed queries, within the caps."""
    dropped: list[str] = []
    core_series = {s.id for s in cfg.US_SERIES}
    core_symbols = {s.symbol for s in cfg.WATCHLIST}

    def pick(raw: list[str], catalog: dict[str, str], core: set[str], cap: int) -> list[str]:
        kept: list[str] = []
        for item in raw:
            norm = item.strip().upper()
            if norm in {c.upper() for c in core}:
                dropped.append(f"{item}: already in the core set")
            elif norm not in catalog:
                dropped.append(f"{item}: not in catalog")
            elif catalog[norm] in kept:
                dropped.append(f"{item}: duplicate")
            elif len(kept) >= cap:
                dropped.append(f"{item}: over the cap of {cap}")
            else:
                kept.append(catalog[norm])
        return kept

    extra_series = pick(plan.extra_series, {s.id.upper(): s.id for s in series}, core_series,
                        cfg.PLANNER_MAX_EXTRA_SERIES)
    extra_symbols = pick(plan.extra_symbols, {s.symbol.upper(): s.symbol for s in symbols}, core_symbols,
                         cfg.PLANNER_MAX_EXTRA_SYMBOLS)

    seen = {q.lower() for q in cfg.NEWS_QUERIES}
    queries: list[str] = []
    for raw in plan.news_queries:
        q = " ".join(raw.split())
        problem = _query_problem(q)
        if problem is None and q.lower() in seen:
            problem = "duplicates another query"
        if problem is None and len(queries) >= cfg.PLANNER_MAX_NEWS_QUERIES:
            problem = f"over the cap of {cfg.PLANNER_MAX_NEWS_QUERIES}"
        if problem:
            dropped.append(f"query {raw!r}: {problem}")
            continue
        seen.add(q.lower())
        queries.append(q)

    cleaned = plan.model_copy(update={
        "extra_series": extra_series, "extra_symbols": extra_symbols, "news_queries": queries,
    })
    return cleaned, dropped


def _matched_tags(request: MarketResearchRequest) -> list[str]:
    text = " ".join([request.query or "", *request.focus]).lower()
    return [
        tag for tag, words in cfg.PLANNER_TAG_KEYWORDS.items()
        if any(re.search(r"(?<![a-z])" + re.escape(w), text) for w in words)
    ]


def heuristic_plan(request: MarketResearchRequest, series: tuple[cfg.SeriesSpec, ...],
                   symbols: tuple[cfg.SymbolSpec, ...]) -> QueryPlan:
    tags = _matched_tags(request)
    n = cfg.PLANNER_HEURISTIC_PICKS
    return QueryPlan(
        intent=request.query or f"Conditions for: {', '.join(request.focus)}",
        areas=[t for t in tags if t in get_args(PlanArea)],
        extra_series=[s.id for s in series if set(s.tags) & set(tags)][:n],
        extra_symbols=[s.symbol for s in symbols if set(s.tags) & set(tags)][:n],
        news_queries=default_news_queries(request),
        rationale="Keyword fallback: catalog entries whose tags match the request's terms.",
    )


async def make_plan(
    request: MarketResearchRequest,
    catalog_series: tuple[cfg.SeriesSpec, ...] = cfg.EXTRA_SERIES_CATALOG,
    catalog_symbols: tuple[cfg.SymbolSpec, ...] = cfg.EXTRA_SYMBOL_CATALOG,
    budget_s: float = cfg.PLANNER_TIMEOUT_S,
) -> tuple[PlanRecord, list[str]]:
    """Returns (plan record, data-quality notes)."""
    if not request.query and not request.focus:
        return PlanRecord(plan=None, plan_source="skipped"), []

    started = time.monotonic()
    dropped: list[str] = []
    reason: Optional[str] = None
    try:
        planner = with_max_tokens(get_groq_model(), PLANNER_MAX_TOKENS).with_structured_output(QueryPlan)
        raw = await asyncio.wait_for(planner.ainvoke([
            SystemMessage(content=get_prompt("market_researcher.planner_system")),
            HumanMessage(content=build_prompt_input(request, catalog_series, catalog_symbols)),
        ]), timeout=budget_s)
        plan, dropped = validate_plan(raw, catalog_series, catalog_symbols)
        had_items = bool(raw.extra_series or raw.extra_symbols or raw.news_queries)
        if had_items and not (plan.extra_series or plan.extra_symbols or plan.news_queries):
            reason = "every planned item failed validation"
    except asyncio.TimeoutError:
        reason = f"timed out after {budget_s:.0f}s"
    except Exception as e:
        reason = f"failed ({type(e).__name__})"

    latency = int((time.monotonic() - started) * 1000)
    if reason is None:
        return PlanRecord(plan=plan, plan_source="llm", dropped=dropped, latency_ms=latency), []
    fallback = heuristic_plan(request, catalog_series, catalog_symbols)
    return (
        PlanRecord(plan=fallback, plan_source="heuristic", dropped=dropped, latency_ms=latency),
        [f"Query plan is a keyword heuristic: the LLM planner {reason}."],
    )
