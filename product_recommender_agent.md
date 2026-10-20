# Product Recommender Agent: Implementation Plan

> **Audience:** Claude Code, working inside this repo (FastAPI backend in `backend/`, React/Vite frontend in `frontend/`).
> **Goal:** Build a real Product Recommender agent for the Product Specialist (PS) role. It runs a hard **suitability gate** (risk, liquidity, currency, exclusions, eligibility), then **ranks** the survivors by fit with the house view and the client's objectives. Fees are attached to each product **for display only**. Expose it over HTTP, wire the frontend PS flow to it, and make it the single product shelf that the Portfolio Manager also reads, replacing `product_candidates.json`.

---

## 0. Before writing any code: inspect the repo

Read these files first. **Repo conventions override this plan.** Where this plan and the code disagree, follow the code and note the deviation in `NOTES.md`.

| What | Where | Why it matters |
|---|---|---|
| Closest existing agent (copy its structure) | `backend/app/agents/portfolio_manager/` (`service.py`, `config.py`, `schemas/`, `engine/`, `explain/`) | Package layout, settings, deterministic engine + optional LLM explainer pattern |
| Existing suitability screen | `backend/app/agents/portfolio_manager/engine/product_screening.py` | Already does restrictions, eligibility, sector exclusions, ESG, lock-in vs horizon, currency. **Reuse/move it; do not write a second copy.** |
| Product contract | `backend/app/agents/portfolio_manager/schemas/upstream.py` (`ProductCandidate`, `ProductCandidates`, `UpstreamResult`) | The shelf schema the Portfolio Manager already consumes |
| Client contract | `backend/app/agents/portfolio_manager/schemas/client.py` (`ClientProfile`) | Request input; reuse it, do not invent a new client schema |
| Mock product shelf (backend) | `backend/app/agents/portfolio_manager/upstream/mock_data/product_candidates.json` (20 `MOCK-*` products) | One of the two lists to merge |
| Integration point to replace | `backend/app/agents/portfolio_manager/upstream/product_specialist.py` (`get_product_candidates`) | Where the PM will start reading from the recommender |
| Taxonomy | `backend/app/agents/portfolio_manager/taxonomy.py` (`AssetClass`, `Liquidity`, `parse_period_to_months`) | Shared enums: 7 asset classes, liquidity terms |
| LLM client + guardrails | `backend/app/agents/portfolio_manager/explain/` (`llm_client.py`, `guardrails.py`, `deterministic.py`) | Groq via `langchain_groq`, lazy import, deterministic fallback |
| Endpoint style | `backend/app/endpoints/portfolio_manager.py`, router registration in `backend/app/app.py` | Prefix `/agents/<name>`, `get_service` on `app.state`, validation handler that never echoes client data |
| Market regime | `backend/app/agents/market_researcher/schemas.py` (`MarketResearchOutput.regime`), `backend/app/agents/portfolio_manager/upstream/market_analysis.py` | Cycle phase. It has **no per-asset-class Buy/Hold/Sell view** (see §3.4). |
| House view source document | `house_views/UBS House View for August 2026.pdf` | Source for the per-asset-class view |
| Test conventions | `backend/tests/portfolio_helpers.py`, `backend/tests/conftest.py` (`FakeLLM`), `backend/tests/test_portfolio_*.py` | Fixed clock, LLM disabled or faked, no network |
| Frontend data seam | `frontend/src/services/arcApi.ts` (`getProducts`, `getMarketViews`, `askMarketResearch`, `buildPortfolioInputs`, `PortfolioManagerError`) | The only place pages get data. `buildPortfolioInputs` already maps frontend client data to `ClientProfile`. |
| Frontend recommendation logic to replace | `frontend/src/components/geneva/GenevaChat.tsx` (`buildRecommendation`, `score`) | Ranking currently happens in the browser; it must move to the backend |
| Frontend product types and mock | `frontend/src/types/arc.ts` (`Product`, `MarketView`, `MarketRow`), `frontend/src/mock/data.ts` (`products`, `marketViews`, `productCatalogue`) | The second product list (17 `PRD-*` products) and the shape PS pages render |
| Frontend rules | `frontend/CLAUDE.md`, `frontend/AGENTS.md` | File ownership per agent, Lux design rules, "Done = `npm run build` passes" |

Then write a short "What I found" section at the top of `backend/app/agents/product_recommender/NOTES.md` before building.

---

## 1. Scope

### In scope
- One canonical **product shelf** (data file + loader + validation), served to both the PS UI and the Portfolio Manager.
- One canonical **house view** (per-asset-class Buy / Hold / Sell, with confidence, rationale and citation id), served to the PS UI, the chat and the ranker.
- A deterministic **suitability gate** that excludes products with a recorded reason for every exclusion.
- A deterministic **ranking** of eligible products with a per-component score breakdown.
- An optional **LLM explanation** layer (plain-language reason per product, with citations). It must work with the LLM switched off.
- HTTP endpoints, backend tests, frontend wiring, and a regression fix to the Portfolio Manager's ranking.

### Out of scope (v1)
- Trade execution or order placement of any kind.
- Approving anything. The agent drafts; the PS approves at gate **G3** in the UI.
- Live product data feeds. The shelf stays illustrative; design the loader so a live source can replace it later.
- Parsing the house-view PDF with an LLM at request time.

### Design principles (non-negotiable)
1. **Suitability first.** Only products that pass every hard check are ranked. No score can rescue an excluded product.
2. **Fees never rank.** `management_fee`, `transaction_fee` and any cost field must not appear anywhere in the scoring function, tie-breaks or the LLM prompt's ranking instructions. Fees are returned in a separate `costs` block with `display_only: true`.
3. **Numbers come from code, not the LLM.** The LLM only rewords and explains. A guardrail rejects any LLM text that introduces a number, product or citation that was not in its input, or that justifies a product by its fee.
4. **Nothing is dropped silently.** Every excluded product appears in the response with a machine code and a human-readable reason.
5. **Unknown is not a pass.** If a hard check cannot be verified because data is missing, the product is excluded with a "cannot verify" reason. This matches the existing `product_screening.py` behaviour.
6. **Deterministic.** Same input, same output order. Ties break by `product_id`.
7. **Illustrative data stays labelled.** `is_illustrative` and the source label flow through to the UI. A mock payload can never promote itself to "verified" (see `UpstreamResult`).

---

## 2. Architecture

```
backend/app/agents/product_recommender/
├── NOTES.md                 # what you found, decisions, deviations
├── __init__.py
├── config.py                # Settings from env (copy portfolio_manager/config.py style)
├── schemas.py               # RecommendRequest, RecommendResponse, HouseView, ScoreBreakdown, Exclusion
├── data/
│   ├── shelf.json           # THE product shelf (merged, see §3.1)
│   └── house_view.json      # THE house view (see §3.4)
├── shelf.py                 # load + validate shelf -> UpstreamResult (per-product validation, bad rows reported not fatal)
├── house_view.py            # load + validate house view; optional regime cross-check
├── suitability.py           # the hard gate (moved from portfolio_manager/engine/product_screening.py)
├── ranking.py               # scoring components, no fee terms
├── explain.py               # optional LLM reasons + deterministic fallback + guardrail
└── service.py               # ProductRecommenderService.recommend(), .shelf(), .house_view()

backend/app/endpoints/product_recommender.py   # router, registered in app/app.py
```

**Shared gate.** Move the screening logic into `product_recommender/suitability.py` and make `portfolio_manager/engine/product_screening.py` import it, or turn it into a thin re-export. There must be one implementation of each hard check.

### Request flow
```
RecommendRequest (ClientProfile + options)
  -> shelf.load()              products + data issues
  -> house_view.load()         per-asset-class views (+ regime cross-check flag)
  -> suitability.gate()        eligible[] + excluded[(product_id, code, reason)]
  -> ranking.rank()            eligible sorted, each with ScoreBreakdown
  -> explain.reasons()         LLM or deterministic text per shortlisted product, guardrail-checked
  -> RecommendResponse
```

---

## 3. Decisions to make first (defaults given; record the choice in NOTES.md)

### 3.1 Merge the two product lists into one shelf
There are two shelves today, and they do not match:
- Backend: 20 `MOCK-*` products in `product_candidates.json`, full `ProductCandidate` schema (currency, hedging, liquidity, lock-in, eligibility, sector exposure, fees, volatility, drawdown).
- Frontend: 17 `PRD-*` products in `frontend/src/mock/data.ts`, a thin `Product` type (`whyBuy`, `stars`, `suitability`, `riskRating`, `feePct`, `tags`). Several use real fund and manager names (iShares, Fidelity, BlackRock, Franklin Templeton, Man AHL) with invented data.

**Default:** the canonical shelf uses the backend `ProductCandidate` schema, extended with the presentation fields the PS UI needs: `why_buy`, `suitability_note`, `rating` (replaces `stars`), and `citations` (replaces `tags`, e.g. `CIO-2026Q4-03`, `MKT-0142`). Start from the 20 backend products. Add frontend products only where they fill a gap in coverage, and give them illustrative names, not real fund names, because the data is invented. Every one of the 7 asset classes in `taxonomy.AssetClass` must have at least two products at different risk ratings. Then update the frontend mock and `productCatalogue` aliases to the new names so the chat's "finalise X and Y" matching still works.

### 3.2 The Portfolio Manager's ranking also uses fees
`portfolio_manager/engine/product_screening.py::rank_products` does `s -= prod.management_fee or 0` and docstrings "Favours ... lower fees". **Remove the fee term** to honour the same rule. This changes PM output: update its tests and `samples/sample_response.json`, and say so in the PR description.

### 3.3 Client input
Reuse `ClientProfile` as-is. The frontend already builds one in `arcApi.buildPortfolioInputs`; extract the profile-building part into a shared helper so the recommender and the PM send identical profiles. Do not add new required fields. A missing field must produce a "cannot verify" exclusion or a `missing_information` entry, not a 422.

Map the risk scale explicitly and test it: the frontend `riskCap` (1-5) → `ClientProfile.risk_tolerance_score` (1-5), compared against `ProductCandidate.risk_rating` (1-5). Reuse `profile_assessment.py` (`ProfileAssessment.effective_level`, `shortest_horizon_years`, `preferred_classes`) rather than recomputing these.

### 3.4 Where the house view comes from
The Market Researcher outputs a cycle phase and indicators, but **no per-asset-class Buy/Hold/Sell view**. The per-asset-class view only exists as frontend mock (`marketViews`) and in the PDF under `house_views/`.

**Default for v1:** a curated `data/house_view.json`, hand-extracted from the latest PDF, with this shape per asset class: `asset_class`, `view` (`Buy|Hold|Sell`), `confidence` (`High|Medium|Low`), `rationale` (one sentence), `citation_id`, plus top-level `as_of`, `source_document`, `is_illustrative`. Cover all 7 asset classes; mark any the PDF does not cover as `Hold` / `Low` with rationale "Not covered in the house view".

Use the Market Researcher regime only as a **cross-check**. If the regime and the view clearly disagree (for example, a recession phase with an Equities `Buy`), add a flag to the response; do not silently change the view. Serve the same file to the frontend so `getMarketViews` and the ranker can never disagree.

### 3.5 How the Portfolio Manager reads the shelf
In-process, not over HTTP. `product_specialist.get_product_candidates()` calls the recommender's `shelf.load()`. Keep `PRODUCT_CANDIDATES_SOURCE = "MOCK"` while the shelf is illustrative; the label reflects the data's provenance, not which code path served it. Delete `product_candidates.json` once nothing reads it, and update `tests/test_portfolio_upstream.py` accordingly.

---

## 4. The suitability gate (`suitability.py`)

Every check returns one of: **pass**, **exclude(code, reason)**, or **pass with note(text)**. Order matters only for which reason is reported first; record the first failing check.

| # | Check | Exclude when | Note (pass) when | Code |
|---|---|---|---|---|
| 1 | Data validity | Asset class unrecognised; `risk_rating` missing | | `DATA_INVALID` |
| 2 | Risk | `risk_rating` > client's effective risk level | `risk_rating` == limit ("at the limit") | `RISK_ABOVE_LIMIT` |
| 3 | Drawdown | Product `maximum_drawdown` is worse than the client's `maximum_acceptable_drawdown` by more than a configured tolerance | Within tolerance but close | `DRAWDOWN` |
| 4 | Liquidity / lock-in | Lock-in exceeds the shortest goal horizon; lock-in > 12 months and horizon unknown; lock-in text unparseable | Any lock-in; non-daily dealing | `LIQUIDITY` |
| 5 | Liquidity need | Non-daily liquidity (`MONTHLY`, `QUARTERLY`, `LOCKED`, `AT_MATURITY`) when the client's near-term withdrawals or cash reserve need it (define the rule from `planned_withdrawals`, `minimum_cash_reserve` and horizon) | | `LIQUIDITY_NEED` |
| 6 | Currency | Unhedged foreign currency and `maximum_currency_exposure == 0` | Unhedged foreign currency otherwise | `CURRENCY` |
| 7 | Restrictions | Product id, name or type in `restricted_products` | | `RESTRICTED` |
| 8 | Sector exclusions | Excluded sector > 5% of the product; sector exposure unknown while exclusions exist | Excluded sector between 0 and 5% | `SECTOR_EXCLUDED` |
| 9 | ESG | ESG `Required` and product not confirmed compliant | ESG `Preferred` and not confirmed | `ESG` |
| 10 | Eligibility | Accredited-only and client not confirmed accredited; residency mismatch or unknown; minimum age not confirmed | | `ELIGIBILITY` |
| 11 | Preferred classes | Asset class outside `preferred_asset_classes` (when set) | | `NOT_PREFERRED` |
| 12 | Data freshness | | `as_of_date` older than `stale_after_days`; `data_completeness` not `COMPLETE` | (note only) |

Checks 1, 4, 6, 7, 8, 9, 10, 11 and 12 already exist in `product_screening.py`; move them, do not rewrite them. Checks 2, 3 and 5 are new.

---

## 5. Ranking (`ranking.py`)

Score only eligible products. Each component is a named, bounded number so the UI can show *why* a product ranked where it did.

| Component | Range | Source |
|---|---|---|
| `objective_fit` | 0 to 10 | Client objective derived from goals and risk appetite: income, growth, preservation or legacy. Matched against product type, sub-asset class, distribution yield, duration. |
| `house_view` | -6 to +8 | `Buy` +8, `Hold` +3, `Sell` -6 for the product's asset class, scaled by view confidence |
| `risk_budget_use` | 0 to 4 | How well `risk_rating` uses (without exceeding) the client's risk level; larger weight for higher-risk clients |
| `horizon_match` | 0 to 3 | `recommended_horizon` vs the client's goal horizons |
| `currency_fit` | 0 to 2 | Base-currency or hedged |
| `data_quality` | -3 to +2 | Completeness; missing volatility or drawdown |
| `rating` | 0 to 2 | Product rating as a minor tie-breaker only |

**Forbidden inputs:** `management_fee`, `transaction_fee`, any cost or commission field, issuer identity. Add a module-level comment saying so.

Tie-break: total score descending, then `product_id` ascending.

Options on the request: `top_n` (default 5), `asset_classes` filter, `max_per_asset_class` (default 2, so the shortlist is not five bond funds), and `named_products` (product ids or names the PS asked about; always return their gate result even if they would not make the shortlist).

---

## 6. Contracts

### 6.1 Request: `POST /agents/product-recommender/recommend`
```json
{
  "request_id": "PS-jfr-1729400000000",
  "client_id": "jfr",
  "client_profile": { "...": "ClientProfile, same schema as /portfolio/generate" },
  "options": { "top_n": 5, "max_per_asset_class": 2, "asset_classes": null, "named_products": [] }
}
```

### 6.2 Response
```json
{
  "request_id": "...",
  "client_id": "jfr",
  "generated_at": "2026-10-20T08:00:00Z",
  "is_illustrative": true,
  "sources": { "shelf": "MOCK", "house_view": "CURATED", "regime": "MOCK|LIVE|UNAVAILABLE" },
  "client_summary": { "risk_level": 3, "risk_category": "Balanced", "objective": "income", "shortest_horizon_years": 4, "base_currency": "SGD" },
  "house_view": { "as_of": "2026-08-31", "views": [ { "asset_class": "Fixed income", "view": "Buy", "confidence": "High", "rationale": "...", "citation_id": "CIO-2026Q4-03" } ], "regime_flags": [] },
  "shortlist": [
    {
      "rank": 1,
      "product": { "product_id": "...", "product_name": "...", "asset_class": "...", "risk_rating": 2, "liquidity": "DAILY", "currency": "SGD", "currency_hedged": null, "why_buy": "...", "rating": 4 },
      "score": { "total": 21.5, "components": { "objective_fit": 10, "house_view": 8, "risk_budget_use": 1.3, "horizon_match": 2, "currency_fit": 2, "data_quality": 2, "rating": 0.8 } },
      "notes": ["Daily dealing."],
      "reason": { "text": "• ... [CIO-2026Q4-03]", "source": "llm|deterministic", "citations": ["CIO-2026Q4-03", "IPS-v2"] },
      "costs": { "management_fee_pct": 0.55, "transaction_fee_pct": 0.0, "display_only": true }
    }
  ],
  "eligible_not_shortlisted": [ { "product_id": "...", "total": 12.0 } ],
  "excluded": [ { "product_id": "...", "product_name": "...", "code": "RISK_ABOVE_LIMIT", "reason": "Risk 4 of 5 is above the client's limit of 3." } ],
  "named_products": [ { "product_id": "...", "status": "shortlisted|eligible|excluded|not_found", "reason": "..." } ],
  "missing_information": ["residency", "accredited_investor"],
  "limitations": ["Products are fictional ..."]
}
```

### 6.3 Other endpoints
- `GET  /agents/product-recommender/health`: status, shelf source, house-view `as_of`, LLM enabled.
- `GET  /agents/product-recommender/shelf`: the whole shelf for the Product Shelf page (no client needed; fees included, labelled display-only).
- `GET  /agents/product-recommender/house-view`: the house view for `getMarketViews` and the chat.

Use the PM's `install_validation_handler` pattern so 422s never echo client data. Generate a JSON schema file for the response (as the Market Researcher does with `market_research_output.schema.json`).

---

## 7. LLM explanations (`explain.py`)
- Same pattern as `portfolio_manager/explain/`: lazy Groq client, `*_LLM_ENABLED` env switch, timeout, deterministic fallback on any failure.
- Input to the LLM: the product's fields, its score components, the house-view rationale and citation, the client summary. Nothing else.
- Output: 3 to 5 plain-language bullets per shortlisted product, each ending in a citation tag from the input list.
- Guardrail (reuse `explain/guardrails.py` where possible) rejects text that:
  - contains a number not present in the input;
  - names a product not in the input;
  - uses a citation id not in the input;
  - mentions fees or cost as a reason to choose the product;
  - uses "guaranteed" or similar.
  On rejection, fall back to the deterministic reason for that product and record `source: "deterministic"`.
- The deterministic reason is built from the score components, for example "Fixed income has a Buy view in the house view [CIO-2026Q4-03]".

---

## 8. Frontend integration

Respect `frontend/CLAUDE.md` file ownership. If you are running as a single agent, make the edits, but list in the PR which files belong to which frontend agent so the owners can review.

1. **`services/arcApi.ts`** (generic agent):
   - `getProducts(clientId)` calls `GET /shelf` and maps to the existing `Product` type (`feePct` ← `management_fee`, `stars` ← `rating`, `tags` ← `citations`, `whyBuy`, `suitability` ← `suitability_note`). Keep the function signature unchanged.
   - Add `recommendProducts(clientId)` that builds the `ClientProfile` with the shared helper (§3.3) and calls `POST /recommend`.
   - `getMarketViews(clientId)` calls `GET /house-view`.
   - Errors follow the `PortfolioManagerError` pattern (`UNREACHABLE`, `TIMEOUT`, `REJECTED`, `SERVER`, `INVALID_RESPONSE`). Show a clear "start the backend" message. **Do not silently fall back to mock data**, because the PS would be approving a list the agent never produced.
2. **`components/geneva/GenevaChat.tsx`** (chatbot agent): `buildRecommendation` stops ranking in the browser. It calls `recommendProducts` and renders the shortlist, the excluded list (with reasons) and each product's fee labelled "for information, not used to rank". Keep the thinking-card steps, but drive them from the real stages.
3. **`pages/ps/ProductShelfPage.tsx`** (PS agent): reads from the new shelf. Optionally show, per product, the gate result for the active client.
4. **`pages/ps/FinaliseProducts.tsx`** (PS agent): seed each product's baseline reason from the recommender's `reason.text` instead of the generic `draftReason`.
5. **`mock/data.ts`**: update product names and `productCatalogue` aliases to match the new shelf; remove the old `products` list once nothing imports it.
6. `npm run build` passes.

---

## 9. Testing

Backend (pytest, offline, fixed clock, LLM disabled or `FakeLLM`; follow `tests/portfolio_helpers.py`):
- **Gate:** one test per row of §4, covering exclude, note and pass, including the "unknown data → exclude" cases.
- **Fee invariance (property test):** shuffle or randomise every product's fees and assert the shortlist order is identical. Run it for both the recommender and the PM's `rank_products`.
- **No silent drops:** `len(shortlist) + len(eligible_not_shortlisted) + len(excluded) == len(shelf)`.
- **Determinism:** same request twice gives identical output.
- **House view sensitivity:** flipping an asset class from `Buy` to `Sell` moves its products down.
- **Max per asset class** and **named products** (shortlisted, eligible, excluded, not found).
- **Guardrail:** an LLM reply that mentions a fee, invents a number or uses an unknown citation is replaced by the deterministic reason.
- **Endpoints:** health, shelf, house-view, recommend (200, 422 without echoing input, partial profile → `missing_information`).
- **PM regression:** the PM reads the new shelf, its fee term is gone, and existing PM tests pass after expected-output updates.
- **Client fixtures:** the five frontend clients (`ser`, `dso`, `jfr`, `teo`, `sha`) as `ClientProfile` fixtures, each with expected exclusions. For example, `dso` (Conservative, limit 2) must exclude every product rated 3 or above.

Frontend: `npm run build` passes. Manually drive the flow: PS inbox → AI Assistant → "Read client IPS, and research market, match products…" → shortlist from backend → finalise → send to IC (G3).

---

## 10. Milestones

1. **Inspect and decide:** write the "What I found" section of NOTES.md, and record decisions for §3.1 to §3.5.
2. **Shelf and house view:** merged `shelf.json` and `house_view.json`, loaders, validation, `GET /shelf`, `GET /house-view`, tests.
3. **Gate:** move the screening into `suitability.py`, add checks 2, 3 and 5, make the PM import it, gate tests green, PM tests green.
4. **Ranking:** `ranking.py`, fee-invariance tests, remove the fee term from the PM ranking.
5. **Recommend endpoint:** service, `POST /recommend`, deterministic reasons, endpoint tests.
6. **LLM explanations:** explainer and guardrail tests.
7. **PM switch-over:** `product_specialist.py` reads the shelf; delete `product_candidates.json`.
8. **Frontend:** arcApi, GenevaChat, PS pages, mock clean-up, `npm run build`.
9. **README:** add a "Product Recommender Agent" section next to the Portfolio Manager one (env vars, endpoints, how to run tests).

Commit after each milestone with a message that names the milestone.

---

## 11. Definition of done
- `pytest` passes in `backend/`, including the fee-invariance tests for both agents.
- `npm run build` passes in `frontend/`.
- Exactly one product shelf file and one house-view file exist in the repo, and both the PS UI and the Portfolio Manager read them.
- No ranking happens in the frontend.
- Every excluded product shows a reason in the UI.
- Fees appear in the UI, labelled "for information, not used to rank".
- `NOTES.md` lists decisions, deviations and open questions.

---

## 12. Open questions for the user (do not block; use the default and note it)
1. **Real fund names on the shelf?** Default: illustrative names only, because the data is invented.
2. **Liquidity-need rule (check 5):** which withdrawals within how many months should exclude non-daily products? Default: any planned withdrawal or cash-reserve shortfall within 12 months excludes `MONTHLY` and less liquid products.
3. **Drawdown tolerance (check 3):** default 0 percentage points (strict).
4. **Shortlist size and diversity:** default `top_n = 5`, `max_per_asset_class = 2`.
5. **House view refresh:** who updates `house_view.json` each month, and should a later version parse the PDF automatically (with human review)?
6. **Structured products:** the frontend type allows `"Structured products"` but the backend taxonomy does not. Default: leave them out of v1.
