# Frontend rules (UBS Geneva)
Read AGENTS.md first (stack, dirs, routes). Use agent `ubs-frontend-design-agent`.

## STOP RULE (highest priority)
If any required resource is unavailable (design system, Claude Doc, tool, file, access), STOP immediately, alert the user, and wait. Never substitute, guess, or keep building. Check availability before spending tokens.

## Design
- **Never compact.** One page = one job, ≤3 blocks per screen, generous spacing (p-7+, gap-8+). Split with routes/tabs/steppers.
- Show the journey: `Stepper` + `NextAction` on workflow pages, `GateChip` for G1–G4.
- Design = Lux (IS4000 UBS): `styles/tokens.css`, Source Sans 3 light headings, hairlines, red `brand` only for the one primary action/current step. Reuse `components/ui`.
- Navigation = left sidebar (Sidebar.tsx): ≤6 links per role, edit only in navConfig.ts. Assistant = AI Assistant page + bottom-right Geneva launcher. App opens on /rm/clients. Few tabs: merge, don't add.
- Chatbot: reuse `components/geneva/GenevaChat`; all-light type (`geneva-light`, weight 300 everywhere), red-light sweep (`animate-geneva-flow`) on every thinking text, no page-scrolling (AGENTS.md "Chatbot style").
- AI output = citation tags `[CIO-…]`, human Accept/Edit; agents never approve.
- Frontend only: data via `services/arcApi.ts`, never import `mock/` in pages.

## Views per role
- **All:** Client 360 (`/:role/clients/:id`): Overview (3L, allocation pie, SAA/TAA, case timeline) + Client's documents (IPS, Sharpe, diversification, holdings heatmap, holdings, notes). 5 clients: ser, dso, teo, jfr, sha; RM Isabel, IC Wei Lun, PS David; dark mode toggle. Read-only unless own section.
- **RM** `/rm/clients`: sidebar = Client Book + AI Assistant. RM Client 360 tabs: Overview, IPS, Meeting Notes, Review Pack. IPS draft = embedded editing opened from the IPS tab; send to IC, G1; Review Pack tab: G4, PDF.
- **IC** `/ic/inbox`: 3L builder, SAA builder (templates A–F), portfolio insights, TAA old vs new, G2, pack §2–5.
- **PS** `/ps/inbox`: sidebar = Requests, Client Book, AI Assistant (`/ps/assistant`); market research chat, house views, product shelf, finalise + send to IC (G3).

## Done = `npm run build` passes.
