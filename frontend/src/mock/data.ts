import type {
  ActivityEvent, AllocationRow, Bucket3L, Citation, Client, Gate, Holding, InboxItem, IpsPart,
  HouseView, MacroBrief, MeetingNote, PackSection, CaseStep, AllocationGroup, GoalProjection,
} from "../types/arc";

export const clients: Client[] = [
  { id: "ser", name: "Sergio Ermotti", riskCategory: "Balanced", riskCap: 3, aumSgd: 5_000_000, nextMeeting: "2026-10-21", nextQuarterlyReview: "2026-10-28", status: "Monitoring Phase", ipsVersion: 2, sharpe: 0.82, diversificationScore: 71 },
  { id: "dso", name: "David Solomon", riskCategory: "Conservative", riskCap: 2, aumSgd: 2_800_000, nextMeeting: "2026-10-28", nextQuarterlyReview: "2027-01-20", status: "Monitoring Phase", ipsVersion: 1, sharpe: 0.61, diversificationScore: 64 },
  { id: "jfr", name: "Jane Fraser", riskCategory: "Conservative", riskCap: 2, aumSgd: 500_000_000, nextMeeting: "2026-11-14", nextQuarterlyReview: null, status: "Onboarding Phase", ipsVersion: null, sharpe: 0.94, diversificationScore: 57 },
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
  jfr: mkHoldings(500_000_000, [19, 31, 20, 6, 3, 6, 0, 0, 5, 10], [2.9, 3.4, 4.1, 14.2, 12.7, 6.3, 5.1, 8.8, 3.0, 18.5]),
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
    { who: "PM", what: "Product list approved (G3)", by: "Wei Lun", state: "done" },
    { who: "PM", what: "New TAA approved (G2)", by: "Wei Lun", state: "waiting" },
    { who: "RM", what: "Final review pack (G4)", by: "Isabel", state: "not_started" },
  ],
  dso: [
    { who: "RM", what: "Life-event noted, SAA request sent", by: "Isabel", state: "done" },
    { who: "PM", what: "Redo 3L and SAA (G2)", by: "Wei Lun", state: "waiting" },
  ],
  jfr: [
    { who: "RM", what: "Draft the IPS and send to PM", by: "Isabel", state: "not_started" },
    { who: "PM", what: "Fill 3L and SAA (G2)", by: "Wei Lun", state: "not_started" },
  ],
  teo: [
    { who: "RM", what: "Case opened, IPS v1 active", by: "Isabel", state: "done" },
    { who: "PM", what: "Product list approved (G3)", by: "Wei Lun", state: "waiting" },
    { who: "PM", what: "TAA for Q1 review (G2)", by: "Wei Lun", state: "not_started" },
  ],
  sha: [
    { who: "RM", what: "Onboarding IPS sent to PM", by: "Isabel", state: "done" },
    { who: "PM", what: "Fill 3L and SAA (G2)", by: "Wei Lun", state: "waiting" },
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
  { part: 2, title: "3L buckets and explanation", owner: "pm", status: "filled", body: "Liquidity 70%, Longevity 20%, Legacy 10%. Buckets move money to the near-term deposit while keeping long-term income." },
  { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Balanced. Risk limit 3 of 5. Risk capacity: Moderate. Can tolerate a 12% drawdown; needs high liquidity for 12 months." },
  { part: 4, title: "Strategic Asset Allocation", owner: "pm", status: "filled", body: "Cash 15, Fixed income 35, Equities 30, Hedge funds 5, Private markets 3, Real estate 5, Gold 7." },
  { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when an asset class drifts more than 5 points from SAA. Benchmark: 40/60 blended index." },
  { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
];

export const meetingNotes: MeetingNote[] = [
  { id: "note_1013", sourceFile: "2026-10-13-first-meeting.pdf", originalText: "First meeting with Jane Fraser, 13 October 2026. Attendees: Jane Fraser, Isabel (RM).\n\nJane is the Chief Executive Officer of CityBank. She earns an annual income of S$10m from salary and bonus. Investable assets managed with the bank total S$500m.\n\nJane described herself as very risk averse. She said a fall of more than 10% in a single year would make her very uncomfortable and likely prompt her to sell. Her priorities are keeping her capital safe and steady income. She prefers cash, government bonds and high-grade bonds.\n\nShe is open to adding some blue-chip equities, up to about 10% of her assets. She would like her assets to grow modestly over time, but she does not want an aggressive approach. She has been investing mainly in deposits and bonds and is not familiar with complex products.\n\nShe does not want hedge funds or private markets in the portfolio, and would like to avoid tobacco and thermal coal. She has a general interest in responsible investing.\n\nShe would not need to touch most of the capital for at least ten years. Jane wants the portfolio to stay mainly in SGD, with some USD.\n\nOpen question: she did not state her monthly spending. Isabel will ask, run the risk questionnaire, and then send the IPS draft to the Portfolio Manager.", clientId: "jfr", date: "2026-10-13", title: "First meeting", summary: ["CEO of CityBank; annual income S$10m; S$500m invested with us", "Very risk averse; a fall above 10% in a year would be very uncomfortable", "Prefers cash, government and high-grade bonds; open to ~10% blue-chip equities for modest growth", "Excludes hedge funds, private markets, tobacco and thermal coal; SGD with some USD", "Open question: monthly spending not stated"], checklist: [{text: "Ask about monthly spending", done: false}, {text: "Run the risk questionnaire", done: false}, {text: "Send IPS draft to PM", done: false}] },
  { id: "note_1020", sourceFile: "2026-10-20-risk-questionnaire-follow-up.pdf", originalText: "Follow-up meeting with Jane Fraser, 20 October 2026. Attendees: Jane Fraser, Isabel (RM).\n\nWe went through the risk questionnaire. Jane confirmed that she is very risk averse and that a fall of more than 10% in a single year would make her very uncomfortable and likely prompt her to sell.\n\nJane spends about S$150,000 a month on living costs. She would like to keep a cash reserve of S$30m so that she never has to sell investments to meet her expenses.\n\nShe is now open to adding up to 15% in blue-chip equities, up from the 10% discussed at the first meeting, as the modest growth part of her assets. She prefers the rest to stay in cash, government bonds and high-grade bonds.\n\nJane would like to keep her currency mix mainly in SGD, with up to 20% in USD. She would like her assets to grow steadily and expects to stay invested for at least ten years.\n\nOpen question: she has not yet told us about assets held outside the bank or any liabilities. Isabel will ask and then update the IPS draft with the Portfolio Manager.", clientId: "jfr", date: "2026-10-20", title: "Risk questionnaire follow-up", summary: ["Risk questionnaire confirms very risk averse; 10% annual fall is the limit", "Spends about S$150,000 a month; wants a S$30m cash reserve", "Growth sleeve raised from 10% to up to 15% in blue-chip equities; rest in cash and bonds", "SGD mainly, up to 20% USD; horizon at least ten years", "Open question: assets outside the bank and liabilities not yet stated"], checklist: [{text: "Ask about assets outside the bank and liabilities", done: false}, {text: "Update IPS draft and send to PM", done: false}] },
];

export const gates: Gate[] = [
  { id: "G1", label: "IPS approval", approver: "rm", state: "approved", approvedAt: "2026-09-20" },
  { id: "G3", label: "Product list", approver: "pm", state: "approved", approvedAt: "2026-10-14 11:20" },
  { id: "G2", label: "TAA and sections 2–5", approver: "pm", state: "pending" },
  { id: "G4", label: "Final pack and PDF", approver: "rm", state: "not_started" },
];

export const inboxes: Record<"pm", InboxItem[]> = {
  pm: [
    { id: "ic1", clientId: "jfr", clientName: "Jane Fraser", kind: "IPS SAA request", from: "rm", receivedAt: "2026-10-16 09:12", summary: "Onboarding IPS sent. Fill 3L and SAA (parts 2 and 4).", priority: "high", trigger: 1 },
    { id: "ic2", clientId: "ser", clientName: "Sergio Ermotti", kind: "Portfolio adjustment request", from: "rm", receivedAt: "2026-10-14 11:20", summary: "Quarterly review sent by the RM. Shortlist products, then propose and approve the TAA.", priority: "high", trigger: 3 },
    { id: "ic3", clientId: "dso", clientName: "David Solomon", kind: "IPS SAA request", from: "rm", receivedAt: "2026-10-12 15:40", summary: "Life event: retirement brought forward. Redo 3L and SAA.", priority: "normal", trigger: 2 },
    { id: "ic4", clientId: "sha", clientName: "Shane", kind: "IPS SAA request", from: "rm", receivedAt: "2026-10-15 14:25", summary: "Onboarding IPS sent. Fill 3L and SAA (parts 2 and 4).", priority: "normal", trigger: 1 },
  ],
};

export const marketCycle = { phase: "Late expansion", tag: "MKT-0142", asOf: "2026-10-14" };
export const packSections: PackSection[] = [
  { n: 1, order: 1, title: "Latest Client's Profile + Goals + Concerns", owner: "rm", gate: "G4", status: "draft", chart: "saa", body: "• Client: Sergio Ermotti; investable assets of S$5.0m; Balanced risk profile.\n• IPS v2 approved on 2026-09-20 following the residential purchase decision [IPS-v2].\n• Principal concern: maintaining adequate liquidity for the house purchase.\n• Portfolio is positioned against the IPS v2 SAA [IPS-v2].\n• Expected S$3.0m deposit within twelve months is ring-fenced in the Liquidity bucket." },
  { n: 2, order: 2, title: "Market view", owner: "pm", gate: "G2", status: "ready", body: "• Macro regime assessed as late expansion [MKT-0142].\n• CIO stance: buy fixed income, hold equities and gold, sell cash [CIO-2026Q4-03].\n• Growth is moderating while corporate earnings remain resilient [MKT-0142].\n• Policy rate reductions are anticipated, supporting duration [MKT-0142].\n• Equity valuations are elevated, which limits the margin of safety for further index gains [CIO-2026Q4-05].\n• Falling cash yields reduce the carry on liquidity held in deposits [CIO-2026Q4-02]." },
  { n: 3, order: 3, title: "Portfolio current health", owner: "pm", gate: "G2", status: "flagged", body: "• Sharpe ratio of 0.82 [CALC-sharpe-v1].\n• Diversification score of 71 [CALC-sharpe-v1].\n• Technology concentration of 31% is elevated and flagged for PM review [HLD-20261013].\n• Microsoft Corp and Apple Inc together account for 26% of the portfolio and move closely in sell-offs [HLD-20261013].\n• Singapore rate-sensitive income holdings total 26% and share exposure to a rise in rates [HLD-20261013].\n• Current weights are within the tactical bands set by IPS v2 for all asset classes [IPS-v2]." },
  { n: 4, order: 4, title: "Old vs new TAA", owner: "pm", gate: "G2", status: "ready", chart: "taa", body: "• Fixed income: increase to 40% (+5 points), at the upper edge of the tactical band [CALC-taa-v1].\n• Equities: reduce to 28% (-5 points from current), reflecting elevated valuations [CIO-2026Q4-05].\n• Cash: reduce to 12% (-1 point from current) as cash yields decline [CIO-2026Q4-02].\n• Hedge funds, private markets, real estate and gold remain at their strategic weights [IPS-v2].\n• Revised TAA is subject to PM approval at G2 [CALC-taa-v1]." },
  { n: 5, order: 6, title: "Product recommendations", owner: "pm", gate: "G3", status: "approved", body: "• Four fixed income products shortlisted by the Portfolio Manager [PRD-FI-007].\n• Shortlist is consistent with the overweight fixed income position [CIO-2026Q4-03].\n• Lead candidate is the SGD Investment Grade Bond Fund, offering diversified credit exposure [PRD-FI-007].\n• Products fit the Longevity bucket and the client Balanced risk profile [IPS-v2].\n• Recommendations are subject to G3 approval [PRD-FI-007]." },
  { n: 6, order: 7, title: "Sign-off", owner: "rm", gate: null, status: "draft", kind: "signoff", body: "• Portfolio Manager sign-off covers the product shortlist, market view and TAA.\n• Relationship Manager sign-off covers client suitability and presentation.\n• Each sign-off is recorded with name, role and timestamp.\n• The pack is released to the client only after all sign-offs are complete." },
  { n: 7, order: 8, title: "Sources and citations", owner: "rm", gate: null, status: "ready", body: "Sources for this pack are listed on the Sources view; every citation tag in the sections above resolves to a registered source." },
  { n: 8, order: 5, title: "Individual holding adjustments", owner: "pm", gate: "G2", status: "draft", chart: "holdings", body: "• Microsoft Corp: 16% to 13% (-3 points), trimmed to ease US large-cap technology concentration [HLD-20261013].\n• Apple Inc: 10% to 8% (-2 points), as it moves closely with Microsoft Corp in sell-offs [HLD-20261013].\n• DBS Group Holdings: 7% to 9% (+2 points) to diversify away from US technology into local financials [CIO-2026Q4-05].\n• Singapore Government Bond 10Y: 22% to 25% (+3 points), supporting the overweight fixed income stance [CALC-taa-v1].\n• All other holdings, including US Treasury Bills 3M and the PIMCO Income Fund, are unchanged, so total weight remains 100% [CALC-taa-v1].\n• All adjustments remain within the IPS v2 tactical bands and are subject to PM approval at G2 [IPS-v2]." },
];

export const citations: Citation[] = [
  { tag: "IPS-v2", what: "Finalised IPS version 2", system: "Client DB, RM", asOf: "2026-09-20", ref: "ips_v2" },
  { tag: "HLD-20261013", what: "Holdings snapshot", system: "Bank portfolio system (read-only)", asOf: "2026-10-13 18:00", ref: "hld_20261013_1800" },
  { tag: "CIO-2026Q4-03", what: "CIO House View, fixed income", system: "UBS CIO House View store", asOf: "2026-10-01", ref: "cio_2026q4, section 3" },
  { tag: "MKT-0142", what: "Market Research Agent case result", system: "Case State", asOf: "2026-10-14", ref: "mkt_0142" },
  { tag: "PRD-FI-007", what: "SGD Investment Grade Bond Fund", system: "Product shelf DB", asOf: "2026-10-10", ref: "prd_fi_007" },
  { tag: "CALC-sharpe-v1", what: "Sharpe ratio, formula and inputs", system: "Analytics Engine", asOf: "2026-10-13", ref: "calc_sharpe_v1" },
];

export const activity: ActivityEvent[] = [
  { id: "a1", at: "2026-10-14 17:05", actor: "RM", role: "rm", text: "Opened quarterly review for Sergio Ermotti" },
  { id: "a2", at: "2026-10-14 11:20", actor: "PM", role: "pm", text: "Approved product list (G3)" },
  { id: "a3", at: "2026-10-14 08:30", actor: "System", role: "system", text: "Notified PM of new CIO House View" },
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
    { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 50_000_000, pct: 10, purpose: "Cash reserve of about S$30m plus a working cushion" },
    { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 300_000_000, pct: 60, purpose: "Capital-preserving core in government and high-grade bonds" },
    { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 150_000_000, pct: 30, purpose: "Long-horizon wealth with modest blue-chip growth" },
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
  jfr: rows(CLS, [20, 50, 15, 0, 0, 5, 10], [19, 51, 15, 0, 0, 5, 10], [20, 50, 15, 0, 0, 5, 10], [20, 50, 15, 0, 0, 5, 10], "IPS-draft"),
  teo: rows(CLS, [8, 20, 45, 8, 6, 6, 7], [6, 18, 48, 8, 7, 6, 7], [8, 20, 45, 8, 6, 6, 7], [7, 19, 47, 8, 6, 6, 7], "IPS-v1"),
  sha: rows(CLS, [12, 38, 25, 6, 2, 8, 9], [12, 40, 24, 6, 2, 7, 9], [12, 39, 24, 6, 2, 8, 9], [11, 40, 25, 6, 2, 7, 9], "IPS-draft"),
};

export const ipsPartsByClient: Record<string, IpsPart[]> = {
  ser: ipsParts,
  dso: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "Preserve capital and draw steady income in retirement. Small bequest to grandchildren." },
    { part: 2, title: "3L buckets and explanation", owner: "pm", status: "filled", body: "Liquidity 20%, Longevity 68%, Legacy 12%." },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Conservative. Risk limit 2 of 5. Risk capacity: Moderately low. Can tolerate a 6% drawdown." },
    { part: 4, title: "Strategic Asset Allocation", owner: "pm", status: "filled", body: "Cash 20, Fixed income 48, Equities 18, Hedge funds 2, Private markets 1, Real estate 5, Gold 6." },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Annual review. Rebalance when drift exceeds 5 points. Benchmark: 20/80 blended index." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
  jfr: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "blank", body: "" },
    { part: 2, title: "3L buckets and explanation", owner: "pm", status: "blank", body: "" },
    { part: 3, title: "Client risk profile", owner: "rm", status: "blank", body: "" },
    { part: 4, title: "Strategic Asset Allocation", owner: "pm", status: "blank", body: "" },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when drift exceeds 5 points." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
  teo: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "Grow wealth over 15+ years, fund children's overseas education, build a legacy." },
    { part: 2, title: "3L buckets and explanation", owner: "pm", status: "filled", body: "Liquidity 10%, Longevity 50%, Legacy 40%." },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Growth. Risk limit 4 of 5. Risk capacity: Moderately high. Can tolerate a 20% drawdown." },
    { part: 4, title: "Strategic Asset Allocation", owner: "pm", status: "filled", body: "Cash 8, Fixed income 20, Equities 45, Hedge funds 8, Private markets 6, Real estate 6, Gold 7." },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when drift exceeds 5 points. Benchmark: 70/30 blended index." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
  sha: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "Buy a condo within 2 years, then build retirement savings steadily." },
    { part: 2, title: "3L buckets and explanation", owner: "pm", status: "blank", body: "" },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "Moderate. Risk limit 3 of 5. Risk capacity: Moderate. Can tolerate a 12% drawdown." },
    { part: 4, title: "Strategic Asset Allocation", owner: "pm", status: "blank", body: "" },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "Quarterly review. Rebalance when drift exceeds 5 points." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "Signed by RM after client confirmation (G1)." },
  ],
};


/** Structured mirror of IPS part 3 (risk capacity, drawdown limit) - what the IPS form would store. */
export const ipsRiskByClient: Record<string, { riskCapacity: string; maxDrawdownPct: number }> = {
  ser: { riskCapacity: "Moderate", maxDrawdownPct: 12 },
  dso: { riskCapacity: "Moderately low", maxDrawdownPct: 6 },
  jfr: { riskCapacity: "High", maxDrawdownPct: 10 },
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
  jfr: { points: gp(500, 0.035, 440, 0.03), events: [{ year: 2031, label: "Family foundation" }, { year: 2044, label: "Retirement" }], yearsOnTrack: 15, summary: "Funds last 15 years beyond the target age under the Conservative plan, with low return variability." },
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

/** Market Researcher seam (cycle phase and events). `views` is filled at runtime from the backend CIO house view. */
export const macroBrief: MacroBrief = {
  phase: "Late expansion", asOf: "2026-10-14",
  events: [
    "US Federal Reserve signals two rate cuts by mid-2027",
    "US core inflation eases to 2.6%, lowest in three years",
    "China adds property support measures, Asia credit spreads tighten",
    "Oil steady near US$78 as supply stays balanced",
  ],
  views: [],
};

