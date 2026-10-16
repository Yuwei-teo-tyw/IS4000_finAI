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
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.agents.market_researcher.config import SCHEMA_VERSION

Phase = Literal["early_expansion", "late_expansion", "recession", "late_recession"]
SignalLiteral = Literal[
    "bullish_growth", "bearish_growth", "inflationary", "disinflationary",
    "tightening", "easing", "neutral",
]

SCHEMA_PATH = Path(__file__).parent / "market_research_output.schema.json"


class MarketResearchRequest(BaseModel):
    query: Optional[str] = Field(default=None, description="The main agent's question or focus, if any.")
    region: Literal["US", "EU", "SG", "GLOBAL"] = Field(default="US", description="Only 'US' is supported in v1.")
    focus: list[str] = Field(default_factory=list, description='Extra focus terms, e.g. ["rates", "energy"].')
    lookback_days_news: int = Field(default=3, ge=1, le=14)
    as_of: Optional[date] = Field(default=None, description="None = now; set for replays/backtests.")
    include_narrative: bool = Field(default=False, description="Also produce an LLM narrative (validated against the data).")


class Indicator(BaseModel):
    id: str
    name: str
    category: str
    value: float
    unit: str
    observation_date: date
    changes: dict[str, float] = Field(default_factory=dict, description="Change over each window, in the value's own unit (pp for % values; % for prices).")
    percentile_10y: Optional[float] = None
    zscore_10y: Optional[float] = None
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
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: Literal["low", "medium", "high"] = "low"
    recession_prob_12m: Optional[float] = Field(default=None, description="NY Fed yield-curve probit model estimate, 0-1.")
    composites: dict[str, Optional[float]] = Field(default_factory=dict, description="G (growth level), M (momentum), I (inflation), P (policy/financial stance).")
    drivers: list[Driver] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    previous_phase: Optional[Phase] = None
    changed: bool = False


class DataQuality(BaseModel):
    failed_sources: list[str] = Field(default_factory=list)
    stale_series: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


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
    key_themes: Optional[list[str]] = None
    risks: Optional[list[str]] = None
    implications: Optional[dict[str, str]] = Field(default=None, description="Descriptive, not advice.")
    narrative: Optional[str] = None
    data_quality: DataQuality = Field(default_factory=DataQuality)


def output_json_schema() -> dict:
    return MarketResearchOutput.model_json_schema()


def write_schema_file(path: Path = SCHEMA_PATH) -> Path:
    path.write_text(json.dumps(output_json_schema(), indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_schema_file())
