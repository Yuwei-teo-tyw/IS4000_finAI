"""
Request/output contract for the market researcher agent (guide §5).

`MarketResearchOutput` is what a run writes to its JSON file and what the
main agent synthesizes from - its JSON Schema is committed next to this
module as `market_research_output.schema.json` (regenerate with
`python -m app.agents.market_researcher.schemas`) and served at
GET /agents/market-researcher/schema.

Deviations from the guide's sketch, all so the structured output stands
on its own without an LLM: `narrative`/`key_themes`/`risks`/`implications`
are optional (only filled when `include_narrative=True`, since the main
agent normally does the synthesis), `Regime.phase` is optional (None when
there isn't enough macro data to classify honestly), and `NewsItem.published_at`
is optional (not every news result carries a date).
"""
import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field

from app.agents.market_researcher.config import (
    MAX_FOCUS_TERM_CHARS,
    MAX_FOCUS_TERMS,
    MAX_QUERY_CHARS,
    SCHEMA_VERSION,
)

Phase = Literal["early_expansion", "late_expansion", "recession", "late_recession"]
SignalLiteral = Literal[
    "bullish_growth", "bearish_growth", "inflationary", "disinflationary",
    "tightening", "easing", "neutral",
]

SCHEMA_PATH = Path(__file__).parent / "market_research_output.schema.json"


class MarketResearchRequest(BaseModel):
    query: Optional[str] = Field(default=None, max_length=MAX_QUERY_CHARS,
                                 description="The main agent's question or focus, if any.")
    region: Literal["US", "EU", "SG", "GLOBAL"] = Field(default="US", description="Only 'US' is supported in v1.")
    focus: list[Annotated[str, Field(max_length=MAX_FOCUS_TERM_CHARS)]] = Field(
        default_factory=list, max_length=MAX_FOCUS_TERMS, description='Extra focus terms, e.g. ["rates", "energy"].')
    lookback_days_news: int = Field(default=3, ge=1, le=14)
    as_of: Optional[date] = Field(default=None, description="None = now; set for replays/backtests.")
    include_narrative: bool = Field(default=False, description="Also produce an LLM narrative (validated against the data).")
    planning: Literal["auto", "off"] = Field(
        default="auto",
        description="'auto': an LLM picks extra series/symbols/news queries from curated catalogs when there is a "
                    "query or focus. 'off': fixed core set only (focus terms become news queries).",
    )
    explain_events: Optional[bool] = Field(
        default=None,
        description="Investigate notable events (targeted news + decompositions + cited explanation). "
                    "None = on for live runs, off for a past as_of.",
    )


class Indicator(BaseModel):
    id: str
    name: str
    category: str
    value: float
    unit: str
    observation_date: date
    changes: dict[str, float] = Field(default_factory=dict, description="Change over each window, in the value's own unit (pp for % values; % for prices).")
    percentile_10y: Optional[float] = Field(default=None, description="0-100, vs the last 10 years - or less; see stats_window_years.")
    zscore_10y: Optional[float] = Field(default=None, description="Std devs from the trailing mean over stats_window_years.")
    stats_window_years: Optional[float] = Field(
        default=None,
        description="Years of history behind percentile_10y/zscore_10y: 10 unless the source's history is shorter.",
    )
    signal: SignalLiteral = "neutral"
    stale: bool = False
    source: str
    source_url: str


class NewsItem(BaseModel):
    title: str
    source: str
    url: str
    published_at: Optional[datetime] = None
    summary: str
    topics: list[str] = Field(default_factory=list)
    sentiment: Literal["risk_on", "risk_off", "neutral"] = "neutral"
    market_impact: Literal["low", "medium", "high"] = "low"


class Event(BaseModel):
    id: str
    severity: Literal["info", "notable", "major"]
    description: str
    evidence: list[str] = Field(default_factory=list, description="Indicator / symbol ids backing this event.")


class Driver(BaseModel):
    indicator: str
    value: Optional[float] = None
    direction: str
    contribution: float


class Regime(BaseModel):
    phase: Optional[Phase] = None
    probabilities: dict[str, float] = Field(
        default_factory=dict,
        description="Per phase. The recession + late_recession share equals in_recession_prob; the split within "
                    "each pair comes from the scores.",
    )
    in_recession_prob: Optional[float] = Field(
        default=None,
        description="P(the economy is in recession now) = P(recession) + P(late_recession), calibrated against "
                    "NBER history when RegimeConfig.calibration is set.",
    )
    scores: dict[str, float] = Field(
        default_factory=dict, description="Raw (smoothed) phase scores behind the call; higher = stronger.")
    confidence: Literal["low", "medium", "high"] = "low"
    recession_prob_12m: Optional[float] = Field(default=None, description="NY Fed yield-curve probit model estimate, 0-1.")
    composites: dict[str, Optional[float]] = Field(default_factory=dict, description="G (growth level), M (momentum), I (inflation), P (policy/financial stance).")
    drivers: list[Driver] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    previous_phase: Optional[Phase] = None
    changed: bool = False


PlanArea = Literal["rates", "inflation", "labor", "growth", "housing", "credit",
                   "energy", "equities", "fx", "global", "fed", "consumer"]


class QueryPlan(BaseModel):
    intent: str = Field(description="One sentence: what the caller wants to know.")
    areas: list[PlanArea] = Field(default_factory=list)
    extra_series: list[str] = Field(default_factory=list, description="Catalog FRED ids only.")
    extra_symbols: list[str] = Field(default_factory=list, description="Catalog symbols only.")
    news_queries: list[str] = Field(default_factory=list, description="Each 3-12 words; no operators beyond quotes/OR.")
    rationale: str = Field(default="", description="<= 60 words: why these choices.")


class PlanRecord(BaseModel):
    plan: Optional[QueryPlan] = None
    plan_source: Literal["llm", "heuristic", "skipped", "failed"]
    dropped: list[str] = Field(default_factory=list, description="Ids/queries rejected by validation, with the reason.")
    latency_ms: Optional[int] = None


class CitedSource(BaseModel):
    url: str
    title: str
    source: str
    published_at: Optional[datetime] = None
    snippet: Optional[str] = Field(default=None, description="The article text the model was shown.")
    retrieved_at: Optional[datetime] = Field(default=None, description="When the search returned this article.")


class EventExplanation(BaseModel):
    event_id: str
    status: Literal["explained", "insufficient_evidence", "unavailable", "skipped"]
    explanation: Optional[str] = Field(default=None, description="<= 70 words, own words; numbers validated.")
    likely_drivers: list[str] = Field(default_factory=list, description="1-3 short phrases.")
    decomposition: Optional[dict] = Field(default=None, description="Code-derived facts (decompositions.py).")
    cited_urls: list[str] = Field(default_factory=list)
    cited_sources: list[CitedSource] = Field(
        default_factory=list, description="Title/source/date of each cited article (same order as cited_urls).")
    cited_indicators: list[str] = Field(default_factory=list)
    confidence: Optional[Literal["low", "medium", "high"]] = None
    queries_run: list[str] = Field(default_factory=list, description="Searches actually run for this event.")


class QualityReport(BaseModel):
    """Final self-check of the run (quality.py). Consumers should read `status`
    before using the output: `unusable` = do not quote the regime or indicators."""
    status: Literal["ok", "degraded", "unusable"]
    checks: dict[str, bool] = Field(
        default_factory=dict,
        description="consistency, completeness, freshness, sources, advice_language: True = passed.")
    issues: list[str] = Field(default_factory=list, description="Why a check failed, one line each.")


class DataQuality(BaseModel):
    failed_sources: list[str] = Field(default_factory=list)
    stale_series: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RunOrigin(BaseModel):
    """Where a run came from. `session_id` identifies a chat session, not a verified person."""
    channel: Literal["chat", "http"]
    session_id: Optional[str] = None
    client_id: Optional[str] = None


class LlmAttempt(BaseModel):
    stage: str
    attempt: int
    outcome: Literal["accepted", "rejected", "error", "timeout"]
    latency_ms: int
    problems: list[str] = Field(default_factory=list, description="Why it was rejected or failed, if it was.")
    rejected_text: Optional[str] = Field(default=None, description="The text that was rejected, kept for review.")


class MarketResearchOutput(BaseModel):
    schema_version: str = SCHEMA_VERSION
    agent: Literal["market_researcher"] = "market_researcher"
    run_id: str
    generated_at: datetime
    as_of: date
    region: str
    request: MarketResearchRequest
    regime: Regime
    events: list[Event] = Field(default_factory=list)
    indicators: list[Indicator] = Field(default_factory=list)
    market_snapshot: list[Indicator] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    plan: Optional[PlanRecord] = None
    planned_indicators: list[Indicator] = Field(
        default_factory=list, description="Planner extras from EXTRA_SERIES_CATALOG; never used by regime/events.")
    planned_market: list[Indicator] = Field(
        default_factory=list, description="Planner extras from EXTRA_SYMBOL_CATALOG; never used by regime/events.")
    event_explanations: list[EventExplanation] = Field(
        default_factory=list, description="Linked to `events` by event_id.")
    key_themes: Optional[list[str]] = None
    risks: Optional[list[str]] = None
    implications: Optional[dict[str, str]] = Field(default=None, description="Descriptive, not advice.")
    narrative: Optional[str] = None
    data_quality: DataQuality = Field(default_factory=DataQuality)
    quality: Optional[QualityReport] = Field(
        default=None, description="Overall verdict from the final quality gate; read this first.")
    llm_model: Optional[str] = Field(default=None, description="Model configured for this run's LLM-written fields.")
    prompt_versions: dict[str, str] = Field(
        default_factory=dict, description="Prompt key -> version resolved for this run, for audit.")
    origin: Optional[RunOrigin] = Field(default=None, description="Who started the run, when known.")
    llm_attempts: list[LlmAttempt] = Field(default_factory=list, description="Every LLM attempt in this run, in order.")


def output_json_schema() -> dict:
    return MarketResearchOutput.model_json_schema()


def write_schema_file(path: Path = SCHEMA_PATH) -> Path:
    path.write_text(json.dumps(output_json_schema(), indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_schema_file())
