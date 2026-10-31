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
- **IPS path (Mei Jia's Portfolio Agent code):** RM IpsDraft "Send IPS draft to PM" (`sendIpsToPm`) -> PM inbox row, type **IPS SAA request** in the dedicated "Request type" column (built live from `useAllIpsSent`, any onboarding client) -> Open `/pm/requests/:id/ips` (`PmIpsReview`): ONE editable IPS page, the same `IpsDocument` the RM sees, loaded from the version the RM sent (`getPmIps` snapshotVersion + `getIpsVersionRecord`). Section 5 (3L and SAA) is highlighted ("PM review: 3L and SAA") and editable; every other section is read-only (`pmReview` prop, `inert`). Liquidity has no SAA (one red italic note in the Allocation section); Longevity and Legacy get strategy A-F pickers there, with no per-bucket portfolio cards. A LOCAL check in the page (not the Portfolio Agent combined review): both strategies chosen and the 3L split adds to 100%, plus the PM signature, must pass before "Send back to RM" (`savePmIps`, `returnPmIpsToRm` backend, `returnIpsToRm`, then back to `/pm/inbox`). Old deep links `/3l`, `/saa`, `/saa/:bucket`, `/saa/review` redirect to the new page. The Geneva sidebar chat (role pm on this route) answers about the open IPS (3L split, strategies, reasons) with seeded 3L/SAA prompts, reading the draft extras the page writes. Legacy `ThreeLBuilder`/`SaaBuilder`/`SaaWeights`/`SaaReview` files remain but are unrouted. -> RM IpsApproval "Approve G1" (enabled only after the return) -> `activateIps` -> client becomes Monitoring.
- **Review pack path:** RM PackReview "Send to Portfolio Manager" (`sendPackToPm`, `services/packHandover.ts`) -> PM inbox row **Quarterly review** -> one page `/pm/cases/:id/review` (`PmReview`: the RM-generated pack, same IPS-style document, editable, PM comments, G2) -> "Send to Relationship Manager" (`sendPmToRm`) -> RM approves G4. Old `/pm/cases/:id/*` paths redirect there.
- PM inbox rows are built live-first from workflow state (`PmInbox.tsx`); seeds only add priority. Do not dedupe against the unfiltered seed list.
