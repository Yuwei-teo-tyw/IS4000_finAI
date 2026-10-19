export type Role = "rm" | "ic" | "ps";
export const ROLE_LABEL: Record<Role, string> = {
  rm: "Relationship Manager",
  ic: "Investment Counsellor",
  ps: "Product Specialist",
};

export type GateId = "G1" | "G2" | "G3" | "G4";
export type GateState = "not_started" | "pending" | "approved" | "reset";
export interface Gate { id: GateId; label: string; approver: Role; state: GateState; approvedAt?: string }

export type RiskCategory = "Conservative" | "Moderate" | "Balanced" | "Growth" | "Aggressive";
export type ClientStatus = "Onboarding Phase" | "Monitoring Phase";

export interface Client {
  id: string; name: string; riskCategory: RiskCategory; riskCap: number; aumSgd: number;
  nextMeeting: string; nextQuarterlyReview: string | null; status: ClientStatus; ipsVersion: number | null;
  sharpe: number; diversificationScore: number;
}

export interface Holding {
  id: string; name: string; ticker?: string; assetClass: AssetClass; valueSgd: number; weightPct: number; returnYtdPct: number;
}
export type AssetClass = "Cash" | "Fixed income" | "Equities" | "Hedge funds" | "Private markets" | "Real estate" | "Gold";

export interface Bucket3L { id: "liquidity" | "longevity" | "legacy"; name: string; horizon: string; amountSgd: number; pct: number; purpose: string }
export interface AllocationRow { assetClass: AssetClass; saa: number; current: number; oldTaa: number; newTaa: number; band: number; reason: string }

export interface IpsPart { part: 1 | 2 | 3 | 4 | 5 | 6; title: string; owner: Role; status: "filled" | "blank" | "locked"; body: string }

export interface InboxItem {
  id: string; clientId: string; clientName: string; kind: string; from: Role; receivedAt: string;
  summary: string; priority: "normal" | "high"; trigger: 1 | 2 | 3;
}

export interface MarketView { assetClass: AssetClass; view: "Buy" | "Hold" | "Sell"; explanation: string; confidence: "High" | "Medium" | "Low"; tags: string[] }
export type ProductClass = AssetClass | "Structured products";
export interface Product { id: string; name: string; assetClass: ProductClass; whyBuy: string; feePct: number; stars: number; suitability: string; riskRating: number; tags: string[];
  /** Professional PS rationale, "• ... [TAG]" bullets (>=5). Seeded for client jfr. */
  psReason?: string }

export interface PackSection { n: number; title: string; owner: Role; gate: GateId | null; status: "draft" | "ready" | "flagged" | "approved"; body: string;
  /** Chart placeholder the compiled document renders beside this section's text. */
  chart?: "saa" | "taa" | "holdings"; kind?: "signoff";
  /** Display position (ascending). Defaults to n when absent. n stays stable as the section id. */
  order?: number }
export interface Citation { tag: string; what: string; system: string; asOf: string; ref: string }
export interface ActivityEvent { id: string; at: string; actor: string; role: Role | "system"; text: string }
export interface MeetingNote { id: string; clientId: string; date: string; title: string; sourceFile: string; originalText: string; summary: string[]; checklist: { text: string; done: boolean }[] }

export interface CorrelationMatrix { labels: string[]; matrix: number[][] }
export interface AllocationGroup { label: string; value: number; color: "chart-equities" | "chart-bonds" | "chart-alternatives" | "chart-liquidity" }
export interface CaseStep { who: string; what: string; by: string; state: "done" | "waiting" | "not_started" }

export interface IpsVersion { version: number; issuedOn: string; status: "Active" | "Superseded" | "Draft"; author: string; summary: string; parts: IpsPart[] }

export interface GoalProjection {
  points: { year: number; projected: number; required: number }[];
  events: { year: number; label: string }[];
  yearsOnTrack: number;
  summary: string;
}

export interface HouseView { id: string; month: string; issuedOn: string; author: string; file: string | null }

export interface MarketRow { assetClass: string; product: string; industryFocus: string; top5: string[]; confidencePct: number; ranking: string[] }
export interface MacroView { assetClass: string; view: "Buy" | "Hold" | "Sell"; industry: string; direction: "Up" | "Flat" | "Down"; note: string }
export interface MacroBrief { phase: string; asOf: string; events: string[]; views: MacroView[] }
/** One chat turn. `steps` (agents fired, thinking) show only while thinking, never in the final answer. */
export interface SectionDraft { section: number; title: string; text: string }
export interface MarketAnswer { summary: string; draft?: SectionDraft; market: MacroBrief | null; rows: MarketRow[]; autoTick: boolean; steps: string[]; tags: string[] }

/** Input for the backend Jinja template that renders the compiled review pack (see backend app/reports). */
export interface PackRenderInput {
  doc: { title: string; clientName: string; version: string; date: string };
  sections: { n: number; title: string; ownerLabel: string; complete: boolean; text: string; wide?: boolean; chart?: "saa" | "taa"; kind?: "signoff" }[];
  allocation: AllocationRow[];
  signatures: Record<string, { name: string; dataUrl: string; signedAt: string }>;
}

/** Block-based pack section content. Charts/tables are LIVE references resolved at render time; `snapshot` optionally freezes chart values. */
export type PackBlock = { id: string } & (
  | { type: "text"; text: string }
  | { type: "image"; src: string; alt: string; caption?: string }
  | { type: "chart"; chart: "saa" | "taa" | "holdings" | "allocation"; clientId?: string; caption?: string; snapshot?: { label: string; value: number }[] }
  | { type: "table"; table: "taa" | "holdings"; caption?: string }
);
