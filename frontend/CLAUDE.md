# Frontend rules (UBS Geneva)
Read AGENTS.md first (stack, dirs, routes, per-role views, agent ownership).

## STOP RULE
If a required resource is unavailable (design system, Claude Doc, tool, file, access), STOP, alert the user, wait. Never substitute or guess.

## Agents (`.claude/agents/`)
`ubs-frontend-` + `chatbot-agent` (Geneva chat), `ps-agent`, `ic-agent`, `rm-agent`, `generic-agent` (everything else). One agent per file in parallel; cross-file needs go to the owner. Finish with `reviewer-agent` (read-only: imports, duplicates, conflicts, ownership, Lux).

## Design (Lux, IS4000 UBS)
- Never compact: one page = one job, ≤3 blocks per screen, generous spacing.
- `Stepper` + `NextAction` on workflow pages, `GateChip` G1-G4.
- Tokens in `styles/tokens.css`; Source Sans 3 light; red `brand` only for the one primary action. Reuse `components/ui`.
- Nav: Sidebar, ≤6 links per role, edit only `navConfig.ts`.
- Chatbot: reuse `GenevaChat` (AGENTS.md "Chatbot style").
- AI output: citation tags `[CIO-…]`, human Accept/Edit.
- Frontend only: data via `services/arcApi.ts`, never import `mock/` in pages.

Done = `npm run build` passes.
