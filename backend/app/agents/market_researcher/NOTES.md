# Market researcher: repo notes and deviations from the guide

This note goes with `market_researcher_agent.md` at the repo root. It records what the repo inspection (guide §0) found and every place this implementation departs from the guide.

## What the repo provides

- **Orchestration**: the only orchestrator today is the chat `StateGraph` in `app/agents/graph.py`, which routes triage to the finance, market researcher or general agents. The planned **main agent** does not exist yet. This agent is therefore built to be driven over HTTP, so a main agent in any process or language can call it. It is not a chat specialist.
- **LLM**: a shared `ChatGroq` from `app.core.get_groq_model()` (`openai/gpt-oss-120b`, `max_tokens=1024`, `with_structured_output`). The model is a reasoning model, and reasoning tokens count against `max_tokens`. For that reason the news-tagging and narrative calls use a `model_copy` with a larger budget.
- **Prompts**: versioned in `app/prompts/prompts.yaml` and loaded through `get_prompt()`.
- **Persistence**: a Postgres pool in `app/core/db.py`. There is no Redis.
- **Tests**: pytest 6.2.5, with `FakeLLM` and `run_async` in `tests/conftest.py`. There is no pytest-asyncio and no VCR. In this environment the globally installed `logfire` and `anyio` pytest plugins break on pytest 6, so run the suite with `pytest -p no:logfire -p no:anyio`.
- **Keys**: `.env` lives at the repo root and already holds `FRED_API_KEY`, `TAVILY_API_KEY`, `GROQ_API_KEY` and `FINNHUB_API_KEY`.

## Deviations from the guide

| Guide | Here | Why |
|---|---|---|
| Agent returns output to the orchestrator in-process | HTTP endpoint (`/agents/market-researcher/...`) plus a **JSON file per run**. Also callable in-process via `run_market_research()` | The main agent synthesizes later, possibly in another process |
| Narrative always produced | `include_narrative=False` by default; `key_themes`, `risks`, `implications` and `narrative` are optional | Synthesis is the main agent's job. The optional narrative is still number-validated |
| `Regime.phase` required | Optional (None when macro data is insufficient) | Never fake a call |
| `prompts/market_researcher.md` | `prompts.yaml` keys under `market_researcher:` | Repo convention |
| SQLite/Redis cache | Postgres (`market_cache`, `market_regime_state`, `market_research_runs`), with an in-memory fallback | Repo already runs Postgres |
| VCR fixtures | `httpx.MockTransport` plus JSON fixtures | No new dependency |
| numpy/pandas | stdlib `statistics`/`math` | Small data; keeps dependencies light (yfinance pulls in pandas, but our code never imports it) |
| News: Tavily/Exa/NewsAPI/GDELT | Tavily only (`topic="news"`) | Key already in the repo. GDELT is a possible later fallback |
| ICE BofA HY OAS for credit (guide §3.1) | Reported, but the regime model and the credit-stress level test use Moody's `BAA10Y` | FRED serves ICE BofA OAS for only ~3 years, too short for 10y statistics or the backtest |
| Market data: primary plus fallback | yfinance only, behind `MarketDataProvider` | Free; `FINNHUB_API_KEY` exists, but Finnhub's free tier has no candles |
| ISM PMI | Omitted | Not on FRED |
| Calendar adapter, EU/SG regions, MCP server, `mid_expansion` | Deferred to v1.1 | Per the plan. Non-US regions return 422 |
| ALFRED vintages in the backtest | Revised data with a per-frequency **publication lag**. Live runs with `as_of` use vintages | A vintage fetch per month for the 1980 onward window is about 10k API calls |
| (Chat) | Built as an optional extra: a triage `market` route leads to `nodes/market_researcher.py`. The Finance Expert is deliberately separate and has no tool access to this agent | The HTTP endpoint is still the primary interface |

## Tuning and findings

- **Backtest** (`backtest_report.md`) covers 1980 to the present, monthly:
  - **Tuning:** with a 3-month momentum window, all 6 NBER recessions were caught but 5 sustained false recession calls appeared, in post-recession recoveries. Moving to `momentum_months=6` cut that to 2: the 2003 jobless recovery and the 2024 Sahm-rule trigger, both genuine scares at the time. That change held across hysteresis, temperature and strong-adjustment weights. This is the only weight changed from the starting values.
  - **Known limitation:** 2010 to 2017 classifies as `early_expansion` throughout, because 10-year z-scores carry the 2008 trough. A `mid_expansion` phase (v1.1) would address this.
- **Percentiles are mid-rank**, so ties count half. A plain "≤ latest" percentile reported a flat series at the 100th percentile and fired false credit-stress events.
- **The narrative validator checks labels as well as numbers.** In live runs the model kept calling trailing 1-year returns "YTD" and 10-year-percentile yields "near-record". The payload now uses explicit `trailing_1y_pct` keys, and "YTD" or "record" wording the data doesn't support fails validation.
- **The retry includes the rejected draft.** Without it, the model rewrote from scratch and made new errors (2 of 3 narrative eval cases fell back to the template). With it, all 3 pass.
- **Ranking boosts the caller's own news queries.** Otherwise the 8 generic macro queries crowded out results for focus terms such as "China economy".
- **httpx request logging is silenced** (`adapters/base.py`), because FRED takes its API key as a URL query parameter and httpx logs full URLs at INFO.
- **Local environment:** the globally installed fastapi 0.117 and starlette 1.6 are incompatible, so `APIRouter()` fails at import. This affects the existing routers too. A fresh `pip install -r requirements-dev.txt` (or Docker) resolves compatible versions, and the suite was verified in a clean venv.
- **The chat's article side panel uses extracted text, not an iframe.** Probing one run's 15 news URLs, 8 refused embedding (`X-Frame-Options` / CSP `frame-ancestors`), and others block bots or are paywalled. `article_reader.py` therefore fetches only URLs the run cited, honours robots.txt and blocks non-public addresses, then extracts the main text with trafilatura: 10 of 15 sources produced readable text. It is the one place outside the API sources where a web page is fetched.
- **The backtest now runs the live model's exact inputs:** `BAA10Y` credit (spliced to `BAA − GS10` before 1986) and S&P 500 for the equity rule. Before this, credit was absent pre-2023 and equities were absent entirely, so those parts of the live model were untested. With matched inputs it is still 6/6 caught with 2 sustained false calls.
- **New metrics show where the model is weak:** Brier skill is −0.47 (the phase "probabilities" are uncalibrated), and it makes 84 phase changes vs 14 for the Sahm rule. It does call earlier, with far fewer false-call months than Sahm (14 vs 38).
- **Walk-forward:** a config tuned only on 1980–2005 (`momentum_months=9, hysteresis_margin=0.1, temperature=1.0, adjustment_weight=0.5, strong_adjustment_weight=0.5`) beats the current defaults on 2006+ (0 vs 1 sustained false calls, 2 vs 5 false-call months, 12 vs 18 phase changes). The defaults are unchanged pending a decision.
