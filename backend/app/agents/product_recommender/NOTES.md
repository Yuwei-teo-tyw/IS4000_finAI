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

- **David Solomon (`dso`) is risk level 1 in the backend, not 2.** The frontend sends `risk_appetite: "Conservative"` with `risk_tolerance_score: 2`, and `taxonomy` maps "Conservative" to 1. `assess_profile` takes the lower. The PM sees the same level, so the agents agree; the frontend's displayed limit of 2 does not. Fix in the frontend milestone by sending a label that matches `riskCap`, or decide that the label wins.
- The PM's `samples/sample_response.json` was not regenerated after the shelf grew from 20 to 23 products and the fee term went. It is documentation, not a test fixture.
- **Asset-class views (§6):** the Market Researcher is US-only. SORA, SGS yields, STI and USD/SGD are the obvious additions for SGD clients.
- The house view's `interpreted` and `not_covered` entries (cash, hedge funds, private markets) should be confirmed against the page 14 chart by a person.

## Status

| Milestone | State |
|---|---|
| 1 Inspect and decide | Done (this file) |
| 2 Shelf and house view | Done: `shelf.py`, `house_view.py`, `GET /shelf`, `GET /house-view` |
| 3 Gate | Done: `suitability.py`, shared core checks, recommender-only product checks |
| 4 Ranking | Done: `ranking.py`, PM fee term removed, fee-invariance tests for both agents |
| 5 Recommend endpoint | Done: deterministic reasons, `POST /recommend` |
| 6 LLM explanations | Not started |
| 7 Asset-class views | Not started |
| 8 PM switch-over | Done early (with milestone 2) |
| 9 Frontend | Not started |
| 10 README | Not started |
