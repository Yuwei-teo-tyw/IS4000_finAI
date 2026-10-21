# Risk & Compliance checks: notes

Plan: hybrid design agreed in review. Each specialist keeps its own checks. This agent is an independent, deterministic second line with two entry points:
- **readiness:** step 4, before advice;
- **review-pack check:** the Review Gate, before the RM's G4 approval.

This file records what was found, the decisions taken, and where the build deviates from the plan.

## What I found

- **The checks the specialists need already exist, and are already shared:**
  - `portfolio_manager/engine/profile_assessment.py` covers appetite vs capacity (the lower governs), missing and contradictory fields, and severity.
  - `portfolio_manager/engine/liquidity.py` covers the reserve, near-term withdrawals and eligible value.
  - `product_recommender/suitability.py` covers the core and product-level gate. `portfolio_manager/engine/product_screening.py` re-exports it, so the PM and the Recommender already apply one implementation.
  - `portfolio_manager/engine/construction.py` enforces the growth ceiling, per-product cap, FX cap and drawdown while building options.
- **No orchestrator, analysis packet, Challenger or Review Gate in this repo.** The Level 3 runtime is the external v5 project behind `advisory-browser/`. `agents/graph.py` is the triage chatbot.
- **The review pack exists only in the frontend:**
  - free-text `PackSection`s and pack drafts in sessionStorage (`services/packDraftStore.ts`);
  - IC allocation rows (`AllocationRow`, plus `IcProgress.taa`);
  - the PS `FinalisedList` (product *names*, no ids or weights);
  - gate states, derived in the pages from workflow state.

  The mock `gates` list is static.
- **No machine-readable house risk policy or IPS limits.** `house_views/` is the CIO market view.
- **The eval agent (`agents/nodes/eval_agent.py`) is not a base for this.** It judges chat replies with an LLM and approves when its own call fails. This agent checks structured data deterministically and fails closed.

## Decisions

| Topic | Decision |
|---|---|
| Runtime | A standalone capability in `backend/`, exposed over HTTP at `/agents/risk-compliance`. Not a node in the chatbot graph. |
| Shared rules | Wrapped in place, never copied:<br>• `assess_profile`, `build_liquidity_plan`, `suitability.gate` and `near_term_need_months` are imported.<br>• The growth ceiling is read from `ConstructionContext.growth_ceiling`, so the PM and this agent cannot drift apart. |
| Policy | `data/policy.json`, versioned, with placeholder values (`_notice` says so).<br>• Each rule has an **effect**: BLOCK, NEEDS_INFO, CONDITION or NOTE. The finding's severity follows from it.<br>• A policy missing any rule the code can raise is refused. |
| Status | BLOCKED > NEEDS_INFO > PASS_WITH_CONDITIONS > PASS.<br>• PM `BLOCKING` conflicts → BLOCKED; `BLOCKING` missing info → NEEDS_INFO; `MATERIAL` → PASS_WITH_CONDITIONS.<br>• `rm_signoff_allowed` only for PASS or PASS_WITH_CONDITIONS. |
| Fail closed | • Policy load error or version mismatch → BLOCKED (`SYS.POLICY`).<br>• Any exception → BLOCKED (`SYS.INTERNAL`); only the error *type* is logged.<br>• Unknown or stale dates, an unavailable shelf or an unknown product → NEEDS_INFO. |
| Fingerprint | sha256 of the canonical request JSON plus the policy file digest. `computed_at` is excluded. |
| Frontend | • `PackReview.tsx` posts the structured pack when every section is complete.<br>• "Approve G4" stays disabled unless `rm_signoff_allowed`, including while the check runs or if it can't run.<br>• Contract types are in `types/riskCompliance.ts`. |

## Deviations from the plan

- **Staleness thresholds** are in `policy.json`, not env vars (`RISK_PROFILE_STALE_AFTER_DAYS` was dropped). Every threshold the agent adds is now in the versioned policy.
- **`DataAsOf` has no `products` date.** Product as-of dates come from the shelf itself, so the caller can't vouch for them.
- **An unknown product** (`PROD.UNVERIFIED`) is NEEDS_INFO, not MATERIAL. Unverifiable data must not pass.
- **`TEXT.NUMBERS` is a NOTE.** Pack text is written by people and cites many figures the agent doesn't compute (Sharpe, YTD returns), so treating these as conditions would be noise. Raise the effect in the policy if wanted.
- **Contract types** are in `types/riskCompliance.ts`, next to `portfolio.ts` and `productRecommender.ts`, rather than `arc.ts`.

## Integration point (v5 orchestrator)

- **After the RM confirms intake (step 2):** call `POST /agents/risk-compliance/readiness`, or `check_readiness()` in process.
  - Attach the report to the Validated Analysis Packet.
  - `next_step` is ADVISORY / CLARIFY / BLOCK. CLARIFY or BLOCK goes to the existing clarify/block path *before* the Advisory Agent.
  - `constraints` are what Candidate Validation (step 6) should check the candidate against.
- **At the Review Gate:** call `POST /agents/risk-compliance/review-pack/check` on the assembled pack. Its `findings` are evidence the Challenger can cite.

## Open items

1. `FinalisedItem` / `MarketRow` carries no `product_id`, so products are matched to the shelf by exact name. Rows that didn't come from the Recommender, e.g. the mock `PRD-*` names, come back unverified. Adding `productId` to `MarketRow` would fix that.
2. The pack has no per-product weights, so the single-product and FX caps are skipped with a NOTE (`PROD.WEIGHTS_MISSING`).
3. Rules reused from the PM keep their module constants (e.g. `MIN_RESERVE_MONTHS_FOR_HIGH_CAPACITY`, the 24-month withdrawal window). They're not in `policy.json`.
4. Every threshold and disclaimer phrase is a placeholder and needs sign-off by the policy owner.
5. In the mock app, G4 approval is local React state, so the lock is enforced in the UI only.
