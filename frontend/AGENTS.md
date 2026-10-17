# AGENTS.md – frontend architecture reference
Read this instead of crawling the repo. Rules live in CLAUDE.md.

## Product
UBS Geneva: co-pilot for wealth advisers. Agents read/draft/explain, Python does maths, humans approve at gates G1–G4. Three roles: **RM** (Relationship Manager), **IC** (Investment Counsellor), **PS** (Product Specialist). Sample client: Mr Tan, S$5.0m. Source doc: Claude Doc `MJzNPvDXHdTyUXFz89EDus`. Design system: Lux, IS4000 UBS design Artifact K7hLmtKJ8MtAxWGjbrgV1U (read via Artifact tool; tokens mirrored).

## Backend architecture (not built here; frontend plugs in later)
Level 2 flow: RM input → LangGraph agentic backend → frontend advice workspace → human review/decision → record & audit. Level 3 graph: Intent Clarifier → Orchestrator → specialist capabilities (Portfolio Analysis, Goal/Scenario Planning, Market Evidence, Risk/Constraint) → Recommendation Agent → Independent Challenger → Response Assembly → frontend. Product Specialist capability = Product Recommender Agent (missing from original diagram): suitability gate first, then rank, fee shown never used to rank. Non-agent: Chat Router, Analytics Engine, Grounding Check, Pack Builder. Shared infra: client DB, tools (NumPy/Pandas/PyPortfolioOpt), Tavily, Gemini/Groq, Pydantic + LangSmith, audit store. No trade execution.

## Stack
React 19, TypeScript, Vite 7, Tailwind 4 (`@theme` tokens), react-router-dom 7, lucide-react. No chart lib: inline SVG. Legacy chat app kept at `/legacy-chat`.

## Directory map (`frontend/src`)
- `routes/router.tsx` – all routes (`/` redirects to `/rm/clients`; `/rm|ic|ps/...`; shared `clients/:clientId` and `.../documents`)
- `layouts/AppShell.tsx` – sidebar shell; `useRole()`
- `layouts/Sidebar.tsx` – role switcher + nav
- `layouts/navConfig.ts` – per-role nav (RM = Client Book + AI Assistant), `ROLE_PEOPLE`, active client
- `pages/rm|ic|ps/` – role workflows; `pages/client/` – shared Client 360, tabs for IC/PS: Overview (summary, 3L, allocation donut, SAA/TAA, case timeline) and Client's documents (IPS, Sharpe, diversification, holdings heatmap, holdings, notes, history)
- `components/geneva/GenevaChat.tsx` – THE chatbot (role-aware). `GenevaLauncher.tsx` – bottom-right Geneva button opening it as a resizable side panel (`compact`). Full pages: `pages/rm/RmAssistant`, `pages/ps/MarketResearch` (AI Assistant). `components/settings/SettingsDialog` – sidebar-bottom system prompt
- `components/ui/index.tsx` – PageHeader, Section, Card, Badge, Button, Stat, Stepper, NextAction, GateChip, CitationTag, Table, useAsync, sgd()
- `components/client/` – reusable client widgets (heatmap, allocation bars, holdings table)
- `services/arcApi.ts` – ONLY data seam (mock now, LangGraph later); `mock/data.ts`; `types/arc.ts`
- `styles/tokens.css` – Lux tokens (surface-100..300, ink, brand, hairline, Source Sans 3)

RM Client 360 tabs: Overview, IPS, Meeting Notes, Review Pack. `pages/rm/IpsDraft` and `PackReview` take `{embedded, clientId}` props and render inside those tabs (no Stepper/flow chrome when embedded); IPS draft is opened from the IPS tab.

## Gates
G1 RM approves IPS · G3 PS approves product list (PS sidebar: Product Requests, Client Book, AI Assistant; Market Research tabs: chat, House View Records, Product Shelf) · G2 IC approves TAA + pack §2–5 · G4 RM approves final pack/PDF. Upstream edits reset downstream gates.

## Chatbot style (all teammates reuse `GenevaChat`; do not build a second chat UI)
- Type: Source Sans 3 light (300) for EVERY element in the chat (root class `geneva-light` forces weight 300, matching page titles). Answers `font-light`; summary 22px/36px, headings 26px `tracking-tight`, lists 16-17px. Labels = 12px uppercase `tracking-[0.12em]` muted.
- Thinking card (subtle, no spinners/bouncing dots): Geneva logo, title "Preparing your analysis" and every text in the card (steps, agent labels, "engaged") with `animate-geneva-flow` (red light sweeping through the words), a plain hairline, then numbered steps (01, 02…) fading in with `animate-geneva-in`, finished steps muted with a thin tick, agents shown as outlined small-caps labels + "engaged". Order: "Intent parser is reading your request…" → "<agents> fired" → work steps → "Thinking…" → "Consolidating…". Steps ~1.7s each (agents step ~2.2s). Keyframes live in `index.css`.
- Final answer never names agents. Show only "Geneva". Answer fades in with `animate-geneva-in`.
- Scroll: never `scrollIntoView` (it scrolls the page). Scroll only the chat box, only if the reader is within 160px of the bottom. Thinking card keeps `min-h-[320px]` to avoid layout jump.
- Layout: empty state = logo, light heading, rounded composer, seeded prompts as list rows; multiple chats (list left, or dropdown when `compact`). Frontend only: answers come from `arcApi` mocks; the intent parser is fake keyword matching.
