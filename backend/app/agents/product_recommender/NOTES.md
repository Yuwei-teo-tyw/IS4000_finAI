# Product Recommender: notes

Plan: `product_recommender_agent.md` (repo root). This file records what was found, the decisions taken, and where the build deviates from the plan.

## What I found (milestone 1)

- **Closest agent to copy:** `portfolio_manager/`. Deterministic engine, settings from env, optional Groq explainer with deterministic fallback, endpoint on `app.state`, and a validation handler that never echoes client data.
- **The suitability screen already existed** in `portfolio_manager/engine/product_screening.py`: restrictions, preferred classes, sector exclusions (5% tolerance), ESG, eligibility, lock-in vs shortest goal horizon, and the no-FX currency rule. It treats unknown data as a fail.
- **The PM's within-class ranking subtracted `management_fee`** and penalised a missing fee. That broke the "fees never rank" rule.
- **There were two product lists:**
  - 20 `MOCK-*` products in `portfolio_manager/upstream/mock_data/product_candidates.json`, using the full `ProductCandidate` schema;
  - 17 `PRD-*` products in `frontend/src/mock/data.ts`, using a thin `Product` type. Several have real fund and manager names with invented data.
- **No per-asset-class house view existed in the backend.**
  - The Market Researcher gives a US cycle regime and indicators only.
  - The only per-class views were frontend mock data (`marketViews`) and `house_views/UBS House View for August 2026.pdf`.
  - The PDF rates classes **Attractive / Neutral / Unattractive**, not Buy / Hold / Sell. Its asset-class preferences chart (page 14) is not machine-readable.
- **Client input:** `ClientProfile` (PM schema) and `assess_profile()` already derive the effective risk level (the lower of willingness and capacity), the shortest goal horizon and preferred classes. The frontend builds the same profile in `arcApi.buildPortfolioInputs`.
- **The environment works on Python 3.14.7.** `pip install -r requirements-dev.txt` succeeded, and the existing suite passed before any change.

## Decisions

| Plan ref | Decision |
|---|---|
| §3.1 shelf | One shelf, `data/shelf.json`, in the `ProductCandidate` schema plus `why_buy`, `suitability_note` and `rating`. Built from the 20 backend products, plus three to fill gaps: `MOCK-CASH-003` (USD money market), `MOCK-GOLD-002` (SGD-hedged gold) and `MOCK-REIT-003` (global REIT, hedged). Every asset class now has at least 2 products. Names stay illustrative; no real fund names, because the data is invented. The frontend `PRD-*` list is not ported, and the frontend milestone switches it to this shelf. |
| §3.2 PM fees | Removed the fee terms (`- management_fee` and the missing-fee penalty) from `rank_products`. All PM tests still pass. `tests/test_product_recommender.py::test_pm_rank_products_ignores_fees` guards it. |
| §3.3 client input | `ClientProfile` and `assess_profile()` are reused unchanged. |
| §3.4 house view | `data/house_view.json`, curated by hand from the August 2026 PDF, with page citations (`HV-2026-08-p10` etc.). Each entry keeps the CIO's own word (`cio_term`) and a `basis`: `rated` (stated in the report), `interpreted` (read from prose: hedge funds and private markets, from the "Diversify with alternatives" paragraph) or `not_covered` (cash: `Hold` / `Low`). Mapping: Attractive → Buy, Neutral → Hold, Unattractive → Sell. |
| §3.5 PM reads the shelf | In-process. `product_specialist.get_product_candidates()` returns `shelf.load_raw()`, and validation goes through the shared `shelf.validate()`. `product_candidates.json` is deleted. `PRODUCT_CANDIDATES_SOURCE` stays `"MOCK"`. |

## Deviations from the plan

1. **The per-product risk, drawdown and liquidity-need checks are recommender-only, not shared with the PM.** The core checks moved into `suitability.py` and the PM re-exports them (`product_screening.py`), so there is one implementation. Applying a per-product risk cap in the PM would remove every equity product (rated 4) for a Balanced (level 3) client. The PM builds diversified portfolios and enforces risk at portfolio level. Guarded by `test_pm_screen_does_not_apply_the_per_product_risk_cap`.
2. **Drawdown (check 3) is a note by default, not an exclusion.** A single product's historical drawdown is not comparable with a client's portfolio drawdown limit: every equity fund (around −30%) would fail a 12% limit. Set `RECOMMENDER_DRAWDOWN_HARD_LIMIT=true` to make it exclude.
3. **Liquidity need (check 5):**
   - Only **dated** withdrawals inside `RECOMMENDER_LIQUIDITY_NEED_MONTHS` (default 12) trigger it. Undated amounts carry no timing, and the PM's liquidity plan already ring-fences them.
   - Within the window: `QUARTERLY` and `LOCKED` dealing, or a lock-in that runs past the need, are excluded. `WEEKLY` and `MONTHLY` dealing pass with a note.
4. **Codes:** `RISK_UNKNOWN` was added for a client whose effective risk level cannot be established (for example, `risk_capacity` missing). Every product is then excluded with that reason, following "unknown is not a pass".
5. **Reason format:** bullets end `[TAG].`, matching the frontend's existing reason format. Citations are the house-view page id and the product id (its factsheet).
6. **Validation handler:** an app has one `RequestValidationError` handler, so the PM's `install_validation_handler` now takes `extra_prefixes`. `app.py` installs it once for both agents.

## Findings for later milestones

- **Resolved in milestone 9: David Solomon (`dso`) risk level.** The frontend sent `risk_appetite: "Conservative"` with `risk_tolerance_score: 2`, and "Conservative" maps to 1, so both agents assessed him at 1. The shared profile builder (`arcApi.buildClientProfile`) now sends the backend label for the IPS risk limit (2 → "Moderately conservative"), so both agents assess the limit the screen shows.
- The PM's `samples/sample_response.json` was not regenerated after the shelf grew to 23 products and the fee term went. It is documentation, not a test fixture.
- The house view's `interpreted` and `not_covered` entries (cash, hedge funds, private markets) should be confirmed against the page 14 chart by a person.
- **Not ours, but it blocks testing:** `frontend/src/layouts/navConfig.ts` has `VALID_IDS = ["jdi", "jfr", "dso"]`. There is no `jdi` client, and `ser`, `teo` and `sha` are missing, so the active-client switcher can only select Jane Fraser or David Solomon.
- `MarketRow.confidencePct` is a mock-era idea. Rows from the recommender fill it with the product rating × 20, and `FinaliseProducts` and `FinalisedTable` still label it "confidence". It should become "product rating" or be removed.

## Asset-class views (milestone 7)

- **Data:** the latest Market Researcher run through the PM's `fetch_market_analysis()` (one seam for both agents). That is still the illustrative mock, which now carries the ~30 series the views map to. The added values are invented to fit the mock's story and remain labelled mock. A live run needs `FRED_API_KEY`.
- **Files:** `config.py` (indicator and segment mapping, cut-offs), `scoring.py` (headline, segments, what-if rescoring; the plan's `signals.py`, `segments.py` and `scenarios.py` in one module), `shelf_lens.py`, `builder.py`, `schemas.py`.
- **Score:** a weighted mean of per-series readings in [-1, 1] plus a regime tilt. It is reproducible from the response's own snapshot; a test checks this. Buy at ≥ +0.20 and Sell at ≤ -0.20. **These cut-offs are not calibrated yet** (open question 11 in the plan); calibrate them against stored Market Researcher runs once live runs exist.
- **Segments are relative:** Most / Least preferred means at least 0.15 above / below the class's own score. This matches how CIO segment preferences read, and makes "every segment Most preferred under a Sell" impossible.
- **Scenarios and watch items use 3-month moves only.** Levels sit in a 10-year range and change slowly, so they make poor triggers. Hedge funds and private markets have only level signals, so their watch item says so.
- **No LLM prose yet.** The plan's LLM explanations and guardrail are still open; all text is deterministic (`narrative_source: "deterministic"`).
- **Frontend:** a chat card for "What's the view on X?" (one class named, no product wording). Full analysis at `/ps/asset-views/:assetClass` with Overview, Market, Risks, Products and Sources tabs and Accept / Edit (stored per client in `workflowStore`, sent nowhere). An overview at `/ps/asset-views` and a sixth PS nav link.

## Status

| Milestone | State |
|---|---|
| 1 Inspect and decide | Done (this file) |
| 2 Shelf and house view | Done: `shelf.py`, `house_view.py`, `GET /shelf`, `GET /house-view` |
| 3 Gate | Done: `suitability.py`, shared core checks, recommender-only product checks |
| 4 Ranking | Done: `ranking.py`, PM fee term removed, fee-invariance tests for both agents |
| 5 Recommend endpoint | Done: deterministic reasons, `POST /recommend` |
| 6 LLM explanations | Not started |
| 7 Asset-class views | Done (backend, frontend); LLM prose not started |
| 8 PM switch-over | Done early (with milestone 2) |
| 9 Frontend | Done: shelf, house view, recommendations, finalise-by-chat through the gate, asset-class views |
| 10 README | Not started |
