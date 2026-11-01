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
  - **Tuning:** with a 3-month momentum window, all 6 NBER recessions were caught but 5 sustained false recession calls appeared, in post-recession recoveries. Moving to `momentum_months=6` cut that to 2: the 2003 jobless recovery and the 2024 Sahm-rule trigger, both genuine scares at the time. That change held across hysteresis, temperature and strong-adjustment weights. The walk-forward config below later replaced these values.
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
- **Walk-forward:** a config tuned only on 1980–2005 (`momentum_months=9, hysteresis_margin=0.1, temperature=1.0, adjustment_weight=0.5, strong_adjustment_weight=0.5`) beats the current defaults on 2006+ (0 vs 1 sustained false calls, 2 vs 5 false-call months, 12 vs 18 phase changes). `RegimeConfig` now uses this config, so the figures earlier in this section describe the earlier defaults.
- **`backtest_report.md` is generated, not committed.** Run `python -m app.agents.market_researcher.backtest` to produce it.
- **Regime calibration is not set yet.** `RegimeConfig.calibration` is `None`, so chat and the template label the phase percentages "uncalibrated model scores". Once it is fitted from the backtest, remove that label from `render.py`, `synthesis.py` and `synthesis_system`.

## Query planner and event explanations

These notes cover the planner and explanations feature (spec: "Market Researcher: Query Planner + Event Explanations"). Where the spec and the code differ, the code wins:

| Spec | Here | Why |
|---|---|---|
| Bump `SCHEMA_VERSION` to `1.1` | Bumped to `1.3` | It was already `1.2` (`stats_window_years`, `in_recession_prob`, `scores`) |
| "The number validator" | `synthesis.allowed_numbers` / `problems` are reused by the explainer | One validator, same ×100 and rounding rules |
| Coalescing key must include `planning` / `explain_events` | No change needed | `runs.py` keys on `request.model_dump_json()`, so the new fields are included automatically |
| A planned-extra failure must not make the run `partial` | `runs.py` ignores `failed_sources` entries prefixed `planned:` | The prefix marks failures in planned extras, which don't affect the core |
| Merge planned news before ranking | `collect_news` is split into `search_queries` + `rank_news`; `collect_news` stays as a wrapper | Core searches start immediately; ranking waits for the planned searches |
| Event-ID keys in the spec table | `EVENT_EXPLAIN_SPECS` is keyed by the real ID prefixes (`dgs10_`, `dgs30_`, `t10y3m_`, `t10y2y_`, `sahm_rule`, `jobless_claims`, `credit_stress`, `financial_conditions`, `core_inflation`, `spy_`, `volatility_spike`, `oil_shock`, `fed_`); the longest prefix wins | Matches `events.py` |
| Inflation context `CPIAUCSL, PCEPILFE` | `CPILFESL, CPIAUCSL, PCEPILFE, T5YIE`; `core_cpi_momentum` uses `CPILFESL` | The re-acceleration event is defined on core CPI |
| Reuse fetched news "whose topics match" | Matches on `keyword_tag(item).topics` against `EventExplainSpec.topics` | Explanations run concurrently with LLM tagging, so LLM topics don't exist yet |
| Four curve-shape labels | Adds `twist steepening` / `twist flattening` | The front and back ends can move in opposite directions |
| Yield decomposition window "matching the triggering change" | Sharp move: 1w if the 1w change crossed `yield_move_1w`, else 1m. Multi-year highs: 1m. DGS30 events decompose the 10Y and say so | `yield_highs` has no window, and there is no 30Y TIPS series in the core set |
| `description` / `tags` on catalog entries | Trailing defaulted fields on `SeriesSpec` / `SymbolSpec` | Core entries and positional construction are unchanged |
| Planned extras in the narrative | `planned_indicators` / `planned_market` are added to the synthesis payload | They are code-derived, and the narrative needs them to answer the planned topic |

Findings from the live runs (2026-10-17):

- **Latency.** A cold run with the planner and explanations took 33.6s; a warm-ish run took 22.7s. The targets are ≤ 50s cold and ≤ 25s warm. The planner (about 3s warm) overlaps the core fetch, and the extra FRED fetch (about 12s) overlaps FRED's own tail. Explanation search took about 1–2s and the explanation LLM call about 1.8s.
- **The planner's timeout can overrun on a cold process.** One cold run logged `planner_ms=13371` against an 8s budget, because building the Groq client and parsing large FRED responses run synchronously on the event loop and delay the `wait_for` check. The planner is still not the slowest step (FRED took about 23s), so this was left as is.
- **Catalog check.** All 35 `EXTRA_SERIES_CATALOG` ids return recent data on FRED (`test_catalog_ids_exist_on_fred`).
- **Sample plan.** For "How is oil affecting the inflation outlook?" the planner chose DCOILWTICO, DCOILBRENTEU, CPIENGSL and BZ=F, with nothing dropped. Both detected events (`core_inflation_reaccelerating`, `fed_raised`) were explained with two cited URLs each and passed the number validator on the first try.
- **Evals: 17/17 pass**, but the first run showed a gap. In 3 cases both explanations were `unavailable` because Groq returned 400 (`tool_use_failed` / `output_parse_failed`). The model had answered with a bare JSON list or with prose reasoning instead of the structured tool call. Two fixes: `event_explainer_system` v2 names the `{"items": [...]}` wrapper and forbids prose or bare lists, and `_invoke` re-asks once when the provider rejects the output. With the fix, all three cases were explained on the first attempt.

## Reliability and chat fixes (schema 1.5)

- **FRED timeouts are per series.** Each series gets `FRED_SERIES_TIMEOUT_SHARE` of the source timeout. A single series retrying through its 4 attempts used to reach the source timeout, which threw away every series already fetched.
- **`/latest` only serves current, usable runs.** It skips replays of a past `as_of` and runs whose quality is `unusable`. `market_research_runs.quality` stores the verdict; `init_market_tables` adds the column to existing databases, and older rows (NULL) are treated as usable.
- **The narrative has a time limit:** the remaining run budget, with a floor of `SYNTHESIS_MIN_BUDGET_S`. If it runs out, the template is used.
- **Empty results are not cached.** Empty FRED, price and news responses can be transient. Empty series and missing symbols appear in `data_quality.notes`.
- **Chat shows more of the run.** The render now includes the quality warning, risks, implications and the planner's extras. Follow-ups are rewritten into a standalone query by the scope check, and only when there are earlier messages. That query reaches external search, so the prompt forbids client names and personal details.
- **Each output records `llm_model` and `prompt_versions`** for audit.

## Logging: checkpoints only

- **INFO and above are checkpoints.** A healthy run logs two lines: `run=... started` and `run=... finished in ...s quality=... llm_problems=...`.
- **WARNING means something needs a look:** a failed source or series, an LLM attempt that was rejected, failed or timed out, or quality issues. ERROR means the run failed. Each line carries the run id.
- **DEBUG holds the detail:** per-request status, per-stage latency and re-asks. Set `MARKET_RESEARCH_LOG_LEVEL=DEBUG` on the server, or use `-v` on the CLI.
- **The full record stays in the output and Langfuse.** `llm_attempts`, `data_quality` and the audit log are unchanged.

## Traceability and guardrails (schema 1.6)

- **`tracing.py` carries a `RunTrace` in a context variable,** so concurrent stages reach it without signature changes. Every LLM call passes a `trace_config` with the run id, stage, attempt and prompt versions. HTTP runs had no Langfuse callback before this, because they run as background tasks outside the chat graph.
- **`output.origin`** records the channel, session and client. A session is not a verified person: the chat has no login.
- **`output.llm_attempts`** lists every attempt with its outcome, problems and rejected text. `explanation_screen` and `narrative_screen` entries record what the advice screen removed.
- **`CitedSource.snippet` and `retrieved_at`** keep the text the model saw, so an explanation can be checked after the article changes.
- **`audit.py` is append-only** (`market_audit_events`): `run_finished` and `response_rendered` hold SHA-256 hashes, and `run_failed` holds the error. Read it at `GET /runs/{run_id}/audit`. An audit write failure logs a warning and doesn't fail the run.
- **No eval agent review.** Chat answers go straight to the user after `quality.py`, so `response_rendered` is the exact text they receive. The LLM compliance pass no longer runs on them, and the advice screen is the only check on tone.
- **The link check only trusts `url` and `cited_urls` fields.** A URL inside a news title or summary is article text, so it can't vouch for itself. Explanations have no URL fields, so any link in one fails: code maps citations to URLs.
- **The advice screen stays narrow on purpose.** "Investors favor energy" passes as description; "could favor" and a sentence opening with "Favor" do not.
- **Superlatives fail the wording check unless the payload uses them,** which can raise retries and template fallbacks. Check `llm_attempts` if template use rises.
- **Client names:** the agent never receives the name as a separate field, so the protection is partial: the heuristic plan prefers focus terms over the raw message, and `planner_system` v2 bans names in news queries.

## Quality gate and explanation-source fix (schema 1.4)

- **Quality gate (`quality.py`).** Added so the pipeline judges itself on every path, since neither HTTP nor chat runs go through the eval agent. It is code-only:
  - **Advice-language screen:** a narrow set of regex patterns, chosen so descriptive words like "selloff" or "risk-free rate" pass. A flagged explanation becomes `unavailable`; a flagged narrative is replaced by the template.
  - **Assessment:** `output.quality.status` is `ok` / `degraded` / `unusable`, with per-check booleans and issues. `planned:` failures and replays without news don't degrade the status.
- **"Why: … [source]" links returned 404 in the chat's side panel.** `article_reader.find_news_item` allowed only `news[].url`, but explanation sources come from the explainer's own searches. `EventExplanation.cited_sources` now records each cited article's title, domain and date, and the reader accepts those URLs. For older run files it falls back to `cited_urls`.
- **Live check (2026-10-17):** "What's driving yields higher?" gave `quality.status = ok`. All 4 explanation sources resolved through the reader: 2 returned extracted text, and 2 were `unavailable` because the sites block bots or are paywalled, which falls back to the summary.
