# Multi-Agent Triage System

A sophisticated multi-agent conversational AI system built with FastAPI backend and React frontend. The system intelligently routes user queries to specialized agents based on intent analysis, providing live macro/market research, and a general-purpose assistant for everything else (including personal-finance and investment-concept questions) - all through a central triage agent.

## 🏗️ Architecture

The system is built on a real **LangGraph `StateGraph`** with conditional edges and a checkpointer - not a hand-rolled loop:

- **🧠 Triage Agent**: routes requests using structured output (`with_structured_output`), not string-matching
- **🤖 General Assistant**: the catch-all specialist, with a bound `tavily_search` tool - the model itself decides when to search based on its system prompt, executed via LangGraph's `ToolNode`. It runs a structured scope check on each new message of a resumed session, so a drift to a market-conditions question hands back to triage instead of getting stuck answering out-of-lane questions (skipped when triage has just routed the message, so the two can't bounce it back and forth).
  - Personal-finance, budgeting and investment-concept questions go to the General Assistant; there is no separate finance specialist.
  - Programming questions go to the General Assistant too; there is no separate technical specialist.
- **📈 Market Researcher**: current macro and market conditions, via the market researcher pipeline - see the Market Researcher section below.
- **🔄 State Management & Persistence**: session state (including full message history) persisted via LangGraph's `AsyncPostgresSaver`, keyed by session ID (LangGraph's `thread_id`) - conversations survive backend restarts, not just reconnects. A separate lightweight `sessions` table drives a ChatGPT-style sidebar without needing to decode LangGraph's own storage format - see the "Postgres Schema" section below.
- **🗂️ Session Sidebar**: `components/Sidebar/Sidebar.tsx` lists past conversations (title, last-active time), sorted most-recent-first - new chat, switch between sessions, delete. The active session id is kept in `localStorage` so a page reload resumes the same chat instead of starting fresh.
- **⚡ Real-time Communication**: WebSocket-based chat with agent handoff notifications
- **🎯 Smart Routing**: a session resumes directly with whichever specialist it was talking to (no re-routing through triage every turn), until that specialist hands back control

Two subagents wrap the core flow:

- **🧹 Context Manager**: runs at the start of every turn; once the conversation gets large, it summarizes the older portion and drops it from state (via LangGraph's `RemoveMessage`), keeping a fixed window of recent messages verbatim - so long conversations don't blow past the model's context window.
- **✅ Eval Agent**: reviews every specialist/triage response before it ships. It can `approve` it, `flag` it with a visible caveat, or `regenerate` it with feedback (capped retries, so it never loops forever). For General Assistant and Market Researcher responses, it also runs a **compliance pass** - see below. Market Researcher answers skip the quality verdict and are never regenerated, since they are a deterministic render that a re-run can't change.

Several more pieces are in as functional placeholders, ready to harden before this handles anything beyond a demo:

- **🔒 PII Guard**: scans every incoming user message for likely SSNs, emails, and account/card numbers (credit cards are Luhn-validated to cut down false positives) and redacts them *before* they ever reach an LLM call or get persisted to state. This is a regex-based first pass - swap in something like Microsoft Presidio or a hosted DLP API before relying on it for real compliance guarantees. See `nodes/pii_guard.py`.
- **⚖️ Compliance check**: a second structured check inside the eval agent, for General Assistant and Market Researcher responses - looks for unqualified "guaranteed returns" language, missing disclaimers, or responses that read as personalized advice rather than general education. Can force a regenerate (rewrite needed) or a flag (just needs a disclaimer). This is an LLM judgment call, not a substitute for a real compliance review process (licensed-advisor sign-off, a maintained rules engine, an audit trail) before production use. See `nodes/eval_agent.py`.

> **Observability**: Langfuse tracing is wired in (`app/core/tracing.py`) - every turn is traced as one tree per session (triage/general/market-researcher/eval/context-manager LLM calls all nest under it automatically via LangGraph's callback propagation, no per-node code needed). Configure via the standard env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`); with them unset, tracing silently no-ops rather than breaking anything.

> **Prompt versioning**: every prompt in this project lives in `app/prompts/prompts.yaml`, loaded through `app/prompts/prompt_builder.py` (`get_prompt("agent.key")`) instead of being hardcoded in each node file. Each key keeps every version it's ever had plus a `latest` pointer; pin a specific key to an older/newer version without a code change via `PROMPT_VERSION_OVERRIDES='{"general.system": "v2"}'` - useful for rollback or an A/B test tied to `get_prompt_version(key)` in your eval/tracing metadata.

Graph shape (built with LangGraph's `StateGraph` - see `agents/graph.py`):

```mermaid
flowchart TD
    START([START]) --> pii_guard[🔒 pii_guard]
    pii_guard --> context_manager[🧹 context_manager]

    context_manager -->|new session| triage[🧠 triage]
    context_manager -->|resuming| general[🤖 general]
    context_manager -->|resuming| market_researcher[📈 market_researcher]

    triage -->|general| general
    triage -->|market| market_researcher
    triage -->|meta / canned reply| END1([END])

    general -->|tool call| general_tools[general_tools]
    general -->|now out of scope| triage
    general -->|final answer| eval[✅ eval]
    general_tools --> general

    market_researcher -->|now out of scope| triage
    market_researcher -->|rendered result| eval

    eval -->|regenerate| general
    eval -->|regenerate| triage
    eval -->|approve / flag| END2([END])
```

## 🗄️ Postgres Schema

Two independent things live in the same Postgres database, both keyed by the same `session_id` (the frontend-generated UUID, which is also LangGraph's `thread_id`) - one small table this codebase owns, and four LangGraph manages entirely on its own.

### `sessions` - sidebar metadata (owned by `app/core/db.py`)

| column       | type          | notes                                                        |
|--------------|---------------|---------------------------------------------------------------|
| `id`         | `text` PK     | = `session_id` = LangGraph's `thread_id`                       |
| `title`      | `text`        | derived from the first user message; never overwritten after  |
| `created_at` | `timestamptz` | set once, on first insert                                     |
| `updated_at` | `timestamptz` | bumped on every turn - drives sidebar sort order (most-recent-first) |

Written by `touch_session()` on every WebSocket turn (see `endpoints/__init__.py`). This table holds **no conversation content** - just enough to serve `GET /sessions` without touching LangGraph's storage at all.

### `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` - actual conversation state (owned by LangGraph's `AsyncPostgresSaver`)

These four tables are created and fully managed by LangGraph (`checkpointer.setup()` runs once in `app.py`'s lifespan) - nothing in this codebase writes to them directly:

- **`checkpoints`** - one row **per graph step**, not per session. A single turn walks through several nodes (`pii_guard → context_manager → triage → general → eval → ...`), and each transition writes a new row linked to the previous one via `parent_checkpoint_id` - a version chain, not one row per conversation. A single exchange can easily produce 5-10+ rows here.
- **`checkpoint_blobs`** - the actual `AgentState` field values (`messages`, `market_research_response`, etc. - one row per `(channel, version)`), msgpack-serialized. This is where message history actually lives byte-for-byte.
- **`checkpoint_writes`** - staged writes for a step before they're committed as the next checkpoint.
- **`checkpoint_migrations`** - the checkpointer's own internal schema-version bookkeeping.

`MultiAgentGraph.get_history()` (`agents/graph.py`) never queries these tables directly - it calls LangGraph's own `graph.aget_state(config)`, which reconstructs the latest `AgentState` from the blobs for you.

Deleting a session (`DELETE /sessions/{id}`) has to clean up both halves separately: `db.delete_session()` for the `sessions` row, plus `checkpointer.adelete_thread()` for everything across the four LangGraph tables.

## 📈 Market Researcher Agent

A data agent for a **main agent (orchestrator)** to call over HTTP. It is separate from the chat flow above. Each run does the following:

1. Pulls current macro, rates, credit and financial-conditions series from **FRED**, prices for about 25 ETFs, indices and futures from **yfinance**, and macro news from **Tavily**. In parallel, a **query planner** picks extra series, symbols and news queries for the caller's question, choosing only from curated catalogs.
2. Detects notable events, such as "10Y at multi-year high", a curve un-inversion, a Sahm rule trigger, or credit stress. It then **explains** the notable ones with targeted news searches and code-computed decompositions (e.g. how much of a yield move came from real yields vs breakevens), producing short explanations with cited sources.
3. Classifies the **economic cycle phase** (`early_expansion` / `late_expansion` / `recession` / `late_recession`), with probabilities, confidence, drivers and conflicting signals. It also reports the NY Fed yield-curve recession probability.
4. Writes everything to a **JSON file** that the main agent synthesizes later.

**Numbers come from code or cited sources, not the LLM.** The LLM chooses extras only from allowlists, tags news, and writes event explanations. Every number in an explanation must appear in the event's data, its decomposition or the articles it cites; code maps article numbers to URLs, so sources can't be invented. An optional narrative (`include_narrative: true`) is checked so that every number in it appears in the data; it falls back to a deterministic template if not. The regime, events, indicators, market snapshot and backtest are unaffected by the planner and explainer: planned extras go to separate fields (`planned_indicators`, `planned_market`) and never feed the regime or event rules. Full documentation (data sources, parsing, analytics, output format) is in [`backend/app/agents/market_researcher/market_research_explain.md`](backend/app/agents/market_researcher/market_research_explain.md); design notes and deviations from the original spec (`market_researcher_agent.md`) are in `NOTES.md` next to it.

### Endpoints

| Method & path | Purpose |
|---|---|
| `POST /agents/market-researcher/runs` | Start a run. The body is a `MarketResearchRequest` (`query`, `region`, `focus`, `lookback_days_news`, `as_of`, `include_narrative`, `planning` = `"auto"`/`"off"`, `explain_events` = `null`/`true`/`false`). Returns **202** with `run_id`, `status_url` and `output_url`. `?wait=true` blocks and returns the output (**200**) |
| `GET /agents/market-researcher/runs/{run_id}` | Status: `queued` / `running` / `succeeded` / `partial` (some sources failed, output still produced) / `failed` |
| `GET /agents/market-researcher/runs/{run_id}/output` | The run's JSON output (409 while still running) |
| `GET /agents/market-researcher/latest?region=US&max_age_minutes=60` | Freshest finished output, so a new run can be skipped |
| `GET /agents/market-researcher/schema` | JSON Schema of the output (the contract; also committed as `market_research_output.schema.json`) |
| `GET /agents/market-researcher/health` | Configured keys and storage reachability |

```bash
curl -X POST localhost:8000/agents/market-researcher/runs \
  -H 'content-type: application/json' -d '{"region": "US", "focus": ["rates", "energy"]}'
# -> {"run_id": "mr_20261016T063145Z_0aa2fb", "status": "queued", "status_url": "...", "output_url": "..."}
curl localhost:8000/agents/market-researcher/runs/mr_20261016T063145Z_0aa2fb/output
```

Operational details:

- **Cold runs** take about 35s, mostly the FRED fan-out of 35 series. **Warm runs** take about 20–25s with the planner and explanations (LLM calls: planner 1, tagging 1, explanations 1 + 1 retry, narrative 1–2 if requested), or about 5s with `planning: "off"` and `explain_events: false`. The run budget is 90s (`MARKET_RESEARCH_RUN_BUDGET`).
- **Query planner:** extras come only from `EXTRA_SERIES_CATALOG` (35 FRED series) and `EXTRA_SYMBOL_CATALOG` (26 symbols) in `config.py`. Anything else is dropped and listed in `plan.dropped`. Caps are 8 series, 8 symbols and 4 news queries. If the LLM fails, a keyword heuristic takes over. To add an option, append a spec with a `description` and `tags`. A failed extra (`planned:...`) does not make the run `partial`.
- **Quality gate:** every output carries `quality.status` (`ok` / `degraded` / `unusable`), with `checks` and `issues`. It comes from a final code-only stage (`quality.py`) that screens LLM-written text for advice wording and checks consistency, completeness, freshness and sources. Callers should read it first. It runs inside the pipeline, so the HTTP orchestrator gets the same verdict as the chat.
- **Event explanations:** the top 4 major/notable events get `event_explanations` (`explained` / `insufficient_evidence` / `unavailable` / `skipped`) with `cited_urls` and an optional code-derived `decomposition`. They are on by default for live runs and off for a past `as_of`. Per-event context, search templates and lookbacks are in `EVENT_EXPLAIN_SPECS`.
- **Caches:**

  | Data | Cache TTL |
  |---|---|
  | Daily series | 1h |
  | Monthly series | 12h |
  | Prices | 5 min |
  | News | 15 min |

- **Postgres tables:** the cache, the last regime (used for hysteresis) and the run registry live in three tables: `market_cache`, `market_regime_state` and `market_research_runs`.
- **Output files:** written to `backend/data/market_research/` (gitignored).
- **Limits:** concurrency is capped (`MARKET_RESEARCH_MAX_CONCURRENT_RUNS`, default 2). Identical in-flight requests share one run.
- **Regions:** only `US` is supported for now; other regions return 422.

### Geneva chat (adviser workspace)

The Geneva chat in the RM / IC / PS workspace (`frontend/src/components/geneva/GenevaChat.tsx`) uses the same LangGraph backend as `/legacy-chat`, over `ws://…/agents/langgraph?session_id=…&greet=false`. Client-data and workflow questions (IPS, goals, notes, holdings, TAA, pack drafts, CIO house view, products) are answered from the workspace. Other questions go to the backend, along with the adviser's role and the client in focus as `context`. The backend turns that context into a system note for the specialists (`app/agents/client_context.py`, prompt `shared.client_context`). Approval pauses for money-moving actions and Market Researcher source links (reader panel) work in Geneva too.

### Chat access (optional)

The same pipeline is also reachable from the chat:

- **Triage** has a `market` route. Questions about current macro or market conditions go to a **📈 Market Researcher** node. The node runs the pipeline with the validated narrative and renders the result as Markdown: the phase, events (each with a cited "Why:" line and decomposition when available), a headline table, sources and a disclaimer. The answer still passes through `eval`, including the compliance pass.
- **Source links open a side panel.** Clicking a news link in a Market Researcher reply opens a reader view of the article (extracted text, plus the agent's summary and tags) instead of leaving the chat. Sites that block this fall back to the summary and an "Open original" button.
- **The General Assistant is separate.** It has no access to the market researcher's tools or data. Its scope check hands questions about current macro or market conditions back to triage, which routes them to the Market Researcher.

### Dev tools

```bash
cd backend
python -m app.agents.market_researcher --focus rates --narrative      # one run from the CLI, prints the JSON path
python -m app.agents.market_researcher.backtest                       # regime backtest vs NBER dates -> backtest_report.md
python -m app.agents.market_researcher.schemas                        # regenerate the committed JSON Schema
python tests/evals/run_market_researcher_evals.py                     # 17-case live eval set (incl. 5 planner cases)
RUN_LIVE_MARKET_TESTS=1 pytest -m live                                # live smoke test (real APIs)
RUN_BACKTEST=1 pytest -m slow                                         # backtest acceptance test
```

The regime classifier is score-based and transparent. Every weight and threshold lives in `market_researcher/config.py`, so tune it there and re-run the backtest. The current backtest covers 1980 to the present. It catches **6/6** NBER recessions and makes 2 sustained false recession calls: the 2003 jobless recovery and the 2024 Sahm-rule trigger. See `backtest_report.md`.

## 📊 Portfolio Manager Agent

`backend/app/agents/portfolio_manager/` builds the six SAA templates the IC uses (**A** Capital preservation, **B** Income, **C** Balanced, **D** Growth, **E** Aggressive growth, **F** Opportunistic) into concrete, constraint-checked portfolios for one client. It then compares them, explains the result, and can nominate a preferred option for review. Each portfolio uses the same seven asset classes and growth-asset limits as the IC SAA builder in the frontend.

It is **proposal-only**: it never executes trades or changes holdings, and every response has `requires_rm_review: true`.

> **Core rule: numbers come from code, not from the LLM.**
> Python does all allocation, amounts, metrics and validation. The LLM, if configured, only writes narrative. That narrative is rejected if it states a number the engine didn't produce, or claims guarantees, optimality, live data or executed trades.

**Endpoints.** The main app serves these under `/agents/portfolio-manager`; the routes live in `app/endpoints/portfolio_manager.py`.

| Endpoint | Purpose |
|---|---|
| `GET /agents/portfolio-manager/health` | Liveness and the data sources in use |
| `GET /agents/portfolio-manager/templates` | The six SAA templates A–F (weights, growth share, minimum risk level and horizon) |
| `POST /agents/portfolio-manager/portfolio/generate` | Validate the profile → fetch market and product data → construct, validate, compare and explain options A–F |
| `GET /agents/portfolio-manager/portfolio/{request_id}` | A stored proposal. The store is in memory and bounded, so proposals are lost on restart. Returns `404` if unknown |
| `POST /agents/portfolio-manager/portfolio/{request_id}/options/{option_id}/evaluate` | Re-checks the IC's adjusted asset-class weights against the stored proposal (return, drawdown, growth share, fees, currency, concentration, minimum investments, ±5-point band) and returns the efficient frontier. Calculation only; nothing is saved |
| `POST /agents/portfolio-manager/portfolio/{request_id}/ask` | Answers a Geneva chat question about that proposal (plus the IC's picked portfolio, edited weights and current holdings). LLM answer checked by the same guardrails as the narratives, with a deterministic fallback. Read-only |

**Inputs**

- **Client profile and review trigger:** the request body. See `samples/sample_request.json`. Missing or contradictory fields are reported as BLOCKING, MATERIAL or MINOR, never guessed.
- **Market Researcher output:** a `MarketResearchOutput`, validated with that agent's own Pydantic model (`market_research_output.schema.json`). The Portfolio Manager uses:
  - the regime call and the 12-month recession probability;
  - events, indicators, implications and the quality flags.

  A recession call, or a recession probability of 50% or more, trims the growth ceiling by 10 points. A run marked `unusable` is not used.
- **Product candidates:** from the Product Specialist (mocked for now). Each product is screened for restrictions, eligibility, sector exclusions, ESG, lock-in versus horizon, minimum investment and currency.
- **House assumptions:** `assumptions/capital_market_assumptions.json`. The Market Researcher publishes no return forecasts, so expected returns for non-yield assets and the Expansion / Slowdown / Recession stress scenarios come from this explicit, illustrative file. They are always labelled `ASSUMPTION`.

**Mock data and integration points.** By default the agent runs on illustrative mock data, so no upstream services are needed. Each upstream source has one function to replace:

| Source | Function to replace | Constant to set to `"LIVE"` |
|---|---|---|
| Market Researcher | `get_market_analysis()` in `upstream/market_analysis.py` | `MARKET_ANALYSIS_SOURCE` |
| Product Specialist | `get_product_candidates()` in `upstream/product_specialist.py` | `PRODUCT_CANDIDATES_SOURCE` |

Both functions are marked `# INPUT API HERE`.

**Run it**

- **Full stack:** the Portfolio Manager is part of the main backend. Start the main backend as described under Getting Started.
- **Without Postgres or Docker:**

  ```bash
  cd backend
  python -m app.agents.portfolio_manager serve --port 8001          # only the Portfolio Manager routes, same paths
  python -m app.agents.portfolio_manager generate app/agents/portfolio_manager/samples/sample_request.json --no-llm
  ```

- **LLM settings:**
  - `GROQ_API_KEY` in the root `.env` enables LLM narratives. Without it, the agent uses deterministic template explanations.
  - `PORTFOLIO_LLM_ENABLED=false` forces the template explanations.
  - `PORTFOLIO_LLM_MODEL` overrides the model. The default is `CURRENT_MODEL` in `app/core/constants.py`.

**Tests:** `cd backend && pytest tests/test_portfolio_*.py`. These run offline: the LLM is faked and the clock is fixed.

**In the frontend.** The agent appears in the Investment Counsellor's **3L And SAA** flow (`/ic/requests/:clientId/3l`, then `saa`):

1. **Client profile and 3L.** The IC reads the RM's IPS and sets the buckets. "Continue to SAA" saves them.
2. **Pick a portfolio** (`/saa`) shows the agent's inputs and where each came from, and the IC clicks **Run the Portfolio Manager**:
   - The portfolio is the client's AUM. The **Liquidity bucket** is held separately in cash, and the agent invests the rest.
   - Risk category, risk limit, **risk capacity** and the drawdown limit come from IPS part 3.
   - Goals come from goal-plan events more than 3 years out. Nearer goals are funded by the Liquidity bucket.
   - Fields that aren't captured are sent as missing, never guessed.
3. Only the portfolios the agent can construct within the client's limits are shown, so the number varies by client (a conservative client may get one; an aggressive one up to six). The rest are listed under "Not proposed for this client" with the reason. If the profile cannot support any portfolio, a **More information needed** panel names the missing fields instead.
4. Two switchable views keep the selection:
   - **Portfolios:** one card per proposed portfolio, with every asset class and sub-class, amounts, risk level, expected return assumption, fees, liquidity, how it differs from the more cautious portfolio, advantages and disadvantages, goal fit and why it was proposed. The selected portfolio is shown in detail below (allocation and products, or the rationale).
   - **Compare portfolios:** one row per asset class found in any portfolio, plus return, downside, scenarios, liquidity, fees, diversification, currency and fit, and the product comparison.
5. **Edit weights** (`/saa/weights`) is its own step. The weight editor sits beside the **efficient frontier**: a long-only mean-variance frontier over the asset classes the client can hold, built from the house assumptions' expected returns, volatilities and correlations. Every change is re-checked by the backend (debounced), which moves the adjusted point and updates the metrics. The editor offers **Reset to original weights**, **Back** (the draft and selection are kept) and **Continue: send back to RM**, which stays disabled until every check passes. The agent never approves anything.

The mapping from captured data to agent inputs is in `buildPortfolioInputs` in `frontend/src/services/arcApi.ts`. The frontend calls `VITE_API_BASE`, which defaults to `http://localhost:8000`.

## 🧺 Product Recommender Agent

`backend/app/agents/product_recommender/` drafts a product shortlist for one client, for a Product Specialist (PS) to review. It also gives its own Buy / Hold / Sell view on each of the seven asset classes, shown beside the CIO house view and never instead of it. It never approves anything: the PS approves at gate G3 in the UI. The plan is `product_recommender_agent.md`; decisions and deviations are in the agent's `NOTES.md`.

> **Core rule: the engine decides, the LLM only writes.**
> The suitability gate, the ranking, which products are shortlisted, and every stance and number in an asset-class view come from code. If configured, the LLM rewrites the explanation text from those facts. A guardrail rejects any text that adds a number, product or citation that was not in its input, mentions fees, gives advice, claims a guarantee, or contradicts a stance. Rejected text is replaced by the rule-based version.

**How a recommendation is made**

1. **Shelf:** one product shelf, `data/shelf.json` (23 illustrative products, at least 2 per asset class), shared with the Portfolio Manager.
2. **Suitability gate:** every hard check must pass. A product that fails is excluded with a code and a reason: `RISK_ABOVE_LIMIT`, `RISK_UNKNOWN`, `LIQUIDITY`, `LIQUIDITY_NEED`, `CURRENCY`, `RESTRICTED`, `SECTOR_EXCLUDED`, `ESG`, `ELIGIBILITY`, `NOT_PREFERRED`, `DATA_INVALID` (`DRAWDOWN` only with `RECOMMENDER_DRAWDOWN_HARD_LIMIT=true`). Unknown data is never a pass, and no score can rescue an excluded product.
3. **Ranking:** each eligible product gets named score components: `objective_fit`, `house_view`, `risk_budget_use`, `horizon_match`, `currency_fit`, `data_quality` and `rating`. Ties break by product id, so the order is reproducible. **Fees never rank**: they are returned in a separate `costs` block marked `display_only`.
4. **Reasons:** 3 to 5 cited bullets per shortlisted product, ending with `[HV-...]` (house view page) or the product id (its factsheet).

**Asset-class views.** The agent's view on a class comes from the latest Market Researcher run. Each mapped series is read as a level (where it sits in its 10-year range), a 3-month change, or a 3-month move relative to another series. The reading is clipped to [-1, 1], signed by whether it helps the class, weighted, and tilted by the cycle regime. A score of +0.20 or more is Buy and -0.20 or less is Sell (not calibrated yet). A segment is Most or Least preferred when it sits 0.15 above or below its class's score. The mapping is in `asset_views/config.py`; the scoring is in `asset_views/scoring.py`.

**Endpoints.** The main app serves these under `/agents/product-recommender`; the routes live in `app/endpoints/product_recommender.py`.

| Endpoint | Purpose |
|---|---|
| `GET /agents/product-recommender/health` | Shelf and house-view status |
| `GET /agents/product-recommender/shelf` | Every product on the shelf (fees for information only) |
| `GET /agents/product-recommender/house-view` | The CIO house view per asset class, with page citations |
| `POST /agents/product-recommender/recommend` | Gate, rank and explain products for one client (`client_id`, `client_profile`, optional `options`) |
| `GET /agents/product-recommender/asset-class-views` | The CIO and agent stance for all seven classes (no prose) |
| `GET /agents/product-recommender/asset-class-views/{asset_class}` | The full view on one class: snapshot, segments, scenarios, risks and implementation |
| `POST /agents/product-recommender/asset-class-views/{asset_class}` | The same, with a client lens (which products and segments this client can access) |

`{asset_class}` takes a slug such as `fixed-income` or `real-estate`.

**LLM text**

- **Who wrote it:** each reason has `source: "llm" | "deterministic"`; each view has `narrative_source`. Both responses carry `explanation_status`, saying whether the LLM was used and why not.
- **What the LLM is sent:** only engine facts, with the rule-based text as its draft. No client id, name or score is sent, and no fee figures.
- **Fallback:** a product or text item that fails the guardrail is retried once, with the violations listed. If it fails again, it keeps its rule-based text. A provider error is retried once; a timeout is not. Without `GROQ_API_KEY` everything is rule-based.
- **Prompts:** `product_recommender.*` in `app/prompts/prompts.yaml`. Each call is traced in Langfuse, when configured, with its prompt versions.
- **Caching:** view prose is cached in memory per class, Market Researcher run, house-view date and client, so a page reload makes no LLM call.
- **Settings:**

  | Variable | Default | Effect |
  |---|---|---|
  | `RECOMMENDER_LLM_ENABLED` | `true` | `false` forces rule-based text even with a key |
  | `RECOMMENDER_LLM_MODEL` | `CURRENT_MODEL` | Groq model id |
  | `RECOMMENDER_LLM_TIMEOUT_SECONDS` | `30` | Per-call timeout before falling back |
  | `RECOMMENDER_LLM_MAX_TOKENS` | `6000` | Includes a reasoning model's hidden reasoning; 2000 is too few for a 5-product shortlist |
  | `RECOMMENDER_LIQUIDITY_NEED_MONTHS` | `12` | A dated withdrawal within this window triggers the liquidity-need check |
  | `RECOMMENDER_DRAWDOWN_HARD_LIMIT` | `false` | `true` turns the single-product drawdown check into an exclusion |
  | `PRODUCT_DATA_STALE_AFTER_DAYS` | `90` | Product data older than this is flagged stale (shared with the PM) |

**Tests:** `cd backend && pytest tests/test_product_recommender.py tests/test_product_recommender_llm.py tests/test_asset_class_views.py`. These run offline: the LLM is faked or switched off, and the clock is fixed.

**In the frontend**

- **PS AI assistant (Geneva chat):** ask for product recommendations to get the ranked shortlist, with reasons, exclusions and a line saying whether the reasons were written by AI or by rules. "What's the view on fixed income?" gives the asset-class card.
- **Asset views:** `/ps/asset-views` shows all seven classes; `/ps/asset-views/:assetClass` shows one class in full, with Overview, Market, Risks, Products and Sources tabs.

Data goes through `recommendProducts` and the asset-view calls in `frontend/src/services/arcApi.ts`.

## 🔧 Technology Stack

### Backend

- **FastAPI** - Modern web framework for building APIs
- **LangChain** / **LangChain-Groq** - LLM application development framework
- **LangGraph** - Multi-agent workflow orchestration (`StateGraph`, `ToolNode`, checkpointer, `interrupt()`)
- **Groq** - High-performance LLM inference
- **Tavily** - Real-time web search integration for current information (called directly over HTTP, no SDK dependency)
- **PostgreSQL** (`langgraph-checkpoint-postgres` + `psycopg[binary,pool]`) - persists LangGraph's own conversation-state checkpoints, plus a small custom `sessions` table for the sidebar - see "Postgres Schema" section below
- **Langfuse** - LLM observability/tracing (optional - no-ops if unconfigured)
- **WebSockets** - Real-time bidirectional communication
- **Pydantic** - Data validation and structured LLM output

### Infrastructure

- **Docker Compose** - `postgres` + `backend` + `frontend` as three services, source bind-mounted into `backend`/`frontend` for hot-reload during development (not a production build)

### Frontend

- **React 19** - Modern UI library with latest features
- **TypeScript** - Type-safe JavaScript development
- **Vite** - Fast build tool and development server
- **Tailwind CSS 4** - Utility-first styling framework
- **React Markdown** (+ `remark-gfm`) - Markdown rendering with GitHub-flavored syntax

## 📁 Project Structure

```
├── docker-compose.yml                   # postgres + backend + frontend, for `docker compose up`
├── backend/
│   ├── Dockerfile
│   ├── app/
│   │   ├── app.py                       # FastAPI app + lifespan (opens the Postgres checkpointer/pool)
│   │   ├── agents/
│   │   │   ├── graph.py                 # Multi-agent orchestration (StateGraph) + get_history()
│   │   │   ├── state.py                 # Agent state schema
│   │   │   ├── tools.py                 # Agent tools (web search)
│   │   │   ├── market_researcher/       # Market researcher agent (HTTP-orchestrated; see its NOTES.md)
│   │   │   │   ├── service.py           # Pipeline: fetch -> features -> events -> regime -> JSON file
│   │   │   │   ├── adapters/            # FRED, yfinance, Tavily news (retry/backoff/rate limits)
│   │   │   │   ├── features.py / events.py / regime.py   # Deterministic analytics
│   │   │   │   ├── news_tagging.py / synthesis.py         # LLM tagging + optional validated narrative
│   │   │   │   ├── runs.py              # Run registry + background runner behind the endpoint
│   │   │   │   ├── config.py            # Series, watchlist, thresholds, regime weights, TTLs
│   │   │   │   └── backtest.py          # Regime backtest vs NBER -> backtest_report.md
│   │   │   ├── product_recommender/     # Product shortlist + asset-class views (see its NOTES.md)
│   │   │   │   ├── data/                # shelf.json, house_view.json
│   │   │   │   ├── suitability.py / ranking.py           # Hard gate, fee-free scoring
│   │   │   │   ├── explain.py           # Rule-based reasons + LLM rewrite
│   │   │   │   ├── llm.py / guardrails.py                # LLM call, retry, fallback; text checks
│   │   │   │   └── asset_views/         # Agent view per asset class (scoring, builder, narrative)
│   │   │   └── nodes/
│   │   │       ├── triage.py            # Main routing agent
│   │   │       ├── general.py           # General-purpose assistant (incl. personal finance)
│   │   │       ├── market_researcher.py # Chat node for the market researcher pipeline
│   │   │       ├── context_manager.py   # Conversation compaction
│   │   │       ├── eval_agent.py        # Response review + compliance pass
│   │   │       └── pii_guard.py         # Inbound PII scan/redaction
│   │   ├── core/
│   │   │   ├── constants.py             # Model constants
│   │   │   ├── tracing.py               # Langfuse tracing setup
│   │   │   ├── db.py                    # Postgres pool + `sessions` table (sidebar metadata)
│   │   │   └── __init__.py              # LLM client factory
│   │   ├── prompts/
│   │   │   ├── prompts.yaml             # Versioned prompt text for every agent
│   │   │   └── prompt_builder.py        # get_prompt()/get_prompt_version() loader
│   │   └── endpoints/
│   │       ├── __init__.py              # WebSocket route + /sessions REST routes
│   │       ├── market_researcher.py     # /agents/market-researcher/* (runs, latest, schema, health)
│   │       └── product_recommender.py   # /agents/product-recommender/* (recommend, asset-class views)
│   └── requirements.txt                 # Python dependencies
├── frontend/
│   ├── Dockerfile
│   ├── src/
│   │   ├── App.tsx                      # Main application component
│   │   ├── components/
│   │   │   ├── Chat/
│   │   │   │   ├── ChatContainer.tsx    # Main chat interface + session/sidebar state
│   │   │   │   ├── MessageList.tsx      # Message display component
│   │   │   │   ├── MessageInput.tsx     # User input component
│   │   │   │   ├── ApprovalPrompt.tsx   # Approve/Decline UI (unused: the backend no longer pauses for approval)
│   │   │   │   ├── AgentBadge.tsx       # Agent identification UI
│   │   │   │   ├── SearchIndicator.tsx  # "Searching..." status indicator
│   │   │   │   └── TypingIndicator.tsx  # Typing/response-pending indicator
│   │   │   └── Sidebar/
│   │   │       └── Sidebar.tsx          # ChatGPT-style session list (new/switch/delete)
│   │   ├── services/
│   │   │   └── api.ts                   # WebSocket client + /sessions REST helpers
│   │   └── types/
│   │       └── index.ts                 # TypeScript type definitions
│   ├── package.json                     # Node.js dependencies
│   └── vite.config.ts                   # Vite configuration
└── README.md                            # This file
```

## 🚀 Getting Started

### Environment Setup (required either way)

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. **Set up environment variables** - create a `.env` file in the project root:
   ```bash
   GROQ_API_KEY=your_groq_key_here
   TAVILY_API_KEY=your_tavily_key_here

   # optional - tracing no-ops if these are unset
   LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
   LANGFUSE_SECRET_KEY=your_langfuse_secret_key
   LANGFUSE_HOST=https://cloud.langfuse.com

   # only read outside Docker - docker-compose.yml overrides this to point
   # at the `postgres` service instead of localhost
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fin_ai_agents

   # market researcher agent (see "Market Researcher Agent" below)
   FRED_API_KEY=your_fred_key_here          # free: https://fred.stlouisfed.org/docs/api/api_key.html
   # optional
   MARKET_RESEARCH_API_TOKEN=               # if set, its endpoints require "Authorization: Bearer <token>"
   MARKET_RESEARCH_OUTPUT_DIR=              # default: backend/data/market_research
   MARKET_DATA_PROVIDER=yfinance
   NEWS_PROVIDER=tavily                     # reuses TAVILY_API_KEY
   ```

### Option A: Docker Compose (recommended)

**Prerequisite:** Docker Desktop (or another Docker Engine) running.

```bash
docker compose up -d
```

Starts all three services - `postgres`, `backend` (`http://localhost:8000`), `frontend` (`http://localhost:5173`). Source is bind-mounted into `backend`/`frontend`, both run with hot-reload, so this stays a normal dev loop (edit code, see it live) rather than needing a rebuild per change.

- Rebuild after a dependency change (`requirements.txt` / `package.json`): `docker compose up -d --build`
- Stop everything: `docker compose down` (add `-v` only if you actually want to wipe the Postgres volume/history)
- Logs: `docker compose logs -f backend` (or `frontend`, `postgres`)

### Option B: Run everything manually

**Prerequisites:** Python 3.10+, Node.js 18+, and a Postgres instance reachable at your `DATABASE_URL` (`docker compose up -d postgres` on its own works fine here too, if you'd rather run the app processes natively).

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.app:app --reload
```

**Backend runs on:** `http://localhost:8000`

```bash
# Frontend
cd frontend
npm install
npm run dev
```

**Frontend runs on:** `http://localhost:5173`

## 💡 Usage Examples

### Starting a Conversation

1. **Launch the stack** (`docker compose up -d`, or backend + frontend manually - see Getting Started above)
2. **Open browser** to `http://localhost:5173`
3. **Start chatting** - triage routes each new topic to the right specialist automatically

### How search actually gets triggered

The General Assistant has `tavily_search` bound as a real tool via `bind_tools()` - **the model decides for itself**, per its system prompt, whether a question depends on information that could have changed recently (current prices, versions, news, recent releases) versus stable, well-known facts it can just answer directly. There's no keyword list or regex gating this - it's a genuine LLM tool-calling decision, and the frontend's search indicator reflects whether a search actually happened that turn, not a client-side guess.

### Example Interactions

#### 📈 Market Research Questions

```
User: "Are recession risks rising?"
Market Researcher: Pulls live FRED, market and news data, then replies with the cycle phase and confidence,
the yield-curve recession probability, notable events, a headline indicator table, and source links
```

#### 💰 Financial Questions

```
User: "What's a good P/E for a growth stock?"
General Assistant: Answers as general education, with a not-personalized-advice caveat
```

```
User: "What's the current Tesla stock performance?"
General Assistant: 🌐 Searches for current prices and news, then answers with a disclaimer
```

```
User: "Buy $500 of VOO"
General Assistant: Explains it can't place trades or move money
```

#### 🤖 General Conversations

```
User: "Explain quantum computing"
General Assistant: Comprehensive explanation of quantum computing principles and applications
```

```
User: "Write a poem about artificial intelligence"
General Assistant: Original creative content without needing web search
```

```
User: "What's the weather in Singapore right now?"
General Assistant: 🌐 Searches for current conditions, then answers
```

#### 🗂️ Session Sidebar

```
Click "+ New chat"          -> starts a fresh session (its own thread_id), sidebar entry appears once you send
                                the first message (that's what sets its title)
Click a past conversation   -> reconnects the socket to that session's thread_id and replays its history from
                                Postgres via GET /sessions/{id}/messages
Click the ✕ on a session    -> deletes it from both the sidebar (`sessions` table) and LangGraph's own
                                checkpoint tables
Restart the whole app       -> reopen the browser, your last active session and all sidebar history are still
                                there (Postgres-backed, not in-memory)
```

### Advanced Features

- **Context Persistence**: Conversations maintain context across agent handoffs, and get compacted automatically once they grow large
- **Persistent Chat History**: conversations survive backend restarts (Postgres-backed checkpointer, not in-memory) and are browsable/switchable from a ChatGPT-style sidebar - see "Postgres Schema" section below
- **Multi-turn Dialogues**: Specialists can handle follow-up questions in their domain without re-routing through triage
- **Intelligent Routing**: LLM-based intent analysis (structured output, not string-matching) ensures accurate agent selection
- **Real-time Web Search**: Tavily integration, model-decided per turn, for current information and market data
- **Response Review**: every final answer passes through an eval agent (approve/flag/regenerate) before it ships, with an extra compliance pass for General Assistant and Market Researcher answers
- **PII Redaction**: likely SSNs, emails, and card/account numbers are stripped from incoming messages before they reach any LLM call
- **Real-time Updates**: WebSocket notifications for agent transitions and search status
- **Error Handling**: Graceful fallbacks and error recovery

## 🛠️ Development

### Adding New Agents

1. **Create agent class** in `backend/app/agents/nodes/`
2. **Implement required methods** (`run`, scope check if it should hand back to triage)
3. **Add its prompt(s)** to `app/prompts/prompts.yaml`
4. **Register agent** as a node + conditional edges in `graph.py` (add a `route_after_<agent>` function and, if it needs tools, a `ToolNode`)

### API Extensions

- **Add endpoints**: Extend `backend/app/endpoints/`
- **Modify state**: Update `AgentState` in `state.py`
- **Add tools**: Implement agent capabilities in `tools.py` (bind them in the relevant node's `bind_tools()` call and add them to that agent's `ToolNode` in `graph.py`); put non-trivial tool logic in its own module rather than inline in the `@tool` function
- **Extend the `sessions` table**: add columns/queries in `core/db.py` - it's a plain `psycopg` pool, no ORM/migration framework, so schema changes are just SQL you run once (`CREATE TABLE IF NOT EXISTS`/`ALTER TABLE`) in that module. Don't touch LangGraph's own `checkpoint*` tables directly - go through `AsyncPostgresSaver`'s API instead (`graph.aget_state()`, `checkpointer.adelete_thread()`, etc.), since it owns their format.
