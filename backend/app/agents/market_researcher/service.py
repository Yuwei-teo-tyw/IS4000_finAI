"""
The market researcher pipeline (guide §2 execution flow):

    fetch FRED / prices / news in parallel (per-source timeouts, partial data OK)
      || query planner (LLM, catalog-only) -> extra series / symbols / news queries
      -> features -> notable events -> regime (with hysteresis)  [core data only]
      -> news tagging (one LLM call, keyword fallback)
         || event explanations (targeted news + decompositions + one cited LLM call)
      -> optional narrative (synthesis.py, number-validated)
      -> quality gate (quality.py): advice-language screen + consistency /
         completeness / freshness checks -> output.quality
      -> MarketResearchOutput, written atomically to <output_dir>/<run_id>.json

Everything except the plan, news tags, event explanations and the optional
narrative is deterministic for a given `as_of` and fetched data; planned
extras go to planned_indicators / planned_market and never reach the regime
or event rules. Any source failing is
recorded in `data_quality` instead of failing the run.
"""
import asyncio
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.agents.market_researcher import config as cfg
from app.agents.market_researcher import features as f
from app.agents.market_researcher import quality
from app.agents.market_researcher.audit import AuditLog, default_audit, sha256_of
from app.agents.market_researcher.adapters.base import SeriesPoint, SourceError
from app.agents.market_researcher.adapters.fred import FredClient
from app.agents.market_researcher.adapters.market_data import MarketDataProvider, get_market_data_provider
from app.agents.market_researcher.adapters.news import (
    NewsProvider,
    RawNewsItem,
    TavilyNewsProvider,
    rank_news,
    search_queries,
)
from app.agents.market_researcher.cache import Cache, default_cache, points_from_json, points_to_json
from app.agents.market_researcher.event_explainer import explain_events
from app.agents.market_researcher.events import detect_events
from app.agents.market_researcher.news_tagging import keyword_tag, tag_news
from app.agents.market_researcher.planner import default_news_queries, make_plan
from app.agents.market_researcher.regime import classify_regime
from app.agents.market_researcher.schemas import (
    DataQuality,
    EventExplanation,
    Indicator,
    MarketResearchOutput,
    MarketResearchRequest,
    NewsItem,
    RunOrigin,
)
from app.agents.market_researcher.tracing import RunTrace, record_failure, run_label, run_trace
from app.core.constants import CURRENT_MODEL
from app.prompts.prompt_builder import get_prompt_version

logger = logging.getLogger("market_researcher")

PLANNED_PREFIX = "planned:"
_CATALOG_SERIES = {s.id: s for s in cfg.EXTRA_SERIES_CATALOG}
_CATALOG_SYMBOLS = {s.symbol: s for s in cfg.EXTRA_SYMBOL_CATALOG}


class UnsupportedRegionError(ValueError):
    pass


@dataclass
class MarketResearchResult:
    output: MarketResearchOutput
    json_path: Path


def new_run_id(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"mr_{now:%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"


def write_json_atomic(output: MarketResearchOutput, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{output.run_id}.json"
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{output.run_id}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(output.model_dump_json(indent=2))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


class _CachedNewsProvider:
    """Wraps a NewsProvider with the TTL cache, keyed by query + lookback."""

    def __init__(self, inner: NewsProvider, cache: Cache):
        self._inner, self._cache = inner, cache
        self.name = inner.name

    async def search(self, query: str, days: int, max_results: int) -> list[RawNewsItem]:
        key = f"news:{self.name}:{days}:{max_results}:{query}"
        hit = await self._cache.get(key)
        if hit is not None:
            return [_raw_from_json(x) for x in hit]
        items = await self._inner.search(query, days, max_results)
        if items:
            await self._cache.set(key, [_raw_to_json(x) for x in items], cfg.NEWS_TTL_SECONDS)
        return items


def _raw_to_json(item: RawNewsItem) -> dict:
    return {
        "title": item.title, "url": item.url, "source": item.source,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "snippet": item.snippet, "query": item.query, "provider_score": item.provider_score,
        "retrieved_at": item.retrieved_at.isoformat() if item.retrieved_at else None,
    }


def _raw_from_json(d: dict) -> RawNewsItem:
    published = datetime.fromisoformat(d["published_at"]) if d.get("published_at") else None
    retrieved = datetime.fromisoformat(d["retrieved_at"]) if d.get("retrieved_at") else None
    return RawNewsItem(d["title"], d["url"], d["source"], published, d["snippet"], d["query"],
                       d.get("provider_score", 0.0), retrieved_at=retrieved)


class MarketResearchService:
    """One instance can serve many runs. Providers left as None are built
    from settings on first use (so missing keys surface as data-quality
    failures for that source, not as a crash)."""

    def __init__(
        self,
        settings: Optional[cfg.Settings] = None,
        cache: Optional[Cache] = None,
        fred: Optional[FredClient] = None,
        market: Optional[MarketDataProvider] = None,
        news: Optional[NewsProvider] = None,
        out_dir: Optional[Path] = None,
        audit: Optional[AuditLog] = None,
    ):
        self.settings = settings or cfg.load_settings()
        self.cache = cache or default_cache()
        self.audit = audit or default_audit()
        self._fred = fred
        self._market = market
        self._news = news
        self.out_dir = out_dir or self.settings.output_dir

    # --- providers ---------------------------------------------------------

    def _fred_client(self) -> FredClient:
        if self._fred is None:
            if not self.settings.fred_api_key:
                raise SourceError("FRED_API_KEY not set")
            self._fred = FredClient(self.settings.fred_api_key, timeout=self.settings.request_timeout_seconds)
        return self._fred

    def _market_provider(self) -> MarketDataProvider:
        if self._market is None:
            self._market = get_market_data_provider(self.settings.market_data_provider)
        return self._market

    def _news_provider(self) -> NewsProvider:
        if self._news is None:
            if self.settings.news_provider != "tavily":
                raise SourceError(f"Unknown NEWS_PROVIDER: {self.settings.news_provider!r}")
            if not self.settings.tavily_api_key:
                raise SourceError("TAVILY_API_KEY not set")
            self._news = TavilyNewsProvider(self.settings.tavily_api_key, timeout=self.settings.request_timeout_seconds)
        return self._news

    # --- fetchers ----------------------------------------------------------

    async def _fetch_series(self, spec: cfg.SeriesSpec, as_of: date, live: bool, dq: DataQuality) -> list[SeriesPoint]:
        vintage = spec.frequency in ("M", "Q") and not live
        key = f"fred:{spec.id}:{'latest' if live else as_of.isoformat()}:{'vintage' if vintage else 'revised'}"
        hit = await self.cache.get(key)
        if hit is not None:
            return points_from_json(hit)

        fred = self._fred_client()
        start = f.shift_years(as_of, -cfg.HISTORY_YEARS[spec.frequency])
        end = None if live else as_of
        points = await fred.get_series(spec.id, start, end, vintage_date=as_of if vintage else None)
        if vintage and not points:
            points = await fred.get_series(spec.id, start, end)
            dq.notes.append(f"{spec.id}: no ALFRED vintage for {as_of}; used revised data.")
        ttl = cfg.SERIES_TTL_SECONDS[spec.frequency] if live else cfg.HISTORICAL_TTL_SECONDS
        if points:  # an empty response may be transient, so it isn't kept for the whole TTL
            await self.cache.set(key, points_to_json(points), ttl)
        return points

    async def _fetch_fred(self, specs: tuple[cfg.SeriesSpec, ...], as_of: date, live: bool,
                          dq: DataQuality, prefix: str = "") -> dict[str, list[SeriesPoint]]:
        self._fred_client()  # fail fast on a missing key
        wanted = [s for s in specs if not s.backtest_only]
        per_series = self._source_timeout * cfg.FRED_SERIES_TIMEOUT_SHARE
        results = await asyncio.gather(
            *(asyncio.wait_for(self._fetch_series(s, as_of, live, dq), per_series) for s in wanted),
            return_exceptions=True,
        )
        series, failed = {}, []
        for spec, res in zip(wanted, results):
            if isinstance(res, Exception):
                failed.append(spec.id)
                logger.warning("run=%s source=%sFRED:%s failed: %r", run_label(), prefix, spec.id, res)
            elif res:
                series[spec.id] = res
            else:
                dq.notes.append(f"{prefix}FRED:{spec.id}: no observations returned.")
        if not series:
            raise SourceError(f"all {len(wanted)} FRED series failed")
        dq.failed_sources.extend(f"{prefix}FRED:{sid}" for sid in failed)
        return series

    async def _fetch_prices(self, symbols: list[str], as_of: date, live: bool,
                            dq: DataQuality, prefix: str = "") -> dict[str, list[SeriesPoint]]:
        provider = self._market_provider()
        tag = "latest" if live else as_of.isoformat()
        prices: dict[str, list[SeriesPoint]] = {}
        missing = []
        for sym in symbols:
            hit = await self.cache.get(f"prices:{sym}:{tag}")
            if hit is not None:
                prices[sym] = points_from_json(hit)
            else:
                missing.append(sym)
        if missing:
            fetched = await provider.get_histories(missing, as_of - timedelta(days=cfg.PRICE_HISTORY_DAYS), as_of)
            ttl = cfg.QUOTE_TTL_SECONDS if live else cfg.HISTORICAL_TTL_SECONDS
            for sym, pts in fetched.items():
                if pts:
                    prices[sym] = pts
                    await self.cache.set(f"prices:{sym}:{tag}", points_to_json(pts), ttl)
        if not prices:
            raise SourceError(f"{provider.name}: no prices returned")
        absent = [sym for sym in missing if sym not in prices]
        if absent:
            dq.notes.append(f"{prefix}Market data: no prices returned for {', '.join(absent)}.")
        return prices

    def _cached_news(self) -> NewsProvider:
        return _CachedNewsProvider(self._news_provider(), self.cache)

    async def _search_news(self, queries: list[str], days: int) -> tuple[list[RawNewsItem], list[str]]:
        """Raw search only - ranking happens once core and planned results are both in."""
        return await search_queries(self._cached_news(), queries, days, cfg.NEWS_RESULTS_PER_QUERY)

    async def _planned(self, request: MarketResearchRequest, as_of: date, live: bool, news_ok: bool,
                       dq: DataQuality):
        """Planner, then the extra fetches it asks for. Runs alongside the core
        fetch; every failure here is labelled `planned:` and never touches core data."""
        started = time.monotonic()
        record, notes = await make_plan(request, budget_s=cfg.PLANNER_TIMEOUT_S)
        dq.notes.extend(notes)
        logger.debug("stage=planner source=%s planner_ms=%d", record.plan_source, int((time.monotonic() - started) * 1000))
        plan = record.plan
        if plan is None:
            return record, {}, {}, ([], [])

        started = time.monotonic()
        specs = tuple(_CATALOG_SERIES[i] for i in plan.extra_series)
        p = PLANNED_PREFIX
        series, prices, news = await asyncio.gather(
            self._guarded(f"{p}FRED", self._fetch_fred(specs, as_of, live, dq, prefix=p), dq, {})
            if specs else _const({}),
            self._guarded(f"{p}Market data", self._fetch_prices(plan.extra_symbols, as_of, live, dq, prefix=p), dq, {})
            if plan.extra_symbols else _const({}),
            self._guarded(f"{p}News", self._search_news(plan.news_queries, request.lookback_days_news), dq, ([], []))
            if plan.news_queries and news_ok else _const(([], [])),
        )
        logger.debug("stage=extra_fetch extra_fetch_ms=%d", int((time.monotonic() - started) * 1000))
        return record, series, prices, news

    async def _explain(self, explain: bool, events, series, prices, raw_news, as_of: date,
                       budget_s: float) -> tuple[list[EventExplanation], list[str]]:
        if not explain:
            return [], []
        try:
            provider = self._cached_news()
        except SourceError:
            provider = None  # explain from already-fetched news only
        try:
            return await explain_events(events, series, prices, raw_news, as_of,
                                        min(cfg.EXPLAIN_TIMEOUT_S, budget_s), provider)
        except Exception as e:
            logger.warning("run=%s stage=explain failed: %r", run_label(), e)
            return [], [f"Event explanations unavailable ({type(e).__name__})."]

    @property
    def _source_timeout(self) -> float:
        return min(self.settings.source_timeout_seconds, self.settings.run_budget_seconds)

    async def _guarded(self, label: str, coro, dq: DataQuality, default):
        """Run one source under its timeout; record failure and return `default`."""
        timeout = self._source_timeout
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            logger.debug("stage=%s ok latency_ms=%d", label, int((time.monotonic() - started) * 1000))
            return result
        except asyncio.TimeoutError:
            dq.failed_sources.append(f"{label} (timed out after {timeout:.0f}s)")
        except Exception as e:
            dq.failed_sources.append(f"{label} ({e})")
        logger.warning("run=%s source failed: %s", run_label(), dq.failed_sources[-1])
        return default

    # --- assembly ----------------------------------------------------------

    @staticmethod
    def _indicators(specs, series: dict[str, list[SeriesPoint]], as_of: date, dq: DataQuality) -> list[Indicator]:
        out = []
        for spec in specs:
            if spec.backtest_only or spec.id not in series:
                continue
            feats = f.compute_indicator_features(spec, series[spec.id], as_of)
            if feats is None:
                dq.notes.append(f"{spec.id}: not enough history to compute {spec.transform}.")
                continue
            if feats.stale:
                dq.stale_series.append(spec.id)
            if feats.stats_window_years is not None and feats.stats_window_years < 9.5:
                dq.notes.append(
                    f"{spec.id}: percentile/z-score cover only {feats.stats_window_years:.1f} years "
                    "(the source's history is shorter than 10 years)."
                )
            out.append(Indicator(
                id=spec.id, name=spec.name, category=spec.category,
                value=round(feats.value, 4), unit=spec.unit, observation_date=feats.observation_date,
                changes=feats.changes,
                percentile_10y=_r(feats.percentile_10y, 1), zscore_10y=_r(feats.zscore_10y, 2),
                stats_window_years=feats.stats_window_years,
                signal=f.signal_for(feats), stale=feats.stale,
                source="FRED", source_url=cfg.FRED_SERIES_URL.format(series_id=spec.id),
            ))
        return out

    @staticmethod
    def _snapshot(symbols, prices: dict[str, list[SeriesPoint]], as_of: date, provider_name: str) -> list[Indicator]:
        out = []
        for sym in symbols:
            pts = f.truncate(prices.get(sym.symbol) or [], as_of)
            if not pts:
                continue
            changes = {}
            for label, days in cfg.PRICE_CHANGE_WINDOWS.items():
                pct = f.pct_change_over(pts, days)
                if pct is not None:
                    changes[label] = round(pct, 2)
            out.append(Indicator(
                id=sym.symbol, name=sym.name, category=sym.category,
                value=round(pts[-1].value, 4), unit=sym.unit, observation_date=pts[-1].date,
                changes=changes, signal="neutral", stale=f.is_stale("D", pts[-1].date, as_of),
                source=provider_name, source_url=cfg.YAHOO_QUOTE_URL.format(symbol=sym.symbol),
            ))
        return out

    async def _audit(self, run_id: str, event: str, details: dict) -> None:
        """An audit-store failure is logged loudly but doesn't take down the answer."""
        try:
            await self.audit.record(run_id, event, details)
        except Exception as e:
            logger.warning("audit event %s for run %s not recorded: %r", event, run_id, e)

    async def record_rendered(self, run_id: str, content: str) -> None:
        """Record the hash of the text a chat answer was rendered to."""
        await self._audit(run_id, "response_rendered", {"sha256": sha256_of(content.encode("utf-8"))})

    async def run(self, request: MarketResearchRequest, run_id: Optional[str] = None,
                  origin: Optional[RunOrigin] = None) -> MarketResearchResult:
        if request.region not in cfg.SUPPORTED_REGIONS:
            raise UnsupportedRegionError(
                f"region {request.region!r} is not supported yet (supported: {', '.join(cfg.SUPPORTED_REGIONS)})"
            )
        run_id = run_id or new_run_id()
        who = origin.model_dump() if origin else None
        logger.info("run=%s started channel=%s", run_id, origin.channel if origin else "-")
        with run_trace(run_id, origin) as trace:
            try:
                result = await self._pipeline(request, run_id, origin, trace)
            except Exception as e:
                logger.error("run=%s failed: %s: %s", run_id, type(e).__name__, e)
                await self._audit(run_id, "run_failed", {
                    "origin": who, "query": request.query, "error": f"{type(e).__name__}: {e}"[:500]})
                raise
        output = result.output
        await self._audit(run_id, "run_finished", {
            "origin": who, "sha256": sha256_of(result.json_path.read_bytes()), "quality": output.quality.status,
            "schema_version": output.schema_version, "llm_model": output.llm_model,
        })
        return result

    async def _pipeline(self, request: MarketResearchRequest, run_id: str, origin: Optional[RunOrigin],
                        trace: RunTrace) -> MarketResearchResult:
        started = time.monotonic()
        now = datetime.now(timezone.utc)
        today = now.date()
        as_of = request.as_of or today
        live = as_of >= today
        specs = cfg.SERIES_BY_REGION[request.region]
        dq = DataQuality()

        explain = request.explain_events if request.explain_events is not None else live
        if explain and not live:
            dq.notes.append("Event explanations for a past as_of search today's news index, not the news as of then.")

        news_ok = live or as_of >= today - timedelta(days=request.lookback_days_news)
        plan_wanted = request.planning == "auto"
        # planning="off": today's behavior - focus terms / query searched with the core
        # queries. "auto": the plan supplies the caller-specific queries.
        own = [] if plan_wanted else default_news_queries(request)
        news_task = None
        if not news_ok:
            dq.notes.append("News search cannot be replayed for a past as_of; news omitted.")
        else:
            news_task = self._guarded(
                "News", self._search_news(list(cfg.NEWS_QUERIES) + own, request.lookback_days_news), dq, ([], []))
        series, prices, news_result, planned = await asyncio.gather(
            self._guarded("FRED", self._fetch_fred(specs, as_of, live, dq), dq, {}),
            self._guarded("Market data", self._fetch_prices([s.symbol for s in cfg.WATCHLIST], as_of, live, dq), dq, {}),
            news_task if news_task is not None else _const(([], [])),
            self._planned(request, as_of, live, news_ok, dq) if plan_wanted else _const((None, {}, {}, ([], []))),
        )
        plan_record, planned_series, planned_prices, (planned_raw, planned_failures) = planned
        core_raw, news_failures = news_result
        news_failures = news_failures + planned_failures
        if news_failures:
            dq.notes.append(f"{len(news_failures)} news queries failed.")

        if plan_wanted and plan_record is not None and plan_record.plan is not None:
            own = plan_record.plan.news_queries
        news_pool = core_raw + planned_raw
        raw_news = rank_news(
            news_pool, list(cfg.NEWS_QUERIES) + own, request.lookback_days_news, cfg.NEWS_TOP_N,
            cfg.NEWS_TITLE_SIMILARITY, focus_terms=request.focus, priority_queries=own,
        ) if news_pool else []

        # Isolation: the regime classifier and event rules see core data only.
        assert set(series) <= {s.id for s in specs} and set(prices) <= {s.symbol for s in cfg.WATCHLIST}, \
            "planned extras must never reach the regime or event rules"
        indicators = self._indicators(specs, series, as_of, dq)
        market_name = self._market.name if self._market is not None else self.settings.market_data_provider
        snapshot = self._snapshot(cfg.WATCHLIST, prices, as_of, market_name)
        events = detect_events(series, prices, as_of)

        planned_indicators: list[Indicator] = []
        planned_market: list[Indicator] = []
        if plan_record is not None and plan_record.plan is not None:
            plan = plan_record.plan
            planned_indicators = self._indicators(
                tuple(_CATALOG_SERIES[i] for i in plan.extra_series), planned_series, as_of, dq)
            planned_market = self._snapshot(
                [_CATALOG_SYMBOLS[s] for s in plan.extra_symbols], planned_prices, as_of, market_name)
        if any(s.startswith(PLANNED_PREFIX) for s in dq.failed_sources):
            dq.notes.append("Some planned extras failed to fetch; core data is unaffected.")

        previous = await self.cache.get_regime(request.region) if live else None
        regime = classify_regime(series, as_of, previous=previous, prices=prices)
        if not series:
            regime.confidence = "low"
            dq.notes.append("No FRED data: the regime call is unavailable or low-confidence.")
        # Persist the call for hysteresis/smoothing only when the macro data was
        # complete - a degraded run must not move the shared state.
        fred_complete = not any(s.startswith("FRED") for s in dq.failed_sources)
        if live and regime.phase and fred_complete:
            await self.cache.set_regime(request.region, {
                "phase": regime.phase, "probabilities": regime.probabilities, "scores": regime.scores,
                "as_of": as_of.isoformat(),
            })

        # News tagging and event explanations both run on the LLM after events are
        # known - concurrently, each inside the remaining run budget.
        remaining = self.settings.run_budget_seconds - (time.monotonic() - started)
        news, explanations = await asyncio.gather(
            self._tag(raw_news, remaining),
            self._explain(explain, events, series, prices, news_pool, as_of, remaining),
        )
        news, tag_notes = news
        event_explanations, explain_notes = explanations
        # Quality gate, part 1: screen explanations for advice wording before
        # the narrative can build on them.
        event_explanations, screen_notes = quality.screen_explanations(event_explanations)
        dq.notes.extend(tag_notes + explain_notes + screen_notes)

        output = MarketResearchOutput(
            run_id=run_id,
            generated_at=now,
            as_of=as_of,
            region=request.region,
            request=request,
            regime=regime,
            events=events,
            indicators=indicators,
            market_snapshot=snapshot,
            news=news,
            plan=plan_record,
            planned_indicators=planned_indicators,
            planned_market=planned_market,
            event_explanations=event_explanations,
            data_quality=dq,
            llm_model=CURRENT_MODEL,
            prompt_versions={key: get_prompt_version(key) for key in cfg.PIPELINE_PROMPT_KEYS},
            origin=origin,
        )

        if request.include_narrative:
            from app.agents.market_researcher.synthesis import synthesize

            elapsed = time.monotonic() - started
            await synthesize(output, timeout=max(cfg.SYNTHESIS_MIN_BUDGET_S, self.settings.run_budget_seconds - elapsed))

        # Quality gate, part 2: screen the narrative, then the final verdict both
        # consumers (HTTP orchestrator and chat) read before using the output.
        narrative_flags = quality.screen_narrative(output)
        screened = list(screen_notes) + (
            [f"narrative replaced by the template (advice-like wording: {', '.join(narrative_flags)})"]
            if narrative_flags else [])
        output.quality = quality.assess(output, news_expected=news_ok, screened=screened)
        output.llm_attempts = trace.attempts

        path = write_json_atomic(output, self.out_dir)
        retried = sum(a.outcome != "accepted" for a in trace.attempts)
        logger.info("run=%s finished in %.1fs quality=%s llm_problems=%d", run_id, time.monotonic() - started,
                    output.quality.status, retried)
        if output.quality.issues:
            logger.warning("run=%s quality issues: %s", run_id, "; ".join(output.quality.issues))
        return MarketResearchResult(output=output, json_path=path)


    async def _tag(self, raw_news: list[RawNewsItem], remaining: float) -> tuple[list[NewsItem], list[str]]:
        if not raw_news:
            return [], []
        # Keep tagging inside the run budget, falling back to keyword tags if it runs long.
        started = time.monotonic()
        try:
            return await asyncio.wait_for(tag_news(raw_news), timeout=max(10.0, remaining))
        except asyncio.TimeoutError as e:
            record_failure("news_tagging", started, e)
            return ([keyword_tag(item) for item in raw_news],
                    ["News tags are keyword-based (LLM tagging exceeded the run budget)."])


async def _const(value):
    return value


def _r(v: Optional[float], n: int) -> Optional[float]:
    return round(v, n) if v is not None else None
