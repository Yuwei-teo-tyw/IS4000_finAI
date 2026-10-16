# Market researcher: repo notes and deviations from the guide

This note goes with `market_researcher_agent.md` at the repo root. It records what the repo inspection (guide §0) found and every place this implementation departs from the guide.

## What the repo provides

- **Orchestration**: the only orchestrator today is the chat `StateGraph` in `app/agents/graph.py`, which routes triage to the technical, finance or general agents. The planned **main agent** does not exist yet. This agent is therefore built to be driven over HTTP, so a main agent in any process or language can call it. It is not a chat specialist.
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
| Market data: primary plus fallback | yfinance only, behind `MarketDataProvider` | Free; `FINNHUB_API_KEY` exists, but Finnhub's free tier has no candles |
| ISM PMI | Omitted | Not on FRED |
| Calendar adapter, EU/SG regions, MCP server, `mid_expansion` | Deferred to v1.1 | Per the plan. Non-US regions return 422 |
| ALFRED vintages in the backtest | Revised data with a per-frequency **publication lag**. Live runs with `as_of` use vintages | A vintage fetch per month for the 1980 onward window is about 10k API calls |
| Chat trigger (triage route or finance tool) | Not built | Optional extra; the service is ready to wrap |
