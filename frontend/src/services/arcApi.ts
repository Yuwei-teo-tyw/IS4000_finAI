/* eslint-disable @typescript-eslint/no-unused-vars -- mock ignores args; signatures are the future backend contract */
/**
 * Single seam between pages and data. Today every function resolves mock data.
 * Later, swap bodies for LangGraph/REST calls; keep signatures stable so pages don't change.
 * Pages must NEVER import from src/mock directly.
 */
import * as m from "../mock/data";
import type {
  ActivityEvent, AllocationRow, Bucket3L, Citation, Client, Gate, Holding, InboxItem, IpsPart,
  MarketView, HouseView, MarketAnswer, MeetingNote, IpsVersion, PackSection, Product, Role, CaseStep, AllocationGroup, CorrelationMatrix, GoalProjection, SectionDraft,
} from "../types/arc";
import type { PmInputField, PmInputs, PmRequest, PmResponse } from "../types/portfolio";

const delay = <T,>(v: T, ms = 150) => new Promise<T>((r) => setTimeout(() => r(v), ms));

/** IC-edited 3L buckets, keyed by client (in memory, like ipsEdits). */
const saved3L: Record<string, Bucket3L[]> = {};

const tweak = (parts: IpsPart[], note: string): IpsPart[] =>
  parts.map((p) => ({ ...p, status: p.status === "blank" ? p.status : p.status === "locked" ? "locked" : "filled", body: p.body && p.part !== 6 ? `${p.body} (${note})` : p.body }));

/** In-memory edits keyed by `${clientId}:${version}` so previews reflect saved changes. */
const ipsEdits: Record<string, IpsPart[]> = {};

const buildIpsHistory = (clientId: string): IpsVersion[] => {
  const c = m.clients.find((x) => x.id === clientId);
  const parts = m.ipsPartsByClient[clientId] ?? m.ipsParts;
  if (!c) return [];
  if (c.status === "Onboarding Phase") {
    return c.id === "sha"
      ? [{ version: 1, issuedOn: "2026-10-15", status: "Draft", author: "Isabel", summary: "Onboarding draft. Parts 2 and 4 await the Investment Counsellor.", parts }]
      : [];
  }
  const v = c.ipsVersion ?? 1;
  const active: IpsVersion = { version: v, issuedOn: clientId === "ser" ? "2026-09-20" : clientId === "dso" ? "2026-03-18" : "2026-04-22", status: "Active", author: "Isabel", summary: clientId === "ser" ? "Updated for the house purchase and a higher liquidity need." : "Initial IPS approved after onboarding.", parts };
  if (v < 2) return [active];
  return [
    active,
    { version: v - 1, issuedOn: "2026-03-10", status: "Superseded", author: "Isabel", summary: "Original IPS from onboarding, before the house purchase.", parts: tweak(parts, "original wording, v1") },
  ];
};

const withEdits = (clientId: string, list: IpsVersion[]): IpsVersion[] =>
  list.map((v) => (ipsEdits[`${clientId}:${v.version}`] ? { ...v, parts: ipsEdits[`${clientId}:${v.version}`] } : v));

export const arcApi = {
  listClients: (): Promise<Client[]> => delay(m.clients),
  getClient: (id: string): Promise<Client | undefined> => delay(m.clients.find((c) => c.id === id)),
  getHoldings: (clientId: string): Promise<Holding[]> => delay(m.holdingsByClient[clientId] ?? m.holdings),
  getCorrelation: (_clientId: string): Promise<CorrelationMatrix> => delay({ labels: [...m.holdingLabels], matrix: m.holdingsCorrelation }),
  getAllocationGroups: (clientId: string): Promise<AllocationGroup[]> => delay(m.allocationGroupsFor(clientId)),
  getCaseTimeline: (clientId: string): Promise<CaseStep[]> => delay(m.caseTimelineByClient[clientId] ?? []),
  getGoalProjection: (clientId: string): Promise<GoalProjection> => delay(m.goalProjectionByClient[clientId] ?? m.goalProjectionByClient.ser),
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
  getAllocation: (clientId: string): Promise<AllocationRow[]> => delay(m.allocationByClient[clientId] ?? m.allocation),
  getSaaTemplates: () => delay(m.saaTemplates),
  getIps: (clientId: string): Promise<IpsPart[]> => delay(m.ipsPartsByClient[clientId] ?? m.ipsParts),
  getMeetingNotes: (clientId: string): Promise<MeetingNote[]> => delay(m.meetingNotes.filter((n) => n.clientId === clientId)),
  /** Newest first. Onboarding clients return [] or a single Draft. */
  getIpsHistory: (clientId: string): Promise<IpsVersion[]> => delay(withEdits(clientId, buildIpsHistory(clientId))),
  /** Mock save: stores edited parts in memory; getIpsHistory then returns them. */
  saveIpsVersion: async (clientId: string, version: number, parts: IpsPart[]): Promise<IpsVersion> => {
    ipsEdits[`${clientId}:${version}`] = parts.map((p) => ({ ...p }));
    const saved = withEdits(clientId, buildIpsHistory(clientId)).find((v) => v.version === version);
    if (!saved) throw new Error(`IPS v${version} not found`);
    return delay(saved, 400);
  },
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
  getMarketViews: (_clientId: string): Promise<MarketView[]> => delay(m.marketViews),
  getProducts: (_clientId: string): Promise<Product[]> => delay(m.products),
  /** Mock intent parser: decides which agents fire and what the reply contains. Replace with a LangGraph run. */
  askMarketResearch: async (_clientId: string, question: string, _systemPrompt = ""): Promise<MarketAnswer> => {
    const t = question.toLowerCase();
    const named = m.productCatalogue.filter((c) => c.aliases.some((a) => t.includes(a))).map((c) => c.row);
    const cls = /equit|stock/.test(t) ? "Equities" : /fixed|bond/.test(t) ? "Fixed income" : /altern|infra|hedge/.test(t) ? "Alternatives" : null;
    const wantsProducts = named.length > 0 || /product|fund|etf|note|suit|recommend|shortlist|top 5|ranking|fit|compare/.test(t);
    const wantsMarket = /macro|cycle|market|economy|cio|view|outlook|compare|suit|direction/.test(t) || !wantsProducts;
    const rows = !wantsProducts ? [] : named.length ? named : cls ? m.marketRows.filter((r) => r.assetClass === cls) : m.marketRows;
    const agents = [wantsMarket && "Market Research Agent", wantsProducts && "Product Recommender"].filter(Boolean) as string[];
    const steps = [
      "Intent parser is reading your request…",
      `${agents.join(" and ")} fired`,
      ...(wantsMarket ? ["Searching the web for macroeconomic events…"] : []),
      ...(wantsProducts ? [named.length ? `Checking ${named.length} requested product${named.length === 1 ? "" : "s"} against the IPS…` : "Screening products against the risk limit…"] : []),
      "Thinking…",
      "Consolidating…",
    ];
    await delay(null);
    const summary = named.length
      ? `I checked the ${named.length} product${named.length === 1 ? "" : "s"} you asked for. They are ticked as considerations. Untick any you do not want.`
      : wantsProducts ? "Here are the best-fit products. Rankings use suitability first. Fees were not used to rank."
      : "Here is the current market picture.";
    return { summary, market: wantsMarket ? m.macroBrief : null, rows, autoTick: named.length > 0, steps, tags: ["MKT-0142", "CIO-2026Q4-03"] };
  },
  getHouseViews: (_clientId: string): Promise<HouseView[]> => delay(m.houseViews),
  getPack: (_clientId: string): Promise<PackSection[]> => delay(m.packSections),
  getCitations: (_clientId: string): Promise<Citation[]> => delay(m.citations),
  getActivity: (_clientId: string): Promise<ActivityEvent[]> => delay(m.activity),

  /** Agent seam: replace with a LangGraph run. Returns an intent-routed mock reply for now. */
  askAgent: (role: Role, clientId: string, message: string): Promise<AgentReply> => answerAsAgent(role, clientId, message),
};

export type AgentName = "Profiling Agent" | "Portfolio Agent" | "Product Agent" | "Orchestrator";
export interface AgentReply { role: Role; clientId: string; reply: string; tags: string[]; agent: AgentName; steps: string[]; draft?: SectionDraft }

/** Keyword intent routing shared by the UI (status line) and the mock agent. */
export function routeAgent(message: string): AgentName {
  const t = message.toLowerCase();
  if (/\b(suits?|suitable|fits?|etf|funds?|products?)\b/.test(t)) return "Product Agent";
  if (/\b(ips|goals?|profile|meetings?|notes)\b/.test(t)) return "Profiling Agent";
  if (/\btaa\b|allocation/.test(t)) return "Portfolio Agent";
  if (t.includes("product")) return "Product Agent";
  return "Orchestrator";
}

const bullets = (items: string[]) => items.map((i) => `• ${i}`).join("\n");
const firstLine = (s: string) => s.replace(/\s+/g, " ").trim();
const clip = (s: string, n = 160) => { const x = firstLine(s); return x.length > n ? `${x.slice(0, n - 1)}…` : x; };

const sgdM = (n: number) => `S$${(n / 1_000_000).toFixed(1)}m`;

async function answerAsAgent(role: Role, clientId: string, message: string): Promise<AgentReply> {
  const t = message.toLowerCase();
  const agent = routeAgent(message);
  const [client, goals, notes, ips, alloc, products] = await Promise.all([
    arcApi.getClient(clientId), arcApi.getGoalProjection(clientId), arcApi.getMeetingNotes(clientId),
    arcApi.getIps(clientId), arcApi.getAllocation(clientId), arcApi.getProducts(clientId),
  ]);
  const name = client?.name ?? "the client";
  const base = { role, clientId, agent };
  const done = (reply: string, tags: string[], steps: string[]): AgentReply => ({ ...base, reply, tags, steps });

  const packKeys: [RegExp, number][] = [
    [/client summary|latest client|profile \+ goals|\bsaa\b|strategic asset/, 1], [/market view|cio view/, 2], [/market conditions/, 3],
    [/portfolio (current )?health|sharpe|diversif/, 4], [/old vs new|\btaa\b/, 5], [/product recommendation/, 6],
    [/sign-?off/, 7], [/sources|citations/, 8],
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
      const sentences = sec.body.split(/(?<=\.)\s+/).map(plain).filter(Boolean);
      const text = [...facts, ...sentences].map((x) => `• ${x.replace(/\.$/, "")}`).join("\n");
      return { ...base, agent: "Orchestrator", reply: `Here is a formal draft of section ${sec.n}, ${sec.title}, in bullet points. Review it, then apply it to the review pack.`, tags: [], steps: ["Opening the review pack…", `Reading section ${sec.n}…`, "Writing in a formal tone…", "Formatting as bullet points…"], draft: { section: sec.n, title: sec.title, text } };
    }
  }

  if (hit) {
    const pack = await arcApi.getPack(clientId);
    const sec = pack.find((x) => x.n === hit[1]);
    if (sec) {
      const items = [`Owner: ${sec.owner.toUpperCase()}. Status: ${sec.status}.`, ...sec.body.split(/(?<=\.)\s+/).filter(Boolean).map((x) => x.replace(/\s*\[[^\]]+\]/g, ""))];
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
    const named = products.find((p) => t.includes(p.name.toLowerCase()) || /pimco|balanced income/.test(t));
    if (/suits?|fits?|why/.test(t) && (named || /etf|fund/.test(t))) {
      const cap = client?.riskCap ?? 3;
      const cycle = await arcApi.getMarketCycle();
      const views = await arcApi.getMarketViews(clientId);
      const p = named ?? products[1] ?? products[0];
      const fiView = views.find((v) => v.assetClass === p.assetClass);
      const items = [
        `Profile: ${name} is ${client?.riskCategory ?? "n/a"} with a risk limit of ${cap}. ${p.name} is rated ${p.riskRating}, ${p.riskRating <= cap ? "inside the limit" : "above the limit"}.`,
        `Suitability: ${clip(p.suitability, 120)}.`,
        `Macro: the cycle is ${cycle.phase}. The house view on ${p.assetClass.toLowerCase()} is ${fiView?.view ?? "n/a"}. ${fiView ? clip(fiView.explanation, 110) : ""}`,
        `Fee ${p.feePct.toFixed(2)}% is shown for information and was not used to rank.`,
      ];
      return done(`Fit check for ${p.name}:\n${bullets(items)}`, [...p.tags.slice(0, 1), ...(fiView?.tags.slice(0, 1) ?? [])], ["Reading the client's profile and IPS…", "Running the suitability gate…", "Checking the house view…", "Drafting explanation…"]);
    }
    const cap = client?.riskCap;
    const fit = products.filter((p) => cap === undefined || p.riskRating <= cap).slice(0, 4);
    const reply = `Products that fit ${name}'s risk limit:\n${bullets(fit.map((p) => `${p.name} (${p.assetClass}, risk ${p.riskRating}): ${clip(p.suitability, 90)}`))}`;
    return done(reply, fit[0]?.tags.slice(0, 1) ?? [], ["Reading the product list…", "Checking the risk limit…", "Drafting shortlist…"]);
  }

  return done(`I can help with ${name}'s IPS, goals, meeting notes, TAA or products. Try one of the suggested questions.`, [], ["Understanding the question…", "Drafting reply…"]);
}

/* ---------- Portfolio Manager agent (real backend) ---------- */

/** Backend base URL: the main app (or `python -m app.agents.portfolio_manager serve`). Override with VITE_API_BASE. */
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");
const PM_URL = `${API_BASE}/agents/portfolio-manager`;
const PM_TIMEOUT_MS = 90_000; // generation can include an LLM call

export class PortfolioManagerError extends Error {
  kind: "UNREACHABLE" | "TIMEOUT" | "REJECTED" | "SERVER" | "INVALID_RESPONSE";
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
async function buildPortfolioInputs(clientId: string): Promise<PmInputs> {
  const [client, buckets, alloc, goals, inbox] = await Promise.all([
    arcApi.getClient(clientId), arcApi.get3L(clientId), arcApi.getAllocation(clientId),
    arcApi.getGoalProjection(clientId), arcApi.getInbox("ic"),
  ]);
  if (!client) throw new Error(`Unknown client ${clientId}`);
  const risk = m.ipsRiskByClient[clientId];
  const liquidity = buckets.find((b) => b.id === "liquidity")?.amountSgd ?? 0;
  const year = new Date().getFullYear();
  const dated = goals.events.map((e) => ({ ...e, years: e.year - year })).sort((a, b) => a.years - b.years);
  const near = dated.filter((e) => e.years <= 3);
  const later = dated.filter((e) => e.years > 3);
  const request = inbox.find((i) => i.clientId === clientId);
  const current = Object.fromEntries(alloc.map((r) => [r.assetClass, r.current]));

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
      client_profile: {
        client_id: clientId,
        base_currency: "SGD",
        total_aum: client.aumSgd,
        investable_assets: client.aumSgd,
        minimum_cash_reserve: liquidity,
        planned_withdrawals: 0,
        risk_appetite: client.riskCategory,
        risk_tolerance_score: client.riskCap,
        risk_capacity: risk?.riskCapacity ?? null,
        maximum_acceptable_drawdown: risk?.maxDrawdownPct ?? null,
        financial_goals: later.map((e) => ({ goal: e.label, years_to_goal: e.years, priority: /retire/i.test(e.label) ? "High" : "Medium", currency: "SGD" })),
        current_asset_allocation: current,
      },
    },
  };
}

async function generatePortfolioProposals(req: PmRequest): Promise<PmResponse> {
  const body: PmRequest = { ...req, request_id: req.request_id ?? `IC-${req.client_id}-${Date.now()}` };
  let res: Response;
  try {
    res = await fetch(`${PM_URL}/portfolio/generate`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(PM_TIMEOUT_MS),
    });
  } catch (err) {
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
    throw new PortfolioManagerError("SERVER", `The Portfolio Manager returned an error (${typeof detail === "string" ? detail : `HTTP ${res.status}`}).`);
  }
  const r = json as Partial<PmResponse> | null;
  const ok = !!r && typeof r.request_id === "string" && Array.isArray(r.portfolio_options) && Array.isArray(r.comparison_matrix)
    && Array.isArray(r.candidate_products) && !!r.market_context_summary && r.requires_rm_review === true && r.execution_status === "NOT_EXECUTED"
    && r.portfolio_options.every((o) => typeof o?.option_id === "string" && Array.isArray(o?.asset_allocation) && Array.isArray(o?.product_selections));
  if (!ok) throw new PortfolioManagerError("INVALID_RESPONSE", "The Portfolio Manager's response did not match the expected format.");
  return r as PmResponse;
}
