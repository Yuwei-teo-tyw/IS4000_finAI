# Market Researcher Agent: Implementation Plan

> **Audience:** Claude Code, working inside the existing multi-agent repo.
> **Goal:** Build, test, and integrate a `market_researcher` agent that the existing orchestrator can call. It gathers current macro and market data plus news, classifies the current economic cycle phase, and returns structured, cited findings that the orchestrator can synthesize with other agents' outputs.

---

## 0. Before writing any code: inspect the repo

Do this first and adapt everything below to what you find. **Repo conventions override this plan.**

1. **Find the orchestrator** and work out:
   - How it calls agents (function call, class with `run()`, message bus, LangGraph node, CrewAI agent, HTTP, etc.).
   - The input it passes to agents and the output contract it expects (Pydantic model, dict, JSON schema, free text).
   - Whether agents run async, and any timeout or retry handling it already does.
2. **Find an existing agent** and copy its structure: base class, registration, prompt location, config loading, logging, tests.
3. **Find the LLM client wrapper** already in use (model, structured output method, retries). Reuse it.
4. **Find config and secrets handling** (`.env`, settings module, vault). Add new keys the same way.
5. **Check the language and tooling** (Python version, package manager, linter, test runner, async style). Code sketches below are Python; translate if the repo uses something else.
6. Write a short `NOTES.md` section (or PR description) listing what you found and any deviations from this plan.

If there is no defined agent output contract yet, propose the schema in Section 5 and flag it for the user.

---

## 1. Scope

### In scope
- Retrieve **current** data from APIs (not LLM memory):
  - Rates and yields (2Y, 10Y, 30Y, curve spreads, policy rate).
  - Inflation, labor, growth, credit, financial conditions, sentiment.
  - Market prices (equity indices, sector ETFs, USD, oil, gold, copper, VIX).
  - Recent macro and market news headlines.
- Detect **notable events** (e.g. "10Y yield at multi-year high", "curve un-inverting", "Sahm rule triggered", "HY spreads widening sharply").
- Classify the **economic cycle phase**: `early_expansion`, `late_expansion`, `recession`, `late_recession`, with probabilities, confidence, and the drivers behind the call.
- Produce a **structured, cited output** for the orchestrator plus a short narrative.

### Out of scope (for v1)
- Trading signals or personalized investment advice.
- Company-level fundamentals (leave to another agent unless the repo has none).
- Heavy web scraping (see Section 3.4).

### Design principle (important)
**Numbers come from code, not from the LLM.** The pipeline is:

```
Data adapters (deterministic)  →  Feature + event detection (deterministic)
       →  Regime classifier (deterministic, rule/score based)
       →  LLM synthesis (interprets, summarizes, cites; never invents numbers)
       →  Validator (checks every number in the narrative exists in the data)
```

This keeps the agent testable, reproducible, and resistant to hallucinated figures.

---

## 2. Architecture

```
market_researcher/
├── __init__.py
├── agent.py                 # Entry point the orchestrator calls (match repo's agent interface)
├── config.py                # Series lists, thresholds, TTLs, region settings
├── schemas.py               # Pydantic models: request, indicators, events, regime, output
├── adapters/                # One file per external source; all return normalized objects
│   ├── base.py              # Adapter protocol, retry/backoff, rate limiting, timeouts
│   ├── fred.py              # Macro + rates (primary)
│   ├── market_data.py       # Prices: provider-agnostic interface + 1–2 implementations
│   ├── news.py              # News search: provider-agnostic interface + implementations
│   └── calendar.py          # Upcoming releases / central bank meetings (optional v1.1)
├── cache.py                 # TTL cache (SQLite or Redis if repo already has it)
├── features.py              # Transforms: YoY, MoM, 3m annualized, z-scores, percentiles, trend gaps
├── events.py                # Rule-based notable-event detection
├── regime.py                # Cycle phase classifier + recession probability
├── synthesis.py             # LLM prompt + structured output + number validator
├── prompts/
│   └── market_researcher.md
└── tests/
    ├── fixtures/            # Recorded API responses
    ├── test_adapters.py
    ├── test_features.py
    ├── test_events.py
    ├── test_regime.py
    ├── test_regime_backtest.py
    ├── test_synthesis_validator.py
    └── test_agent_contract.py
```

Place it wherever the repo keeps agents (e.g. `agents/market_researcher/`).

### Execution flow per request
1. Parse orchestrator request → `MarketResearchRequest`.
2. Fetch in parallel (`asyncio.gather` with per-source timeouts): macro series, market prices, news.
3. Any source failing → record in `data_quality.failed_sources`, continue with partial data.
4. Compute features → detect events → classify regime.
5. LLM synthesis over the structured data (and news snippets) → narrative, themes, risks.
6. Validate narrative numbers against data; on failure, retry once with the error, then fall back to a template narrative.
7. Return `MarketResearchOutput`.

Target latency: under ~30s with warm cache, under ~60s cold. Make timeouts configurable.

---

## 3. Data sources

> Verify current pricing, rate limits, and terms for each provider before committing; these change. Keep every source behind an adapter interface so providers can be swapped.

### 3.1 Macro and rates: FRED API (primary, free, key required)
`https://api.stlouisfed.org/fred/series/observations` with `api_key`, `series_id`, `observation_start`, `file_type=json`.

Recommended series (US default):

| Category | Series ID | Notes |
|---|---|---|
| Yields | `DGS3MO`, `DGS2`, `DGS10`, `DGS30` | Daily Treasury constant maturity |
| Curve | `T10Y2Y`, `T10Y3M` | Spreads; `T10Y3M` drives recession probability model |
| Policy rate | `DFF` (daily), `FEDFUNDS` (monthly) | Also `DFEDTARU`/`DFEDTARL` for target range |
| Real yields / breakevens | `DFII10`, `T5YIE`, `T10YIE` | Inflation expectations |
| Inflation | `CPIAUCSL`, `CPILFESL`, `PCEPI`, `PCEPILFE` | Compute YoY and 3m annualized |
| Labor | `UNRATE`, `PAYEMS`, `ICSA`, `CCSA`, `SAHMREALTIME` | Sahm rule real-time series |
| Growth | `GDPC1`, `INDPRO`, `RSAFS`, `PI`, `DSPIC96` | Quarterly + monthly |
| Housing | `HOUST`, `PERMIT` | Leading indicators |
| Credit | `BAMLH0A0HYM2`, `BAMLC0A0CM` | HY and IG OAS. History available via FRED may be limited; check |
| Financial conditions | `NFCI`, `STLFSI4` | Weekly |
| Volatility / sentiment | `VIXCLS`, `UMCSENT` | |
| Recession reference | `USREC`, `USRECM` | NBER dates; **for backtesting only** |

Notes:
- ISM Manufacturing PMI is **not** available on FRED. If needed, use a licensed source or a news-search fallback and mark it lower-confidence.
- Use `realtime_start`/`realtime_end` (ALFRED vintages) when backtesting, to avoid look-ahead bias from revised data.
- Monthly macro data is inherently lagged. "Real-time" for this agent means: daily rates and market prices, weekly claims/conditions, and same-day news. Always report each indicator's `observation_date` and flag staleness.

### 3.2 Market prices (pick one primary, one fallback)
Provider-agnostic interface: `get_quote(symbol)`, `get_history(symbol, start, end, interval)`.

Options:
- **Alpha Vantage**: free tier with low rate limits; also offers an MCP server.
- **Polygon.io / Twelve Data / Finnhub**: better limits on paid tiers.
- **yfinance**: free and convenient, but unofficial and can break; acceptable for prototyping or as a fallback only.

Default watchlist (configurable):
- Indices: SPY, QQQ, IWM, EFA, EEM.
- Sectors: XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB, XLRE, XLC (feed sector rotation read).
- Rates / credit proxies: TLT, IEF, HYG, LQD.
- Macro assets: dollar index proxy (UUP or DXY if provider has it), USO or WTI, GLD, copper (CPER or HG futures).
- Volatility: VIX.

### 3.3 News
Provider-agnostic interface: `search(query, since, max_results) -> list[NewsItem]`.

Options (choose based on budget and existing keys in the repo):
- **Search APIs built for LLM agents**: Tavily, Exa, Brave Search API. Return snippets and URLs; good fit.
- **NewsAPI.org**: headline search; check commercial-use terms.
- **GDELT**: free, global, noisy; good secondary source.
- **Finnhub / Alpha Vantage news endpoints**: market news with tickers and sometimes sentiment.

Query templates (rotate and parameterize by region):
- `"Treasury yields" OR "bond yields"` last 48h
- `"Federal Reserve" rate decision OR FOMC`
- `inflation CPI report`, `jobs report payrolls`, `recession fears`
- `oil prices OPEC`, `"credit spreads"`, `China economy`, plus user focus terms.

Processing:
- Deduplicate by URL and by title similarity.
- Score relevance (keyword + recency); keep top N (default 15).
- LLM tags each item: `topic`, `sentiment` (risk-on/off/neutral), `market_impact` (low/med/high). Do this in one batched call.

### 3.4 Web scraping: position
Do **not** build scrapers as a primary source. They are brittle, slow, and often against site terms. Allowed use: fetching the full text of an article URL returned by a news API when the snippet is insufficient, respecting robots.txt, with a short timeout, and failing gracefully. Paywalled content is skipped.

### 3.5 Non-US / global (config-driven, v1.1)
Make `region` a request parameter. Sources to add per region:
- **Eurozone**: ECB Data Portal API, Eurostat.
- **Singapore / Asia**: MAS statistics, SingStat Table Builder API.
- **Global**: OECD API (composite leading indicators), IMF data API, World Bank API.
Start with US only; design the config so adding a region means adding a series map, not new code paths.

### 3.6 MCP vs direct API
- **Inside this agent:** call APIs directly through the adapters. This is deterministic, testable with fixtures, and avoids an extra process.
- **Optional:** wrap the adapters as an MCP server (`get_series`, `get_quotes`, `search_news`, `get_regime`) so other agents or Claude clients can reuse them. Only do this if the orchestrator or other agents already use MCP. Community FRED MCP servers and the Alpha Vantage MCP server exist, but vet them before depending on them.

---

## 4. Analytics

### 4.1 Features (`features.py`)
For each series compute what is relevant: latest value and date, change over 1d/1w/1m/3m/1y as fits the frequency, YoY %, 3m annualized %, z-score vs 10y history, percentile vs 10y and full history, distance from N-year high/low, and trend gap (value vs 12m or 24m moving average).

### 4.2 Notable event detection (`events.py`)
Rule-based, each rule returns `Event(id, severity, description, evidence: list[indicator_id])`. Thresholds in `config.py`. Starter rules:

| Event | Rule (starting point, tune later) |
|---|---|
| Yield at multi-year / record high | `DGS10` or `DGS30` at highest level in ≥ N years (report the actual lookback; do not say "all-time high" unless it is) |
| Sharp yield move | 10Y change over 1 week > 25bp, or 1 month > 50bp |
| Curve inversion / un-inversion | `T10Y3M` or `T10Y2Y` crosses 0; note that re-steepening after a long inversion has historically preceded recessions |
| Sahm rule | `SAHMREALTIME` ≥ 0.50 |
| Claims rising | 4-week avg `ICSA` up > 15% from 52-week low |
| Credit stress | HY OAS up > 100bp in 3 months or above 80th percentile |
| Financial conditions tightening | `NFCI` > 0 or rising sharply |
| Inflation re-acceleration | Core 3m annualized > core YoY by > 0.5pp |
| Equity drawdown | SPY > 10% below 52-week high (correction), > 20% (bear market) |
| Volatility spike | VIX > 30 or up > 50% in a week |
| Oil shock | Oil up > 25% in 3 months |

### 4.3 Recession probability (`regime.py`)
Implement the NY Fed yield-curve probit model as one input:

```
P(recession in 12 months) = Φ(α + β · spread_10y_3m)
```
Use the NY Fed's published coefficients (verify the current values on the NY Fed "Yield Curve as a Leading Indicator" page; historically α ≈ −0.5333, β ≈ −0.6330 using the monthly average spread on a bond-equivalent basis). Label it clearly as a model estimate.

### 4.4 Cycle phase classifier (`regime.py`)
Four phases as requested. Keep it transparent and score-based so it can be explained and backtested.

**Step 1: composite scores** (each a weighted average of z-scored indicators, weights in config):
- **Growth level `G`**: industrial production YoY, real retail sales YoY, payrolls 3m avg growth, real GDP YoY, inverted unemployment gap (UNRATE vs 12m low), inverted claims trend.
- **Growth momentum `M`**: 3–6 month change in `G` components.
- **Inflation pressure `I`**: core CPI/PCE YoY and 3m annualized vs 2% target, breakevens.
- **Policy / financial stance `P`**: real policy rate, curve slope, HY OAS, NFCI.

**Step 2: base quadrant** (classic growth-gap / momentum framing):

| | Momentum rising (`M > 0`) | Momentum falling (`M ≤ 0`) |
|---|---|---|
| **Growth above trend (`G ≥ 0`)** | `early_expansion` | `late_expansion` |
| **Growth below trend (`G < 0`)** | `late_recession` (trough / recovery forming) | `recession` |

**Step 3: confirmation adjustments** (shift scores, not hard overrides):
- Toward `late_expansion`: tight labor (UNRATE near cycle low), `I` elevated, policy restrictive, curve flat/inverted, credit spreads tight but widening.
- Toward `early_expansion`: unemployment high but falling, curve steep, policy easing or accommodative, inflation subdued, spreads tightening from wide levels.
- Toward `recession`: Sahm rule triggered, claims surging, HY spreads blowing out, payrolls negative, probit probability high.
- Toward `late_recession`: policy easing aggressively, spreads peaking/rolling over, claims peaking, equities rallying off lows, leading indicators (permits, sentiment) turning up.

**Step 4: probabilities**: convert per-phase scores to probabilities via softmax with a temperature in config. `confidence = max_prob − second_max_prob` mapped to `low/medium/high`.

**Step 5: stability**: apply hysteresis. Only change the phase vs the last cached classification if the new phase's probability exceeds the old by a margin (e.g. 0.10). Persist the last result in the cache.

**Output**: phase, probabilities for all four, confidence, top 3–5 drivers (indicator, value, direction, contribution), and conflicting signals. Conflicting signals are valuable for the orchestrator; never hide them.

Optional later: add `mid_expansion` as a fifth phase if backtests show the four-phase split is too coarse. Keep it behind a config flag so the default matches the four phases requested.

### 4.5 Backtest (required before shipping)
`tests/test_regime_backtest.py`:
- Run the classifier monthly from ~1980 to present using ALFRED vintages where practical (at minimum, note look-ahead bias if using revised data).
- Compare to NBER `USREC`: the `recession` phase should overlap most NBER recessions; `late_expansion` should frequently precede them; `early_expansion` should follow troughs.
- Report a confusion-style summary and lead/lag in months. Save as `backtest_report.md`.
- Acceptance: catches at least most of the NBER recessions in the window with no more than a small number of sustained false recession calls. Tune weights in config, not code.

---

## 5. Contracts

### 5.1 Request (adapt to orchestrator)
```python
class MarketResearchRequest(BaseModel):
    query: str | None = None           # Orchestrator's question or focus
    region: Literal["US", "EU", "SG", "GLOBAL"] = "US"
    focus: list[str] = []              # e.g. ["rates", "inflation", "energy", "tech sector"]
    lookback_days_news: int = 3
    as_of: date | None = None          # None = now; set for backtests / replays
    include_narrative: bool = True
```

### 5.2 Output
```python
class Indicator(BaseModel):
    id: str                  # e.g. "DGS10"
    name: str
    value: float
    unit: str                # "%", "bp", "index", "USD"
    observation_date: date
    changes: dict[str, float]   # {"1w": 0.12, "1m": 0.35}
    percentile_10y: float | None
    signal: Literal["bullish_growth", "bearish_growth", "inflationary", "disinflationary", "tightening", "easing", "neutral"]
    stale: bool
    source: str              # "FRED"
    source_url: str

class NewsItem(BaseModel):
    title: str
    source: str
    url: str
    published_at: datetime
    summary: str             # Agent's own words, short
    topics: list[str]
    sentiment: Literal["risk_on", "risk_off", "neutral"]
    market_impact: Literal["low", "medium", "high"]

class Event(BaseModel):
    id: str
    severity: Literal["info", "notable", "major"]
    description: str
    evidence: list[str]      # Indicator ids

class Regime(BaseModel):
    phase: Literal["early_expansion", "late_expansion", "recession", "late_recession"]
    probabilities: dict[str, float]
    confidence: Literal["low", "medium", "high"]
    recession_prob_12m: float | None
    drivers: list[dict]        # indicator, value, direction, contribution
    conflicting_signals: list[str]
    previous_phase: str | None
    changed: bool

class DataQuality(BaseModel):
    failed_sources: list[str]
    stale_series: list[str]
    notes: list[str]

class MarketResearchOutput(BaseModel):
    agent: Literal["market_researcher"] = "market_researcher"
    generated_at: datetime
    as_of: date
    region: str
    regime: Regime
    events: list[Event]
    indicators: list[Indicator]
    market_snapshot: list[Indicator]   # prices, same shape
    news: list[NewsItem]
    key_themes: list[str]              # 3–6 bullets
    risks: list[str]                   # upside and downside risks
    implications: dict[str, str]       # e.g. {"equities": "...", "duration": "...", "sectors": "..."} descriptive, not advice
    narrative: str                     # 150–300 words
    data_quality: DataQuality
```

The orchestrator should be able to use the structured fields directly without parsing the narrative.

---

## 6. LLM synthesis (`synthesis.py`)

- Input: compact JSON of indicators, events, regime, and top news items (titles, snippets, URLs). Do not send raw full series.
- Use the repo's LLM client with structured output matching the `key_themes`, `risks`, `implications`, `narrative` fields, plus per-news tagging.
- System prompt rules (put in `prompts/market_researcher.md`):
  - Use only numbers present in the provided data; cite indicator ids or news URLs for claims.
  - Report observation dates for lagged data; do not call monthly data "today's".
  - State the regime call with its confidence and the main conflicting signal.
  - Describe implications, not recommendations; no personalized advice.
  - Summarize news in your own words; no long quotes.
  - If data is missing or stale, say so.
- **Number validator**: extract all numbers from the narrative and themes; each must match (within rounding tolerance) a value, change, or probability in the input payload, or be a date. On failure, retry once with the offending numbers listed; if it fails again, use a deterministic template narrative and add a `data_quality.notes` entry.

---

## 7. Reliability and operations

- **Caching** (`cache.py`): key by `(source, series/symbol, params)`. TTLs: market quotes 1–5 min, daily series 1h, weekly 6h, monthly 12h, news 15 min. Reuse Redis if the repo has it; otherwise SQLite.
- **Retries**: exponential backoff with jitter, max 3, only on 429/5xx/timeouts.
- **Rate limiting**: per-provider token bucket using documented limits.
- **Timeouts**: per-call (e.g. 10s) and overall agent budget (e.g. 60s); return partial results on budget expiry.
- **Graceful degradation**: if news fails, still return macro + regime; if FRED fails, return news + prices with `regime.confidence="low"` and a note.
- **Staleness**: mark a series stale if its last observation is older than its expected frequency plus a grace period (configurable per series).
- **Logging**: structured logs per source call (latency, status, cache hit). No API keys in logs.
- **Secrets**: `FRED_API_KEY`, `MARKET_DATA_API_KEY` (+ provider name), `NEWS_API_KEY` (+ provider name). Add to `.env.example` and config the way the repo already does.
- **Determinism**: given the same fetched data and `as_of`, everything except the narrative is deterministic.

---

## 8. Testing

1. **Adapter tests**: recorded fixtures (VCR.py / respx / responses, whatever the repo uses). Test parsing, missing values (FRED uses `"."`), errors, retries.
2. **Feature tests**: hand-computed YoY, 3m annualized, z-scores, percentiles on small synthetic series.
3. **Event tests**: synthetic series that should and should not trigger each rule.
4. **Regime tests**: synthetic scenarios for each phase; hysteresis behavior; probabilities sum to 1.
5. **Backtest**: Section 4.5; mark as slow / optional in CI.
6. **Synthesis validator tests**: narratives with correct numbers pass, invented numbers fail, fallback works.
7. **Contract test**: orchestrator calls the agent with a mocked environment and receives a valid `MarketResearchOutput`.
8. **Live smoke test** (opt-in via env flag, skipped in CI): real API calls, asserts non-empty indicators, recent observation dates, at least some news items.
9. **Eval set**: 10–15 orchestrator-style queries (e.g. "Are recession risks rising?", "What is driving yields higher?", "Impact of oil on inflation outlook?"). Check outputs for citations, no invented numbers, correct regime field, sensible relevance. Store in `tests/evals/`.

---

## 9. Milestones

| # | Milestone | Done when |
|---|---|---|
| 1 | Repo inspection + schemas | `schemas.py` matches orchestrator contract; notes written |
| 2 | FRED adapter + cache + features | Pulls all US series, computes features, tests pass |
| 3 | Events + regime classifier | Unit tests pass; recession probability implemented |
| 4 | Backtest | Report generated; thresholds tuned in config |
| 5 | Market data + news adapters | Parallel fetch, fallbacks, dedupe, tests pass |
| 6 | LLM synthesis + validator | Structured output, validator, fallback narrative |
| 7 | Orchestrator integration | Contract test passes; agent registered; end-to-end run works |
| 8 | Hardening | Timeouts, partial results, live smoke test, eval set run |
| 9 | (v1.1) Calendar + regions + optional MCP server | Upcoming events in output; EU/SG series maps |

Commit after each milestone. Keep PRs small.

---

## 10. Suggested extra outputs (beyond the requested examples)

Add incrementally; each should be a config-toggleable module:
- **Recession probability (12m)** from the yield-curve model, alongside the regime call.
- **Inflation regime**: disinflation / sticky / re-accelerating, with core 3m vs YoY.
- **Central bank stance**: current policy rate, direction of last move, next meeting date; market-implied path if a source is available.
- **Financial conditions & liquidity**: NFCI, credit spreads, dollar strength.
- **Sector rotation read**: relative performance of cyclicals vs defensives over 1m/3m, compared with what the regime would typically favor (descriptive).
- **Cross-asset snapshot**: stocks, bonds, dollar, oil, gold, copper/gold ratio (growth proxy).
- **Upcoming catalysts**: next CPI, payrolls, central bank meetings, major earnings within 2 weeks.
- **Risk dashboard**: VIX, HY spreads, drawdowns, with traffic-light status.
- **What changed since last run**: diff of regime probabilities, new events, biggest indicator moves. Very useful for the orchestrator when the agent runs on a schedule.
- **Geopolitical / commodity shocks**: tagged from news.

---

## 11. Open questions for the user (do not block on these; use defaults and note them)

1. Which markets/regions matter most? Default: US, with Singapore/Asia added in v1.1.
2. Budget for paid APIs? Default: free tiers (FRED + one free market data source + one news search API).
3. Which news / search API keys already exist in the repo or org?
4. How often will the orchestrator call this agent (on demand vs scheduled)? Affects caching and "what changed" output.
5. Does the orchestrator want the narrative, or only structured data?
6. Is four phases sufficient, or is `mid_expansion` wanted?