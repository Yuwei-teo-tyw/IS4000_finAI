export type Role = "rm" | "pm" | "ps";
export const ROLE_LABEL: Record<Role, string> = {
  rm: "Relationship Manager",
  pm: "Portfolio Manager",
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
export interface Product { id: string; name: string; assetClass: ProductClass; whyBuy: string; /** Management fee, for information only; null when the shelf has no fee data. */ feePct: number | null; stars: number; suitability: string; riskRating: number; tags: string[] }

export interface PackSection { n: number; title: string; owner: Role; gate: GateId | null; status: "draft" | "ready" | "flagged" | "approved"; body: string;
  /** Chart placeholder the compiled document renders beside this section's text. */
  chart?: "saa" | "taa" | "holdings"; kind?: "signoff";
  /** Display position (ascending). Defaults to n when absent. n stays stable as the section id. */
  order?: number }
export interface Citation { tag: string; what: string; system: string; asOf: string; ref: string }
export interface ActivityEvent { id: string; at: string; actor: string; role: Role | "system"; text: string }
/** Search-index state reported by the backend after a note upload or edit (chunks is null for the JSON store). */
export interface NoteIndexing { status: "indexed" | "pending"; chunks: number | null; message: string }
export interface MeetingNote { indexing?: NoteIndexing; id: string; clientId: string; clientName?: string; date: string; title: string; sourceFile: string; originalText: string; summary: string[]; checklist: { text: string; done: boolean }[] }

export interface CorrelationMatrix { labels: string[]; matrix: number[][] }
export interface AllocationGroup { label: string; value: number; color: "chart-equities" | "chart-bonds" | "chart-alternatives" | "chart-liquidity" }
export interface CaseStep { who: string; what: string; by: string; state: "done" | "waiting" | "not_started" }

export interface IpsVersion { clientName?: string; version: number; issuedOn: string; status: "Active" | "Superseded" | "Draft"; author: string; summary: string; parts: IpsPart[]; /** Structured IPS JSON from the backend (see backend schemas.py); absent on mock versions. */ data?: IpsData }

/** Backend structured IPS JSON (`data` of an IPS version). Read tolerantly; every field is optional. */
export interface IpsNoteRef { id?: string; date?: string; title?: string }
export interface IpsThreeLItem {
  portfolio: string; strategy: string; strategyName?: string; reason?: string;
  source?: { noteId?: string; date?: string; title?: string; passage?: string } | null;
  default?: boolean;
  conflict?: { note?: string; message?: string; dates?: string[]; latest?: unknown; earlier?: unknown } | null;
}
export interface IpsData {
  goals?: { key: string; title: string; bullets: string[]; empty?: boolean; placeholder?: string }[];
  targets?: { amount?: number | string | null; currency?: string | null; horizonYears?: number | null; text?: string; source_note?: IpsNoteRef | string | null }[];
  lifeEvents?: { id?: string; date?: string | null; year?: number | null; label: string; detail?: string; source_note?: IpsNoteRef | string | null; manual?: boolean }[];
  reviewRules?: { title: string; text: string }[];
  threeL?: IpsThreeLItem[];
  threeLStatus?: "ok" | "no_notes" | "unavailable"; threeLMessage?: string;
  riskScore?: number | null;
  model?: string | null; modelMessage?: string;
  notIncluded?: string[];
  rmSignatureImage?: string; rmSignedDate?: string;
  demographics?: { fields?: Record<string, string> }; philosophy?: { approach?: string; believes?: string; avoids?: string };
  risk?: { fields?: Record<string, string>; bullets?: string[] };
  [k: string]: unknown;
}

export interface GoalProjection {
  points: { year: number; projected: number; required: number }[];
  events: { year: number; label: string }[];
  yearsOnTrack: number;
  summary: string;
}

export interface HouseView { id: string; month: string; issuedOn: string; author: string; file: string | null }

export interface MarketRow { assetClass: string; product: string; industryFocus: string; top5: string[]; confidencePct: number; ranking: string[];
  /** Product Recommender's cited reason ("• ... [TAG]." bullets) when the row came from a recommendation. */
  agentReason?: string }
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

/* ---- Geneva chat <-> LangGraph backend (services/genevaBackend.ts) ---- */
/** Workspace context sent with a Geneva turn; the backend turns it into one system note (backend agents/client_context.py). */
export interface GenevaContext { role: Role; client_id: string; client_name?: string; risk_category?: string; ips_version?: number | null }
/** A money-moving action the backend paused on; nothing happens until the user approves. */
export interface GenevaPendingAction { action_type?: string; amount?: number; description?: string }
/** One backend reply: Markdown text, plus an approval request when an action is proposed. `runId` is set when a Market Researcher run is cited. */
export interface GenevaReply { text: string; runId: string | null; requiresConfirmation: boolean; pendingAction: GenevaPendingAction | null }
/** Reader view of a source article a Market Researcher run cited (GET /agents/market-researcher/articles). */
export interface GenevaArticle {
  url: string; source: string | null; title: string | null; published: string | null; author: string | null;
  summary: string | null; topics: string[]; sentiment: "risk_on" | "risk_off" | "neutral" | null;
  market_impact: "low" | "medium" | "high" | null; status: "ok" | "unavailable"; reason: string | null; paragraphs: string[];
}

/** Investment philosophy: clause blanks plus an optional free-text statement that, when set, overrides the composed sentence. */
export interface Philosophy { approach?: string; believes?: string; avoids?: string; statement?: string }

/** AI IPS generation (Client Profiling Agent reads the client's meeting notes and fills the IPS). Sections run in this order. */
export type IpsGenSectionId = "demographics" | "philosophy" | "goals" | "risk" | "allocation";
export const IPS_GEN_SECTIONS: { id: IpsGenSectionId; label: string }[] = [
  { id: "demographics", label: "Client demographics" },
  { id: "philosophy", label: "Investment philosophy" },
  { id: "goals", label: "Goals & objectives" },
  { id: "risk", label: "Risk profile" },
  { id: "allocation", label: "3L allocation" },
];

/** Strategy A-F from the strategy table (asset-class weights in %). */
export interface Strategy {
  code: string; name: string; riskLabel?: string;
  allocation: Record<string, number>;
  expectedReturnPct?: number; volatilityPct?: number; maxDrawdownPct?: number; longestDrawdownYears?: number;
}
export interface IpsAllocationBucket {
  id: "liquidity" | "longevity" | "legacy";
  strategy: string; strategyName: string; justification: string;
  evidence?: IpsGenEvidence[];
}
export interface IpsAllocation { riskCategory?: string; summary?: string; buckets: IpsAllocationBucket[] }
export interface IpsChatMessage {
  id: string; role: "user" | "assistant"; kind: "chat" | "generation" | "discuss";
  text: string; ts: string; meta?: Record<string, unknown> | null;
}
export interface IpsDiscussResult {
  answer: string; stance: "agree" | "disagree" | "partial" | "info"; model?: string;
  allocation?: { buckets: Omit<IpsAllocationBucket, "evidence">[] };
  citations: { noteId?: string; date?: string; title?: string; passage?: string }[];
}
/** One generated section. Only facts found in the notes are filled; everything else stays empty. */
export interface IpsGenSectionResult {
  section: IpsGenSectionId;
  status: "ok" | "no_notes" | "unavailable";
  message: string;
  /** demographics: KV label -> value ("Date of birth / age", "Occupation", "Employment / income source", "Annual income", "AUM"); risk: "Risk category" | "Risk tolerance (willingness)" | "Risk capacity (ability)" | "Time horizon" | "Liquidity needs". */
  fields: Record<string, string>;
  philosophy?: Philosophy;
  /** goals: one string per bullet; risk: loss-tolerance bullets. */
  bullets: string[];
  sources: { id: string; date?: string; label?: string }[];
  /** Per-item provenance shown to the RM in the Geneva sidebar: which meeting note each filled item was pulled from. */
  evidence?: IpsGenEvidence[];
  /** Chat model id the backend actually used. */
  model?: string | null;
  modelMessage?: string;
  allocation?: IpsAllocation;
  /** Auto-save result: the backend stores a Draft version as soon as something is generated. */
  saved?: boolean; version?: number | null;
  ips?: IpsVersion | null; saved_ips?: IpsVersion | null;
}
/** One filled item and the meeting note it came from. */
export interface IpsGenEvidence {
  /** What was filled, e.g. "Annual income: About S$10m" or the bullet text. */
  item: string;
  noteId: string; date?: string; title?: string;
  /** Verbatim supporting passage from the note. */
  passage?: string;
}
/** All generated sections merged; IpsDraft prefills the live editor from this. */
export interface IpsGenerated {
  demo: Record<string, string>; risk: Record<string, string>;
  philosophy: Philosophy;
  text: { 1?: string; 3?: string };
  sources: { id: string; date?: string; label?: string }[];
  /** Per-item provenance merged across sections (unique). */
  evidence?: IpsGenEvidence[];
  allocation?: IpsAllocation;
  model?: string;
}
