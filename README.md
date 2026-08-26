# Multi-Agent Triage System

A sophisticated multi-agent conversational AI system built with FastAPI backend and React frontend. The system intelligently routes user queries to specialized agents based on intent analysis, providing expert responses for technical and financial questions, and a general-purpose assistant for everything else - all through a central triage agent.

## 🏗️ Architecture

The system is built on a real **LangGraph `StateGraph`** with conditional edges and a checkpointer - not a hand-rolled loop:

- **🧠 Triage Agent**: routes requests using structured output (`with_structured_output`), not string-matching
- **💻 Technical Specialist** / **💰 Finance Expert** / **🤖 General Assistant**: specialists with a bound `tavily_search` tool - the model itself decides when to search based on its system prompt, executed via LangGraph's `ToolNode`. Each also runs its own structured scope check per new message, so a topic drift mid-conversation hands back to triage instead of getting stuck answering out-of-lane questions.
  - **Finance** additionally has two tools: `propose_financial_action` (any money-moving action, gated by human approval - see below) and `generate_client_report` (a currently-placeholder tool for producing a client-ready document; see Functional Placeholders below).
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

> **Observability**: Langfuse tracing is wired in (`app/core/tracing.py`) - every turn is traced as one tree per session (triage/technical/finance/general/eval/context-manager LLM calls all nest under it automatically via LangGraph's callback propagation, no per-node code needed). Configure via the standard env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`); with them unset, tracing silently no-ops rather than breaking anything.

> **Prompt versioning**: every prompt in this project lives in `app/prompts/prompts.yaml`, loaded through `app/prompts/prompt_builder.py` (`get_prompt("agent.key")`) instead of being hardcoded in each node file. Each key keeps every version it's ever had plus a `latest` pointer; pin a specific key to an older/newer version without a code change via `PROMPT_VERSION_OVERRIDES='{"finance.system": "v2"}'` - useful for rollback or an A/B test tied to `get_prompt_version(key)` in your eval/tracing metadata.

Graph shape (built with LangGraph's `StateGraph` - see `agents/graph.py`):

```mermaid
flowchart TD
    START([START]) --> pii_guard[🔒 pii_guard]
    pii_guard --> context_manager[🧹 context_manager]

    context_manager -->|new session| triage[🧠 triage]
    context_manager -->|resuming| technical[💻 technical]
    context_manager -->|resuming| finance[💰 finance]
    context_manager -->|resuming| general[🤖 general]

    triage -->|technical| technical
    triage -->|finance| finance
    triage -->|general| general
    triage -->|meta / canned reply| END1([END])

    technical -->|tool call| technical_tools[technical_tools]
    technical -->|now out of scope| triage
    technical -->|final answer| eval[✅ eval]
    technical_tools --> technical

    finance -->|tool call| finance_tools[finance_tools]
    finance -->|money-moving action| human_approval[🛑 human_approval]
    finance -->|now out of scope| triage
    finance -->|final answer| eval
    finance_tools --> finance
    human_approval -->|resume with decision| finance

    general -->|tool call| general_tools[general_tools]
    general -->|now out of scope| triage
    general -->|final answer| eval
    general_tools --> general

    eval -->|regenerate| technical
    eval -->|regenerate| finance
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

- **`checkpoints`** - one row **per graph step**, not per session. A single turn walks through several nodes (`pii_guard → context_manager → triage → finance → eval → ...`), and each transition writes a new row linked to the previous one via `parent_checkpoint_id` - a version chain, not one row per conversation. A single exchange can easily produce 5-10+ rows here.
- **`checkpoint_blobs`** - the actual `AgentState` field values (`messages`, `finance_response`, etc. - one row per `(channel, version)`), msgpack-serialized. This is where message history actually lives byte-for-byte.
- **`checkpoint_writes`** - staged writes for a step before they're committed as the next checkpoint; also backs the `human_approval` node's `interrupt()`/resume mechanism.
- **`checkpoint_migrations`** - the checkpointer's own internal schema-version bookkeeping.

`MultiAgentGraph.get_history()` (`agents/graph.py`) never queries these tables directly - it calls LangGraph's own `graph.aget_state(config)`, which reconstructs the latest `AgentState` from the blobs for you.

Deleting a session (`DELETE /sessions/{id}`) has to clean up both halves separately: `db.delete_session()` for the `sessions` row, plus `checkpointer.adelete_thread()` for everything across the four LangGraph tables.

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
│   │   │   └── nodes/
│   │   │       ├── triage.py            # Main routing agent
│   │   │       ├── technical.py         # Technical specialist
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
│   │       └── __init__.py              # WebSocket route + /sessions REST routes
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

Each specialist (Technical, Finance, General) has `tavily_search` bound as a real tool via `bind_tools()` - **the model decides for itself**, per its system prompt, whether a question depends on information that could have changed recently (current prices, versions, news, recent releases) versus stable, well-known facts it can just answer directly. There's no keyword list or regex gating this - it's a genuine LLM tool-calling decision, and the frontend's search indicator reflects whether a search actually happened that turn, not a client-side guess.

### Example Interactions

#### 🔧 Technical Questions

```
User: "How do I fix a Python memory leak?"
Technical Specialist: Provides debugging steps and memory profiling techniques (answered directly, no search needed)
```

```
User: "What are the latest Python 3.14 features?"
Technical Specialist: 🌐 Searches for current release notes/docs, then answers with up-to-date info
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
