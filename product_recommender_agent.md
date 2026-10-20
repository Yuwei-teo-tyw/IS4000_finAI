# Product Recommender Agent: Implementation Plan

> **Audience:** Claude Code, working inside this repo (FastAPI backend in `backend/`, React/Vite frontend in `frontend/`).
> **Goal:** Build a real Product Recommender agent for the Product Specialist (PS) role. It runs a hard **suitability gate** (risk, liquidity, currency, exclusions, eligibility), then **ranks** the survivors by fit with the house view and the client's objectives. Fees are attached to each product **for display only**. It also generates an **evidence-based view on any individual asset class**: the CIO house view, the market data behind or against it, what the shelf offers in that class, and (optionally) what that means for one client. Expose it over HTTP, wire the frontend PS flow to it, and make it the single product shelf that the Portfolio Manager also reads, replacing `product_candidates.json`.

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
- **Asset-class views** (§6): for any of the 7 asset classes, the agent's own view in the CIO's format (`Buy` / `Hold` / `Sell`, confidence, rationale), backed by a detailed, cited analysis: market snapshot, segment views, drivers, scenarios, risks, implementation from the shelf, and an optional client lens. Shown beside the CIO view, never instead of it.
- An optional **LLM explanation** layer (plain-language reason per product and narrative per asset-class view, with citations). It must work with the LLM switched off.
- HTTP endpoints, backend tests, frontend wiring, and a regression fix to the Portfolio Manager's ranking.

### Out of scope (v1)
- Trade execution or order placement of any kind.
- Approving anything. The agent drafts; the PS approves at gate **G3** in the UI.
- Live product data feeds. The shelf stays illustrative; design the loader so a live source can replace it later.
- Parsing the house-view PDF with an LLM at request time.
- Overriding the CIO house view. The agent's asset-class view is analysis shown beside the CIO stance, never a replacement for it (§6.1).
- Price targets, return forecasts or timing calls.

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
├── asset_views/
│   ├── signals.py           # indicator mapping + deterministic agent stance and confidence (§6.3)
│   ├── segments.py          # segment mapping + Most preferred / Neutral / Least preferred per segment
│   ├── scenarios.py         # base/upside/downside with indicator triggers; watch items
│   ├── shelf_lens.py        # products mapped to segments; client eligibility counts (§6.4)
│   └── builder.py           # assembles AssetClassView, agreement with CIO, data-quality caveats
├── explain.py               # optional LLM reasons/narratives + deterministic fallback + guardrail
└── service.py               # ProductRecommenderService.recommend(), .shelf(), .house_view(), .asset_class_view()

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

The ranking uses the **CIO house view only**. The agent's own asset-class view from §6 does not feed the score in v1 (see §13, question 7).

---

## 6. Asset-class views (`asset_views/`)

The PS asks things like "What's the view on fixed income?", "Is now a good time for gold?" or "How do equities look for David Solomon?". The agent answers with its **own asset-class view, written in the same format as the CIO house view** (stance, confidence, rationale) but with a far more detailed analysis of that one asset class: segments, market levels, drivers, scenarios, risks and how to implement it from the shelf. Everything is built from data, never from LLM memory.

### 6.1 Agent view vs CIO view
| | CIO house view | Agent view |
|---|---|---|
| Format | `Buy` / `Hold` / `Sell` + confidence + rationale | **Same format**, plus the detailed analysis in §6.2 |
| Depth | One line per asset class | Full note on one asset class |
| Source | `data/house_view.json` (§3.4) | Deterministic scoring of Market Researcher data (§6.3), CIO text as context |
| Authority | Official. Drives ranking (§5) and the review pack. | Analysis for the PS. Never replaces the CIO view. |

Rules:
- The agent view is always shown **next to** the CIO view and labelled "Agent view (analysis, not the CIO house view)". It is never shown alone.
- The response states **agreement**: `aligned` (same stance), `differs` (one step apart, e.g. Buy vs Hold) or `opposed` (Buy vs Sell). When it differs or is opposed, the note must say which evidence drives the difference, and the UI flags it for the PS to raise with the CIO desk. The agent never changes the CIO view.
- The agent stance comes from the deterministic score in §6.3, not from the LLM. The LLM only writes the prose around it.

### 6.2 What an agent view contains
Modelled on a CIO asset-class note, top to bottom:

1. **Headline:** agent stance, confidence (`High` / `Medium` / `Low`), and a one-sentence thesis. Beside it, the CIO stance, confidence and citation, and the agreement badge.
2. **Thesis:** 3 to 5 bullets explaining the stance, each tied to data (indicator id, Market Researcher event id) or a house-view citation.
3. **Market snapshot:** a table of the key levels for the class (for example, for fixed income: 2Y/10Y/30Y yields, curve, real yield, breakevens, IG and HY spreads), each with value, 1-month and 3-month change, 10-year percentile, and whether it supports or weighs on the class.
4. **Segment views:** the class broken into segments, each with its own stance in the CIO's segment vocabulary (`Most preferred` / `Neutral` / `Least preferred`), plus a one-line reason and refs. Segments must be consistent with the headline: for example, a `Sell` headline cannot have every segment `Most preferred`. Default segments:

   | Asset class | Segments |
   |---|---|
   | Cash | Overnight / money market; 3 to 12 month deposits and bills |
   | Fixed income | Duration (short, intermediate, long); quality (government, investment grade, high yield); region (US, Asia, SGD); currency hedging |
   | Equities | Region (US, developed ex-US, emerging, Asia / Singapore); style (growth, value, quality, dividend); sectors (from the XL* sector ETFs) |
   | Gold | Physical / ETF exposure; role as a portfolio hedge |
   | Real estate | Listed REITs by region; income vs growth sub-sectors |
   | Hedge funds | Trend-following / macro; event-driven; multi-strategy |
   | Private markets | Private equity; private credit |

   A segment without supporting data gets `Neutral` with the reason "Not enough data to differentiate", never a guess.
5. **Drivers and catalysts:** what is moving the class now, plus recent or upcoming events from the Market Researcher's `events` and `event_explanations`.
6. **Scenarios:** base, upside and downside. Each is described qualitatively, with the **trigger** that would signal it (an indicator crossing a stated level, taken from the snapshot) and what it would mean for the stance. No price targets, return forecasts or dates.
7. **What would change the view:** 2 to 3 concrete watch items, for example "A move in the HY spread above its 10-year median would move high yield to `Least preferred`".
8. **Risks to the view:** including any evidence that contradicts the agent's own stance and any reason it differs from the CIO.
9. **Implementation from the shelf:** products in this class mapped to the segments above (which segment each product expresses), with risk rating, liquidity, currency and hedging. Fees are shown as a min/median/max summary marked "for information, not used to rank".
10. **Client lens (optional, when a `ClientProfile` is supplied):** how many products in the class pass the suitability gate, the main exclusion reasons, which segments the client can actually access, and the client's current and SAA weight in the class if known. Descriptive only; no instruction to the client.
11. **Sources and data quality:** every indicator with its observation date; the Market Researcher `run_id`, `as_of` and `quality.status`; stale or missing series; the house-view `as_of`; and the US-only coverage caveat (§6.3).

### 6.3 Scoring the agent stance (`signals.py`, `segments.py`)
Map each asset class, and each segment, to the series the Market Researcher already produces (`backend/app/agents/market_researcher/config.py`: `US_SERIES`, `WATCHLIST`). Keep the mapping in config, with a direction for each series ("higher supports the class" or "higher weighs on it") and a weight. Suggested starting map for the headline:

| Asset class | Indicators (ids from the Market Researcher) | Notes |
|---|---|---|
| Cash | `DFF`, `DGS3MO`, `DFEDTARU`, `CPIAUCSL` | Real cash yield = policy/bill rate minus CPI. Expected easing weighs on cash. |
| Fixed income | `DGS2`, `DGS10`, `DGS30`, `T10Y2Y`, `T10Y3M`, `DFII10`, `T10YIE`, `BAMLC0A0CM`, `BAMLH0A0HYM2`, `TLT`, `IEF`, `LQD`, `HYG` | Duration segments from the curve and yield levels; quality segments from the IG and HY spreads. |
| Equities | `SPY`, `QQQ`, `IWM`, `EFA`, `EEM`, sector ETFs, `VIXCLS`, `NFCI`, `UMCSENT`, `INDPRO` | Region segments from SPY/EFA/EEM; sectors from XL*; regime phase weighs heavily. |
| Gold | `GLD`, `DFII10`, `DX-Y.NYB`, `VIXCLS` | Falling real yields and a weaker USD support gold. |
| Real estate | `XLRE`, `DGS10`, `HOUST`, `PERMIT`, `BAA10Y` | Rate-sensitive; listed REIT proxy only. |
| Hedge funds | `VIXCLS`, `NFCI`, `STLFSI4`, `T10Y2Y` | **Low coverage.** Describes the environment (volatility, stress), not the class directly. Confidence capped at `Low`. |
| Private markets | `BAMLH0A0HYM2`, `NFCI`, `DGS10` | **Low coverage.** No direct data. Confidence capped at `Low`. |

Rules:
- The score is a weighted sum of per-indicator contributions (direction × a bounded transform of recent change and 10-year percentile), plus a regime-phase contribution. Configured thresholds turn it into `Buy` / `Hold` / `Sell`; segment scores turn into `Most preferred` / `Neutral` / `Least preferred` the same way. The result must be reproducible from the response's own `snapshot` list.
- **Confidence** comes from coverage and from whether the indicators agree. High coverage with indicators pointing the same way gives `High`; conflicting indicators or patchy data give `Low`.
- If fewer than half the mapped indicators are available or fresh, the stance is `Hold` / `Low` with an "insufficient evidence" caveat. Never invent a value.
- **US-only coverage.** The Market Researcher supports `region="US"` only, while the clients are SGD-based. Every view carries this caveat. SGD and Asia segments are `Neutral` with "No SGD/Asia data yet" until SG/Asia series are added. Record SORA, SGS yields, STI and USD/SGD in NOTES.md as the obvious next additions.
- If the Market Researcher is unavailable, the response still returns the CIO view and the shelf lens, with `agent_view = null` and a clear reason.

### 6.4 Shelf lens (`shelf_lens.py`)
Computed from the same shelf as the recommender. For the client lens, call the same `suitability.gate()`; do not reimplement eligibility. Fees appear only as a min/median/max summary with `display_only: true`.

### 6.5 Human approval
An asset-class view is a draft for the PS. In the UI it gets citation tags and an **Accept / Edit** control. Nothing is written to the review pack or sent to the IC until the PS accepts it. It never auto-approves.

---

## 7. Contracts

### 7.1 Request: `POST /agents/product-recommender/recommend`
```json
{
  "request_id": "PS-jfr-1729400000000",
  "client_id": "jfr",
  "client_profile": { "...": "ClientProfile, same schema as /portfolio/generate" },
  "options": { "top_n": 5, "max_per_asset_class": 2, "asset_classes": null, "named_products": [] }
}
```

### 7.2 Response
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

### 7.3 Asset-class view: `GET /agents/product-recommender/asset-class-views/{asset_class}` and `POST` with a client
`GET` returns the client-agnostic view; `asset_class` is a `taxonomy.AssetClass` value, URL-encoded or as a slug (`fixed-income`). `POST` takes `{ "client_id": "...", "client_profile": { ClientProfile } }` and adds the client lens. `GET /agents/product-recommender/asset-class-views` returns all 7 headlines only: agent stance, confidence, CIO stance, agreement. This is for an overview page; it is cheap and makes no LLM call.

```json
{
  "asset_class": "Fixed income",
  "generated_at": "2026-10-20T08:00:00Z",
  "is_illustrative": true,
  "cio_view": { "view": "Buy", "confidence": "High", "rationale": "...", "citation_id": "CIO-2026Q4-03", "as_of": "2026-08-31" },
  "agent_view": {
    "label": "Agent view (analysis, not the CIO house view)",
    "view": "Buy", "confidence": "Medium", "score": 0.42,
    "thesis": "One sentence ... [DGS10]",
    "thesis_points": [ { "text": "...", "refs": ["DGS10", "CIO-2026Q4-03"] } ],
    "regime": { "phase": "late_expansion", "confidence": "medium", "run_id": "..." },
    "coverage": { "mapped": 13, "available": 12, "fresh": 11 }
  },
  "agreement": { "status": "aligned|differs|opposed", "explanation": null },
  "snapshot": [ { "id": "DGS10", "name": "10-Year Treasury Yield", "value": 4.1, "unit": "%", "change": { "1m": -0.12, "3m": -0.35 }, "percentile_10y": 78, "effect": "supports|weighs", "weight": 0.2, "observation_date": "2026-10-17" } ],
  "segments": [
    { "group": "Duration", "segment": "Intermediate (5-10y)", "view": "Most preferred", "reason": "...", "refs": ["T10Y2Y", "DGS10"] },
    { "group": "Quality", "segment": "High yield", "view": "Least preferred", "reason": "...", "refs": ["BAMLH0A0HYM2"] },
    { "group": "Region", "segment": "SGD", "view": "Neutral", "reason": "No SGD/Asia data yet", "refs": [] }
  ],
  "drivers": [ { "text": "...", "refs": ["DGS10", "event:dgs10_multi_year_high"] } ],
  "scenarios": [ { "case": "base|upside|downside", "description": "...", "trigger": { "indicator": "BAMLH0A0HYM2", "condition": "above 10-year median" }, "stance_implication": "..." } ],
  "watch_items": [ { "text": "...", "refs": ["BAMLH0A0HYM2"] } ],
  "risks": [ { "text": "...", "refs": ["T10YIE"] } ],
  "implementation": {
    "products": [ { "product_id": "...", "product_name": "...", "segment": "Investment grade", "risk_rating": 2, "liquidity": "DAILY", "currency": "SGD", "currency_hedged": true } ],
    "fees": { "min_pct": 0.15, "median_pct": 0.45, "max_pct": 0.9, "display_only": true }
  },
  "client_lens": { "client_id": "dso", "eligible": 3, "excluded": [ { "code": "RISK_ABOVE_LIMIT", "count": 2 } ], "accessible_segments": ["Government", "Investment grade"], "current_weight_pct": 55, "saa_weight_pct": null },
  "narrative": { "source": "llm|deterministic" },
  "caveats": ["Market data is US-only; SGD rates and Singapore markets are not yet covered."],
  "data_quality": { "market_researcher_run_id": "...", "market_researcher_as_of": "2026-10-17", "market_researcher_status": "ok", "stale_indicators": ["HOUST"] }
}
```

### 7.4 Other endpoints
- `GET  /agents/product-recommender/health`: status, shelf source, house-view `as_of`, Market Researcher availability, LLM enabled.
- `GET  /agents/product-recommender/shelf`: the whole shelf for the Product Shelf page (no client needed; fees included, labelled display-only).
- `GET  /agents/product-recommender/house-view`: the house view for `getMarketViews` and the chat.

The asset-class view reads the **latest finished Market Researcher run**, in-process, using the same lookup that backs `GET /agents/market-researcher/latest` (see `market_researcher/runs.py`) or `portfolio_manager/upstream/market_analysis.py`, whichever the code already shares. It does not trigger a fresh FRED/market fetch per request. Return the run's `as_of` and `run_id` so the PS can see how old the evidence is.

Use the PM's `install_validation_handler` pattern so 422s never echo client data. Generate a JSON schema file for the response (as the Market Researcher does with `market_research_output.schema.json`).

---

## 8. LLM explanations (`explain.py`)
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
- **Asset-class views** use the same client and guardrail. The deterministic builder fixes every stance, number and ref; the LLM only writes the thesis sentence, thesis points, segment reasons, scenario descriptions and risks from that skeleton. Extra guardrail rules for views:
  - the agent stance, confidence and every segment stance in the text must match the deterministic ones;
  - the CIO stance must be quoted exactly as in `house_view.json`, and the agent view must never be presented as the CIO's or the house view;
  - if agreement is `differs` or `opposed`, the text must name the evidence that drives the difference;
  - no instruction to the client ("you should buy …");
  - no forecast of a level, return or date (scenario triggers come from the snapshot, not the LLM).
  Every bullet ends in a ref from the view's own indicator ids, event ids or citation ids.

---

## 9. Frontend integration

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
6. **Asset-class views in the PS AI Assistant chat** (chatbot agent, `GenevaChat.tsx`): detect an asset-class question ("view on fixed income", "outlook for gold", "how do equities look for this client") and call `arcApi.getAssetClassView(assetClass, clientId?)`. In the chat, render a compact card:
   - the headline: agent stance and confidence, labelled "Agent view (analysis, not the CIO house view)", next to the CIO stance with its citation, and the agreement badge (a difference is shown prominently, not hidden);
   - the thesis sentence and 3 to 5 thesis points with citation tags;
   - an **Open full analysis** button.

   The full analysis is too much for a chat bubble (Lux: one page, one job, at most 3 blocks above the fold). Open it as its own route, `/ps/asset-views/:assetClass` (PS agent; add the route in `router.tsx` through its owner), with tabs: **Overview** (headline, thesis, segment views), **Market** (snapshot table, drivers, scenarios, watch items), **Risks**, **Products** (implementation from the shelf, client lens, fee summary), and **Sources** (indicators with dates, run id, caveats).

   Then **Accept / Edit** on the full page. Accepting stores the text against the client for reuse (for example, in pack section 5 or the PS's product reasons); it never sends anything on its own. Add 2 seeded prompts for PS, such as "What's the view on fixed income?" and "How does gold look for this client?".
7. **Optional overview** (PS agent): a "Asset class views" tab next to House View Records showing all 7 classes in a simple list (CIO stance, agent stance, agreement), each opening the full analysis. Keep to Lux density rules (one page, one job; ≤ 6 cards).
8. `arcApi.getAssetClassView` and `arcApi.getAssetClassViews` follow the same error pattern as `recommendProducts`; no mock fallback.
9. `npm run build` passes.

---

## 10. Testing

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
- **Asset-class views** (use a fixed Market Researcher output fixture from `tests/fixtures/market_researcher/`):
  - `cio_view` in the output is exactly the entry in `house_view.json` for every class (the agent never alters it);
  - the agent stance, confidence and segment stances can be recomputed from the output's own `snapshot` and the configured weights and thresholds;
  - moving an indicator in its "supports" direction never lowers the score (monotonicity);
  - agreement covers all 9 CIO × agent stance combinations (`aligned` / `differs` / `opposed`), and `differs` or `opposed` always comes with an explanation that names indicators;
  - segment stances are consistent with the headline (for example, no `Sell` headline with every segment `Most preferred`);
  - with under half the mapped indicators available → `Hold` / `Low` + "insufficient evidence";
  - with the Market Researcher unavailable → CIO view and shelf still returned, `agent_view = null`, reason given;
  - Hedge funds and Private markets never exceed `Low` confidence; SGD/Asia segments are `Neutral` while only US data exists;
  - every scenario trigger refers to an indicator in the snapshot;
  - every shelf product in the class is mapped to exactly one segment;
  - the client lens counts match `suitability.gate()` exactly;
  - the guardrail rejects text whose stances differ from the deterministic ones, misquotes the CIO, presents the agent view as the house view, instructs the client, forecasts, or uses unknown refs;
  - every view carries the US-only caveat while only US data exists;
  - endpoint tests for the list, single `GET`, and `POST` with a client, plus an unknown asset class → 404.

Frontend: `npm run build` passes. Manually drive the flow: PS inbox → AI Assistant → "Read client IPS, and research market, match products…" → shortlist from backend → finalise → send to IC (G3). Then ask "What's the view on fixed income?" with a client active and check the card, the agreement badge and Accept / Edit.

---

## 11. Milestones

1. **Inspect and decide:** write the "What I found" section of NOTES.md, and record decisions for §3.1 to §3.5.
2. **Shelf and house view:** merged `shelf.json` and `house_view.json`, loaders, validation, `GET /shelf`, `GET /house-view`, tests.
3. **Gate:** move the screening into `suitability.py`, add checks 2, 3 and 5, make the PM import it, gate tests green, PM tests green.
4. **Ranking:** `ranking.py`, fee-invariance tests, remove the fee term from the PM ranking.
5. **Recommend endpoint:** service, `POST /recommend`, deterministic reasons, endpoint tests.
6. **LLM explanations:** explainer and guardrail tests.
7. **Asset-class views:** indicator and segment mapping in config, `signals.py`, `segments.py`, `scenarios.py`, `shelf_lens.py`, `builder.py`, deterministic text, endpoints, tests (§10). Start with Fixed income and Equities (best data coverage), then the other five. LLM prose and its guardrail after that.
8. **PM switch-over:** `product_specialist.py` reads the shelf; delete `product_candidates.json`.
9. **Frontend:** arcApi, GenevaChat (recommendation and asset-class view cards), PS pages, mock clean-up, `npm run build`.
10. **README:** add a "Product Recommender Agent" section next to the Portfolio Manager one (env vars, endpoints, the indicator mapping, how to run tests).

Commit after each milestone with a message that names the milestone.

---

## 12. Definition of done
- `pytest` passes in `backend/`, including the fee-invariance tests for both agents.
- `npm run build` passes in `frontend/`.
- Exactly one product shelf file and one house-view file exist in the repo, and both the PS UI and the Portfolio Manager read them.
- No ranking happens in the frontend.
- Every excluded product shows a reason in the UI.
- Fees appear in the UI, labelled "for information, not used to rank".
- The PS can ask for a view on any of the 7 asset classes in the chat. They get the agent's own Buy / Hold / Sell view beside the CIO's with an agreement badge, and can open a full analysis: segments, market snapshot, drivers, scenarios, risks, products, client lens and sources. The full analysis has Accept / Edit.
- `NOTES.md` lists decisions, deviations and open questions.

---

## 13. Open questions for the user (do not block; use the default and note it)
1. **Real fund names on the shelf?** Default: illustrative names only, because the data is invented.
2. **Liquidity-need rule (check 5):** which withdrawals within how many months should exclude non-daily products? Default: any planned withdrawal or cash-reserve shortfall within 12 months excludes `MONTHLY` and less liquid products.
3. **Drawdown tolerance (check 3):** default 0 percentage points (strict).
4. **Shortlist size and diversity:** default `top_n = 5`, `max_per_asset_class = 2`.
5. **House view refresh:** who updates `house_view.json` each month, and should a later version parse the PDF automatically (with human review)?
6. **Structured products:** the frontend type allows `"Structured products"` but the backend taxonomy does not. Default: leave them out of v1.
7. **Should the agent's own view affect ranking?** Default: no. Ranking uses the CIO house view only, and the agent view is shown beside it. A later version could add a small, capped component to §5, or use segment preferences to break ties within an asset class.
8. **Asia/SGD market data for views:** the Market Researcher is US-only. Default: ship with the caveat. The next step is adding SORA, SGS yields, STI and USD/SGD to the Market Researcher (its own plan, not this one).
9. **Where an accepted asset-class view goes:** default is stored against the client and offered as text for pack section 5 and the PS's product reasons. Should it also reach the IC's Market Health page?
10. **Agent-vs-CIO differences:** should an `opposed` result notify anyone (for example, a flag on the IC's Market Health page), or only show in the PS view? Default: PS view only.
11. **Score thresholds:** the cut-offs that turn the score into `Buy` / `Hold` / `Sell`. Default: symmetric, set so that roughly a third of historical Market Researcher runs land in each, recorded in NOTES.md. Check them against the Market Researcher backtest before trusting them.
