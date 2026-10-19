import type {
  ActivityEvent, AllocationRow, Bucket3L, Citation, Client, Gate, Holding, InboxItem, IpsPart,
  MarketView, HouseView, MarketRow, MacroBrief, MeetingNote, PackSection, Product, CaseStep, AllocationGroup, GoalProjection,
} from "../types/arc";

export const clients: Client[] = [
  { id: "ser", name: "Sergio Ermotti", riskCategory: "Balanced", riskCap: 3, aumSgd: 5_000_000, nextMeeting: "2026-10-21", nextQuarterlyReview: "2026-10-28", status: "Monitoring Phase", ipsVersion: 2, sharpe: 0.82, diversificationScore: 71 },
  { id: "dso", name: "David Solomon", riskCategory: "Conservative", riskCap: 2, aumSgd: 2_800_000, nextMeeting: "2026-10-28", nextQuarterlyReview: "2027-01-20", status: "Monitoring Phase", ipsVersion: 1, sharpe: 0.61, diversificationScore: 64 },
  { id: "jfr", name: "Jane Fraser", riskCategory: "Aggressive", riskCap: 5, aumSgd: 12_100_000, nextMeeting: "2026-11-14", nextQuarterlyReview: null, status: "Onboarding Phase", ipsVersion: null, sharpe: 0.94, diversificationScore: 57 },
  { id: "teo", name: "Teo Yuwei", riskCategory: "Growth", riskCap: 4, aumSgd: 7_400_000, nextMeeting: "2026-11-05", nextQuarterlyReview: "2027-01-14", status: "Monitoring Phase", ipsVersion: 1, sharpe: 0.88, diversificationScore: 66 },
  { id: "sha", name: "Shane", riskCategory: "Moderate", riskCap: 3, aumSgd: 3_600_000, nextMeeting: "2026-10-30", nextQuarterlyReview: null, status: "Onboarding Phase", ipsVersion: null, sharpe: 0.70, diversificationScore: 68 },
];

export const holdings: Holding[] = [
  { id: "h1", name: "US Treasury Bills 3M", ticker: "T-BILL", assetClass: "Cash", valueSgd: 650_000, weightPct: 13, returnYtdPct: 2.9 },
  { id: "h2", name: "Singapore Government Bond 10Y", ticker: "SGS 10Y", assetClass: "Fixed income", valueSgd: 1_100_000, weightPct: 22, returnYtdPct: 3.4 },
  { id: "h3", name: "PIMCO Income Fund (Inst.)", ticker: "PIMIX", assetClass: "Fixed income", valueSgd: 700_000, weightPct: 14, returnYtdPct: 4.1 },
  { id: "h4", name: "Microsoft Corp", ticker: "MSFT", assetClass: "Equities", valueSgd: 800_000, weightPct: 16, returnYtdPct: 14.2 },
  { id: "h5", name: "Apple Inc", ticker: "AAPL", assetClass: "Equities", valueSgd: 500_000, weightPct: 10, returnYtdPct: 12.7 },
  { id: "h6", name: "DBS Group Holdings", ticker: "D05", assetClass: "Equities", valueSgd: 350_000, weightPct: 7, returnYtdPct: 6.3 },
  { id: "h7", name: "Man AHL Diversified", ticker: "MAN AHL", assetClass: "Hedge funds", valueSgd: 250_000, weightPct: 5, returnYtdPct: 5.1 },
  { id: "h8", name: "Blackstone Private Equity Strategies", ticker: "BXPE", assetClass: "Private markets", valueSgd: 150_000, weightPct: 3, returnYtdPct: 8.8 },
  { id: "h9", name: "CapitaLand Ascendas REIT", ticker: "A17U", assetClass: "Real estate", valueSgd: 200_000, weightPct: 4, returnYtdPct: 3.0 },
  { id: "h10", name: "SPDR Gold Shares", ticker: "GLD", assetClass: "Gold", valueSgd: 300_000, weightPct: 6, returnYtdPct: 18.5 },
];

export const assetClassOrder = ["Cash", "Fixed income", "Equities", "Hedge funds", "Private markets", "Real estate", "Gold"] as const;

/** Asset-class correlation matrix, same order as assetClassOrder. */
export const correlationByClass: number[][] = [
  [1.0, 0.25, 0.05, 0.1, 0.0, 0.05, 0.02],
  [0.25, 1.0, 0.35, 0.3, 0.2, 0.45, 0.3],
  [0.05, 0.35, 1.0, 0.7, 0.65, 0.6, 0.1],
  [0.1, 0.3, 0.7, 1.0, 0.55, 0.45, 0.12],
  [0.0, 0.2, 0.65, 0.55, 1.0, 0.5, 0.05],
  [0.05, 0.45, 0.6, 0.45, 0.5, 1.0, 0.08],
  [0.02, 0.3, 0.1, 0.12, 0.05, 0.08, 1.0],
];


/* ---------- Per-client variants (ser = base data above/below) ---------- */
const mkHoldings = (aum: number, w: number[], ytd: number[]): Holding[] =>
  holdings.map((h, i) => ({ ...h, weightPct: w[i], valueSgd: Math.round((aum * w[i]) / 100), returnYtdPct: ytd[i] }));

export const holdingsByClient: Record<string, Holding[]> = {
  ser: holdings,
  dso: mkHoldings(2_800_000, [20, 30, 20, 4, 3, 8, 2, 1, 5, 7], [2.9, 3.4, 4.1, 14.2, 12.7, 6.3, 5.1, 8.8, 3.0, 18.5]),
  jfr: mkHoldings(12_100_000, [3, 5, 7, 25, 20, 10, 8, 10, 4, 8], [2.9, 3.4, 4.1, 14.2, 12.7, 6.3, 5.1, 8.8, 3.0, 18.5]),
  teo: mkHoldings(7_400_000, [4, 8, 8, 28, 22, 8, 6, 8, 3, 5], [2.9, 3.4, 4.1, 14.2, 12.7, 6.3, 5.1, 8.8, 3.0, 18.5]),
  sha: mkHoldings(3_600_000, [12, 28, 18, 10, 8, 6, 4, 2, 6, 6], [2.9, 3.4, 4.1, 14.2, 12.7, 6.3, 5.1, 8.8, 3.0, 18.5]),
};

export const holdingLabels = ["T-Bills", "SGS 10Y", "PIMCO Income", "MSFT", "AAPL", "DBS", "Man AHL", "BXPE", "CLAR REIT", "Gold"];

const upper: Record<string, number> = {
  "0-1": 0.25, "0-2": 0.2, "0-3": 0.03, "0-4": 0.04, "0-5": 0.05, "0-6": 0.08, "0-7": 0.02, "0-8": 0.05, "0-9": 0.03,
  "1-2": 0.75, "1-3": 0.15, "1-4": 0.17, "1-5": 0.2, "1-6": 0.1, "1-7": 0.05, "1-8": 0.55, "1-9": 0.2,
  "2-3": 0.3, "2-4": 0.32, "2-5": 0.3, "2-6": 0.25, "2-7": 0.15, "2-8": 0.45, "2-9": 0.15,
  "3-4": 0.92, "3-5": 0.6, "3-6": 0.55, "3-7": 0.6, "3-8": 0.4, "3-9": 0.05,
  "4-5": 0.62, "4-6": 0.55, "4-7": 0.58, "4-8": 0.4, "4-9": 0.06,
  "5-6": 0.5, "5-7": 0.5, "5-8": 0.6, "5-9": 0.08,
  "6-7": 0.45, "6-8": 0.3, "6-9": 0.1,
  "7-8": 0.35, "7-9": 0.04,
  "8-9": 0.1,
};
/** Holdings correlation, same order as holdingLabels. Symmetric, diagonal 1. */
export const holdingsCorrelation: number[][] = holdingLabels.map((_, i) =>
  holdingLabels.map((_, j) => (i === j ? 1 : upper[`${Math.min(i, j)}-${Math.max(i, j)}`])),
);

const groupOf = (c: string): "Equities" | "Bonds" | "Alternatives" | "Liquidity" =>
  c === "Equities" ? "Equities" : c === "Fixed income" ? "Bonds" : c === "Cash" ? "Liquidity" : "Alternatives";
const groupColor = { Equities: "chart-equities", Bonds: "chart-bonds", Alternatives: "chart-alternatives", Liquidity: "chart-liquidity" } as const;
export const allocationGroupsFor = (clientId: string): AllocationGroup[] => {
  const hs = holdingsByClient[clientId] ?? holdings;
  const total = hs.reduce((a, h) => a + h.weightPct, 0);
  return (["Equities", "Bonds", "Alternatives", "Liquidity"] as const).map((label) => ({
    label,
    value: Math.round((hs.filter((h) => groupOf(h.assetClass) === label).reduce((a, h) => a + h.weightPct, 0) / total) * 1000) / 10,
    color: groupColor[label],
  }));
};

export const caseTimelineByClient: Record<string, CaseStep[]> = {
  ser: [
    { who: "RM", what: "Case opened", by: "Isabel", state: "done" },
    { who: "PS", what: "Product list sent (G3)", by: "David", state: "done" },
    { who: "IC", what: "New TAA approved (G2)", by: "Wei Lun", state: "waiting" },
    { who: "RM", what: "Final review pack (G4)", by: "Isabel", state: "not_started" },
  ],
  dso: [
    { who: "RM", what: "Life-event noted, SAA request sent", by: "Isabel", state: "done" },
    { who: "IC", what: "Redo 3L and SAA (G2)", by: "Wei Lun", state: "waiting" },
  ],
  jfr: [
    { who: "RM", what: "Draft the IPS and send to IC", by: "Isabel", state: "not_started" },
    { who: "IC", what: "Fill 3L and SAA (G2)", by: "Wei Lun", state: "not_started" },
  ],
  teo: [
    { who: "RM", what: "Case opened, IPS v1 active", by: "Isabel", state: "done" },
    { who: "PS", what: "Product list sent (G3)", by: "David", state: "waiting" },
    { who: "IC", what: "TAA for Q1 review (G2)", by: "Wei Lun", state: "not_started" },
  ],
  sha: [
    { who: "RM", what: "Onboarding IPS sent to IC", by: "Isabel", state: "done" },
    { who: "IC", what: "Fill 3L and SAA (G2)", by: "Wei Lun", state: "waiting" },
    { who: "RM", what: "IPS approval (G1)", by: "Isabel", state: "not_started" },
  ],
};

export const correlation = correlationByClass;

export const holdingClusters = [
  { id: "c1", label: "2 holdings are both US large-cap tech", holdings: ["Microsoft Corp", "Apple Inc"], combinedPct: 26, note: "Move together in sell-offs (avg correlation 0.74)." },
  { id: "c2", label: "2 holdings are Singapore rate-sensitive income", holdings: ["Singapore Government Bond 10Y", "CapitaLand Ascendas REIT"], combinedPct: 26, note: "Both fall if rates rise." },
];

export const buckets3L: Bucket3L[] = [
  { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 3_500_000, pct: 70, purpose: "S$3.0m house deposit plus S$0.5m cushion" },
  { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 1_000_000, pct: 20, purpose: "Income for retirement years" },
  { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 500_000, pct: 10, purpose: "Wealth passed to the next generation" },
];

export const allocation: AllocationRow[] = [
  { assetClass: "Cash", saa: 15, current: 13, oldTaa: 14, newTaa: 12, band: 5, reason: "Cash yield is falling [CIO-2026Q4-02]" },
  { assetClass: "Fixed income", saa: 35, current: 36, oldTaa: 33, newTaa: 40, band: 5, reason: "Buy view [CIO-2026Q4-03]" },
  { assetClass: "Equities", saa: 30, current: 33, oldTaa: 33, newTaa: 28, band: 5, reason: "Hold, trim a rich market [CIO-2026Q4-05]" },
  { assetClass: "Hedge funds", saa: 5, current: 5, oldTaa: 5, newTaa: 5, band: 5, reason: "No change [IPS-v2]" },
  { assetClass: "Private markets", saa: 3, current: 3, oldTaa: 3, newTaa: 3, band: 5, reason: "No change [IPS-v2]" },
  { assetClass: "Real estate", saa: 5, current: 4, oldTaa: 5, newTaa: 5, band: 5, reason: "No change [IPS-v2]" },
  { assetClass: "Gold", saa: 7, current: 6, oldTaa: 7, newTaa: 7, band: 5, reason: "Hold [CIO-2026Q4-09]" },
];

export const saaTemplates = [
  { id: "A", name: "Capital preservation", split: [30, 40, 10, 5, 0, 5, 10] },
  { id: "B", name: "Income", split: [20, 45, 15, 5, 0, 8, 7] },
  { id: "C", name: "Balanced", split: [15, 35, 30, 5, 3, 5, 7] },
  { id: "D", name: "Growth", split: [10, 25, 40, 7, 5, 6, 7] },
  { id: "E", name: "Aggressive growth", split: [5, 15, 50, 8, 8, 6, 8] },
  { id: "F", name: "Opportunistic", split: [5, 10, 45, 12, 12, 8, 8] },
];

export const ipsParts: IpsPart[] = [
  { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "Buy a S$15m home within 12 months (S$3.0m deposit). Retain lifetime income and leave a legacy for two children." },
  { part: 2, title: "3L buckets and explanation", owner: "ic", status: "filled", body: "Liquidity 70%, Longevity 20%, Legacy 10%. Buckets move money to the near-term deposit while keeping long-term income." },
  { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Balanced. Risk limit 3 of 5. Risk capacity: Moderate. Can tolerate a 12% drawdown; needs high liquidity for 12 months." },
  { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "filled", body: "Cash 15, Fixed income 35, Equities 30, Hedge funds 5, Private markets 3, Real estate 5, Gold 7." },
  { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when an asset class drifts more than 5 points from SAA. Benchmark: 40/60 blended index." },
  { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
];

export const meetingNotes: MeetingNote[] = [
  { id: "note_0318", sourceFile: "2026-09-12-house-purchase-meeting.pdf", originalText: "Meeting with Sergio Ermotti, 12 September 2026. Attendees: Sergio Ermotti, Isabel (RM).\n\nSergio opened by explaining that he and his family have found a house they want to buy, at about S$15m. He expects to pay a deposit of S$3.0m within the next twelve months and would like to fund it without disturbing the part of the portfolio that supports his retirement income.\n\nI asked how firm the timeline is. He said the sellers are flexible but he does not want to be rushed into selling investments in a weak market. He repeated that volatility worries him more than it did a year ago, and that he would prefer to hold more in cash and short-dated bonds until the deposit is paid.\n\nWe agreed that the Liquidity bucket in the IPS should be enlarged, and that the IPS should be updated to version 2. Isabel will confirm the deposit date with him and send the draft to the Investment Counsellor for the revised allocation.", clientId: "ser", date: "2026-09-12", title: "House purchase meeting", summary: ["Plans to buy a S$15m house", "Needs S$3.0m deposit within 12 months", "Wants to keep retirement income intact", "Concerned about market volatility"], checklist: [{ text: "Confirm deposit date with client", done: true }, { text: "Review liquidity bucket", done: false }, { text: "Send IPS v2 draft to IC", done: false }] },
  { id: "note_0421", sourceFile: "2026-08-04-annual-review.pdf", originalText: "Annual review with David Solomon, 4 August 2026. Attendees: David Solomon, Isabel (RM).\n\nDavid said his priorities are steady income and keeping his capital safe. He is now considering bringing his retirement forward by about two years, though no date has been fixed.\n\nWhen we discussed risk, he said a fall of more than 10% in a single year would make him uncomfortable and likely prompt him to sell. We went through the current holdings and he was happy with the bond-heavy mix.\n\nNext steps: confirm the new retirement date and review his income needs with the Investment Counsellor, since an earlier retirement would change the SAA.", clientId: "dso", date: "2026-08-04", title: "Annual review", summary: ["Wants steady income and capital kept safe", "Retirement may be brought forward by two years", "Would be uncomfortable with a fall of more than 10% in a year"], checklist: [{ text: "Confirm new retirement date", done: false }, { text: "Review income needs with IC", done: false }] },
  { id: "note_0502", sourceFile: "2026-10-13-first-meeting.pdf", originalText: "First meeting with Jane Fraser, 13 October 2026. Attendees: Jane Fraser, Isabel (RM).\n\nJane recently sold her business and has S$12.1m to invest. She described herself as comfortable with large swings in value in exchange for long-term growth, and said she would not need to touch the capital for at least ten years.\n\nShe would like to set up a family foundation within five years and asked how that might affect how the portfolio is structured. We did not go into detail and agreed to revisit it once the IPS is drafted.\n\nOpen question: she did not state how much cash she needs each month. Isabel will ask, run the risk questionnaire, and then send the IPS draft to the Investment Counsellor.", clientId: "jfr", date: "2026-10-13", title: "First meeting", summary: ["Sold his business and has S$12.1m to invest", "Comfortable with large swings for long-term growth", "Wants to start a family foundation within 5 years", "Open question: monthly cash needs not stated"], checklist: [{ text: "Run the risk questionnaire", done: false }, { text: "Ask about monthly cash needs", done: false }, { text: "Send IPS draft to IC", done: false }] },
  { id: "note_0610", sourceFile: "2026-10-02-half-year-review.pdf", originalText: "Half-year review with Teo Yuwei, 2 October 2026. Attendees: Teo Yuwei, Isabel (RM).\n\nTeo is pleased with the growth portfolio, which is up about 9% year to date. His children begin overseas education in four years and he wants to be sure the money will be available when it is needed.\n\nHe is open to adding private markets exposure, provided it does not tie up too much of the portfolio. He also raised a concern about how much of the portfolio sits in US technology shares.\n\nNext steps: review the technology concentration with the Investment Counsellor and prepare an education funding estimate (already drafted).", clientId: "teo", date: "2026-10-02", title: "Half-year review", summary: ["Happy with growth portfolio, up 9% year to date", "Children's overseas education starts in 4 years", "Open to adding private markets exposure", "Worried about US tech concentration"], checklist: [{ text: "Review tech concentration with IC", done: false }, { text: "Prepare education funding estimate", done: true }] },
  { id: "note_0715", sourceFile: "2026-10-09-first-meeting.pdf", originalText: "First meeting with Shane, 9 October 2026. Attendees: Shane, Isabel (RM).\n\nShane would like to buy a condominium within two years. He has a moderate appetite for risk but dislikes large drops in value, especially as the purchase date gets closer. He saves roughly S$8k a month.\n\nOpen question: he has not decided on the expected price of the condo. Isabel will confirm his budget, then send the IPS draft to the Investment Counsellor. The risk questionnaire was completed during the meeting.", clientId: "sha", date: "2026-10-09", title: "First meeting", summary: ["Wants to buy a condo within 2 years", "Moderate risk appetite, dislikes large drops", "Saves roughly S$8k a month", "Open question: expected condo price not stated"], checklist: [{ text: "Run the risk questionnaire", done: true }, { text: "Confirm condo budget", done: false }, { text: "Send IPS draft to IC", done: false }] },
];

export const gates: Gate[] = [
  { id: "G1", label: "IPS approval", approver: "rm", state: "approved", approvedAt: "2026-09-20" },
  { id: "G3", label: "Product list", approver: "ps", state: "approved", approvedAt: "2026-10-14 11:20" },
  { id: "G2", label: "TAA and sections 2–5", approver: "ic", state: "pending" },
  { id: "G4", label: "Final pack and PDF", approver: "rm", state: "not_started" },
];

export const inboxes: Record<"ic" | "ps", InboxItem[]> = {
  ic: [
    { id: "ic1", clientId: "jfr", clientName: "Jane Fraser", kind: "IPS SAA request", from: "rm", receivedAt: "2026-10-16 09:12", summary: "Onboarding IPS sent. Fill 3L and SAA (parts 2 and 4).", priority: "high", trigger: 1 },
    { id: "ic2", clientId: "ser", clientName: "Sergio Ermotti", kind: "Portfolio adjustment request", from: "ps", receivedAt: "2026-10-14 11:20", summary: "PS approved 4 fixed income products. Propose and approve the TAA.", priority: "high", trigger: 3 },
    { id: "ic3", clientId: "dso", clientName: "David Solomon", kind: "IPS SAA request", from: "rm", receivedAt: "2026-10-12 15:40", summary: "Life event: retirement brought forward. Redo 3L and SAA.", priority: "normal", trigger: 2 },
    { id: "ic4", clientId: "sha", clientName: "Shane", kind: "IPS SAA request", from: "rm", receivedAt: "2026-10-15 14:25", summary: "Onboarding IPS sent. Fill 3L and SAA (parts 2 and 4).", priority: "normal", trigger: 1 },
  ],
  ps: [
    { id: "ps1", clientId: "ser", clientName: "Sergio Ermotti", kind: "Product-review request", from: "rm", receivedAt: "2026-10-14 08:30", summary: "Quarterly review opened. Research the market and shortlist products.", priority: "high", trigger: 3 },
    { id: "ps2", clientId: "dso", clientName: "David Solomon", kind: "Product-review request", from: "rm", receivedAt: "2026-10-13 10:05", summary: "New CIO House View landed. Check fixed income shelf.", priority: "normal", trigger: 3 },
    { id: "ps3", clientId: "teo", clientName: "Teo Yuwei", kind: "Product-review request", from: "rm", receivedAt: "2026-10-15 09:45", summary: "Concentration in US tech. Shortlist diversifying equity and alternatives products.", priority: "normal", trigger: 3 },
  ],
};

export const marketCycle = { phase: "Late expansion", tag: "MKT-0142", asOf: "2026-10-14" };
export const marketViews: MarketView[] = [
  { assetClass: "Fixed income", view: "Buy", explanation: "Growth is slowing, so rates are likely to fall. High-grade bonds lock in today's yield.", confidence: "High", tags: ["CIO-2026Q4-03", "MKT-0142"] },
  { assetClass: "Equities", view: "Hold", explanation: "Profits are solid but prices are high for late expansion.", confidence: "Medium", tags: ["CIO-2026Q4-05", "MKT-0142"] },
  { assetClass: "Cash", view: "Sell", explanation: "Cash yields fall when rate cuts come.", confidence: "Medium", tags: ["CIO-2026Q4-02"] },
  { assetClass: "Gold", view: "Hold", explanation: "Supports the portfolio if growth surprises on the downside.", confidence: "Medium", tags: ["CIO-2026Q4-09"] },
];

export const products: Product[] = [
  { id: "PRD-FI-007", name: "SGD Investment Grade Bond Fund", assetClass: "Fixed income", whyBuy: "Fits the Buy view on fixed income. Rated 2 of 5 for risk, below Sergio Ermotti's limit of 3. Daily dealing fits the Liquidity bucket.", feePct: 0.55, stars: 5, suitability: "Inside risk limit, fits Liquidity bucket", riskRating: 2, tags: ["MKT-0142", "IPS-v2"] },
  { id: "PRD-FI-011", name: "Global Aggregate Bond ETF", assetClass: "Fixed income", whyBuy: "Wide mix of bonds lowers single-issuer risk.", feePct: 0.2, stars: 4, suitability: "Fits Longevity bucket, small currency risk", riskRating: 2, tags: ["CIO-2026Q4-03"] },
  { id: "PRD-FI-004", name: "Short-Duration Treasury Fund", assetClass: "Fixed income", whyBuy: "Less hit if rates rise.", feePct: 0.3, stars: 4, suitability: "Equal fit to row 2, ranked below it only on the fee tie-break", riskRating: 1, tags: ["MKT-0142"] },
  { id: "PRD-FI-015", name: "Asia High Yield Bond Fund", assetClass: "Fixed income", whyBuy: "Higher income.", feePct: 0.95, stars: 3, suitability: "Risk rating 3 is at the limit, adds Asia credit concentration", riskRating: 3, tags: ["MKT-0142"] },
  { id: "PRD-FI-018", name: "Franklin Templeton Global Bond Fund", assetClass: "Fixed income", whyBuy: "Broad government and corporate bonds across regions.", feePct: 0.75, stars: 3, suitability: "Inside risk limit, unhedged currency exposure", riskRating: 2, tags: ["MKT-0142"] },
  { id: "PRD-EQ-021", name: "iShares Core MSCI World ETF", assetClass: "Equities", whyBuy: "Low-cost exposure to developed-market shares.", feePct: 0.2, stars: 5, suitability: "Core holding, tech-heavy weights", riskRating: 3, tags: ["CIO-2026Q4-05"] },
  { id: "PRD-EQ-024", name: "Fidelity Global Dividend Fund", assetClass: "Equities", whyBuy: "Dividend payers tend to hold up better late in the cycle.", feePct: 0.95, stars: 4, suitability: "Income tilt, fits Longevity bucket", riskRating: 3, tags: ["CIO-2026Q4-05"] },
  { id: "PRD-EQ-027", name: "BlackRock Global Allocation Fund", assetClass: "Equities", whyBuy: "Flexible mix of shares, bonds and cash managed by one team.", feePct: 1.05, stars: 4, suitability: "Multi-asset, moderate swings", riskRating: 3, tags: ["MKT-0142"] },
  { id: "PRD-EQ-031", name: "Franklin Technology Fund", assetClass: "Equities", whyBuy: "Concentrated growth in technology companies.", feePct: 1.2, stars: 3, suitability: "Adds sector concentration, above Balanced limits", riskRating: 4, tags: ["CIO-2026Q4-05"] },
  { id: "PRD-HF-033", name: "Man AHL Diversified", assetClass: "Hedge funds", whyBuy: "Trend-following strategy that can gain when markets fall.", feePct: 1.8, stars: 3, suitability: "Diversifier, limited daily liquidity", riskRating: 4, tags: ["MKT-0142"] },
  { id: "PRD-HF-036", name: "BlackRock Event Driven Equity Fund", assetClass: "Hedge funds", whyBuy: "Profits from mergers and corporate events, low link to markets.", feePct: 1.6, stars: 3, suitability: "Monthly dealing, suits Longevity bucket", riskRating: 4, tags: ["MKT-0142"] },
  { id: "PRD-PM-041", name: "Blackstone Private Equity Strategies Fund", assetClass: "Private markets", whyBuy: "Access to private companies not available in public markets.", feePct: 1.25, stars: 3, suitability: "Long lock-up, only for Legacy bucket", riskRating: 4, tags: ["CIO-2026Q4-09"] },
  { id: "PRD-RE-044", name: "Fidelity Asia Pacific Property Fund", assetClass: "Real estate", whyBuy: "Rental income from listed property across Asia.", feePct: 1.1, stars: 3, suitability: "Income with inflation link, moderate risk", riskRating: 3, tags: ["MKT-0142"] },
  { id: "PRD-GD-047", name: "SPDR Gold Shares", assetClass: "Gold", whyBuy: "Simple exposure to the gold price as a portfolio hedge.", feePct: 0.4, stars: 4, suitability: "Supports the Hold view on gold", riskRating: 3, tags: ["CIO-2026Q4-09"] },
  { id: "PRD-CS-050", name: "UBS SGD Money Market Fund", assetClass: "Cash", whyBuy: "Daily access to cash with a money-market yield.", feePct: 0.25, stars: 4, suitability: "Fits Liquidity bucket, yield falls with rate cuts", riskRating: 1, tags: ["CIO-2026Q4-02"] },
  { id: "PRD-SP-053", name: "Capital-Protected Equity-Linked Note", assetClass: "Structured products", whyBuy: "Keeps the invested amount at maturity and shares part of any equity gain.", feePct: 0.8, stars: 3, suitability: "3-year term, issuer credit risk", riskRating: 3, tags: ["MKT-0142"] },
  { id: "PRD-SP-056", name: "Autocallable Note on Nasdaq-100", assetClass: "Structured products", whyBuy: "Pays a fixed coupon and can end early if the index holds up.", feePct: 0.9, stars: 2, suitability: "Capital at risk if the index falls sharply", riskRating: 4, tags: ["MKT-0142"] },
];

export const packSections: PackSection[] = [
  { n: 1, title: "Latest Client's Profile + Goals", owner: "rm", gate: "G4", status: "draft", body: "Sergio Ermotti, S$5.0m, Balanced. IPS v2 approved 2026-09-20 following the house purchase [NOTE-2026-09-12] [IPS-v2]." },
  { n: 2, title: "Market view", owner: "ic", gate: "G2", status: "ready", body: "Late expansion [MKT-0142]. Buy fixed income, hold equities and gold, sell cash [CIO-2026Q4-03]." },
  { n: 3, title: "Current market conditions", owner: "ic", gate: "G2", status: "ready", body: "Growth is slowing while profits remain solid; rate cuts are expected [MKT-0142]." },
  { n: 4, title: "Portfolio current health", owner: "ic", gate: "G2", status: "flagged", body: "Sharpe 0.82 [CALC-sharpe-v1]. Diversification 71. Tech concentration of 31% looks high." },
  { n: 5, title: "Old vs new TAA", owner: "ic", gate: "G2", status: "ready", body: "Fixed income to 40 (+5, at band edge); equities to 28; cash to 12 [CALC-taa-v1]." },
  { n: 6, title: "Product recommendations", owner: "ps", gate: "G3", status: "approved", body: "4 fixed income products shortlisted by PS [PRD-FI-007]." },
  { n: 7, title: "Sign-off", owner: "rm", gate: null, status: "draft", body: "PS, IC and RM each sign their own line." },
  { n: 8, title: "Sources and citations", owner: "rm", gate: null, status: "ready", body: "Generated by Pack Builder from the source registry." },
];

export const citations: Citation[] = [
  { tag: "NOTE-2026-09-12", what: "Meeting notes on the house purchase", system: "Client DB, RM", asOf: "2026-09-12", ref: "note_0318" },
  { tag: "IPS-v2", what: "Finalised IPS version 2", system: "Client DB, RM", asOf: "2026-09-20", ref: "ips_v2" },
  { tag: "HLD-20261013", what: "Holdings snapshot", system: "Bank portfolio system (read-only)", asOf: "2026-10-13 18:00", ref: "hld_20261013_1800" },
  { tag: "CIO-2026Q4-03", what: "CIO House View, fixed income", system: "UBS CIO House View store", asOf: "2026-10-01", ref: "cio_2026q4, section 3" },
  { tag: "MKT-0142", what: "Market Research Agent case result", system: "Case State", asOf: "2026-10-14", ref: "mkt_0142" },
  { tag: "PRD-FI-007", what: "SGD Investment Grade Bond Fund", system: "Product shelf DB", asOf: "2026-10-10", ref: "prd_fi_007" },
  { tag: "CALC-sharpe-v1", what: "Sharpe ratio, formula and inputs", system: "Analytics Engine", asOf: "2026-10-13", ref: "calc_sharpe_v1" },
];

export const activity: ActivityEvent[] = [
  { id: "a1", at: "2026-10-14 17:05", actor: "RM", role: "rm", text: "Opened quarterly review for Sergio Ermotti" },
  { id: "a2", at: "2026-10-14 11:20", actor: "PS", role: "ps", text: "Approved product list (G3) and sent to IC" },
  { id: "a3", at: "2026-10-14 08:30", actor: "System", role: "system", text: "Notified PS of new CIO House View" },
  { id: "a4", at: "2026-09-20 10:00", actor: "RM", role: "rm", text: "Approved IPS v2 (G1)" },
];

/* ---------- Per-client 3L, allocation, IPS ---------- */
export const buckets3LByClient: Record<string, Bucket3L[]> = {
  ser: buckets3L,
  dso: [
    { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 560_000, pct: 20, purpose: "Three years of living costs and medical cushion" },
    { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 1_900_000, pct: 68, purpose: "Stable income for retirement, brought forward" },
    { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 340_000, pct: 12, purpose: "Modest bequest to grandchildren" },
  ],
  jfr: [
    { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 1_210_000, pct: 10, purpose: "Tax on business sale and working cushion" },
    { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 4_840_000, pct: 40, purpose: "Long-run growth for retirement income" },
    { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 6_050_000, pct: 50, purpose: "Long-horizon wealth for the family" },
  ],
  teo: [
    { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 740_000, pct: 10, purpose: "Living costs and tax cushion" },
    { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 3_700_000, pct: 50, purpose: "Long-run growth for retirement income" },
    { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 2_960_000, pct: 40, purpose: "Wealth for children's education and inheritance" },
  ],
  sha: [
    { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 1_080_000, pct: 30, purpose: "Condo down payment and emergency fund" },
    { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 1_620_000, pct: 45, purpose: "Retirement savings" },
    { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 900_000, pct: 25, purpose: "Support for parents and future family" },
  ],
};

const rows = (cls: AllocationRow["assetClass"][], saa: number[], cur: number[], oldT: number[], newT: number[], tag: string): AllocationRow[] =>
  cls.map((assetClass, i) => ({ assetClass, saa: saa[i], current: cur[i], oldTaa: oldT[i], newTaa: newT[i], band: 5, reason: `Per IPS [${tag}]` }));
const CLS = assetClassOrder as unknown as AllocationRow["assetClass"][];
export const allocationByClient: Record<string, AllocationRow[]> = {
  ser: allocation,
  dso: rows(CLS, [20, 48, 18, 2, 1, 5, 6], [20, 50, 15, 2, 1, 5, 7], [20, 49, 16, 2, 1, 5, 7], [18, 52, 15, 2, 1, 5, 7], "IPS-v1"),
  jfr: rows(CLS, [5, 15, 50, 8, 8, 6, 8], [3, 12, 55, 8, 10, 4, 8], [5, 15, 50, 8, 8, 6, 8], [4, 14, 52, 8, 8, 6, 8], "IPS-draft"),
  teo: rows(CLS, [8, 20, 45, 8, 6, 6, 7], [6, 18, 48, 8, 7, 6, 7], [8, 20, 45, 8, 6, 6, 7], [7, 19, 47, 8, 6, 6, 7], "IPS-v1"),
  sha: rows(CLS, [12, 38, 25, 6, 2, 8, 9], [12, 40, 24, 6, 2, 7, 9], [12, 39, 24, 6, 2, 8, 9], [11, 40, 25, 6, 2, 7, 9], "IPS-draft"),
};

export const ipsPartsByClient: Record<string, IpsPart[]> = {
  ser: ipsParts,
  dso: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "Preserve capital and draw steady income in retirement. Small bequest to grandchildren." },
    { part: 2, title: "3L buckets and explanation", owner: "ic", status: "filled", body: "Liquidity 20%, Longevity 68%, Legacy 12%." },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Conservative. Risk limit 2 of 5. Risk capacity: Moderately low. Can tolerate a 6% drawdown." },
    { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "filled", body: "Cash 20, Fixed income 48, Equities 18, Hedge funds 2, Private markets 1, Real estate 5, Gold 6." },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Annual review. Rebalance when drift exceeds 5 points. Benchmark: 20/80 blended index." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
  jfr: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "blank", body: "" },
    { part: 2, title: "3L buckets and explanation", owner: "ic", status: "blank", body: "" },
    { part: 3, title: "Client risk profile", owner: "rm", status: "blank", body: "" },
    { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "blank", body: "" },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when drift exceeds 5 points." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
  teo: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "Grow wealth over 15+ years, fund children's overseas education, build a legacy." },
    { part: 2, title: "3L buckets and explanation", owner: "ic", status: "filled", body: "Liquidity 10%, Longevity 50%, Legacy 40%." },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Growth. Risk limit 4 of 5. Risk capacity: Moderately high. Can tolerate a 20% drawdown." },
    { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "filled", body: "Cash 8, Fixed income 20, Equities 45, Hedge funds 8, Private markets 6, Real estate 6, Gold 7." },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when drift exceeds 5 points. Benchmark: 70/30 blended index." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
  sha: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "Buy a condo within 2 years, then build retirement savings steadily." },
    { part: 2, title: "3L buckets and explanation", owner: "ic", status: "blank", body: "" },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Moderate. Risk limit 3 of 5. Risk capacity: Moderate. Can tolerate a 12% drawdown." },
    { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "blank", body: "" },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when drift exceeds 5 points." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
};


/** Structured mirror of IPS part 3 (risk capacity, drawdown limit) - what the IPS form would store. */
export const ipsRiskByClient: Record<string, { riskCapacity: string; maxDrawdownPct: number }> = {
  ser: { riskCapacity: "Moderate", maxDrawdownPct: 12 },
  dso: { riskCapacity: "Moderately low", maxDrawdownPct: 6 },
  jfr: { riskCapacity: "High", maxDrawdownPct: 30 },
  teo: { riskCapacity: "Moderately high", maxDrawdownPct: 20 },
  sha: { riskCapacity: "Moderate", maxDrawdownPct: 12 },
};

const gp = (start: number, grow: number, req0: number, reqGrow: number) =>
  Array.from({ length: 35 }, (_, i) => ({
    year: 2026 + i,
    projected: +(start * Math.pow(1 + grow, i)).toFixed(2),
    required: +(req0 * Math.pow(1 + reqGrow, i)).toFixed(2),
  }));

export const goalProjectionByClient: Record<string, GoalProjection> = {
  ser: { points: gp(5, 0.052, 4.6, 0.05), events: [{ year: 2027, label: "House deposit" }, { year: 2034, label: "Child's education" }, { year: 2042, label: "Retirement" }], yearsOnTrack: 6, summary: "Funds last 6 years beyond the target age under the current Balanced plan." },
  dso: { points: gp(2.8, 0.036, 2.6, 0.035), events: [{ year: 2029, label: "Retirement" }, { year: 2045, label: "Legacy gift" }], yearsOnTrack: 4, summary: "Funds last 4 years beyond the target age; a small buffer on a conservative path." },
  teo: { points: gp(7.4, 0.07, 6.6, 0.066), events: [{ year: 2031, label: "Business exit" }, { year: 2030, label: "Children's education" }], yearsOnTrack: 9, summary: "Funds last 9 years beyond the target age, helped by the business exit proceeds." },
  jfr: { points: gp(12.1, 0.082, 10.5, 0.075), events: [{ year: 2035, label: "Philanthropy fund" }, { year: 2044, label: "Retirement" }], yearsOnTrack: 12, summary: "Funds last 12 years beyond the target age, with higher return variability." },
  sha: { points: gp(3.6, 0.055, 3.3, 0.052), events: [{ year: 2028, label: "Condo down payment" }, { year: 2050, label: "Retirement" }], yearsOnTrack: 5, summary: "Funds last 5 years beyond the target age under the Moderate plan." },
};

export const houseViews: HouseView[] = [
  { id: "HV-2026-09", month: "September 2026", issuedOn: "2026-09-15", author: "UBS Chief Investment Office", file: null },
  { id: "HV-2026-08", month: "August 2026", issuedOn: "2026-08-14", author: "UBS Chief Investment Office", file: "/house-views/ubs-house-view-2026-08.pdf" },
  { id: "HV-2026-07", month: "July 2026", issuedOn: "2026-07-15", author: "UBS Chief Investment Office", file: null },
  { id: "HV-2026-06", month: "June 2026", issuedOn: "2026-06-15", author: "UBS Chief Investment Office", file: null },
  { id: "HV-2026-05", month: "May 2026", issuedOn: "2026-05-14", author: "UBS Chief Investment Office", file: null },
  { id: "HV-2026-04", month: "April 2026", issuedOn: "2026-04-14", author: "UBS Chief Investment Office", file: null },
];

export const marketRows: MarketRow[] = [
  { assetClass: "Fixed income", product: "PIMCO Balanced Income Fund", industryFocus: "Government and investment-grade credit", top5: ["US Treasury 10Y", "SGS 10Y Bond", "Microsoft Corp bond", "Apple Inc bond", "DBS Group bond"], confidencePct: 99,
    ranking: ["1. US Treasury 10Y: highest quality, locks in today's yield before rate cuts.", "2. SGS 10Y Bond: SGD-denominated, no currency risk for the client.", "3. Microsoft Corp bond: strong balance sheet, small spread pick-up.", "4. Apple Inc bond: similar credit quality, adds diversification.", "5. DBS Group bond: local bank credit, within the risk limit."] },
  { assetClass: "Equities", product: "Global Quality Equity Fund", industryFocus: "Mostly concentrated on tech", top5: ["Microsoft", "Apple", "NVIDIA", "Alphabet", "Amazon"], confidencePct: 90,
    ranking: ["1. Microsoft: steady profit growth, supports the Hold view on equities.", "2. Apple: strong cash generation, defensive for late expansion.", "3. NVIDIA: high growth but adds concentration, ranked lower for risk.", "4. Alphabet: diversified earnings, fair valuation.", "5. Amazon: cyclical exposure, ranked last in late expansion."] },
  { assetClass: "Alternatives", product: "Asia Infrastructure Income Fund", industryFocus: "Infrastructure and real assets", top5: ["CapitaLand Ascendas REIT", "Singapore Power", "Changi Airport Group", "PSA International", "Keppel Infrastructure"], confidencePct: 80,
    ranking: ["1. CapitaLand Ascendas REIT: stable rental income, inflation linked.", "2. Singapore Power: regulated returns with low volatility.", "3. Changi Airport Group: recovery in travel, moderate risk.", "4. PSA International: trade exposure, ranked lower on cycle risk.", "5. Keppel Infrastructure: smaller scale, lower liquidity."] },
];

export const macroBrief: MacroBrief = {
  phase: "Late expansion", asOf: "2026-10-14",
  events: [
    "US Federal Reserve signals two rate cuts by mid-2027",
    "US core inflation eases to 2.6%, lowest in three years",
    "China adds property support measures, Asia credit spreads tighten",
    "Oil steady near US$78 as supply stays balanced",
  ],
  views: [
    { assetClass: "Fixed income", view: "Buy", industry: "Government and investment-grade credit", direction: "Up", note: "Rate cuts lift bond prices." },
    { assetClass: "Equities", view: "Hold", industry: "Quality tech and healthcare", direction: "Flat", note: "Profits solid, prices already high." },
    { assetClass: "Alternatives", view: "Hold", industry: "Infrastructure and trend-following", direction: "Up", note: "Diversifies late-cycle risk." },
    { assetClass: "Cash", view: "Sell", industry: "Money market", direction: "Down", note: "Yields fall as rates are cut." },
    { assetClass: "Gold", view: "Hold", industry: "Precious metals", direction: "Flat", note: "Hedge if growth slows faster." },
  ],
};

/** Mock product universe the intent parser can match by name. */
export const productCatalogue: { aliases: string[]; row: MarketRow }[] = [
  { aliases: ["pimco"], row: { assetClass: "Fixed income", product: "PIMCO Balanced Income & Growth Fund", industryFocus: "Investment-grade credit with an equity sleeve", top5: ["US Treasury 10Y", "SGS 10Y Bond", "Microsoft Corp bond", "Apple Inc bond", "DBS Group bond"], confidencePct: 96,
    ranking: ["Fits the Buy view on fixed income as rates fall.", "Risk rating 2 sits inside the client's limit.", "Equity sleeve adds some growth for the Longevity bucket.", "Monthly income suits the client's stated cash needs."] } },
  { aliases: ["ishare", "blackrock"], row: { assetClass: "Fixed income", product: "BlackRock iShares Core Global Aggregate Bond ETF", industryFocus: "Global government and corporate bonds", top5: ["US Treasury 5Y", "German Bund 10Y", "Japan JGB 10Y", "UK Gilt 10Y", "Apple Inc bond"], confidencePct: 92,
    ranking: ["Very low fee and daily liquidity.", "Broad mix lowers single-issuer risk.", "Small currency exposure to flag with the client.", "Matches the Buy view on high-grade bonds."] } },
  { aliases: ["equity linked", "equity-linked", "eln", "dbs"], row: { assetClass: "Structured products", product: "Equity-Linked Note on DBS Group", industryFocus: "Singapore banks", top5: ["DBS Group (underlying)", "Issuer: UBS AG", "Coupon 7.2% p.a.", "Strike 90%", "Tenor 6 months"], confidencePct: 78,
    ranking: ["Pays a high coupon while DBS stays above the strike.", "Capital at risk if DBS falls below 90%.", "Concentrated in one bank, so keep the size small.", "Risk rating 3 is at the client's limit."] } },
  { aliases: ["fidelity"], row: { assetClass: "Equities", product: "Fidelity Global Dividend Fund", industryFocus: "Dividend payers, mostly defensive sectors", top5: ["Unilever", "Roche", "Procter & Gamble", "Taiwan Semiconductor", "Deutsche Boerse"], confidencePct: 88,
    ranking: ["Dividend payers hold up better late in the cycle.", "Fits the Hold view on equities with lower swings.", "Income suits the Longevity bucket."] } },
  { aliases: ["franklin"], row: { assetClass: "Fixed income", product: "Franklin Templeton Global Bond Fund", industryFocus: "Sovereign bonds across regions", top5: ["US Treasury 10Y", "Korea KTB 10Y", "India G-Sec 10Y", "Brazil NTN-F", "Norway NGB 10Y"], confidencePct: 74,
    ranking: ["Adds emerging-market yield.", "Unhedged currency risk lowers the rank.", "Inside the risk limit."] } },
  { aliases: ["man ahl", "hedge"], row: { assetClass: "Alternatives", product: "Man AHL Diversified", industryFocus: "Trend-following futures", top5: ["US Treasury futures", "S&P 500 futures", "Gold futures", "EUR/USD", "Brent crude futures"], confidencePct: 70,
    ranking: ["Can gain when markets fall, useful late in the cycle.", "Limited liquidity, Longevity bucket only.", "Risk rating 4 is above a Balanced limit, needs IC sign-off."] } },
  { aliases: ["nasdaq", "autocall"], row: { assetClass: "Structured products", product: "Autocallable Note on Nasdaq-100", industryFocus: "US technology", top5: ["Nasdaq-100 (underlying)", "Issuer: UBS AG", "Coupon 9.0% p.a.", "Barrier 65%", "Tenor 12 months"], confidencePct: 62,
    ranking: ["High coupon if the index holds up.", "Capital at risk below the 65% barrier.", "Tech concentration adds to existing holdings."] } },
];
