# Client Portfolio seed data (IS-97)

Files: `instruments.csv`, `holdings.csv`.

## Instruments (prices)
- Source: Yahoo Finance public chart API (`query1.finance.yahoo.com/v8/finance/chart/<TICKER>`, daily close, `price_source` column).
- Fetched: 2026-10-27. Price is the official daily close of **2026-10-26** (`price_as_at`). Quote currency: USD.
- Real and fetched for 31 of 32 instruments (9 famous bank and tech stocks added: GS, MS, BAC, C, UBS, NVDA, GOOGL, AMZN, META). Tickers, names and sector/industry labels are real (GICS-style for stocks; category-style for funds, as an issuer or Morningstar-like label).
- **No price: VMFXX** (Vanguard Federal Money Market Fund). Yahoo returns no close series for it. `price` and `price_as_at` are left empty on purpose (the "Price not available" case). No value was guessed.
- Prices per asset class (with price): Equities 17, Fixed Income 6, Cash 3 (plus VMFXX unpriced), Alternatives 5. Each class has at least 2 priced instruments.

## Holdings
- **Team-entered, illustrative.** Per the story, holdings are "entered or loaded by the team". They are not real client positions. All clients are fictional (see `clients.json`).
- Clients: **only jfr, jft (Jane Fraser and her test twin) and ser (Sergio Ermotti)**. Every other client id (dso, teo, sha, mlm, ...) has no holdings, so the API returns `status: no_holdings` / AUM "No holdings yet". Holdings: jfr 9, jft 10, ser 10 (max 10 each). Holding sets differ per client (jfr and jft are the same persona but have different mixes; ser differs from both). Tickers overlap between clients. Instruments no client holds are kept (>= 2 priced per asset class still holds).
- The loader reconciles: rows in the DB that are not in `holdings.csv` are deleted.
- Jane's equities (jft: JPM, MSFT, GS, AAPL; jfr: NVDA, UBS, GOOGL) are famous bank and tech stocks. Her bond/cash/alternative sleeves use ETFs.
- **TAA vs SAA demo.** Quantities are set so the actual mix of each L portfolio differs from its saved SAA (IPS strategies A/B/C) by 10 points or more for some classes (warning icons in the UI) and by less for others. jft actual vs SAA: liquidity Bonds 82 vs 95 (-13), Cash 18 vs 5 (+13); longevity Bonds 60 vs 72 (-12), Equities 28 vs 13 (+15), Alternatives 12 vs 7 (+5); legacy Bonds 48 vs 51, Equities 38 vs 29 (+9), Alternatives 14 vs 11 (all within 10). jfr is built the same way with different holdings (longevity Equities +17, Bonds -12; legacy Equities +11). SAA/strategy data is not touched; only holdings. ser has no saved 3L IPS, so no comparison.
- Mix follows risk category. Conservative (jft, jfr) is heavy in cash, short bonds and investment-grade bonds. Balanced (ser) is about 40-50% equity-like.
- `portfolio` (3L bucket): liquidity = cash / T-bill / short bond ETFs; longevity = core bonds and equities; legacy = longer-horizon equity, alternatives, gold.
- `cost_per_unit`: the real Yahoo daily close on `date_bought` (all dates are real trading days in 2025, before `price_as_at`). The exception is VMFXX, entered at 1.00 (money-market stable NAV, team-entered, no price series).
- Quantities are team-chosen (rounded to 10 units) so total market value at the 2026-10-26 prices is about the target below.

## Currency
All instruments are USD-quoted and `cost_per_unit` is USD, so the **reporting currency for this dataset is USD**. `clients.json` states AUM in SGD (`aum_sgd`). Holdings are a **sample** of each client's book, not converted or reconciled to those AUM figures.

| client | sample market value (USD, approx.) | managed assets (`aum_sgd`) |
|---|---|---|
| jft | 40.0m | S$500m |
| jfr | 30.0m | S$500m |
| ser | 3.9m | S$5.0m |
