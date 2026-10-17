# Multi-Agent Triage System

A sophisticated multi-agent conversational AI system built with FastAPI backend and React frontend. The system intelligently routes user queries to specialized agents based on intent analysis, providing expert responses for financial questions and live macro/market research, and a general-purpose assistant for everything else - all through a central triage agent.

## 🏗️ Architecture

The system is built on a real **LangGraph `StateGraph`** with conditional edges and a checkpointer - not a hand-rolled loop:

- **🧠 Triage Agent**: routes requests using structured output (`with_structured_output`), not string-matching
- **💰 Finance Expert** / **🤖 General Assistant**: specialists with a bound `tavily_search` tool - the model itself decides when to search based on its system prompt, executed via LangGraph's `ToolNode`. Each also runs its own structured scope check per new message, so a topic drift mid-conversation hands back to triage instead of getting stuck answering out-of-lane questions.
  - **Finance** additionally has two tools: `propose_financial_action` (any money-moving action, gated by human approval - see below) and `generate_client_report` (a currently-placeholder tool for producing a client-ready document; see Functional Placeholders below).
  - Programming questions go to the General Assistant; there is no separate technical specialist.
  - Finance also runs incoming queries through a small glossary (`agents/finance_glossary.py`) that expands common shorthand/acronyms (P/E, YoY, EBITDA, etc.) before scope-checking, so jargon-heavy questions still classify correctly.
- **🔄 State Management & Persistence**: session state (including full message history) persisted via LangGraph's `AsyncPostgresSaver`, keyed by session ID (LangGraph's `thread_id`) - conversations survive backend restarts, not just reconnects. A separate lightweight `sessions` table drives a ChatGPT-style sidebar without needing to decode LangGraph's own storage format - see the "Postgres Schema" section below.
- **🗂️ Session Sidebar**: `components/Sidebar/Sidebar.tsx` lists past conversations (title, last-active time), sorted most-recent-first - new chat, switch between sessions, delete. The active session id is kept in `localStorage` so a page reload resumes the same chat instead of starting fresh.
- **⚡ Real-time Communication**: WebSocket-based chat with agent handoff notifications
- **🎯 Smart Routing**: a session resumes directly with whichever specialist it was talking to (no re-routing through triage every turn), until that specialist hands back control

Two subagents wrap the core flow:

- **🧹 Context Manager**: runs at the start of every turn; once the conversation gets large, it summarizes the older portion and drops it from state (via LangGraph's `RemoveMessage`), keeping a fixed window of recent messages verbatim - so long conversations don't blow past the model's context window.
- **✅ Eval Agent**: reviews every specialist/triage response before it ships. It can `approve` it, `flag` it with a visible caveat, or `regenerate` it with feedback (capped retries, so it never loops forever). For finance responses specifically, it also runs a **compliance pass** - see below.

Several more pieces are in as functional placeholders, ready to harden before this handles anything beyond a demo:

- **🔒 PII Guard**: scans every incoming user message for likely SSNs, emails, and account/card numbers (credit cards are Luhn-validated to cut down false positives) and redacts them *before* they ever reach an LLM call or get persisted to state. This is a regex-based first pass - swap in something like Microsoft Presidio or a hosted DLP API before relying on it for real compliance guarantees. See `nodes/pii_guard.py`.
- **⚖️ Compliance check**: a second structured check inside the eval agent, finance responses only - looks for unqualified "guaranteed returns" language, missing disclaimers, or responses that read as personalized advice rather than general education. Can force a regenerate (rewrite needed) or a flag (just needs a disclaimer). This is an LLM judgment call, not a substitute for a real compliance review process (licensed-advisor sign-off, a maintained rules engine, an audit trail) before production use. See `nodes/eval_agent.py`.
- **🛑 Human-in-the-loop approval**: any money-moving action (trade, transfer, rebalance) goes through a `propose_financial_action` tool that's gated by a hard `interrupt()` - the graph pauses mid-turn and won't proceed until the user explicitly confirms. The tool itself is currently inert (it returns a description, it doesn't touch any real account); the approval gate is real and should stay in front of an actual brokerage/banking integration later, not be removed. See `nodes/human_approval.py`. The WebSocket protocol pauses with `requires_confirmation: true` + a `pending_action` payload; the frontend swaps the normal message box for an explicit Approve/Decline prompt (`components/Chat/ApprovalPrompt.tsx`) rather than leaving free text open - typing a plain reply while paused here wouldn't work anyway, since LangGraph just re-triggers the same interrupt on anything that isn't the exact `{"action": "confirm_financial_action", "approved": true|false}` payload.
- **📄 Client-ready report generation**: `generate_client_report`, bound only to the Finance Expert, is meant to turn a conversation's findings/recommendations into a formatted, downloadable document (PDF, Markdown, etc.). The output format and generation logic are undecided, so calling it today just returns a stub string. See `agents/report_generator.py`.

> **Observability**: Langfuse tracing is wired in (`app/core/tracing.py`) - every turn is traced as one tree per session (triage/finance/general/market-researcher/eval/context-manager LLM calls all nest under it automatically via LangGraph's callback propagation, no per-node code needed). Configure via the standard env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`); with them unset, tracing silently no-ops rather than breaking anything.

> **Prompt versioning**: every prompt in this project lives in `app/prompts/prompts.yaml`, loaded through `app/prompts/prompt_builder.py` (`get_prompt("agent.key")`) instead of being hardcoded in each node file. Each key keeps every version it's ever had plus a `latest` pointer; pin a specific key to an older/newer version without a code change via `PROMPT_VERSION_OVERRIDES='{"finance.system": "v2"}'` - useful for rollback or an A/B test tied to `get_prompt_version(key)` in your eval/tracing metadata.

Graph shape (built with LangGraph's `StateGraph` - see `agents/graph.py`):

```mermaid
flowchart TD
    START([START]) --> pii_guard[🔒 pii_guard]
    pii_guard --> context_manager[🧹 context_manager]

    context_manager -->|new session| triage[🧠 triage]
    context_manager -->|resuming| finance[💰 finance]
    context_manager -->|resuming| general[🤖 general]
    context_manager -->|resuming| market_researcher[📈 market_researcher]

    triage -->|finance| finance
    triage -->|general| general
    triage -->|market| market_researcher
    triage -->|meta / canned reply| END1([END])

    finance -->|tool call| finance_tools[finance_tools]
    finance -->|money-moving action| human_approval[🛑 human_approval]
    finance -->|now out of scope| triage
    finance -->|final answer| eval[✅ eval]
    finance_tools --> finance
    human_approval -->|resume with decision| finance

    general -->|tool call| general_tools[general_tools]
    general -->|now out of scope| triage
    general -->|final answer| eval
    general_tools --> general

    market_researcher -->|now out of scope| triage
    market_researcher -->|rendered result| eval

    eval -->|regenerate| finance
    eval -->|regenerate| general
    eval -->|regenerate| market_researcher
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

- **`checkpoints`** - one row **per graph step**, not per session. A single turn walks through several nodes (`pii_guard → context_manager → triage → finance → eval → ...`), and each transition writes a new row linked to the previous one via `parent_checkpoint_id` - a version chain, not one row per conversation. A single exchange can easily produce 5-10+ rows here.
- **`checkpoint_blobs`** - the actual `AgentState` field values (`messages`, `finance_response`, etc. - one row per `(channel, version)`), msgpack-serialized. This is where message history actually lives byte-for-byte.
- **`checkpoint_writes`** - staged writes for a step before they're committed as the next checkpoint; also backs the `human_approval` node's `interrupt()`/resume mechanism.
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

### Chat access (optional)

The same pipeline is also reachable from the chat:

- **Triage** has a `market` route. Questions about current macro or market conditions go to a **📈 Market Researcher** node. The node runs the pipeline with the validated narrative and renders the result as Markdown: the phase, events (each with a cited "Why:" line and decomposition when available), a headline table, sources and a disclaimer. The answer still passes through `eval`, including the compliance pass.
- **Source links open a side panel.** Clicking a news link in a Market Researcher reply opens a reader view of the article (extracted text, plus the agent's summary and tags) instead of leaving the chat. Sites that block this fall back to the summary and an "Open original" button.
- **The Finance Expert is separate.** It has no access to the market researcher's tools or data. Its scope check hands questions about current macro or market conditions back to triage, which routes them to the Market Researcher.

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
│   │   │   ├── tools.py                 # Agent tools (search, propose action, generate report)
│   │   │   ├── report_generator.py      # Placeholder client-report generation logic
│   │   │   ├── finance_glossary.py      # Financial shorthand/acronym -> full term mapping
│   │   │   ├── market_researcher/       # Market researcher agent (HTTP-orchestrated; see its NOTES.md)
│   │   │   │   ├── service.py           # Pipeline: fetch -> features -> events -> regime -> JSON file
│   │   │   │   ├── adapters/            # FRED, yfinance, Tavily news (retry/backoff/rate limits)
│   │   │   │   ├── features.py / events.py / regime.py   # Deterministic analytics
│   │   │   │   ├── news_tagging.py / synthesis.py         # LLM tagging + optional validated narrative
│   │   │   │   ├── runs.py              # Run registry + background runner behind the endpoint
│   │   │   │   ├── config.py            # Series, watchlist, thresholds, regime weights, TTLs
│   │   │   │   └── backtest.py          # Regime backtest vs NBER -> backtest_report.md
│   │   │   └── nodes/
│   │   │       ├── triage.py            # Main routing agent
│   │   │       ├── finance.py           # Finance expert
│   │   │       ├── general.py           # General-purpose assistant
│   │   │       ├── context_manager.py   # Conversation compaction
│   │   │       ├── eval_agent.py        # Response review + finance compliance pass
│   │   │       ├── pii_guard.py         # Inbound PII scan/redaction
│   │   │       └── human_approval.py    # Money-moving action approval gate
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
│   │       └── market_researcher.py     # /agents/market-researcher/* (runs, latest, schema, health)
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
│   │   │   │   ├── ApprovalPrompt.tsx   # HITL Approve/Decline UI (see human_approval.py)
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

The Finance Expert and General Assistant each have `tavily_search` bound as a real tool via `bind_tools()` - **the model decides for itself**, per its system prompt, whether a question depends on information that could have changed recently (current prices, versions, news, recent releases) versus stable, well-known facts it can just answer directly. There's no keyword list or regex gating this - it's a genuine LLM tool-calling decision, and the frontend's search indicator reflects whether a search actually happened that turn, not a client-side guess.

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
Finance Expert: Shorthand ("P/E") is expanded via the finance glossary before scope-checking, then answered
with an educational disclaimer.
```

```
User: "What's the current Tesla stock performance?"
Finance Expert: 🌐 Searches for current market data, then answers with a disclaimer
```

```
User: "Buy $500 of VOO"
Finance Expert: calls propose_financial_action instead of just describing it -> the message box is replaced
with an Approve/Decline prompt; nothing proceeds until you click one (nothing is actually wired to a broker yet)
```

```
User: "Put together a report I can send my accountant"
Finance Expert: calls generate_client_report -> currently returns a placeholder response, since document
generation isn't implemented yet
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
- **Human-in-the-Loop Safety**: money-moving finance actions pause for an explicit Approve/Decline in the UI before proceeding
- **Response Review**: every final answer passes through an eval agent (approve/flag/regenerate) before it ships, with an extra compliance pass for finance
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
- **Add tools**: Implement agent capabilities in `tools.py` (bind them in the relevant node's `bind_tools()` call and add them to that agent's `ToolNode` in `graph.py`); put non-trivial tool logic in its own module (e.g. `report_generator.py`) rather than inline in the `@tool` function
- **Extend the `sessions` table**: add columns/queries in `core/db.py` - it's a plain `psycopg` pool, no ORM/migration framework, so schema changes are just SQL you run once (`CREATE TABLE IF NOT EXISTS`/`ALTER TABLE`) in that module. Don't touch LangGraph's own `checkpoint*` tables directly - go through `AsyncPostgresSaver`'s API instead (`graph.aget_state()`, `checkpointer.adelete_thread()`, etc.), since it owns their format.
