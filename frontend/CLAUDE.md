# Frontend rules (UBS Geneva)
Read AGENTS.md first (stack, dirs, routes, per-role views, agent ownership).

## STOP RULE
If a required resource is unavailable (design system, Claude Doc, tool, file, access), STOP, alert the user, wait. Never substitute or guess.

## Agents (`.claude/agents/`)
`ubs-frontend-` + `chatbot-agent` (Geneva chat), `ps-agent`, `pm-agent`, `rm-agent`, `generic-agent` (everything else). One agent per file in parallel; cross-file needs go to the owner. Finish with `reviewer-agent` (read-only: imports, duplicates, conflicts, ownership, Lux).

## Design (Lux, IS4000 UBS)
- Never compact: one page = one job, ≤3 blocks per screen, generous spacing.
- `Stepper` + `NextAction` on workflow pages, `GateChip` G1-G4.
- Tokens in `styles/tokens.css`; Source Sans 3 light; red `brand` only for the one primary action. Reuse `components/ui`.
- Nav: Sidebar, ≤6 links per role, edit only `navConfig.ts`.
- Chatbot: reuse `GenevaChat` (AGENTS.md "Chatbot style").
- AI output: citation tags `[CIO-…]`, human Accept/Edit.
- Frontend only: data via `services/arcApi.ts`, never import `mock/` in pages.

Done = `npm run build` passes.

## Client phase rule (all roles)
- A client moves **Onboarding Phase -> Monitoring Phase only when onboarding progress is full (5/5) AND an IPS is active.** Never flip status any other way. Phase is derived, never stored: `arcApi.effective()` reads `workflowStore.isActivated()`, which re-checks IPS sent + returned by PM + active IPS.
- Only `activateIps(clientId, version)` (workflowStore) can activate; it refuses unless the RM sent the IPS and the PM returned it. `returnIpsToRm` refuses unless the IPS was sent. Do not call `setActiveIps` + a status flip separately for onboarding clients.
- Onboarding progress steps (RM Client Book bar): draft -> sent to PM (3) -> returned by PM (4) -> approved at G1 and IPS active (5). "-" while not started. Seeded Monitoring clients (ser, dso, teo) count as complete.
- Review pack progress is for Monitoring clients only; "-" when 0.

## Request paths (keep these intact)
- **IPS path (Mei Jia's Portfolio Agent code):** RM IpsDraft "Send IPS draft to PM" (`sendIpsToPm`) -> PM inbox row, type **IPS SAA request** in the dedicated "Request type" column (built live from `useAllIpsSent`, any onboarding client) -> Open `/pm/requests/:id/3l` (ThreeLBuilder, client profile + 3L) -> `/saa` (SaaBuilder "Pick a portfolio": runs the Portfolio Agent, Portfolios / Compare portfolios views, number of portfolios comes from the backend) -> "Continue to Edit weights" -> `/saa/weights` (SaaWeights: weights beside the efficient frontier, checked by the backend) -> "Continue: send back to RM" (`returnIpsToRm`, then back to `/pm/inbox`, row shows Finished). SAA draft lives in `workflowStore` PmProgress (`paRequestId`, `saaTemplate`, `saaWeights`, `saaOriginal`; legacy `saa` array still written) -> RM IpsApproval "Approve G1" (enabled only after the return) -> `activateIps` -> client becomes Monitoring.
- **Review pack path (Wei Lun's code):** RM PackReview "Send to Product Specialist" (`sendReviewRequest`) -> PS inbox -> PS chat names products -> FinaliseProducts "send to PM" (`sendFinalised`) -> PM inbox row **Quarterly review** (built live from `useAllFinalised`) -> `/pm/cases/:id/products` -> market health -> TAA -> holdings -> pack -> "Send to Relationship Manager" (`sendPmToRm`) -> RM approves G4.
- PM inbox rows are built live-first from workflow state (`PmInbox.tsx`); seeds only add priority. Do not dedupe against the unfiltered seed list.
