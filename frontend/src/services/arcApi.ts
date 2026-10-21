/* eslint-disable @typescript-eslint/no-unused-vars -- mock ignores args; signatures are the future backend contract */
/**
 * Single seam between pages and data. Today every function resolves mock data.
 * Later, swap bodies for LangGraph/REST calls; keep signatures stable so pages don't change.
 * Pages must NEVER import from src/mock directly.
 */
import * as m from "../mock/data";
import { getActiveIps, isActivated, isIpsReturned, loadIcProgress } from "./workflowStore";
import { bulletLines, toBulletItems } from "../utils/bullets";
import { findProducts } from "../utils/productMatch";
import { askBackend, confirmBackendAction, fetchBackendArticle, newSessionId } from "./genevaBackend";
export { GenevaBackendError } from "./genevaBackend";
import type {
  ActivityEvent, AllocationRow, Bucket3L, Client, Gate, GateId, GateState, Holding, InboxItem, IpsPart, MacroBrief, MarketRow,
  MarketView, HouseView, PackRenderInput, MarketAnswer, MeetingNote, IpsVersion, PackSection, Product, ProductClass, Role, AllocationGroup, CorrelationMatrix, GoalProjection, SectionDraft, GenevaArticle, GenevaContext, GenevaReply,
} from "../types/arc";
import type { PmClientProfile, PmInputField, PmInputs, PmRequest, PmResponse, PmWeightEvaluation } from "../types/portfolio";
import type { PrAssetClassHeadline, PrAssetView, PrHouseView, PrOptions, PrRequest, PrResponse, PrShelf, PrShelfProduct, PrShortlistItem } from "../types/productRecommender";
import type { RcPackReport, RcPackRequest, RcPackSection } from "../types/riskCompliance";

const delay = <T,>(v: T, ms = 150) => new Promise<T>((r) => setTimeout(() => r(v), ms));

/** IC-edited 3L buckets, keyed by client (in memory, like ipsEdits). */
const saved3L: Record<string, Bucket3L[]> = {};

const tweak = (parts: IpsPart[], note: string): IpsPart[] =>
  parts.map((p) => ({ ...p, status: p.status === "blank" ? p.status : p.status === "locked" ? "locked" : "filled", body: p.body && p.part !== 6 ? `${p.body} (${note})` : p.body }));

/** In-memory edits keyed by `${clientId}:${version}` so previews reflect saved changes. */
const ipsEdits: Record<string, IpsPart[]> = {};

/** An onboarding client whose IPS was made active moves to the Monitoring Phase. */
const effective = (c: Client): Client =>
  c.status === "Onboarding Phase" && isActivated(c.id) ? { ...c, status: "Monitoring Phase", ipsVersion: getActiveIps(c.id) ?? c.ipsVersion ?? 1 } : c;

const SAA_ASSETS = ["Cash", "Fixed income", "Equities", "Hedge funds", "Private markets", "Real estate", "Gold"];
/** Once the IC returned the IPS, parts 2 (3L buckets) and 4 (SAA) carry the IC's saved values. */
const withIcReturn = (clientId: string, parts: IpsPart[]): IpsPart[] => {
  if (!isIpsReturned(clientId)) return parts;
  const { buckets, saa, saaWeights } = loadIcProgress(clientId);
  const bk = m.buckets3LByClient[clientId] ?? m.buckets3L;
  return parts.map((p) => {
    if (p.part === 2 && buckets && buckets.length === bk.length) {
      const tot = buckets.reduce((a, b) => a + b, 0) || 1;
      return { ...p, status: "filled", body: bk.map((b, i) => `• ${b.name ?? b.id}: ${Math.round((buckets[i] / tot) * 100)}% (S$${buckets[i].toLocaleString("en-SG")})`).join("\n") };
    }
    if (p.part === 4 && saaWeights && Object.keys(saaWeights).length) {
      return { ...p, status: "filled", body: Object.entries(saaWeights).filter(([, w]) => w > 0).map(([a, w]) => `• ${a} ${+w.toFixed(2)}%`).join("\n") };
    }
    if (p.part === 4 && saa && saa.length === SAA_ASSETS.length) return { ...p, status: "filled", body: SAA_ASSETS.map((a, i) => `• ${a} ${saa[i]}%`).join("\n") };
    return p;
  });
};

const buildIpsHistory = (clientId: string): IpsVersion[] => {
  const base = m.clients.find((x) => x.id === clientId);
  const parts = m.ipsPartsByClient[clientId] ?? m.ipsParts;
  if (!base) return [];
  const c = effective(base);
  if (base.status === "Onboarding Phase" && c.status === "Onboarding Phase") {
    return m.ipsPartsByClient[c.id]
      ? [{ version: 1, issuedOn: "2026-10-15", status: "Draft", author: "Isabel", summary: "Onboarding draft. Parts 2 and 4 await the Investment Counsellor.", parts }]
      : [];
  }
  if (base.status === "Onboarding Phase") {
    return [{ version: 1, issuedOn: "2026-10-15", status: "Active", author: "Isabel", summary: "Initial IPS approved after onboarding.", parts }];
  }
  const v = c.ipsVersion ?? 1;
  const active: IpsVersion = { version: v, issuedOn: clientId === "jfr" ? "2026-09-20" : "2026-04-22", status: "Active", author: "Isabel", summary: clientId === "jfr" ? "Updated for the house purchase and a higher liquidity need." : "Initial IPS approved after onboarding.", parts };
  if (v < 2) return [active];
  return [
    active,
    { version: v - 1, issuedOn: "2026-03-10", status: "Superseded", author: "Isabel", summary: "Original IPS from onboarding, before the house purchase.", parts: tweak(parts, "original wording, v1") },
  ];
};

const withEdits = (clientId: string, list: IpsVersion[]): IpsVersion[] =>
  list.map((v) => (ipsEdits[`${clientId}:${v.version}`] ? { ...v, parts: ipsEdits[`${clientId}:${v.version}`] } : v));

export interface ProfessionaliseInput {
  clientId: string; role: "rm" | "ic" | "ps"; context: "ips" | "pack" | "products";
  items: { id: string; label: string; text: string }[]; chat?: string[];
}
const ROLE_DESC = { rm: "Relationship Manager", ic: "Investment Counsellor", ps: "Product Specialist" } as const;
const CTX_TAG = { ips: "IPS-v2", pack: "CIO-2026Q4-03", products: "MKT-0142" } as const;
function professionaliseText(input: ProfessionaliseInput, it: { label: string; text: string }): string {
  const tag = CTX_TAG[input.context];
  const existing = Array.from(it.text.matchAll(/\[([A-Z0-9][A-Za-z0-9-]+)\]/g)).map((x) => x[1]);
  const t1 = existing[0] ?? tag;
  const clean = it.text.replace(/\[[^\]]*\]/g, "").replace(/^[\s•\-*]+/gm, "").trim();
  const sentences = clean.split(/(?<=[.!?\n])\s+/).map((s) => s.trim().replace(/[.\s]+$/, "")).filter((s) => s.length > 3);
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const chat = (input.chat ?? []).map((c) => c.replace(/\s+/g, " ").trim()).filter(Boolean);
  const bullets: string[] = [];
  sentences.slice(0, 3).forEach((s, i) => bullets.push(`• ${i === 0 ? `${it.label}: ` : ""}${cap(s)}, documented for client ${input.clientId.toUpperCase()} [${existing[i] ?? t1}].`));
  if (chat[0]) bullets.push(`• Supporting research context: ${cap(chat[0].slice(0, 160))}${chat[0].length > 160 ? "..." : ""} [MKT-0142].`);
  if (chat[1]) bullets.push(`• Additional research consideration: ${cap(chat[1].slice(0, 160))}${chat[1].length > 160 ? "..." : ""} [${tag}].`);
  const fillers = [
    `• Consistency with the Balanced mandate and the risk limit of 3 has been assessed [IPS-v2].`,
    `• Liquidity needs, including the planned S$3.0m house deposit, were considered [IPS-v2].`,
    `• Diversification and concentration effects were reviewed against the SAA bands [${tag}].`,
    `• Fees and costs are disclosed transparently and were not used to rank suitability [${tag}].`,
    `• Prepared by the ${ROLE_DESC[input.role]} for review; subject to human approval before release [${tag}].`,
  ];
  for (const f of fillers) if (bullets.length < 5) bullets.push(f);
  return bullets.join("\n");
}

export const arcApi = {
  listClients: (): Promise<Client[]> => delay(m.clients.map(effective)),
  getClient: (id: string): Promise<Client | undefined> => delay(m.clients.filter((c) => c.id === id).map(effective)[0]),
  getHoldings: (clientId: string): Promise<Holding[]> => delay(m.holdingsByClient[clientId] ?? m.holdings),
  getCorrelation: (_clientId: string): Promise<CorrelationMatrix> => delay({ labels: [...m.holdingLabels], matrix: m.holdingsCorrelation }),
  getAllocationGroups: (clientId: string): Promise<AllocationGroup[]> => delay(m.allocationGroupsFor(clientId)),
  getGoalProjection: (clientId: string): Promise<GoalProjection> => delay(m.goalProjectionByClient[clientId] ?? m.goalProjectionByClient.jfr),
  getHoldingClusters: (_clientId: string) => delay(m.holdingClusters),
  get3L: (clientId: string): Promise<Bucket3L[]> => delay(saved3L[clientId] ?? m.buckets3LByClient[clientId] ?? m.buckets3L),
  /** Mock save: keeps the IC's bucket amounts in memory so the SAA step and the Portfolio Manager use them. */
  save3L: (clientId: string, buckets: Bucket3L[]): Promise<Bucket3L[]> => {
    saved3L[clientId] = buckets.map((b) => ({ ...b }));
    return delay(saved3L[clientId]);
  },
  /** Portfolio Manager inputs derived from the 3L buckets, IPS part 3 and the goal plan (see buildPortfolioInputs). */
  getPortfolioInputs: (clientId: string): Promise<PmInputs> => buildPortfolioInputs(clientId),
  /** Real backend call: the Portfolio Manager agent builds and compares SAA templates A-F. */
  generatePortfolioProposals: (request: PmRequest): Promise<PmResponse> => generatePortfolioProposals(request),
  /** Real backend call: the Risk & Compliance agent's final check of the review pack. Never approves G4; it only says whether the RM may. */
  checkReviewPack: (input: PackCheckInput): Promise<RcPackReport> => checkReviewPack(input),
  /** A proposal generated earlier (kept by the backend), so Back does not re-run the agent. */
  getPortfolioProposal: (requestId: string): Promise<PmResponse> => getPortfolioProposal(requestId),
  /** Backend re-check of adjusted asset-class weights: risk, return, limits and the efficient frontier. */
  evaluatePortfolioWeights: (requestId: string, optionId: string, weights: Record<string, number>, signal?: AbortSignal): Promise<PmWeightEvaluation> =>
    evaluatePortfolioWeights(requestId, optionId, weights, signal),
  getAllocation: (clientId: string): Promise<AllocationRow[]> => delay(m.allocationByClient[clientId] ?? m.allocation),
  getSaaTemplates: () => delay(m.saaTemplates),
  getIps: (clientId: string): Promise<IpsPart[]> => delay(withIcReturn(clientId, m.ipsPartsByClient[clientId] ?? m.ipsParts)),
  getMeetingNotes: (clientId: string): Promise<MeetingNote[]> => delay(m.meetingNotes.filter((n) => n.clientId === clientId)),
  /** Newest first. Onboarding clients return [] or a single Draft. */
  getIpsHistory: (clientId: string): Promise<IpsVersion[]> => delay(withEdits(clientId, buildIpsHistory(clientId))),
  /** Mock upload: appends a note to the in-memory list so getMeetingNotes returns it. */
  uploadMeetingNote: (clientId: string, fileName: string): Promise<MeetingNote> => {
    const note: MeetingNote = {
      id: `note_up_${Date.now()}`, clientId, date: "2026-10-17", title: fileName.replace(/\.[^.]+$/, ""), sourceFile: fileName,
      originalText: `Original contents of ${fileName} (demo preview).\n\nIn the live system this shows the uploaded document or the transcript of the recording, exactly as received.`,
      summary: [`Notes extracted from ${fileName}`, "Client goals and constraints captured", "Follow-ups flagged for the Relationship Manager"],
      checklist: [{ text: "Review extracted notes", done: false }, { text: "Update IPS draft", done: false }],
    };
    m.meetingNotes.unshift(note);
    return delay(note, 600);
  },
  /** Mock edit: mutates the in-memory note so getMeetingNotes and the preview show the edited text. */
  updateMeetingNote: (noteId: string, patch: { title: string; originalText: string }): Promise<MeetingNote> => {
    const note = m.meetingNotes.find((n) => n.id === noteId);
    if (!note) return Promise.reject(new Error(`Meeting note ${noteId} not found`));
    note.title = patch.title;
    note.originalText = patch.originalText;
    return delay(note, 400);
  },
  getGates: (_clientId: string): Promise<Gate[]> => delay(m.gates),
  getInbox: (role: Exclude<Role, "rm">): Promise<InboxItem[]> => delay(m.inboxes[role]),
  getMarketCycle: () => delay(m.marketCycle),
  /** CIO view per asset class, from the Product Recommender's curated house view (one copy shared with the ranker). */
  getMarketViews: async (_clientId: string): Promise<MarketView[]> => (await getHouseView()).views.map((v) => ({
    assetClass: v.asset_class as MarketView["assetClass"], view: v.view, explanation: v.rationale, confidence: v.confidence, tags: [v.citation_id],
  })),
  /** The shared product shelf (Product Recommender). Fees are for information only. */
  getProducts: async (_clientId: string): Promise<Product[]> => (await getShelf()).products.map(toProduct),
  /** Suitability gate + ranked shortlist for one client, from the Product Recommender. Never approves anything. */
  recommendProducts: (clientId: string, options: PrOptions = {}): Promise<PrResponse> => recommendProducts(clientId, options),
  /** CIO and agent stance for all seven asset classes (no narrative). */
  getAssetClassViews: (): Promise<PrAssetClassHeadline[]> => prFetch<PrAssetClassHeadline[]>("/asset-class-views"),
  /** The agent's own view on one asset class beside the CIO's; with a client, adds what that client can access. */
  getAssetClassView: (assetClass: string, clientId?: string): Promise<PrAssetView> => getAssetClassView(assetClass, clientId),
  /** Mock rewrite of lay-language text into professional bullets. Replace with a LangGraph run. */
  professionalise: (input: ProfessionaliseInput): Promise<{ id: string; text: string }[]> =>
    new Promise((res) => setTimeout(() => res(input.items.map((it) => ({ id: it.id, text: professionaliseText(input, it) }))), 1500)),
  /**
   * Geneva chat, local half: client-data and workflow intents answered from the workspace (IPS, goals, notes,
   * holdings/TAA, pack drafts, CIO house view, product tables). Returns null when the question is not one of
   * those; the chat then sends it to the LangGraph backend (`askBackend`).
   */
  answerLocally: async (role: Role, clientId: string, text: string, ipsVersion: number | null = null): Promise<MarketAnswer | null> => {
    if (role === "ps") return answerPsLocally(clientId, text, ipsVersion);
    const r = await answerAsAgent(role, clientId, text);
    if (!r) return null;
    const reply = ipsVersion && !r.draft ? `Using IPS v${ipsVersion}.\n${r.reply}` : r.reply;
    return {
      summary: reply, draft: r.draft, market: null, rows: [], autoTick: false, tags: r.tags,
      steps: ["Intent parser is reading your request…", `${r.agent} fired`, ...r.steps, "Consolidating…"],
    };
  },
  /** Geneva chat, backend half: one turn of the LangGraph assistant, with the role and client as workspace context. */
  askBackend: async (role: Role, clientId: string, sessionId: string, text: string, ipsVersion: number | null = null): Promise<GenevaReply> => {
    const c = await arcApi.getClient(clientId);
    const context: GenevaContext = { role, client_id: clientId, client_name: c?.name, risk_category: c?.riskCategory, ips_version: ipsVersion };
    return askBackend(sessionId, text, context);
  },
  /** Approve or decline the money-moving action the backend paused on. */
  confirmBackendAction: (sessionId: string, approved: boolean): Promise<GenevaReply> => confirmBackendAction(sessionId, approved),
  /** One backend session per Geneva chat. */
  newChatSession: (role: Role, clientId: string): string => newSessionId(role, clientId),
  /** Reader view of a source a Market Researcher run cited. */
  getArticle: (runId: string, url: string, signal?: AbortSignal): Promise<GenevaArticle> => fetchBackendArticle(runId, url, signal),

  getHouseViews: (_clientId: string): Promise<HouseView[]> => delay(m.houseViews),
  getPack: (_clientId: string): Promise<PackSection[]> => delay([...m.packSections].sort((a, b) => (a.order ?? a.n) - (b.order ?? b.n))),
  /** Backend Jinja render of the compiled pack: RM's current text in, standalone HTML out (same HTML feeds the PDF). */
  renderPackHtml: async (input: PackRenderInput): Promise<string> => {
    const base = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
    const body = {
      doc: { title: input.doc.title, client_name: input.doc.clientName, version: input.doc.version, date: input.doc.date },
      sections: input.sections.map((x) => ({ n: x.n, title: x.title, owner_label: x.ownerLabel, complete: x.complete, text: x.text, wide: x.wide ?? false, chart: x.chart ?? null, kind: x.kind ?? null })),
      allocation: input.allocation.map((a) => ({ asset_class: a.assetClass, saa: a.saa, old_taa: a.oldTaa, new_taa: a.newTaa, band: a.band })),
      signatures: Object.fromEntries(Object.entries(input.signatures).map(([r, g]) => [r, { data_url: g.dataUrl, signed_at: g.signedAt }])),
    };
    const res = await fetch(`${base}/review-pack/render`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`Preview service returned ${res.status}`);
    return res.text();
  },
  getActivity: (_clientId: string): Promise<ActivityEvent[]> => delay(m.activity),

};

/** PS research chat, local half: CIO house view and product tables (Product Recommender). Null = ask the backend. */
async function answerPsLocally(clientId: string, question: string, ipsVersion: number | null): Promise<MarketAnswer | null> {
  const t = question.toLowerCase();
  const ipsNote = ipsVersion ? ` Using IPS v${ipsVersion}.` : "";
  const houseView = /house view|cio view|what is the cio/.test(t) && !/product|fund|etf|note|suit|recommend|top 5|ranking/.test(t);
  const [brief, shelf] = await Promise.all([cioBrief(), getShelf()]);
  const hvTags = [...new Set((await getHouseView()).views.map((v) => v.citation_id))];
  if (houseView) {
    const pos = (view: string) => brief.views.filter((v) => v.view === view).map((v) => v.assetClass.toLowerCase()).join(", ") || "none";
    return {
      summary: `The CIO House View as of ${brief.asOf} puts the economy in a ${brief.phase.toLowerCase()} phase. The CIO is positive on ${pos("Buy")}, neutral on ${pos("Hold")} and negative on ${pos("Sell")}.${ipsNote}`,
      market: brief, rows: [], autoTick: false, tags: hvTags,
      steps: ["Intent parser is reading your request…", "Market Research Agent fired", "Reading the latest CIO House View…", "Mapping Buy, Hold and Sell views per asset class…", "Thinking…", "Consolidating…"],
    };
  }
  const named = findProducts(t, shelf.products, (p) => p.product_name, (p) => p.product_id);
  const classes = /equit|stock/.test(t) ? ["Equities"] : /fixed|bond/.test(t) ? ["Fixed income"] : /altern|hedge/.test(t) ? ["Hedge funds", "Private markets"]
    : /private/.test(t) ? ["Private markets"] : /reit|real estate|property/.test(t) ? ["Real estate"] : /gold/.test(t) ? ["Gold"] : /\bcash\b|money market/.test(t) ? ["Cash"] : null;
  const wantsProducts = named.length > 0 || /product|fund|etf|note|suit|recommend|shortlist|top 5|ranking|fit|compare/.test(t);
  const wantsMarket = /macro|cycle|market|economy|cio|view|outlook|compare|suit|direction/.test(t) || !wantsProducts;
  const agents = [wantsMarket && "Market Research Agent", wantsProducts && "Product Recommender"].filter(Boolean) as string[];
  const steps = [
    "Intent parser is reading your request…",
    `${agents.join(" and ")} fired`,
    ...(wantsMarket ? ["Searching the web for macroeconomic events…"] : []),
    ...(wantsProducts ? [named.length ? `Checking ${named.length} requested product${named.length === 1 ? "" : "s"} against the suitability gate…` : "Running the suitability gate, then ranking by fit and house view…"] : []),
    "Thinking…",
    "Consolidating…",
  ];
  // Plain market questions go to the real Market Researcher via the LangGraph backend.
  if (!wantsProducts) return null;
  const rec = await recommendProducts(clientId, { top_n: 5, asset_classes: named.length ? null : classes, named_products: named.map((p) => p.product_id) });
  let rows: MarketRow[];
  let summary: string;
  if (named.length) {
    const ok = rec.named_products.filter((n) => n.status === "shortlisted" || n.status === "eligible");
    const no = rec.named_products.filter((n) => n.status === "excluded");
    rows = ok.map((n) => {
      const item = rec.shortlist.find((s) => s.product.product_id === n.product_id);
      const p = shelf.products.find((x) => x.product_id === n.product_id)!;
      return item ? shortlistRow(item) : { ...shelfRow(p), ranking: [n.reason] };
    });
    summary = [
      ok.length ? `${ok.length} of the ${named.length} product${named.length === 1 ? "" : "s"} you asked about pass the suitability gate. They are ticked as considerations; untick any you do not want.` : "",
      ...no.map((n) => `${shelf.products.find((p) => p.product_id === n.product_id)?.product_name ?? n.query} is not suitable: ${n.reason}`),
    ].filter(Boolean).join(" ");
  } else {
    rows = rec.shortlist.map(shortlistRow);
    summary = rows.length
      ? "Here are the best-fit products after the suitability gate, grouped by asset class. Tick the ones to consider. Fees were not used to rank."
      : `No product passes the suitability gate for this client${classes ? ` in ${classes.join(" and ").toLowerCase()}` : ""}.${rec.missing_information.length ? ` Missing from the profile: ${rec.missing_information.join(", ")}.` : ""}`;
  }
  const shown = rows.filter((r) => r.agentReason).length;
  const reasonsBy = !shown ? ""
    : rec.shortlist.some((s) => s.reason.source === "llm")
      ? " The reasons are written by AI from the engine's facts and checked against them; the ranking is the engine's."
      : " The reasons are rule-based.";
  return { summary: summary + reasonsBy + ipsNote, market: wantsMarket ? brief : null, rows, autoTick: rows.length > 0 && named.length > 0, steps, tags: hvTags };
}

export type AgentName = "Profiling Agent" | "Portfolio Agent" | "Product Agent" | "Orchestrator";
export interface AgentReply { role: Role; clientId: string; reply: string; tags: string[]; agent: AgentName; steps: string[]; draft?: SectionDraft }

/** Keyword intent routing shared by the UI (status line) and the mock agent. */
function routeAgent(message: string): AgentName {
  const t = message.toLowerCase();
  if (/\b(suits?|suitable|fits?|etf|funds?|products?)\b/.test(t)) return "Product Agent";
  if (/\b(ips|goals?|profile|meetings?|notes)\b/.test(t)) return "Profiling Agent";
  if (/\btaa\b|allocation/.test(t)) return "Portfolio Agent";
  if (t.includes("product")) return "Product Agent";
  return "Orchestrator";
}

const bullets = bulletLines;
const bodyItems = (body: string): string[] => toBulletItems(body);
const firstLine = (s: string) => s.replace(/\s+/g, " ").trim();
const clip = (s: string, n = 160) => { const x = firstLine(s); return x.length > n ? `${x.slice(0, n - 1)}…` : x; };

const sgdM = (n: number) => `S$${(n / 1_000_000).toFixed(1)}m`;

/** RM/IC chat, local half. Null = not a client-data or workflow question; Geneva sends it to the backend. */
async function answerAsAgent(role: Role, clientId: string, message: string): Promise<AgentReply | null> {
  const t = message.toLowerCase();
  const agent = routeAgent(message);
  const [client, goals, notes, ips, alloc] = await Promise.all([
    arcApi.getClient(clientId), arcApi.getGoalProjection(clientId), arcApi.getMeetingNotes(clientId),
    arcApi.getIps(clientId), arcApi.getAllocation(clientId),
  ]);
  const name = client?.name ?? "the client";
  const base = { role, clientId, agent };
  const done = (reply: string, tags: string[], steps: string[]): AgentReply => ({ ...base, reply, tags, steps });

  if (role === "ic") {
    const pf = ["Reading the client's holdings…", "Running portfolio analytics…"];
    if (/market.*(today|regime)|regime/.test(t) && /house view|cio|web|market/.test(t)) {
      const mb = m.macroBrief;
      const hv = await getHouseView();
      const cio = hv.views.map((v) => `${v.asset_class}: ${v.view} (${v.cio_term}) [${v.citation_id}]`);
      const web = mb.events.map((e, i) => `${e} [MKT-0142-${i + 1}]`);
      const reply = `Market regime: ${mb.phase}, as of ${mb.asOf} [MKT-0142].\nFrom the CIO House View (${hv.as_of}):\n${bullets(cio)}\nFrom the web:\n${bullets(web)}`;
      return done(reply, ["MKT-0142", ...new Set(hv.views.map((v) => v.citation_id))], ["Reading the macro brief…", "Reading the CIO House View…", "Scanning online macro events…", "Drafting summary by source…"]);
    }
    if (/\bedit\b.*holdings?|holdings?.*\bedit/.test(t)) {
      const holdings = await arcApi.getHoldings(clientId);
      const lines: string[] = [], edits: string[] = [];
      for (const r of alloc) {
        const hs = holdings.filter((h) => h.assetClass === r.assetClass);
        const sum = Math.round(hs.reduce((a, h) => a + h.weightPct, 0) * 10) / 10;
        const diff = Math.round((r.newTaa - sum) * 10) / 10;
        lines.push(`${r.assetClass}: holdings ${sum}% vs TAA ${r.newTaa}%${diff === 0 ? ", aligned" : `, off by ${diff > 0 ? "+" : ""}${diff} pts`}${hs.length ? ` (${hs.map((h) => `${h.name} ${h.weightPct}%`).join(", ")})` : ""}`);
        if (diff !== 0) {
          const tgt = [...hs].sort((a, b) => b.weightPct - a.weightPct)[0];
          edits.push(tgt ? `${r.assetClass}: change ${tgt.name} from ${tgt.weightPct}% to ${Math.round((tgt.weightPct + diff) * 10) / 10}%` : `${r.assetClass}: add a ${r.newTaa}% position, no holding exists yet`);
        }
      }
      const tail = edits.length ? `Suggested edits:\n${bullets(edits)}` : "All classes already match the TAA, no edits needed.";
      return done(`Holdings against the new TAA for ${name}:\n${bullets(lines)}\n${tail}\nApply them on the Individual holdings step: /ic/cases/${clientId}/holdings. Draft only, for your review.`, ["PORT-HOLD", "CIO-2026Q4-05"], ["Reading the client's holdings…", "Reading the new TAA…", "Comparing weights per asset class…", "Drafting suggested edits…"]);
    }
    if (/strength|weakness|analyse|analyze|portfolio (health|analysis)/.test(t) && !/taa/.test(t)) {
      const holdings = await arcApi.getHoldings(clientId);
      const top = [...holdings].sort((a, b) => b.weightPct - a.weightPct).slice(0, 2);
      const off = alloc.filter((r) => Math.abs(r.current - r.saa) >= 3);
      const sharpe = client?.sharpe ?? 0, div = client?.diversificationScore ?? 0;
      const strengths = [
        `Sharpe ratio ${sharpe.toFixed(2)}, ${sharpe >= 1 ? "a healthy return for the risk taken" : "moderate return for the risk taken"} [PORT-SHARPE]`,
        `Diversification score ${div}/100 across ${holdings.length} holdings and ${new Set(holdings.map((h) => h.assetClass)).size} asset classes [PORT-DIV]`,
      ];
      const weaknesses = [
        top.length ? `Concentration: ${top.map((h) => `${h.name} (${h.weightPct}%)`).join(" and ")} are the largest positions [PORT-HOLD]` : "No holdings on file",
        ...(div < 70 ? [`Diversification score of ${div}/100 is below the 70 comfort level [PORT-DIV]`] : []),
        ...off.map((r) => `${r.assetClass} is ${r.current}% against a ${r.saa}% SAA (${r.current > r.saa ? "+" : ""}${r.current - r.saa} pts)`),
      ];
      return done(`Portfolio view for ${name}.\nStrengths:\n${bullets(strengths)}\nWeaknesses:\n${bullets(weaknesses)}`, ["PORT-SHARPE", "PORT-DIV", "PORT-HOLD"], [...pf, "Comparing with the SAA…", "Drafting analysis…"]);
    }
    if (/move together|correlat|cluster|overlap/.test(t)) {
      const clusters = await arcApi.getHoldingClusters(clientId);
      const items = clusters.map((c) => `${c.label}: ${c.holdings.join(" and ")}, together ${c.combinedPct}% of the portfolio. ${c.note}`);
      return done(`Holdings that move together in ${name}'s portfolio:\n${bullets(items)}`, ["PORT-CORR", "PORT-HOLD"], ["Reading the client's holdings…", "Computing pairwise correlations…", "Grouping holdings into clusters…", "Drafting explanation…"]);
    }
    if (/compare.*taa|old (and|vs\.?|versus) new|new vs old/.test(t)) {
      const rowsTxt = alloc.map((r) => `${r.assetClass}: SAA ${r.saa}%, old TAA ${r.oldTaa}%, new TAA ${r.newTaa}% (${r.newTaa - r.oldTaa >= 0 ? "+" : ""}${r.newTaa - r.oldTaa} pts)`);
      return done(`Old versus new TAA for ${name}:\n${bullets(rowsTxt)}`, ["CIO-2026Q4-03", "CIO-2026Q4-05"], ["Reading the SAA and current TAA…", "Comparing old and new TAA…", "Drafting comparison…"]);
    }
    if (/propose.*taa|suggest.*taa|recommend.*taa|new taa proposal/.test(t)) {
      const lo = (r: typeof alloc[number]) => Math.max(0, r.saa - r.band), hi = (r: typeof alloc[number]) => r.saa + r.band;
      const prop = alloc.map((r) => Math.min(hi(r), Math.max(lo(r), r.newTaa)));
      let gap = 100 - prop.reduce((a, b) => a + b, 0);
      for (let i = 0; gap !== 0 && i < 50; i++) {
        const k = i % alloc.length, step = gap > 0 ? 1 : -1;
        if (prop[k] + step >= lo(alloc[k]) && prop[k] + step <= hi(alloc[k]) && alloc[k].assetClass !== "Hedge funds") { prop[k] += step; gap -= step; }
      }
      const rowsTxt = alloc.map((r, i) => `${r.assetClass}: ${r.oldTaa}% to ${prop[i]}% (SAA ${r.saa}%, band ${lo(r)}-${hi(r)}%). ${clip(r.reason, 80)}`);
      return done(`Proposed TAA for ${name}, every line inside the +/-${alloc[0]?.band ?? 5} band around the SAA. Draft only, for your review and G2 approval:\n${bullets(rowsTxt)}`, ["CIO-2026Q4-03", "CIO-2026Q4-05", "IPS-v2"], ["Reading the SAA and bands…", "Reading the CIO House View…", "Drafting a TAA within the bands…", "Checking the total equals 100%…"]);
    }
  }

  const packKeys: [RegExp, number][] = [
    [/client summary|latest client|profile \+ goals|\bsaa\b|strategic asset/, 1], [/market view|market conditions|cio view/, 2],
    [/portfolio (current )?health|sharpe|diversif/, 3], [/old vs new|\btaa\b/, 4], [/product recommendation/, 5],
    [/sign-?off/, 6], [/sources|citations/, 7],
  ];
  const hit = packKeys.find(([re]) => re.test(t));
  const wantsDraft = /\b(write|draft|rewrite|redraft|compose)\b/.test(t);
  if (hit && wantsDraft) {
    const pack = await arcApi.getPack(clientId);
    const sec = pack.find((x) => x.n === hit[1]);
    if (sec && sec.owner !== role) {
      const who = sec.owner === "ic" ? "the Investment Counsellor (Wei Lun)" : sec.owner === "ps" ? "the Product Specialist (David)" : "the Relationship Manager (Isabel)";
      return { ...base, agent: "Orchestrator", reply: `Section ${sec.n}, ${sec.title}, belongs to ${who}. I can summarise it, but I cannot rewrite it for you.`, tags: [], steps: ["Checking section ownership…", "Drafting reply…"] };
    }
    if (sec) {
      const plain = (x: string) => x.replace(/\s*\[[^\]]+\]/g, "").trim();
      const facts = sec.n === 1 && client
        ? [`${client.name}, ${sgdM(client.aumSgd)} under management, ${client.riskCategory} risk profile`, `IPS version ${client.ipsVersion ?? "pending"} governs this portfolio`]
        : [];
      const sentences = bodyItems(sec.body).map(plain).filter(Boolean);
      const text = bullets([...facts, ...sentences]);
      return { ...base, agent: "Orchestrator", reply: `Here is a formal draft of section ${sec.n}, ${sec.title}, in bullet points. Review it, then apply it to the review pack.`, tags: [], steps: ["Opening the review pack…", `Reading section ${sec.n}…`, "Writing in a formal tone…", "Formatting as bullet points…"], draft: { section: sec.n, title: sec.title, text } };
    }
  }

  if (hit) {
    const pack = await arcApi.getPack(clientId);
    const sec = pack.find((x) => x.n === hit[1]);
    if (sec) {
      const items = [`Owner: ${sec.owner.toUpperCase()}. Status: ${sec.status}.`, ...bodyItems(sec.body).map((x) => x.replace(/\s*\[[^\]]+\]/g, ""))];
      return { ...base, agent: "Orchestrator", reply: `Section ${sec.n}, ${sec.title}, for ${name}:\n${bullets(items)}`, tags: sec.body.match(/[A-Z]+-[A-Za-z0-9-]+(?=\])/g)?.slice(0, 2) ?? [], steps: ["Opening the review pack…", `Reading section ${sec.n}…`, "Drafting summary…"] };
    }
  }

  if (agent === "Profiling Agent") {
    if (/meeting|notes/.test(t)) {
      const n = notes[0];
      if (!n) return done(`There are no meeting notes on file for ${name} yet.`, [], ["Searching meeting notes…", "Drafting reply…"]);
      const last = /last|say|said/.test(t);
      const lines = last
        ? `${name} in the meeting "${n.title}" (${n.date}):\n${bullets(n.summary)}`
        : `Meeting notes for ${name} (${notes.length} on file). Latest "${n.title}", ${n.date}:\n${bullets(n.summary)}`;
      return done(lines, [], ["Reading meeting notes…", "Extracting key statements…", "Drafting summary…"]);
    }
    if (/goal/.test(t)) {
      const items = [goals.summary, ...goals.events.map((e) => `${e.year}: ${e.label}`), `Projection is on track for ${goals.yearsOnTrack} years.`];
      return done(`Goals for ${name}:\n${bullets(items)}`, [], ["Reading the client's goals…", "Checking life events…", "Drafting summary…"]);
    }
    const filled = ips.filter((p) => p.status !== "blank");
    const blank = ips.filter((p) => p.status === "blank");
    if (/review/.test(t)) {
      const items = [
        `${filled.length} of ${ips.length} IPS parts are complete.`,
        blank.length ? `Missing: ${blank.map((p) => `Part ${p.part} ${p.title}`).join(", ")}.` : "No blank parts remain.",
        `Risk category ${client?.riskCategory ?? "n/a"} with a risk limit of ${client?.riskCap ?? "n/a"} should be confirmed with the client.`,
      ];
      return done(`IPS review for ${name}:\n${bullets(items)}`, [], ["Reading the client's IPS…", "Checking completeness…", "Drafting review…"]);
    }
    const items = filled.map((p) => `Part ${p.part} ${p.title}: ${clip(p.body, 110)}`);
    return done(`IPS summary for ${name}:\n${bullets(items.length ? items : ["No IPS content yet."])}`, [], ["Reading the client's IPS…", "Reading meeting notes…", "Drafting summary…"]);
  }

  if (agent === "Portfolio Agent") {
    const moves = alloc.filter((r) => r.newTaa !== r.oldTaa).map((r) => `${r.assetClass}: ${r.oldTaa}% to ${r.newTaa}%, ${clip(r.reason, 90)}`);
    const reply = `TAA changes for ${name}:\n${bullets(moves.length ? moves : ["No tactical changes proposed."])}`;
    return done(reply, ["CIO-2026Q4-05"], ["Reading the SAA and current TAA…", "Comparing old and new TAA…", "Drafting explanation…"]);
  }

  if (agent === "Product Agent") {
    // Suitability and ranking come from the Product Recommender; nothing is judged here.
    const products = await arcApi.getProducts(clientId);
    const named = findProducts(t, products, (p) => p.name, (p) => p.id)[0];
    if (/suits?|fits?|why/.test(t) && named) {
      const [rec, cycle, views] = await Promise.all([
        recommendProducts(clientId, { named_products: [named.id] }), arcApi.getMarketCycle(), arcApi.getMarketViews(clientId),
      ]);
      const result = rec.named_products[0];
      const view = views.find((v) => v.assetClass === named.assetClass);
      const items = [
        `Suitability gate: ${result?.status === "excluded" ? "not suitable" : "suitable"} for ${name} (risk level ${rec.client_summary.risk_level ?? "unknown"}). ${result?.reason ?? ""}`,
        `Product: ${named.name}, risk ${named.riskRating} of 5. ${clip(named.suitability, 120)}`,
        `Macro: the cycle is ${cycle.phase}. The house view on ${named.assetClass.toLowerCase()} is ${view?.view ?? "n/a"}. ${view ? clip(view.explanation, 110) : ""}`,
        `${named.feePct === null ? "No fee data" : `Fee ${named.feePct.toFixed(2)}%`} is shown for information and was not used to rank.`,
      ];
      return done(`Fit check for ${named.name}:\n${bullets(items)}`, [named.id, ...(view?.tags.slice(0, 1) ?? [])], ["Reading the client's profile and IPS…", "Running the suitability gate…", "Checking the house view…", "Drafting explanation…"]);
    }
    const rec = await recommendProducts(clientId, { top_n: 4 });
    const fit = rec.shortlist.map((s) => `${s.product.product_name} (${s.product.asset_class}, risk ${s.product.risk_rating}): ${clip(s.product.why_buy ?? "", 90)}`);
    const reply = `Best-fit products for ${name} after the suitability gate:\n${bullets(fit.length ? fit : ["No product passes the suitability gate for this client."])}`;
    return done(reply, [...new Set(rec.shortlist.flatMap((s) => s.reason.citations))].slice(0, 3), ["Reading the product shelf…", "Running the suitability gate…", "Ranking by fit and house view…", "Drafting shortlist…"]);
  }

  return null;
}

/* ---------- Portfolio Manager agent (real backend) ---------- */

/** Backend base URL: the main app (or `python -m app.agents.portfolio_manager serve`). Override with VITE_API_BASE. */
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");
const PM_URL = `${API_BASE}/agents/portfolio-manager`;
const PM_TIMEOUT_MS = 90_000; // generation can include an LLM call

export class PortfolioManagerError extends Error {
  kind: "UNREACHABLE" | "TIMEOUT" | "REJECTED" | "NOT_FOUND" | "SERVER" | "INVALID_RESPONSE";
  details: string[];
  constructor(kind: PortfolioManagerError["kind"], message: string, details: string[] = []) {
    super(message);
    this.kind = kind;
    this.details = details;
  }
}

const shortS = (n: number) => `S$${(n / 1_000_000).toFixed(2)}m`;

/**
 * Turn what the RM and IC have captured into the agent's client profile.
 * - Portfolio = client AUM. The Liquidity bucket (0-3 years) is the cash
 *   ring-fenced from investing; the agent invests the rest.
 * - Risk: category + limit (willingness), capacity and drawdown limit from IPS part 3.
 * - Goals: dated goal-plan events beyond 3 years; nearer ones are funded by the
 *   Liquidity bucket. The Legacy bucket has no date, so it is not a dated goal.
 * - Anything not captured (age, income, expenses, accredited status...) is left
 *   out so the agent reports it as missing instead of the UI guessing.
 */
/**
 * The backend's risk label for each IPS risk limit (taxonomy.RISK_LEVEL_LABELS). The UI's five risk
 * categories are bands ("Conservative" covers limits 1 and 2), so sending the category would make the
 * backend read a limit-2 client as level 1. The IPS limit is the precise value, so its label is sent.
 */
const RISK_LABEL_FOR_LIMIT: Record<number, string> = { 1: "Conservative", 2: "Moderately conservative", 3: "Balanced", 4: "Growth", 5: "Aggressive" };

/** Shared by the Portfolio Manager and the Product Recommender so both agents see the same client. */
async function buildClientProfile(clientId: string) {
  const [client, buckets, alloc, goals] = await Promise.all([
    arcApi.getClient(clientId), arcApi.get3L(clientId), arcApi.getAllocation(clientId), arcApi.getGoalProjection(clientId),
  ]);
  if (!client) throw new Error(`Unknown client ${clientId}`);
  const risk = m.ipsRiskByClient[clientId];
  const liquidity = buckets.find((b) => b.id === "liquidity")?.amountSgd ?? 0;
  const year = new Date().getFullYear();
  const dated = goals.events.map((e) => ({ ...e, years: e.year - year })).sort((a, b) => a.years - b.years);
  const near = dated.filter((e) => e.years <= 3);
  const later = dated.filter((e) => e.years > 3);
  const current = Object.fromEntries(alloc.map((r) => [r.assetClass, r.current]));
  const profile: PmClientProfile = {
    client_id: clientId,
    base_currency: "SGD",
    total_aum: client.aumSgd,
    investable_assets: client.aumSgd,
    minimum_cash_reserve: liquidity,
    planned_withdrawals: 0,
    risk_appetite: RISK_LABEL_FOR_LIMIT[client.riskCap] ?? client.riskCategory,
    risk_tolerance_score: client.riskCap,
    risk_capacity: risk?.riskCapacity ?? null,
    maximum_acceptable_drawdown: risk?.maxDrawdownPct ?? null,
    financial_goals: later.map((e) => ({ goal: e.label, years_to_goal: e.years, priority: /retire/i.test(e.label) ? "High" : "Medium", currency: "SGD" })),
    current_asset_allocation: current,
  };
  return { client, risk, liquidity, near, later, alloc, profile };
}

async function buildPortfolioInputs(clientId: string): Promise<PmInputs> {
  const [{ client, risk, liquidity, near, later, alloc, profile }, inbox] = await Promise.all([buildClientProfile(clientId), arcApi.getInbox("ic")]);
  const request = inbox.find((i) => i.clientId === clientId);

  const fields: PmInputField[] = [
    { label: "Portfolio", value: shortS(client.aumSgd), source: "Client record" },
    { label: "Liquidity bucket (held separately)", value: shortS(liquidity), source: "3L buckets, this request" },
    { label: "Invested by the agent", value: shortS(client.aumSgd - liquidity), source: "Portfolio minus Liquidity bucket" },
    { label: "Risk category and limit", value: `${client.riskCategory}, ${client.riskCap} of 5`, source: "IPS part 3" },
    { label: "Risk capacity", value: risk?.riskCapacity ?? null, source: risk ? "IPS part 3" : "Not captured" },
    { label: "Maximum drawdown", value: risk ? `${risk.maxDrawdownPct}%` : null, source: risk ? "IPS part 3" : "Not captured" },
    { label: "Goals", value: later.length ? later.map((e) => `${e.label} in ${e.years} yrs`).join(" · ") : null, source: later.length ? "Goal plan" : "Not captured" },
    { label: "Current allocation", value: alloc.map((r) => `${r.assetClass} ${r.current}%`).join(" · "), source: "Holdings" },
    ...["Age", "Residency", "Accredited investor status", "Income and monthly expenses", "Liabilities"].map((label) => ({
      label, value: null, source: "Not captured",
    })),
  ];
  const notes = [
    ...near.map((e) => `${e.label} (${e.year}) falls within 3 years, so it is funded from the Liquidity bucket, not the invested portfolio.`),
    "The Legacy bucket has no target date (beyond lifetime); it is invested with the Longevity bucket.",
  ];
  return {
    fields,
    notes,
    request: {
      client_id: clientId,
      trigger: request ? { requirement_change: request.kind, reason_for_review: request.summary, effective_date: new Date().toISOString().slice(0, 10) } : null,
      client_profile: profile,
    },
  };
}

/** One fetch path for every Portfolio Manager call: same timeouts, error kinds and messages. */
async function pmJson(path: string, init: RequestInit, timeoutMs = PM_TIMEOUT_MS, signal?: AbortSignal): Promise<unknown> {
  let res: Response;
  try {
    const timeout = AbortSignal.timeout(timeoutMs);
    res = await fetch(`${PM_URL}${path}`, { ...init, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  } catch (err) {
    if (signal?.aborted) throw err; // superseded by a newer request; callers ignore it
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new PortfolioManagerError("TIMEOUT", "The Portfolio Manager did not respond in time.");
    }
    throw new PortfolioManagerError("UNREACHABLE", `Cannot reach the Portfolio Manager at ${API_BASE}.`, [
      "Start the backend: cd backend, then python -m app.agents.portfolio_manager serve",
    ]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    if (res.status === 422 && Array.isArray(detail)) {
      throw new PortfolioManagerError("REJECTED", "The Portfolio Manager rejected the inputs.",
        detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).filter((x) => x !== "body").join(" › ")}: ${d.msg ?? "invalid"}`));
    }
    if (res.status === 404 || res.status === 409) {
      throw new PortfolioManagerError(res.status === 404 ? "NOT_FOUND" : "REJECTED", typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    throw new PortfolioManagerError("SERVER", `The Portfolio Manager returned an error (${typeof detail === "string" ? detail : `HTTP ${res.status}`}).`);
  }
  return json;
}

function asProposal(json: unknown): PmResponse {
  const r = json as Partial<PmResponse> | null;
  const ok = !!r && typeof r.request_id === "string" && Array.isArray(r.portfolio_options) && Array.isArray(r.comparison_matrix)
    && Array.isArray(r.candidate_products) && !!r.market_context_summary && r.requires_rm_review === true && r.execution_status === "NOT_EXECUTED"
    && r.portfolio_options.every((o) => typeof o?.option_id === "string" && Array.isArray(o?.asset_allocation) && Array.isArray(o?.product_selections));
  if (!ok) throw new PortfolioManagerError("INVALID_RESPONSE", "The Portfolio Manager's response did not match the expected format.");
  return r as PmResponse;
}

async function generatePortfolioProposals(req: PmRequest): Promise<PmResponse> {
  const body: PmRequest = { ...req, request_id: req.request_id ?? `IC-${req.client_id}-${Date.now()}` };
  return asProposal(await pmJson("/portfolio/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
}

async function getPortfolioProposal(requestId: string): Promise<PmResponse> {
  return asProposal(await pmJson(`/portfolio/${encodeURIComponent(requestId)}`, { method: "GET" }, 15_000));
}

async function evaluatePortfolioWeights(requestId: string, optionId: string, weights: Record<string, number>, signal?: AbortSignal): Promise<PmWeightEvaluation> {
  const json = await pmJson(`/portfolio/${encodeURIComponent(requestId)}/options/${encodeURIComponent(optionId)}/evaluate`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ weights }) }, 20_000, signal);
  const e = json as Partial<PmWeightEvaluation> | null;
  if (!e || !Array.isArray(e.lines) || !Array.isArray(e.checks) || !e.original || !e.adjusted || typeof e.valid !== "boolean") {
    throw new PortfolioManagerError("INVALID_RESPONSE", "The weight check response did not match the expected format.");
  }
  return e as PmWeightEvaluation;
}

/* ---------- Product Recommender agent (real backend) ---------- */

const PR_URL = `${API_BASE}/agents/product-recommender`;
const PR_TIMEOUT_MS = 30_000;

/** No mock fallback: the PS must never approve a list the agent did not produce. */
export class ProductRecommenderError extends Error {
  kind: "UNREACHABLE" | "TIMEOUT" | "REJECTED" | "NOT_FOUND" | "SERVER" | "INVALID_RESPONSE";
  details: string[];
  constructor(kind: ProductRecommenderError["kind"], message: string, details: string[] = []) {
    super(message);
    this.kind = kind;
    this.details = details;
  }
}

async function prFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${PR_URL}${path}`, { ...init, signal: AbortSignal.timeout(PR_TIMEOUT_MS) });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new ProductRecommenderError("TIMEOUT", "The Product Recommender did not respond in time.");
    }
    throw new ProductRecommenderError("UNREACHABLE", `Cannot reach the Product Recommender at ${API_BASE}.`, [
      "Start the backend: cd backend, then uvicorn app.app:app --reload",
    ]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    if (res.status === 422 && Array.isArray(detail)) {
      throw new ProductRecommenderError("REJECTED", "The Product Recommender rejected the inputs.",
        detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).filter((x) => x !== "body").join(" › ")}: ${d.msg ?? "invalid"}`));
    }
    throw new ProductRecommenderError("SERVER", `The Product Recommender returned an error (${typeof detail === "string" ? detail : `HTTP ${res.status}`}).`);
  }
  if (json === null || typeof json !== "object") throw new ProductRecommenderError("INVALID_RESPONSE", "The Product Recommender's response was not JSON.");
  return json as T;
}

/** Cached for the session; a failed call is not cached, so the next call retries. */
const once = <T,>(load: () => Promise<T>) => {
  let p: Promise<T> | null = null;
  return () => (p ??= load().catch((e) => { p = null; throw e; }));
};

const getShelf = once(async () => {
  const s = await prFetch<PrShelf>("/shelf");
  if (!Array.isArray(s.products)) throw new ProductRecommenderError("INVALID_RESPONSE", "The product shelf did not match the expected format.");
  return s;
});

const getHouseView = once(async () => {
  const hv = await prFetch<PrHouseView>("/house-view");
  if (!Array.isArray(hv.views)) throw new ProductRecommenderError("INVALID_RESPONSE", "The house view did not match the expected format.");
  return hv;
});

const toProduct = (p: PrShelfProduct): Product => ({
  id: p.product_id,
  name: p.product_name,
  assetClass: p.asset_class as ProductClass,
  whyBuy: p.why_buy ?? "",
  feePct: p.management_fee,
  stars: p.rating ?? 0,
  suitability: p.suitability_note ?? "",
  // The backend excludes a product with no risk rating; treat it as the highest risk here too.
  riskRating: p.risk_rating ?? 5,
  tags: [p.product_id],
});

/** A shortlist item as a chat row; carries the agent's cited reason through to the finalise page. */
export function shortlistRow(s: PrShortlistItem): MarketRow {
  const lines = toBulletItems(s.reason.text);
  return {
    assetClass: s.product.asset_class, product: s.product.product_name, industryFocus: s.product.why_buy ?? s.product.sub_asset_class ?? "",
    top5: [], confidencePct: (s.product.rating ?? 0) * 20, ranking: lines, agentReason: s.reason.text,
  };
}

const shelfRow = (p: PrShelfProduct): MarketRow => ({
  assetClass: p.asset_class, product: p.product_name, industryFocus: p.why_buy ?? p.sub_asset_class ?? "", top5: [], confidencePct: (p.rating ?? 0) * 20, ranking: [],
});

/** Mock cycle phase and events (Market Researcher seam) with the CIO views from the curated house view. */
async function cioBrief(): Promise<MacroBrief> {
  const hv = await getHouseView();
  const direction = { Buy: "Up", Hold: "Flat", Sell: "Down" } as const;
  return {
    ...m.macroBrief,
    views: hv.views.map((v) => ({ assetClass: v.asset_class, view: v.view, industry: v.cio_term, direction: direction[v.view], note: v.rationale })),
  };
}

async function recommendProducts(clientId: string, options: PrOptions = {}): Promise<PrResponse> {
  const { profile } = await buildClientProfile(clientId);
  const body: PrRequest = { request_id: `PS-${clientId}-${Date.now()}`, client_id: clientId, client_profile: profile, options };
  const r = await prFetch<PrResponse>("/recommend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const ok = Array.isArray(r.shortlist) && Array.isArray(r.excluded) && Array.isArray(r.named_products) && !!r.client_summary
    && r.shortlist.every((s) => s.costs?.display_only === true && typeof s.reason?.text === "string");
  if (!ok) throw new ProductRecommenderError("INVALID_RESPONSE", "The Product Recommender's response did not match the expected format.");
  return r;
}

/** "Fixed income" -> "fixed-income" (the backend accepts either). */
export const assetClassSlug = (assetClass: string) => assetClass.toLowerCase().replace(/\s+/g, "-");

async function getAssetClassView(assetClass: string, clientId?: string): Promise<PrAssetView> {
  const path = `/asset-class-views/${encodeURIComponent(assetClassSlug(assetClass))}`;
  const v = clientId
    ? await prFetch<PrAssetView>(path, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId, client_profile: (await buildClientProfile(clientId)).profile }) })
    : await prFetch<PrAssetView>(path);
  if (!v.cio_view || !Array.isArray(v.segments) || v.implementation?.fees?.display_only !== true) {
    throw new ProductRecommenderError("INVALID_RESPONSE", "The asset-class view did not match the expected format.");
  }
  return v;
}

/* ---------- Risk & Compliance agent (real backend) ---------- */

const RC_URL = `${API_BASE}/agents/risk-compliance`;
const RC_TIMEOUT_MS = 30_000;

/** No mock fallback: if the check cannot run, G4 stays locked. */
export class RiskComplianceError extends Error {
  kind: "UNREACHABLE" | "TIMEOUT" | "REJECTED" | "SERVER" | "INVALID_RESPONSE";
  details: string[];
  constructor(kind: RiskComplianceError["kind"], message: string, details: string[] = []) {
    super(message);
    this.kind = kind;
    this.details = details;
  }
}

/** What the RM's pack screen hands over; the client profile and data dates are added here. */
export interface PackCheckInput {
  clientId: string;
  sections: RcPackSection[];
  /** Allocation rows with the IC's saved new TAA applied. */
  allocation: AllocationRow[];
  /** The Product Specialist's finalised list (names; matched to the shelf by the agent). */
  products: { name: string; assetClass: string }[];
  gates: Partial<Record<GateId, GateState>>;
}

async function rcFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${RC_URL}${path}`, { ...init, signal: AbortSignal.timeout(RC_TIMEOUT_MS) });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new RiskComplianceError("TIMEOUT", "The Risk & Compliance check did not respond in time.");
    }
    throw new RiskComplianceError("UNREACHABLE", `Cannot reach the Risk & Compliance agent at ${API_BASE}.`, [
      "Start the backend: cd backend, then uvicorn app.app:app --reload",
    ]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    if (res.status === 422 && Array.isArray(detail)) {
      throw new RiskComplianceError("REJECTED", "The Risk & Compliance agent rejected the pack.",
        detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).filter((x) => x !== "body").join(" › ")}: ${d.msg ?? "invalid"}`));
    }
    throw new RiskComplianceError("SERVER", `The Risk & Compliance agent returned an error (${typeof detail === "string" ? detail : `HTTP ${res.status}`}).`);
  }
  if (json === null || typeof json !== "object") throw new RiskComplianceError("INVALID_RESPONSE", "The Risk & Compliance agent's response was not JSON.");
  return json as T;
}

const isoDate = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

async function checkReviewPack(input: PackCheckInput): Promise<RcPackReport> {
  const { clientId } = input;
  const [{ profile }, ips, market] = await Promise.all([
    buildClientProfile(clientId), arcApi.getIpsHistory(clientId), arcApi.getMarketCycle(),
  ]);
  const body: RcPackRequest = {
    request_id: `PACK-${clientId}-${Date.now()}`,
    client_id: clientId,
    reference_date: isoDate(new Date()),
    client_profile: profile,
    allocation: input.allocation.map((r) => ({ asset_class: r.assetClass, saa: r.saa, current: r.current, old_taa: r.oldTaa, new_taa: r.newTaa, band: r.band })),
    products: input.products.map((p) => ({ product_name: p.name, asset_class: p.assetClass })),
    sections: input.sections,
    gates: input.gates,
    // Unknown dates are sent as null so the agent reports them, instead of the UI guessing.
    data_as_of: { profile: ips.find((v) => v.status === "Active")?.issuedOn ?? null, market: market?.asOf ?? null },
  };
  const r = await rcFetch<RcPackReport>("/review-pack/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const ok = typeof r.status === "string" && typeof r.rm_signoff_allowed === "boolean" && Array.isArray(r.findings)
    && Array.isArray(r.missing_information) && Array.isArray(r.conflicts);
  if (!ok) throw new RiskComplianceError("INVALID_RESPONSE", "The Risk & Compliance agent's response did not match the expected format.");
  return r;
}
