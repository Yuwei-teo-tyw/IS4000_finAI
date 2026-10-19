import type {
  ActivityEvent, AllocationRow, Bucket3L, Client, Gate, Holding, InboxItem, IpsPart,
  MarketView, HouseView, MarketRow, MacroBrief, MeetingNote, PackSection, Product, AllocationGroup, GoalProjection,
} from "../types/arc";

export const clients: Client[] = [
  { id: "jdi", name: "Jamie Dimon", riskCategory: "Aggressive", riskCap: 5, aumSgd: 3_600_000, nextMeeting: "2026-10-30", nextQuarterlyReview: null, status: "Onboarding Phase", ipsVersion: null, sharpe: 0.70, diversificationScore: 68 },
  { id: "jfr", name: "Jane Fraser", riskCategory: "Balanced", riskCap: 3, aumSgd: 5_000_000, nextMeeting: "2026-10-21", nextQuarterlyReview: "2026-10-28", status: "Monitoring Phase", ipsVersion: 2, sharpe: 0.82, diversificationScore: 71 },
  { id: "dso", name: "David Solomon", riskCategory: "Conservative", riskCap: 1, aumSgd: 2_800_000, nextMeeting: "2026-11-03", nextQuarterlyReview: null, status: "Onboarding Phase", ipsVersion: null, sharpe: 0.61, diversificationScore: 64 },
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
const correlationByClass: number[][] = [
  [1.0, 0.25, 0.05, 0.1, 0.0, 0.05, 0.02],
  [0.25, 1.0, 0.35, 0.3, 0.2, 0.45, 0.3],
  [0.05, 0.35, 1.0, 0.7, 0.65, 0.6, 0.1],
  [0.1, 0.3, 0.7, 1.0, 0.55, 0.45, 0.12],
  [0.0, 0.2, 0.65, 0.55, 1.0, 0.5, 0.05],
  [0.05, 0.45, 0.6, 0.45, 0.5, 1.0, 0.08],
  [0.02, 0.3, 0.1, 0.12, 0.05, 0.08, 1.0],
];


/* ---------- Per-client variants (jfr = base data above/below) ---------- */
const mkHoldings = (aum: number, w: number[], ytd: number[]): Holding[] =>
  holdings.map((h, i) => ({ ...h, weightPct: w[i], valueSgd: Math.round((aum * w[i]) / 100), returnYtdPct: ytd[i] }));

export const holdingsByClient: Record<string, Holding[]> = {
  jfr: holdings,
  dso: mkHoldings(2_800_000, [20, 30, 20, 4, 3, 8, 2, 1, 5, 7], [2.9, 3.4, 4.1, 14.2, 12.7, 6.3, 5.1, 8.8, 3.0, 18.5]),
  jdi: mkHoldings(3_600_000, [12, 28, 18, 10, 8, 6, 4, 2, 6, 6], [2.9, 3.4, 4.1, 14.2, 12.7, 6.3, 5.1, 8.8, 3.0, 18.5]),
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
  { assetClass: "Cash", saa: 15, current: 13, oldTaa: 14, newTaa: 12, band: 5, reason: "• Cash is held below the strategic weight because the cash yield is declining [CIO-2026Q4-02].\n• CIO stance on cash is Sell for the current quarter [CIO-2026Q4-02].\n• Policy rate reductions are anticipated, lowering returns on deposits [MKT-0142].\n• The S$3.0m house deposit stays in the Liquidity bucket, so core liquidity is retained [NOTE-2026-09-12].\n• The 12% target remains inside the tactical band around the 15% SAA [IPS-v2]." },
  { assetClass: "Fixed income", saa: 35, current: 36, oldTaa: 33, newTaa: 40, band: 5, reason: "• Fixed income is held above the strategic weight in line with the CIO Buy view [CIO-2026Q4-03].\n• Anticipated rate reductions support bond prices and duration [MKT-0142].\n• Investment grade yields offer attractive income for the Longevity bucket [CIO-2026Q4-03].\n• The 40% target sits at the upper edge of the tactical band around the 35% SAA [IPS-v2].\n• Overweight is funded from equities and cash, keeping total risk within the Balanced profile [CALC-taa-v1]." },
  { assetClass: "Equities", saa: 30, current: 33, oldTaa: 33, newTaa: 28, band: 5, reason: "• Equities are held below the strategic weight because valuations are elevated [CIO-2026Q4-05].\n• CIO stance on equities is Hold, with no case to add exposure [CIO-2026Q4-05].\n• Growth is moderating in a late-expansion regime [MKT-0142].\n• Technology concentration of 31% is flagged for IC review [HLD-20261013].\n• The 28% target remains inside the tactical band around the 30% SAA [IPS-v2]." },
  { assetClass: "Hedge funds", saa: 5, current: 5, oldTaa: 5, newTaa: 5, band: 5, reason: "• Held at the strategic weight, within the tactical band [IPS-v2].\n• No CIO House View change requires a tactical move for this asset class [CIO-2026Q4-03].\n• The current weight is within the 5-point band around the SAA [IPS-v2].\n• Holding avoids transaction cost and keeps the portfolio aligned to the IPS [CALC-taa-v1].\n• The position will be reviewed at the next quarterly review [IPS-v2]." },
  { assetClass: "Private markets", saa: 3, current: 3, oldTaa: 3, newTaa: 3, band: 5, reason: "• Held at the strategic weight, within the tactical band [IPS-v2].\n• No CIO House View change requires a tactical move for this asset class [CIO-2026Q4-03].\n• The current weight is within the 5-point band around the SAA [IPS-v2].\n• Holding avoids transaction cost and keeps the portfolio aligned to the IPS [CALC-taa-v1].\n• The position will be reviewed at the next quarterly review [IPS-v2]." },
  { assetClass: "Real estate", saa: 5, current: 4, oldTaa: 5, newTaa: 5, band: 5, reason: "• Held at the strategic weight, within the tactical band [IPS-v2].\n• No CIO House View change requires a tactical move for this asset class [CIO-2026Q4-03].\n• The current weight is within the 5-point band around the SAA [IPS-v2].\n• Holding avoids transaction cost and keeps the portfolio aligned to the IPS [CALC-taa-v1].\n• The position will be reviewed at the next quarterly review [IPS-v2]." },
  { assetClass: "Gold", saa: 7, current: 6, oldTaa: 7, newTaa: 7, band: 5, reason: "• Gold is held at the strategic weight in line with the CIO Hold view [CIO-2026Q4-09].\n• Gold provides diversification against equity drawdowns [CIO-2026Q4-09].\n• Falling policy rates reduce the opportunity cost of holding gold [MKT-0142].\n• The current 6% weight is 1 point below the 7% SAA and within the tactical band [IPS-v2].\n• No tactical change is proposed, avoiding unnecessary trading cost [CALC-taa-v1]." },
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
  { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "• Primary objective: acquisition of a S$15m residence within 12 months, requiring a S$3.0m deposit.\n• Secondary objective: retention of lifetime income through retirement.\n• Tertiary objective: provision of a legacy for two children." },
  { part: 2, title: "3L buckets and explanation", owner: "ic", status: "filled", body: "• Liquidity bucket: 70% of investable assets, earmarked for the near-term deposit.\n• Longevity bucket: 20%, supporting long-term retirement income.\n• Legacy bucket: 10%, reserved for intergenerational transfer.\n• Bucket weights prioritise the 12-month liquidity requirement while preserving income capacity." },
  { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "• Risk profile: Balanced, with a risk limit of 3 on a 5-point scale.\n• Loss tolerance: maximum drawdown of approximately 12%.\n• Liquidity requirement: high over the next 12 months." },
  { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "filled", body: "• Cash 15%, Fixed income 35%, Equities 30%.\n• Hedge funds 5%, Private markets 3%, Real estate 5%, Gold 7%.\n• Tactical deviations are permitted within a band of 5 points around each SAA weight." },
  { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "• Portfolio review frequency: quarterly.\n• Rebalancing trigger: drift of more than 5 points from SAA in any asset class.\n• Reference benchmark: 40/60 blended index." },
  { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "• Executed by the Relationship Manager following client confirmation (G1).\n• Effective only upon recorded client acknowledgement." },
];

export const meetingNotes: MeetingNote[] = [
  { id: "note_0318", sourceFile: "2026-09-12-house-purchase-meeting.pdf", originalText: "Meeting with Jane Fraser, 12 September 2026. Attendees: Jane Fraser, Isabel (RM).\n\nJane opened by explaining that she and her family have found a house they want to buy, at about S$15m. She expects to pay a deposit of S$3.0m within the next twelve months and would like to fund it without disturbing the part of the portfolio that supports her retirement income.\n\nI asked how firm the timeline is. She said the sellers are flexible but she does not want to be rushed into selling investments in a weak market. She repeated that volatility worries him more than it did a year ago, and that she would prefer to hold more in cash and short-dated bonds until the deposit is paid.\n\nWe agreed that the Liquidity bucket in the IPS should be enlarged, and that the IPS should be updated to version 2. Isabel will confirm the deposit date with her and send the draft to the Investment Counsellor for the revised allocation.", clientId: "jfr", date: "2026-09-12", title: "House purchase meeting", summary: ["Plans to buy a S$15m house", "Needs S$3.0m deposit within 12 months", "Wants to keep retirement income intact", "Concerned about market volatility", "Prefers cash and short-dated bonds until the deposit is paid"], checklist: [{ text: "Confirm deposit date with client", done: true }, { text: "Review liquidity bucket", done: false }, { text: "Send IPS v2 draft to IC", done: false }] },
  { id: "note_0421", sourceFile: "2026-10-12-first-meeting.pdf", originalText: "First meeting with David Solomon, 12 October 2026. Attendees: David Solomon, Isabel (RM).\n\nDavid said his priorities are steady income and keeping his capital safe. He is considering retiring about two years earlier than planned, though no date has been fixed.\n\nWhen we discussed risk, he said a fall of more than 10% in a single year would make him uncomfortable and likely prompt him to sell. He holds a bond-heavy portfolio transferred from another bank and would like it reviewed.\n\nNext steps: confirm the retirement date, complete the risk questionnaire, then send the IPS draft to the Investment Counsellor for the 3L and SAA.", clientId: "dso", date: "2026-10-12", title: "First meeting", summary: ["Wants steady income and capital kept safe", "May retire about two years early", "Would be uncomfortable with a fall of more than 10% in a year", "Bond-heavy portfolio transferred from another bank", "Retirement date not yet fixed"], checklist: [{ text: "Run the risk questionnaire", done: true }, { text: "Confirm retirement date", done: false }, { text: "Send IPS draft to IC", done: false }] },
  { id: "note_0715", sourceFile: "2026-10-09-first-meeting.pdf", originalText: "First meeting with Jamie Dimon, 9 October 2026. Attendees: Jamie Dimon, Isabel (RM).\n\nJamie would like to buy a condominium within two years. He has a moderate appetite for risk but dislikes large drops in value, especially as the purchase date gets closer. He saves roughly S$8k a month.\n\nOpen question: he has not decided on the expected price of the condo. Isabel will confirm his budget, then send the IPS draft to the Investment Counsellor. The risk questionnaire was completed during the meeting.", clientId: "jdi", date: "2026-10-09", title: "First meeting", summary: ["Wants to buy a condo within 2 years", "Moderate risk appetite, dislikes large drops", "Saves roughly S$8k a month", "Open question: expected condo price not stated", "Risk questionnaire completed in the meeting"], checklist: [{ text: "Run the risk questionnaire", done: true }, { text: "Confirm condo budget", done: false }, { text: "Send IPS draft to IC", done: false }] },
];

export const gates: Gate[] = [
  { id: "G1", label: "IPS approval", approver: "rm", state: "approved", approvedAt: "2026-09-20" },
  { id: "G3", label: "Product list", approver: "ps", state: "approved", approvedAt: "2026-10-14 11:20" },
  { id: "G2", label: "TAA and sections 2–4", approver: "ic", state: "pending" },
  { id: "G4", label: "Final pack and PDF", approver: "rm", state: "not_started" },
];

/** Seed requests per role: 2 Onboarding clients (jdi, dso) + 1 Monitoring client (jfr, quarterly review). */
export const inboxes: Record<"ic" | "ps", InboxItem[]> = {
  ic: [
    { id: "ic-jfr", clientId: "jfr", clientName: "Jane Fraser", kind: "Quarterly review: new TAA and sections 2-4", from: "rm", receivedAt: "2026-10-14 17:05", summary: "Quarterly review opened; revise the TAA against the new CIO House View.", priority: "high", trigger: 2 },
    { id: "ic-jdi", clientId: "jdi", clientName: "Jamie Dimon", kind: "Onboarding: fill 3L and SAA", from: "rm", receivedAt: "2026-10-15 09:30", summary: "Onboarding IPS draft sent; parts 2 and 4 await the Investment Counsellor.", priority: "normal", trigger: 1 },
    { id: "ic-dso", clientId: "dso", clientName: "David Solomon", kind: "Onboarding: fill 3L and SAA", from: "rm", receivedAt: "2026-10-16 10:15", summary: "Onboarding IPS draft sent; parts 2 and 4 await the Investment Counsellor.", priority: "normal", trigger: 1 },
  ],
  ps: [
    { id: "ps-jfr", clientId: "jfr", clientName: "Jane Fraser", kind: "Quarterly review: product list", from: "rm", receivedAt: "2026-10-14 11:00", summary: "Shortlist products for the revised TAA before the 28 Oct quarterly review.", priority: "high", trigger: 2 },
    { id: "ps-jdi", clientId: "jdi", clientName: "Jamie Dimon", kind: "Onboarding: initial product list", from: "rm", receivedAt: "2026-10-15 14:00", summary: "Initial product review for the onboarding IPS.", priority: "normal", trigger: 1 },
    { id: "ps-dso", clientId: "dso", clientName: "David Solomon", kind: "Onboarding: initial product list", from: "rm", receivedAt: "2026-10-16 11:30", summary: "Initial product review for the onboarding IPS.", priority: "normal", trigger: 1 },
  ],
};

export const marketCycle = { phase: "Late expansion", tag: "MKT-0142", asOf: "2026-10-14" };
export const marketViews: MarketView[] = [
  { assetClass: "Fixed income", view: "Buy", explanation: "Growth is slowing, so rates are likely to fall. High-grade bonds lock in today's yield.", confidence: "High", tags: ["CIO-2026Q4-03", "MKT-0142"] },
  { assetClass: "Equities", view: "Hold", explanation: "Profits are solid but prices are high for late expansion.", confidence: "Medium", tags: ["CIO-2026Q4-05", "MKT-0142"] },
  { assetClass: "Cash", view: "Sell", explanation: "Cash yields fall when rate cuts come.", confidence: "Medium", tags: ["CIO-2026Q4-02"] },
  { assetClass: "Gold", view: "Hold", explanation: "Supports the portfolio if growth surprises on the downside.", confidence: "Medium", tags: ["CIO-2026Q4-09"] },
];

const baseProducts: Product[] = [
  { id: "PRD-FI-007", name: "SGD Investment Grade Bond Fund", assetClass: "Fixed income", whyBuy: "Fits the Buy view on fixed income. Rated 2 of 5 for risk, below Jane Fraser's limit of 3. Daily dealing fits the Liquidity bucket.", feePct: 0.55, stars: 5, suitability: "Inside risk limit, fits Liquidity bucket", riskRating: 2, tags: ["MKT-0142", "IPS-v2"] },
  { id: "PRD-FI-011", name: "BlackRock iShares Core Global Aggregate Bond ETF", assetClass: "Fixed income", whyBuy: "Wide mix of bonds lowers single-issuer risk.", feePct: 0.2, stars: 4, suitability: "Fits Longevity bucket, small currency risk", riskRating: 2, tags: ["CIO-2026Q4-03"] },
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
  { id: "PRD-FI-020", name: "PIMCO Balanced Income Fund", assetClass: "Fixed income", whyBuy: "Investment-grade credit income with a modest equity sleeve.", feePct: 0.85, stars: 4, suitability: "Inside risk limit, income focus", riskRating: 2, tags: ["CIO-2026Q4-03"] },
  { id: "PRD-EQ-035", name: "Global Quality Equity Fund", assetClass: "Equities", whyBuy: "Quality-screened global shares with resilient earnings.", feePct: 0.9, stars: 4, suitability: "Core growth holding, tech-concentrated", riskRating: 3, tags: ["CIO-2026Q4-05"] },
  { id: "PRD-RE-048", name: "Asia Infrastructure Income Fund", assetClass: "Real estate", whyBuy: "Stable income from infrastructure and real assets across Asia.", feePct: 1.0, stars: 3, suitability: "Income with inflation link, moderate liquidity", riskRating: 3, tags: ["MKT-0142"] },
  { id: "PRD-SP-058", name: "Equity-Linked Note on DBS Group", assetClass: "Structured products", whyBuy: "Fixed coupon with equity-linked downside at a 90% strike.", feePct: 0.8, stars: 2, suitability: "6-month term, capital at risk below strike, issuer credit risk", riskRating: 4, tags: ["MKT-0142"] },
];

const BUCKET_FIT: Record<string, string> = {
  "Cash": "Liquidity bucket (0-2 years), supporting the S$3.0m house deposit",
  "Fixed income": "Liquidity and Longevity buckets, supporting deposit funding and retirement income",
  "Equities": "Longevity bucket (3-15 years), supporting long-term growth",
  "Hedge funds": "Longevity bucket as a satellite diversifier",
  "Private markets": "Legacy bucket only, given the multi-year lock-up",
  "Real estate": "Longevity bucket, providing income with an inflation link",
  "Gold": "Longevity bucket as a portfolio hedge",
  "Structured products": "Longevity bucket as a limited, defined-payoff satellite",
};
const LIQ: Record<string, string> = {
  "Cash": "Daily dealing; no lock-up or redemption gate",
  "Fixed income": "Daily or T+2 dealing; no lock-up",
  "Equities": "Daily dealing at NAV or exchange liquidity",
  "Hedge funds": "Periodic dealing with notice period; limited daily liquidity",
  "Private markets": "Illiquid with a multi-year lock-up and no secondary market assured",
  "Real estate": "Listed vehicle; daily trading subject to market depth",
  "Gold": "Exchange-traded; daily liquidity",
  "Structured products": "Held to term; secondary pricing is indicative and issuer-dependent",
};
const CONC: Record<string, string> = {
  "Cash": "Adds no concentration; reduces portfolio volatility",
  "Fixed income": "Improves diversification away from the existing equity-heavy holdings",
  "Equities": "Moderate equity beta; monitor technology sector weight against the SAA band",
  "Hedge funds": "Low correlation to equities; improves diversification",
  "Private markets": "Adds illiquid exposure; position size must stay within the Legacy bucket",
  "Real estate": "Adds Asia property exposure; moderate correlation to equities",
  "Gold": "Low correlation to equities and bonds; improves diversification",
  "Structured products": "Adds issuer credit concentration; size conservatively",
};
function psReasonFor(p: Product): string {
  const tag = p.tags[0] ?? "MKT-0142";
  const fit = p.riskRating <= 3 ? `within the client limit of 3 (headroom ${3 - p.riskRating})` : `above the client limit of 3 by ${p.riskRating - 3}; escalation to the Investment Counsellor required before inclusion`;
  return [
    `• Suitability: ${p.name} is consistent with the Balanced mandate for Jane Fraser; ${p.suitability.charAt(0).toLowerCase()}${p.suitability.slice(1)} [IPS-v2].`,
    `• Risk fit: product risk rating ${p.riskRating} of 5 is ${fit} [${p.id}].`,
    `• 3L bucket fit: ${BUCKET_FIT[p.assetClass] ?? "Longevity bucket"} [IPS-v2].`,
    `• Liquidity and fees: ${LIQ[p.assetClass] ?? "Standard dealing terms"}; ongoing charge ${p.feePct.toFixed(2)}% p.a., disclosed in full and not used to rank suitability [${p.id}].`,
    `• Concentration and diversification: ${CONC[p.assetClass] ?? "Neutral impact on diversification"} [${tag}].`,
    `• Rationale: ${p.whyBuy} Subject to G3 approval by the Product Specialist [${tag}].`,
  ].join("\n");
}
export const products: Product[] = baseProducts.map((p) => ({ ...p, psReason: psReasonFor(p) }));

export const packSections: PackSection[] = [
  { n: 1, order: 1, title: "Latest Client's Profile + Goals + Concerns", owner: "rm", gate: "G4", status: "draft", chart: "saa", body: "• Client: Jane Fraser; investable assets of S$5.0m; Balanced risk profile.\n• IPS v2 approved on 2026-09-20 following the residential purchase decision [NOTE-2026-09-12] [IPS-v2].\n• Principal concern: maintaining adequate liquidity for the house purchase [NOTE-2026-09-12].\n• Portfolio is positioned against the IPS v2 SAA [IPS-v2].\n• Expected S$3.0m deposit within twelve months is ring-fenced in the Liquidity bucket [NOTE-2026-09-12]." },
  { n: 2, order: 2, title: "Market view", owner: "ic", gate: "G2", status: "ready", body: "• Macro regime assessed as late expansion [MKT-0142].\n• CIO stance: buy fixed income, hold equities and gold, sell cash [CIO-2026Q4-03].\n• Growth is moderating while corporate earnings remain resilient [MKT-0142].\n• Policy rate reductions are anticipated, supporting duration [MKT-0142].\n• Equity valuations are elevated, which limits the margin of safety for further index gains [CIO-2026Q4-05].\n• Falling cash yields reduce the carry on liquidity held in deposits [CIO-2026Q4-02]." },
  { n: 3, order: 3, title: "Portfolio current health", owner: "ic", gate: "G2", status: "flagged", body: "• Sharpe ratio of 0.82 [CALC-sharpe-v1].\n• Diversification score of 71 [CALC-sharpe-v1].\n• Technology concentration of 31% is elevated and flagged for IC review [HLD-20261013].\n• Microsoft Corp and Apple Inc together account for 26% of the portfolio and move closely in sell-offs [HLD-20261013].\n• Singapore rate-sensitive income holdings total 26% and share exposure to a rise in rates [HLD-20261013].\n• Current weights are within the tactical bands set by IPS v2 for all asset classes [IPS-v2]." },
  { n: 4, order: 4, title: "Old vs new TAA", owner: "ic", gate: "G2", status: "ready", chart: "taa", body: "• Fixed income: increase to 40% (+5 points), at the upper edge of the tactical band [CALC-taa-v1].\n• Equities: reduce to 28% (-5 points from current), reflecting elevated valuations [CIO-2026Q4-05].\n• Cash: reduce to 12% (-1 point from current) as cash yields decline [CIO-2026Q4-02].\n• Hedge funds, private markets, real estate and gold remain at their strategic weights [IPS-v2].\n• Revised TAA is subject to IC approval at G2 [CALC-taa-v1]." },
  { n: 5, order: 6, title: "Product recommendations", owner: "ps", gate: "G3", status: "approved", body: "• Four fixed income products shortlisted by Product Specialist [PRD-FI-007].\n• Shortlist is consistent with the overweight fixed income position [CIO-2026Q4-03].\n• Lead candidate is the SGD Investment Grade Bond Fund, offering diversified credit exposure [PRD-FI-007].\n• Products fit the Longevity bucket and the client Balanced risk profile [IPS-v2].\n• Recommendations are subject to G3 approval [PRD-FI-007]." },
  { n: 6, order: 7, title: "Sign-off", owner: "rm", gate: null, status: "draft", kind: "signoff", body: "• Product Specialist sign-off covers the product shortlist.\n• Investment Committee sign-off covers market view and TAA.\n• Relationship Manager sign-off covers client suitability and presentation.\n• Each sign-off is recorded with name, role and timestamp.\n• The pack is released to the client only after all sign-offs are complete." },
  { n: 7, order: 8, title: "Sources and citations", owner: "rm", gate: null, status: "ready", body: "Sources for this pack are listed on the Sources view; every citation tag in the sections above resolves to a registered source." },
  { n: 8, order: 5, title: "Individual holding adjustments", owner: "ic", gate: "G2", status: "draft", chart: "holdings", body: "• Microsoft Corp: 16% to 13% (-3 points), trimmed to ease US large-cap technology concentration [HLD-20261013].\n• Apple Inc: 10% to 8% (-2 points), as it moves closely with Microsoft Corp in sell-offs [HLD-20261013].\n• DBS Group Holdings: 7% to 9% (+2 points) to diversify away from US technology into local financials [CIO-2026Q4-05].\n• Singapore Government Bond 10Y: 22% to 25% (+3 points), supporting the overweight fixed income stance [CALC-taa-v1].\n• All other holdings, including US Treasury Bills 3M and the PIMCO Income Fund, are unchanged, so total weight remains 100% [CALC-taa-v1].\n• All adjustments remain within the IPS v2 tactical bands and are subject to IC approval at G2 [IPS-v2]." },
];

export const activity: ActivityEvent[] = [
  { id: "a1", at: "2026-10-14 17:05", actor: "RM", role: "rm", text: "Opened quarterly review for Jane Fraser" },
  { id: "a2", at: "2026-10-14 11:20", actor: "PS", role: "ps", text: "Approved product list (G3) and sent to IC" },
  { id: "a3", at: "2026-10-14 08:30", actor: "System", role: "system", text: "Notified PS of new CIO House View" },
  { id: "a4", at: "2026-09-20 10:00", actor: "RM", role: "rm", text: "Approved IPS v2 (G1)" },
];

/* ---------- Per-client 3L, allocation, IPS ---------- */
export const buckets3LByClient: Record<string, Bucket3L[]> = {
  jfr: buckets3L,
  dso: [
    { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 560_000, pct: 20, purpose: "Three years of living costs and medical cushion" },
    { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 1_900_000, pct: 68, purpose: "Stable income for retirement, possibly brought forward" },
    { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 340_000, pct: 12, purpose: "Modest bequest to grandchildren" },
  ],
  jdi: [
    { id: "liquidity", name: "Liquidity", horizon: "0–3 years", amountSgd: 1_080_000, pct: 30, purpose: "Condo down payment and emergency fund" },
    { id: "longevity", name: "Longevity", horizon: "Lifetime income", amountSgd: 1_620_000, pct: 45, purpose: "Retirement savings" },
    { id: "legacy", name: "Legacy", horizon: "Beyond lifetime", amountSgd: 900_000, pct: 25, purpose: "Support for parents and future family" },
  ],
};

const rows = (cls: AllocationRow["assetClass"][], saa: number[], cur: number[], oldT: number[], newT: number[], tag: string): AllocationRow[] =>
  cls.map((assetClass, i) => ({ assetClass, saa: saa[i], current: cur[i], oldTaa: oldT[i], newTaa: newT[i], band: 5, reason: [`Positioned in line with the client IPS [${tag}].`, `Current weight is ${cur[i]}% against a strategic weight of ${saa[i]}% [${tag}].`, `Proposed weight is ${newT[i]}%, a move of ${newT[i] - oldT[i] >= 0 ? "+" : ""}${newT[i] - oldT[i]} points from the prior TAA [CALC-taa-v1].`, "The proposal stays within the 5-point tactical band around the SAA [" + tag + "].", "The proposal is consistent with the CIO House View for the quarter [CIO-2026Q4-03]."].map((t) => "• " + t).join("\n") }));
const CLS = assetClassOrder as unknown as AllocationRow["assetClass"][];
export const allocationByClient: Record<string, AllocationRow[]> = {
  jfr: allocation,
  dso: rows(CLS, [20, 48, 18, 2, 1, 5, 6], [20, 50, 15, 2, 1, 5, 7], [20, 49, 16, 2, 1, 5, 7], [18, 52, 15, 2, 1, 5, 7], "IPS-draft"),
  jdi: rows(CLS, [12, 38, 25, 6, 2, 8, 9], [12, 40, 24, 6, 2, 7, 9], [12, 39, 24, 6, 2, 8, 9], [11, 40, 25, 6, 2, 7, 9], "IPS-draft"),
};

export const ipsPartsByClient: Record<string, IpsPart[]> = {
  jfr: ipsParts,
  dso: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "• Primary objective: capital preservation.\n• Secondary objective: steady income drawdown throughout retirement.\n• Tertiary objective: modest bequest to grandchildren." },
    { part: 2, title: "3L buckets and explanation", owner: "ic", status: "blank", body: "" },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "• Risk profile: Conservative, with a risk limit of 1 on a 5-point scale.\n• Loss tolerance: maximum drawdown of approximately 6%." },
    { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "blank", body: "" },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "• Portfolio review frequency: quarterly.\n• Rebalancing trigger: drift exceeding 5 points from SAA." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "• Executed by the Relationship Manager following client confirmation (G1).\n• Effective only upon recorded client acknowledgement." },
  ],
  jdi: [
    { part: 1, title: "Client goals and objectives", owner: "rm", status: "filled", body: "• Primary objective: acquisition of a condominium within 2 years.\n• Secondary objective: steady accumulation of retirement savings thereafter." },
    { part: 2, title: "3L buckets and explanation", owner: "ic", status: "blank", body: "" },
    { part: 3, title: "Client risk profile", owner: "rm", status: "filled", body: "• Risk profile: Moderate, with a risk limit of 3 on a 5-point scale.\n• Loss tolerance: maximum drawdown of approximately 12%." },
    { part: 4, title: "Strategic Asset Allocation", owner: "ic", status: "blank", body: "" },
    { part: 5, title: "Review rules", owner: "rm", status: "locked", body: "• Portfolio review frequency: quarterly.\n• Rebalancing trigger: drift exceeding 5 points from SAA." },
    { part: 6, title: "Signature line", owner: "rm", status: "locked", body: "• Executed by the Relationship Manager following client confirmation (G1).\n• Effective only upon recorded client acknowledgement." },
  ],
};


const gp = (start: number, grow: number, req0: number, reqGrow: number) =>
  Array.from({ length: 35 }, (_, i) => ({
    year: 2026 + i,
    projected: +(start * Math.pow(1 + grow, i)).toFixed(2),
    required: +(req0 * Math.pow(1 + reqGrow, i)).toFixed(2),
  }));

export const goalProjectionByClient: Record<string, GoalProjection> = {
  jfr: { points: gp(5, 0.052, 4.6, 0.05), events: [{ year: 2027, label: "House deposit" }, { year: 2034, label: "Child's education" }, { year: 2042, label: "Retirement" }], yearsOnTrack: 6, summary: "Funds last 6 years beyond the target age under the current Balanced plan." },
  dso: { points: gp(2.8, 0.036, 2.6, 0.035), events: [{ year: 2029, label: "Retirement" }, { year: 2045, label: "Legacy gift" }], yearsOnTrack: 4, summary: "Funds last 4 years beyond the target age; a small buffer on a conservative path." },
  jdi: { points: gp(3.6, 0.055, 3.3, 0.052), events: [{ year: 2028, label: "Condo down payment" }, { year: 2050, label: "Retirement" }], yearsOnTrack: 5, summary: "Funds last 5 years beyond the target age under the Moderate plan." },
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
  { aliases: ["pimco"], row: { assetClass: "Fixed income", product: "PIMCO Balanced Income Fund", industryFocus: "Investment-grade credit with an equity sleeve", top5: ["US Treasury 10Y", "SGS 10Y Bond", "Microsoft Corp bond", "Apple Inc bond", "DBS Group bond"], confidencePct: 96,
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
