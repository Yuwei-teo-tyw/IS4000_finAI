/* eslint-disable @typescript-eslint/no-unused-vars -- mock ignores args; signatures are the future backend contract */
/**
 * Single seam between pages and data. Today every function resolves mock data.
 * Later, swap bodies for LangGraph/REST calls; keep signatures stable so pages don't change.
 * Pages must NEVER import from src/mock directly.
 */
import * as m from "../mock/data";
import type { ClientPortfolio, ThreeLValidation } from "../types/arc";
import { getActiveIps, isActivated, isIpsReturned, loadPmProgress } from "./workflowStore";
import { bulletLines, toBulletItems } from "../utils/bullets";
import { findProducts } from "../utils/productMatch";
import { askBackend, confirmBackendAction, fetchBackendArticle, newSessionId } from "./genevaBackend";
export { GenevaBackendError } from "./genevaBackend";
import { philosophySentence } from "./ipsText";
import type { BookClient, BookResult, ClientProfilingRequestOpts, ClientProfilingResult, IpsAssistMode, IpsAssistResult } from "../types/clientProfiling";
import type {
  ActivityEvent, AllocationRow, Bucket3L, Client, Gate, GateId, GateState, Holding, InboxItem, IpsPart, MacroBrief, MarketRow,
  MarketView, HouseView, PackRenderInput, MarketAnswer, MeetingNote, IpsVersion, PackSection, Product, ProductClass, Role, AllocationGroup, CorrelationMatrix, GoalProjection, SectionDraft, GenevaArticle, GenevaContext, GenevaReply, IpsGenSectionId, IpsGenSectionResult, IpsGenerated, IpsGenEvidence, Strategy, IpsChatMessage, IpsDiscussResult, IpsData,
} from "../types/arc";
import { PA_BUCKETS } from "../types/portfolio";
import type {
  PaAnswer, PaBucketChoice, PaBucketId, PaBucketInputs, PaChatReply, PaChatTurn, PaClientProfile, PaCombinedReview,
  PaInputField, PaInputs, PaRequest, PaResponse, PaWeightEvaluation,
} from "../types/portfolio";
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
/** Once the PM returned the IPS, parts 2 (3L buckets) and 4 (SAA) carry the PM's saved values. */
const withPmReturn = (clientId: string, parts: IpsPart[]): IpsPart[] => {
  if (!isIpsReturned(clientId)) return parts;
  const { buckets, saa, saaWeights, saaBuckets } = loadPmProgress(clientId);
  const fmtWeights = (w: Record<string, number>) => Object.entries(w).filter(([, v]) => v > 0).map(([a, v]) => `${a} ${+v.toFixed(2)}%`).join(", ");
  const perBucket = PA_BUCKETS.filter((b) => saaBuckets?.[b]?.optionId && saaBuckets[b]?.weights).map((b) => {
    const d = saaBuckets![b]!;
    return `• ${BUCKET_LABEL[b]} (S$${(d.amount ?? 0).toLocaleString("en-SG")}): Portfolio ${d.optionId}${d.optionName ? ` · ${d.optionName}` : ""}. ${fmtWeights(d.weights!)}`;
  });
  const bk = m.buckets3LByClient[clientId] ?? m.buckets3L;
  return parts.map((p) => {
    if (p.part === 2 && buckets && buckets.length === bk.length) {
      const tot = buckets.reduce((a, b) => a + b, 0) || 1;
      return { ...p, status: "filled", body: bk.map((b, i) => `• ${b.name ?? b.id}: ${Math.round((buckets[i] / tot) * 100)}% (S$${buckets[i].toLocaleString("en-SG")})`).join("\n") };
    }
    if (p.part === 4 && perBucket.length) {
      return { ...p, status: "filled", body: [...perBucket, ...(saaWeights ? [`• Whole portfolio: ${fmtWeights(saaWeights)}`] : [])].join("\n") };
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
      ? [{ version: 1, issuedOn: "2026-10-15", status: "Draft", author: "Isabel", summary: "Onboarding draft. Parts 2 and 4 await the Portfolio Manager.", parts }]
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

/** Backend IPS (database) is the source of truth for the read side; null when unreachable so callers fall back to mock. */
const fetchRemoteIps = async (clientId: string): Promise<{ current_version: number | null; versions: IpsVersion[] } | null> => {
  try {
    const res = await fetch(`${CP_URL}/ips/${encodeURIComponent(clientId)}`, { signal: AbortSignal.timeout(4000) });
    if (!res.ok) return null;
    const j = (await res.json()) as { current_version: number | null; versions: IpsVersion[]; client_name?: string; clientName?: string };
    if (!Array.isArray(j.versions)) return null;
    const cn = j.clientName ?? j.client_name;
    return { ...j, versions: j.versions.map((v) => ({ ...v, clientName: v.clientName ?? cn })) };
  } catch { return null; }
};

/** Local in-session workflow on top of the database copy: onboarding drafts activated here show Active, and the PM's returned 3L/SAA parts show on the newest version. */
const overlayIpsWorkflow = (clientId: string, list: IpsVersion[]): IpsVersion[] => {
  const base = m.clients.find((x) => x.id === clientId);
  if (!base || base.status !== "Onboarding Phase" || !list.length) return list;
  const activated = effective(base).status === "Monitoring Phase";
  return list.map((v, i) => (i === 0 ? { ...v, status: activated && v.status === "Draft" ? "Active" : v.status, parts: withPmReturn(clientId, v.parts) } : v));
};

const withEdits = (clientId: string, list: IpsVersion[]): IpsVersion[] =>
  list.map((v) => (ipsEdits[`${clientId}:${v.version}`] ? { ...v, parts: ipsEdits[`${clientId}:${v.version}`] } : v));

export interface ProfessionaliseInput {
  clientId: string; role: "rm" | "pm"; context: "ips" | "pack" | "products";
  items: { id: string; label: string; text: string }[]; chat?: string[];
}
const ROLE_DESC = { rm: "Relationship Manager", pm: "Portfolio Manager" } as const;
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

const RISK_CAP: Record<string, number> = { Conservative: 1, Moderate: 2, Balanced: 3, Growth: 4, Aggressive: 5 };
/** Backend book row -> Client view; fields the DB does not hold stay empty. */
export function bookToClient(b: BookClient): Client {
  const cat = b.risk_category ?? "";
  return {
    id: b.id, name: (b.surname && !b.name.includes(b.surname) ? `${b.name} ${b.surname}` : b.name) || b.id,
    riskCategory: cat as Client["riskCategory"], riskCap: RISK_CAP[cat] ?? 0, aumSgd: b.aum_sgd ?? 0,
    nextMeeting: "", nextQuarterlyReview: null,
    status: (b.status ?? "").toLowerCase().startsWith("monitor") ? "Monitoring Phase" : "Onboarding Phase",
    ipsVersion: null, sharpe: 0, diversificationScore: 0,
  };
}
/** Mock clients first; otherwise the RM's backend book (e.g. Jane Fraser `jft`). Undefined when neither has the id. */
async function getClient(id: string): Promise<Client | undefined> {
  const mock = m.clients.filter((c) => c.id === id).map(effective)[0];
  if (mock) return delay(mock);
  try {
    const row = (await listBook()).clients.find((c) => c.id === id);
    return row ? bookToClient(row) : undefined;
  } catch {
    return undefined;
  }
}

export const arcApi = {
  getStrategies: (): ReturnType<typeof getStrategies> => getStrategies(),
  logStrategyOverride: (i: Parameters<typeof logStrategyOverride>[0]) => logStrategyOverride(i),
  discussAllocation: (i: Parameters<typeof discussAllocation>[0]) => discussAllocation(i),
  listIpsChat: (c: string) => listIpsChat(c),
  listIpsChatPage: (c: string) => listIpsChatPage(c),
  appendIpsChat: (c: string, m: Parameters<typeof appendIpsChat>[1]) => appendIpsChat(c, m),
  clearIpsChat: (c: string) => clearIpsChat(c),
  listClients: (): Promise<Client[]> => delay(m.clients.map(effective)),
  getClient,
  getHoldings: (clientId: string): Promise<Holding[]> => delay(m.holdingsByClient[clientId] ?? m.holdings),
  getCorrelation: (_clientId: string): Promise<CorrelationMatrix> => delay({ labels: [...m.holdingLabels], matrix: m.holdingsCorrelation }),
  getAllocationGroups: (clientId: string): Promise<AllocationGroup[]> => delay(m.allocationGroupsFor(clientId)),
  getGoalProjection: (clientId: string): Promise<GoalProjection> => delay(m.goalProjectionByClient[clientId] ?? m.goalProjectionByClient.jfr),
  getHoldingClusters: (_clientId: string) => delay(m.holdingClusters),
  get3L: (clientId: string): Promise<Bucket3L[]> => delay(saved3L[clientId] ?? m.buckets3LByClient[clientId] ?? m.buckets3L),
  /** Mock save: keeps the PM's bucket amounts in memory so the SAA step and the Portfolio Agent use them. */
  save3L: (clientId: string, buckets: Bucket3L[]): Promise<Bucket3L[]> => {
    saved3L[clientId] = buckets.map((b) => ({ ...b }));
    return delay(saved3L[clientId]);
  },
  /** Portfolio Agent inputs derived from the 3L buckets, IPS part 3 and the goal plan (see buildPortfolioInputs). */
  getPortfolioInputs: (clientId: string): Promise<PaInputs> => buildPortfolioInputs(clientId),
  /** Real backend call: the Portfolio Agent builds and compares SAA templates A-F. */
  generatePortfolioProposals: (request: PaRequest): Promise<PaResponse> => generatePortfolioProposals(request),
  /** Real backend call: the Risk & Compliance agent's final check of the review pack. Never approves G4; it only says whether the RM may. */
  checkReviewPack: (input: PackCheckInput): Promise<RcPackReport> => checkReviewPack(input),
  /** A proposal generated earlier (kept by the backend), so Back does not re-run the agent. */
  getPortfolioProposal: (requestId: string): Promise<PaResponse> => getPortfolioProposal(requestId),
  /** Backend re-check of adjusted asset-class weights: risk, return, limits and the efficient frontier. */
  evaluatePortfolioWeights: (requestId: string, optionId: string, weights: Record<string, number>, signal?: AbortSignal): Promise<PaWeightEvaluation> =>
    evaluatePortfolioWeights(requestId, optionId, weights, signal),
  /** The three 3L buckets for the SAA step: amount, purpose, goals, default horizon and the request to send. */
  getBucketInputs: (clientId: string): Promise<PaBucketInputs[]> => buildBucketInputs(clientId),
  /** Backend check of the chosen portfolio for every bucket, as one client portfolio. Calculation only. */
  reviewCombined: (choices: PaBucketChoice[], clientTotal: number | null): Promise<PaCombinedReview> => reviewCombined(choices, clientTotal),
  /** Geneva chat: Client Profiling Agent (IPS and meeting notes; proposals only). */
  clientProfilingChat,
  /** RM Client Book from the backend DB (onboarding and monitoring progress included). */
  listBook,
  /** IS-75: server-side check that Liquidity + Longevity + Legacy = 100. */
  validateThreeLProportion: (v: { liquidity: number; longevity: number; legacy: number }): Promise<ThreeLValidation> => validateThreeLProportion(v),
  /** IPS section assist (write / professionalise); proposals only, the RM accepts. */
  ipsAssist,
  /**
   * Geneva chat: a question about the client's portfolio, answered by the Portfolio Agent from the
   * proposal the PM is working on (with their picked portfolio and edited weights), or, when there is none,
   * from a run made just for the chat (never written to the SAA request).
   */
  askPortfolioAgent: (clientId: string, question: string, history: PaChatTurn[] = []): Promise<PaChatReply> =>
    askPortfolioAgent(clientId, question, history),
  /** RM review pack generation (LangGraph backend): sections A-G, taa, products, holdings_shifts, sources, narrative_status, generated_at. Errors surface as the backend `detail`. */
  generateReviewPack: async (clientId: string, rmContext?: string): Promise<{ sections: { id: string; body: string; [k: string]: unknown }[]; taa?: unknown; products?: unknown; holdings_shifts?: unknown; sources?: unknown; narrative_status?: unknown; generated_at?: string; [k: string]: unknown }> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/review-pack/generate`, { method: "POST", headers: { "Content-Type": "application/json", ...rmHeaders() }, body: JSON.stringify({ client_id: clientId, rm_context: rmContext ?? "" }) });
    } catch { throw new Error(`Cannot reach the backend at ${API_BASE}, so the pack could not be generated.`); }
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof (json as { detail?: unknown }).detail === "string" ? (json as { detail: string }).detail : JSON.stringify((json as { detail?: unknown }).detail ?? `Request failed (${res.status})`));
    return json;
  },
  /** Review pack persistence (backend source of truth): one opaque state object per client. */
  getReviewPackStates: async (): Promise<Record<string, Record<string, unknown>>> => {
    const res = await fetch(`${API_BASE}/review-pack/states`, { headers: rmHeaders() });
    if (!res.ok) throw new Error(`Request failed (${res.status})`);
    return ((await res.json()) as { states?: Record<string, Record<string, unknown>> }).states ?? {};
  },
  getReviewPackState: async (clientId: string): Promise<Record<string, unknown> | null> => {
    const res = await fetch(`${API_BASE}/review-pack/state/${encodeURIComponent(clientId)}`, { headers: rmHeaders() });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Request failed (${res.status})`);
    return ((await res.json()) as { state: Record<string, unknown> }).state;
  },
  putReviewPackState: async (clientId: string, state: Record<string, unknown>): Promise<{ state: Record<string, unknown>; updated_at: string }> => {
    const res = await fetch(`${API_BASE}/review-pack/state/${encodeURIComponent(clientId)}`, { method: "PUT", headers: rmHeaders(), body: JSON.stringify({ state }) });
    if (!res.ok) throw new Error(`Request failed (${res.status})`);
    return res.json();
  },
  deleteReviewPackState: async (clientId: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/review-pack/state/${encodeURIComponent(clientId)}`, { method: "DELETE", headers: rmHeaders() });
    if (!res.ok && res.status !== 404) throw new Error(`Request failed (${res.status})`);
  },
  getAllocation: (clientId: string): Promise<AllocationRow[]> => delay(m.allocationByClient[clientId] ?? m.allocation),
  getSaaTemplates: () => delay(m.saaTemplates),
  /** Save an IPS (new version, or edit when `version` is set); the backend vectorizes it. Returns the confirmation text ("IPS v3 indexed" / "IPS saved, but not yet searchable"); throws the backend message (e.g. "Client is not in your book"). */
  /** Deletes one IPS version from the database (and any local edits of it). Throws when the backend cannot delete it. */
  deleteIps: async (clientId: string, version: number): Promise<void> => {
    await cpJson<{ deleted: boolean }>(`/ips/${encodeURIComponent(clientId)}/${version}`, { method: "DELETE" });
    delete ipsEdits[`${clientId}:${version}`];
  },
  /** IS-97: portfolio of a client. null = not in the RM's book (403/404) or portfolio data unavailable. A client with no holdings returns the status "no_holdings" payload (AUM label "No holdings yet", no value), not null. */
  getClientPortfolio: async (clientId: string): Promise<ClientPortfolio | null> => {
    // Not in the book (403) or unknown (404) = no portfolio, no tab. A network failure, timeout or 5xx throws so the page can offer Retry.
    const res = await fetch(`${API_BASE}/agents/client-portfolio/${encodeURIComponent(clientId)}`, { headers: rmHeaders(), signal: AbortSignal.timeout(CP_TIMEOUT_MS) });
    if (res.status === 403 || res.status === 404 || res.status === 503) return null;  // 503 = portfolio database unreachable: the page says so and shows no numbers
    if (!res.ok) throw new Error(`Portfolio request failed (${res.status})`);
    const r = (await res.json().catch(() => null)) as ClientPortfolio | null;
    return r?.available && (r.status === "ok" || r.status === "no_holdings" || r.status === "no_priced_holdings") ? r : null;
  },
  /** IS-101: current send-to-PM status of the client's IPS (Draft / Sent to PM / Returned by PM / No IPS) and whether the PM's copy is older than the latest save. */
  /** PM hand-over (DB-backed client): working 3L + SAA seeded from the RM-sent IPS. Liquidity never has an SAA. */
  getPmIps: (clientId: string): Promise<PmIps> => cpJson<PmIps>(`/pm-ips/${encodeURIComponent(clientId)}`),
  savePmIps: (clientId: string, edit: PmIpsEdit): Promise<PmIps> => cpJson<PmIps>(`/pm-ips/${encodeURIComponent(clientId)}`, { method: "PUT", body: JSON.stringify(edit) }),
  returnPmIps: (clientId: string): Promise<{ status: string; version: number; returnedAt: string }> => cpJson(`/pm-ips/${encodeURIComponent(clientId)}/return`, { method: "POST" }),
  /** G1: the backend sets IpsVersion.status = Active (older ones Superseded) and moves the client to Monitoring. Required before a pack can be generated. */
  activateIpsVersion: (clientId: string, version: number): Promise<{ client_id: string; version: number; status: string; clientStatus: string }> => cpJson(`/ips/${encodeURIComponent(clientId)}/${version}/activate`, { method: "POST" }),
  getIpsSendStatus: (clientId: string): Promise<IpsSendStatus> => cpJson<IpsSendStatus>(`/ips-send/${encodeURIComponent(clientId)}`),
  /** Sends one IPS version (null = latest) to the PM. Throws IpsSendError (message is shown to the RM) when it is not sent. */
  sendIpsToPm: async (clientId: string, version: number | null): Promise<IpsSendResult> => {
    let res: Response;
    try {
      res = await fetch(`${CP_URL}/ips-send/${encodeURIComponent(clientId)}`, { method: "POST", headers: rmHeaders(), body: JSON.stringify({ version }), signal: AbortSignal.timeout(CP_TIMEOUT_MS) });
    } catch { throw new IpsSendError("Not sent. The IPS is still a Draft."); }
    const j = (await res.json().catch(() => null)) as (Partial<IpsSendResult> & { detail?: unknown; message?: string }) | null;
    if (!res.ok || !j || j.status !== "Sent to PM") {
      if (res.status === 409 && typeof j?.detail === "string") throw new IpsSendError(j.detail);
      throw new IpsSendError("Not sent. The IPS is still a Draft.");
    }
    return { status: "Sent to PM", version: Number(j.version), sentAt: String(j.sentAt), emptySections: Array.isArray(j.emptySections) ? j.emptySections : [] };
  },
  /** Pulls the sent IPS back to Draft. */
  withdrawIpsSend: async (clientId: string): Promise<void> => { await cpJson<{ status: string }>(`/ips-send/${encodeURIComponent(clientId)}`, { method: "DELETE" }); },
  /** The exact IPS (content + version) that was sent to the PM; null when nothing was sent through the backend (legacy flag) or the backend is unreachable. */
  getSentIpsSnapshot: async (clientId: string): Promise<IpsVersion | null> => {
    try {
      const j = await cpJson<Partial<IpsVersion> & { ips?: IpsVersion; sentAt?: string }>(`/ips-send/${encodeURIComponent(clientId)}/snapshot`);
      const v = (j.ips ?? j) as IpsVersion & { sentAt?: string };
      if (!v || typeof v.version !== "number" || !Array.isArray(v.parts)) return null;
      return { ...v, sentAt: j.sentAt ?? v.sentAt } as IpsVersion;
    } catch { return null; }
  },
  saveClientIps: async (clientId: string, parts: { part: number; title: string; owner?: string; status?: string; body: string }[], opts: { version?: number; summary?: string; author?: string; status?: "Active" | "Draft"; data?: IpsData } = {}): Promise<{ version: number; indexing: { status: "indexed" | "pending"; chunks: number; message: string } }> => {
    const res = await fetch(`${CP_URL}/ips/${encodeURIComponent(clientId)}`, {
      method: "POST", headers: rmHeaders(), body: JSON.stringify({ parts, ...opts }),
    });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof j.detail === "string" ? j.detail : "IPS could not be saved");
    return { version: j.ips.version, indexing: j.indexing };
  },
  /** The IPS template with every field empty: what a brand-new onboarder's IPS starts from (same parts and layout as any IPS). */
  getBlankIpsParts: (): Promise<IpsPart[]> => delay(m.ipsParts.map((p) => ({ ...p, status: "blank" as const, body: "" }))),
  /** The 3L buckets with names and horizons but no amounts or purposes, for a blank IPS. */
  getBlank3L: (): Promise<Bucket3L[]> => delay(m.buckets3L.map((b) => ({ ...b, amountSgd: 0, pct: 0, purpose: "" }))),
  /** The IPS version the editor opens: `version` if given, else the newest Draft, else the current/newest one. Null when the backend has none (mock fallback). */
  getIpsVersionRecord: async (clientId: string, version?: number): Promise<IpsVersion | null> => {
    const remote = await fetchRemoteIps(clientId);
    if (!remote || !remote.versions.length) return null;
    const vs = remote.versions;
    return (version ? vs.find((x) => x.version === version) : undefined)
      ?? (version ? undefined : [...vs].filter((x) => x.status === "Draft").sort((a, b) => b.version - a.version)[0])
      ?? vs.find((x) => x.version === remote.current_version) ?? vs[0] ?? null;
  },
  /** Writes a confirmed 3L allocation into the client's saved DRAFT IPS (data.threeL) when no editor is open. Never touches an Active IPS. Returns whether it saved. */
  applyAllocationToIps: async (clientId: string, buckets: { id: string; strategy: string; strategyName?: string; justification?: string }[]): Promise<boolean> => {
    const rec = await arcApi.getIpsVersionRecord(clientId);
    if (!rec || rec.status !== "Draft" || !rec.data) return false;
    const old = new Map((rec.data.threeL ?? []).map((b) => [String(b.portfolio).toLowerCase(), b]));
    const threeL = buckets.map((b) => {
      const o = old.get(b.id);
      return { ...o, portfolio: b.id[0].toUpperCase() + b.id.slice(1), strategy: b.strategy, strategyName: b.strategyName ?? o?.strategyName ?? "",
        reason: b.justification || o?.reason || "", default: o?.strategy === b.strategy ? !!o?.default : false };
    });
    try {
      await arcApi.saveClientIps(clientId, rec.parts.map((p) => ({ part: p.part, title: p.title, owner: p.owner, status: p.status, body: p.body })),
        { version: rec.version, author: "Relationship Manager", data: { ...rec.data, threeL } });
      return true;
    } catch { return false; }
  },
  getIps: async (clientId: string): Promise<IpsPart[]> => {
    const remote = await fetchRemoteIps(clientId);
    if (remote && remote.versions.length) {
      const v = remote.versions.find((x) => x.version === remote.current_version) ?? remote.versions[0];
      return delay(withPmReturn(clientId, v.parts));
    }
    return delay(withPmReturn(clientId, m.ipsPartsByClient[clientId] ?? m.ipsParts));
  },
  /** The backend is the source of truth when it responds (its version replaces local copies with the same id); backend down => local only. */
  getMeetingNotes: async (clientId: string): Promise<MeetingNote[]> => {
    try {
      const res = await fetch(`${CP_URL}/meeting-notes/${encodeURIComponent(clientId)}`, { signal: AbortSignal.timeout(4000) });
      if (res.ok) {
        const remote = ((await res.json()) as MeetingNote[]).filter((n) => n.clientId === clientId);
        const rids = new Set(remote.map((n) => n.id));
        const others = m.meetingNotes.filter((n) => n.clientId !== clientId || !rids.has(n.id));
        m.meetingNotes.splice(0, m.meetingNotes.length, ...remote, ...others);
      }
    } catch { /* backend unavailable: show the local notes */ }
    return delay(m.meetingNotes.filter((n) => n.clientId === clientId));
  },
  /** Newest first. Onboarding clients return [] or a single Draft. */
  getIpsHistory: async (clientId: string): Promise<IpsVersion[]> => {
    const remote = await fetchRemoteIps(clientId);
    return delay(withEdits(clientId, remote ? overlayIpsWorkflow(clientId, remote.versions) : buildIpsHistory(clientId)));
  },
  /** Uploads the file to the backend meeting-notes database (PDF/TXT text is extracted there) and mirrors the stored note locally. Errors are surfaced, never faked. */
  uploadMeetingNote: async (clientId: string, file: File): Promise<MeetingNote> => {
    const body = new FormData();
    body.append("client_id", clientId);
    body.append("file", file);
    let res: Response;
    try { res = await fetch(`${CP_URL}/meeting-notes`, { method: "POST", body, signal: AbortSignal.timeout(60_000) }); }
    catch { throw new ClientProfilingError("UNREACHABLE", `Cannot reach the backend at ${API_BASE}, so ${file.name} was not saved.`); }
    const json: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = (json as { detail?: unknown } | null)?.detail;
      throw new ClientProfilingError("REJECTED", typeof detail === "string" ? `${file.name}: ${detail}` : `${file.name}: upload failed (HTTP ${res.status}).`);
    }
    const note = json as MeetingNote;
    if (!m.meetingNotes.some((n) => n.id === note.id)) m.meetingNotes.unshift(note);
    return note;
  },
  /** Saves the edit to the backend meeting-notes database, then refreshes the local copy. Errors are surfaced, never faked. */
  updateMeetingNote: async (noteId: string, patch: { title: string; originalText: string; date?: string }): Promise<MeetingNote> => {
    const note = m.meetingNotes.find((n) => n.id === noteId);
    if (!note) throw new Error(`Meeting note ${noteId} not found`);
    let res: Response;
    try {
      res = await fetch(`${CP_URL}/meeting-notes/${encodeURIComponent(note.clientId)}/${encodeURIComponent(noteId)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: patch.title, original_text: patch.originalText, ...(patch.date ? { date: patch.date } : {}) }), signal: AbortSignal.timeout(15_000),
      });
    } catch { throw new ClientProfilingError("UNREACHABLE", `Cannot reach the backend at ${API_BASE}, so the edit was not saved.`); }
    const json: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = (json as { detail?: unknown } | null)?.detail;
      const msg = typeof detail === "string" ? detail : `Saving the edit failed (HTTP ${res.status}).`;
      throw new ClientProfilingError(res.status === 404 ? "NOT_FOUND" : res.status >= 500 ? "SERVER" : "REJECTED", msg);
    }
    const saved = json as MeetingNote;
    Object.assign(note, saved);
    return note;
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
  /** PM product questions in the Geneva chat: CIO house view and product tables (Product Recommender). Null = not a product question; ask the backend. */
  answerProductsLocally: (clientId: string, text: string, ipsVersion: number | null = null): Promise<MarketAnswer | null> => answerProductsLocally(clientId, text, ipsVersion),
  /**
   * Geneva chat, local half: client-data and workflow intents answered from the workspace (IPS, goals, notes,
   * holdings/TAA, pack drafts, CIO house view, product tables). Returns null when the question is not one of
   * those; the chat then sends it to the LangGraph backend (`askBackend`).
   */
  answerLocally: async (role: Role, clientId: string, text: string, ipsVersion: number | null = null): Promise<MarketAnswer | null> => {
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

/** PM product chat, local half: CIO house view and product tables (Product Recommender). Null = ask the backend. */
async function answerProductsLocally(clientId: string, question: string, ipsVersion: number | null): Promise<MarketAnswer | null> {
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

/** RM/PM chat, local half. Null = not a client-data or workflow question; Geneva sends it to the backend. */
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

  if (role === "pm") {
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
      return done(`Holdings against the new TAA for ${name}:\n${bullets(lines)}\n${tail}\nApply them on the Individual holdings step: /pm/cases/${clientId}/holdings. Draft only, for your review.`, ["PORT-HOLD", "CIO-2026Q4-05"], ["Reading the client's holdings…", "Reading the new TAA…", "Comparing weights per asset class…", "Drafting suggested edits…"]);
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
      const who = sec.owner === "pm" ? "the Portfolio Manager (Wei Lun)" : "the Relationship Manager (Isabel)";
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

/* ---------- Portfolio Agent (real backend) ---------- */

/** Backend base URL: the main app (or `python -m app.agents.portfolio_agent serve`). Override with VITE_API_BASE. */
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");
const PA_URL = `${API_BASE}/agents/portfolio-agent`;
const PA_TIMEOUT_MS = 90_000; // generation can include an LLM call

export class PortfolioAgentError extends Error {
  kind: "UNREACHABLE" | "TIMEOUT" | "REJECTED" | "NOT_FOUND" | "SERVER" | "INVALID_RESPONSE";
  details: string[];
  constructor(kind: PortfolioAgentError["kind"], message: string, details: string[] = []) {
    super(message);
    this.kind = kind;
    this.details = details;
  }
}

/* ---- Client Profiling Agent: IPS and meeting-note questions. Proposals only; nothing is saved or executed. ---- */
const CP_URL = `${API_BASE}/agents/client-profiling`;
const CP_TIMEOUT_MS = 90_000;
/** The RM whose IPS chat history and override audit rows are scoped by the backend (header X-RM-Id). No auth yet: the backend's default RM. */
export const CURRENT_RM_ID = "rm_default";
/** Chat history and audit rows are scoped by this id. The PM gets its own id so RM and PM never share chat histories. */
export const chatOwnerId = (): string => (typeof window !== "undefined" && window.location.pathname.startsWith("/pm") ? "pm_default" : CURRENT_RM_ID);
const rmHeaders = (): Record<string, string> => ({ "Content-Type": "application/json", "X-RM-Id": chatOwnerId() });
/** IS-101 send-to-PM contract. */
export type PmIpsBucketId = "liquidity" | "longevity" | "legacy";
export interface PmIps {
  client_id: string; clientName: string; status: string; version: number; returned: boolean; snapshotVersion: number; sentAt: string | null; total: number; edited: boolean; updatedAt: string;
  threeL: Record<PmIpsBucketId, { pct: number | null; amount: number | null; reason: string }>;
  saa: Record<"longevity" | "legacy", { strategy: string | null; optionId: string | null; source: "rm" | "pm"; weights: Record<string, number> | null; reason: string }>;
}
export interface PmIpsEdit {
  threeL?: Partial<Record<PmIpsBucketId, { pct: number }>>;
  saa?: Partial<Record<"longevity" | "legacy", { strategy: string; weights?: Record<string, number>; reason?: string }>>;
  reason?: string;
}
export interface IpsSendStatus { sent: boolean; status: "Draft" | "Sent to PM" | "Returned by PM" | "No IPS"; sentVersion: number | null; sentAt: string | null; latestVersion: number | null; outdated: boolean; message: string }
export interface IpsSendResult { status: "Sent to PM"; version: number; sentAt: string; emptySections: string[] }
export class IpsSendError extends Error {}
export class ClientProfilingError extends Error {
  kind: "UNREACHABLE" | "TIMEOUT" | "REJECTED" | "NOT_FOUND" | "SERVER" | "INVALID_RESPONSE";
  details: string[];
  constructor(kind: ClientProfilingError["kind"], message: string, details: string[] = []) {
    super(message);
    this.kind = kind;
    this.details = details;
  }
}
/** The IPS chat history database is down (HTTP 503 {historyAvailable:false}); the conversation continues in the session only. */
export class HistoryUnavailableError extends ClientProfilingError {
  constructor() { super("SERVER", "History unavailable. This conversation continues for this session but is not saved."); }
}
export async function clientProfilingChat(clientId: string, text: string, ipsVersion?: number | null, opts: ClientProfilingRequestOpts = {}): Promise<ClientProfilingResult> {
  let res: Response;
  try {
    res = await fetch(`${CP_URL}/chat`, {
      method: "POST", headers: rmHeaders(),
      body: JSON.stringify({ message: text, client_id: clientId, ...(ipsVersion != null ? { ips_version: ipsVersion } : {}), ...(opts.source ? { source: opts.source } : {}),
        ...(opts.allocation ? { allocation: opts.allocation } : {}), ...(opts.pending_proposal ? { pending_proposal: opts.pending_proposal } : {}) }),
      signal: AbortSignal.timeout(CP_TIMEOUT_MS),
    });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) throw new ClientProfilingError("TIMEOUT", "The Client Profiling Agent did not respond in time.");
    throw new ClientProfilingError("UNREACHABLE", `Cannot reach the Client Profiling Agent at ${API_BASE}.`, ["Start the backend: cd backend, then run the main app."]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    if (res.status === 422 && Array.isArray(detail)) {
      throw new ClientProfilingError("REJECTED", "The Client Profiling Agent rejected the request.",
        detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).filter((x) => x !== "body").join(" › ")}: ${d.msg ?? "invalid"}`));
    }
    const msg = typeof detail === "string" ? detail : `HTTP ${res.status}`;
    if (res.status === 404) throw new ClientProfilingError("NOT_FOUND", msg === "Not Found" ? "The running backend does not have the Client Profiling Agent yet. Restart it so it runs the latest code." : msg);
    throw new ClientProfilingError("SERVER", `The Client Profiling Agent returned an error (${msg}).`);
  }
  const r = json as Partial<ClientProfilingResult> | null;
  if (!r || typeof r.tool !== "string" || typeof r.status !== "string" || typeof r.message !== "string") {
    throw new ClientProfilingError("INVALID_RESPONSE", "The Client Profiling Agent's response did not match the expected format.");
  }
  return { ...r, data: r.data ?? {}, sources: r.sources ?? [], candidates: r.candidates ?? [] } as ClientProfilingResult;
}

/** The RM's client book from the backend client book DB (single source of truth). Never falls back to mock data. */
export async function listBook(): Promise<BookResult> {
  let res: Response;
  try {
    res = await fetch(`${CP_URL}/book`, { signal: AbortSignal.timeout(15_000) });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) throw new ClientProfilingError("TIMEOUT", "The client book did not load in time.");
    throw new ClientProfilingError("UNREACHABLE", `Cannot reach the backend at ${API_BASE}, so the client book cannot be loaded.`, ["Start the backend: cd backend, then run the main app."]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    if (res.status === 503) throw new ClientProfilingError("SERVER", "The client database is unavailable.");
    if (res.status === 404) throw new ClientProfilingError("NOT_FOUND", "The running backend does not have the client book yet. Restart it so it runs the latest code.");
    throw new ClientProfilingError("SERVER", `The client book returned an error (${typeof detail === "string" ? detail : `HTTP ${res.status}`}).`);
  }
  const r = json as Partial<BookResult> | null;
  if (!r || !Array.isArray(r.clients)) throw new ClientProfilingError("INVALID_RESPONSE", "The client book response did not match the expected format.");
  return { clients: r.clients, ...(r.message ? { message: r.message } : {}) };
}

export async function ipsAssist(req: { clientId: string; section: string; mode: IpsAssistMode; currentText: string; selection?: string; message: string }): Promise<IpsAssistResult> {
  let res: Response;
  try {
    res = await fetch(`${CP_URL}/ips-assist`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: req.clientId, section: req.section, mode: req.mode, current_text: req.currentText, selection: req.selection ?? "", message: req.message }),
      signal: AbortSignal.timeout(CP_TIMEOUT_MS),
    });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) throw new ClientProfilingError("TIMEOUT", "Geneva did not respond in time.");
    throw new ClientProfilingError("UNREACHABLE", `Cannot reach the Client Profiling Agent at ${API_BASE}.`, ["Start the backend: cd backend, then run the main app."]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail : `HTTP ${res.status}`;
    if (res.status === 404) throw new ClientProfilingError("NOT_FOUND", msg === "Not Found" ? "The running backend does not have IPS assist yet. Restart it so it runs the latest code." : msg);
    if (res.status === 422) throw new ClientProfilingError("REJECTED", "Geneva rejected the request.");
    throw new ClientProfilingError("SERVER", `Geneva returned an error (${msg}).`);
  }
  const r = json as Partial<IpsAssistResult> | null;
  if (!r || typeof r.status !== "string" || typeof r.message !== "string") throw new ClientProfilingError("INVALID_RESPONSE", "Geneva's response did not match the expected format.");
  return { original: "", revised: "", ...r, notes: r.notes ?? [], sources: r.sources ?? [] } as IpsAssistResult;
}

/** AI IPS generation: one section per call. The backend auto-saves a Draft version; pass the `version` of the first response to keep filling the same draft. */
export async function generateIpsSection(clientId: string, section: IpsGenSectionId, version?: number | null): Promise<IpsGenSectionResult> {
  let res: Response;
  try {
    res = await fetch(`${CP_URL}/ips-generate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId, section, ...(version ? { version } : {}) }),
      signal: AbortSignal.timeout(CP_TIMEOUT_MS),
    });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) throw new ClientProfilingError("TIMEOUT", "Geneva did not respond in time.");
    throw new ClientProfilingError("UNREACHABLE", `Cannot reach the Client Profiling Agent at ${API_BASE}.`, ["Start the backend: cd backend, then run the main app."]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail : `HTTP ${res.status}`;
    if (res.status === 403) throw new ClientProfilingError("REJECTED", msg);
    if (res.status === 503) throw new ClientProfilingError("SERVER", "The client database is unavailable.");
    if (res.status === 404) throw new ClientProfilingError("NOT_FOUND", msg === "Not Found" ? "The running backend does not have AI IPS generation yet. Restart it so it runs the latest code." : msg);
    if (res.status === 422) throw new ClientProfilingError("REJECTED", "Geneva rejected the request.");
    throw new ClientProfilingError("SERVER", `Geneva returned an error (${msg}).`);
  }
  const r = json as Partial<IpsGenSectionResult> | null;
  if (!r || typeof r.status !== "string" || typeof r.message !== "string") throw new ClientProfilingError("INVALID_RESPONSE", "Geneva's response did not match the expected format.");
  return { section, fields: {}, bullets: [], sources: [], ...r } as IpsGenSectionResult;
}

/** Final NDJSON line of the stream: the single autosave of the new Draft version. */
export interface IpsGenStreamDone { saved: boolean; version: number | null; ips: unknown; model: string | null; modelMessage: string; error?: string }
/**
 * AI IPS generation, streamed: the backend runs the sections concurrently, sends one NDJSON line per section as it finishes
 * (`onSection`), then ONE line with the single autosaved Draft version. Resolves with that final line, or null when the stream
 * ended without it (connection died mid-way: whatever arrived through `onSection` is what finished). Throws ClientProfilingError
 * when the backend is unreachable / rejects the request, and an AbortError DOMException when `signal` aborts.
 */
export async function streamIpsGeneration(
  clientId: string,
  handlers: { onStart?: (sections: IpsGenSectionId[]) => void; onSection: (r: IpsGenSectionResult) => void },
  signal?: AbortSignal,
): Promise<IpsGenStreamDone | null> {
  let res: Response;
  try {
    res = await fetch(`${CP_URL}/ips-generate/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_id: clientId }), signal,
    });
  } catch (err) {
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    throw new ClientProfilingError("UNREACHABLE", `Cannot reach the Client Profiling Agent at ${API_BASE}.`, ["Start the backend: cd backend, then run the main app."]);
  }
  if (!res.ok || !res.body) {
    const json: unknown = await res.json().catch(() => null);
    const detail = (json as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail : `HTTP ${res.status}`;
    if (res.status === 403) throw new ClientProfilingError("REJECTED", msg);
    if (res.status === 503) throw new ClientProfilingError("SERVER", "The client database is unavailable.");
    if (res.status === 404 || res.status === 405) throw new ClientProfilingError("NOT_FOUND", "The running backend does not have streamed AI IPS generation yet. Restart it so it runs the latest code.");
    throw new ClientProfilingError("SERVER", `Geneva returned an error (${msg}).`);
  }
  let done: IpsGenStreamDone | null = null;
  const handle = (line: string) => {
    if (!line.trim()) return;
    let o: Record<string, unknown>;
    try { o = JSON.parse(line) as Record<string, unknown>; } catch { return; }
    if (o.type === "start") handlers.onStart?.((o.sections as IpsGenSectionId[]) ?? []);
    else if (o.type === "section" && typeof o.section === "string") {
      const { type: _t, ...r } = o;
      handlers.onSection({ fields: {}, bullets: [], sources: [], message: "", status: "error", ...r } as unknown as IpsGenSectionResult);
    } else if (o.type === "done") done = o as unknown as IpsGenStreamDone;
  };
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n")) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 1); }
    }
    handle(buf);
  } catch (err) {
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    return done; // stream died mid-way: the caller reports what finished
  }
  return done;
}

/** Pure: merge the section results into what the IPS editor prefills. Empty values are dropped. */
export function mergeIpsGenerated(results: IpsGenSectionResult[]): IpsGenerated {
  const keep = (o: Record<string, string> | undefined, keys: string[]) => {
    const out: Record<string, string> = {};
    for (const k of keys) { const v = (o?.[k] ?? "").trim(); if (v) out[k] = v; }
    return out;
  };
  const by = (id: IpsGenSectionId) => results.find((r) => r.section === id);
  const join = (b?: string[]) => (b ?? []).map((x) => x.trim()).filter(Boolean).join("\n");
  const philosophy: IpsGenerated["philosophy"] = {};
  for (const k of ["approach", "believes", "avoids", "investmentPeriod"] as const) { const v = (by("philosophy")?.philosophy?.[k] ?? "").trim(); if (v) philosophy[k] = v; }
  const statement = philosophySentence(philosophy); if (statement) philosophy.statement = statement;
  const text: IpsGenerated["text"] = {};
  const goals = join(by("goals")?.bullets); if (goals) text[1] = goals;
  const loss = join(by("risk")?.bullets); if (loss) text[3] = loss;
  const seen = new Set<string>(); const sources: IpsGenerated["sources"] = [];
  for (const r of results) for (const s of r.sources ?? []) if (s.id && !seen.has(s.id)) { seen.add(s.id); sources.push(s); }
  const ev = new Set<string>(); const evidence: IpsGenEvidence[] = [];
  for (const r of results) for (const e of r.evidence ?? []) { const key = `${e.noteId}|${e.item}`; if (!ev.has(key)) { ev.add(key); evidence.push(e); } }
  const alloc = by("allocation")?.allocation;
  const model = results.find((r) => r.model)?.model;
  const allocRes = by("allocation");
  return {
    ...(allocRes?.proportion ? { proportion: allocRes.proportion } : {}),
    ...(allocRes?.proportionMissing?.length ? { proportionMissing: allocRes.proportionMissing } : {}),
    ...(alloc && alloc.buckets?.length ? { allocation: alloc } : {}),
    ...(model ? { model } : {}),
    demo: keep(by("demographics")?.fields, ["Date of birth / age", "Occupation", "Employment / income source", "Annual income", "AUM"]),
    risk: keep(by("risk")?.fields, ["Risk category", "Risk tolerance (willingness)", "Risk capacity (ability)", "Time horizon", "Liquidity needs"]),
    philosophy, text, sources, evidence,
  };
}

/** Shared fetch for the Client Profiling Agent's JSON endpoints. */
async function cpJson<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${CP_URL}${path}`, { ...init, headers: rmHeaders(), signal: AbortSignal.timeout(CP_TIMEOUT_MS) });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) throw new ClientProfilingError("TIMEOUT", "Geneva did not respond in time.");
    throw new ClientProfilingError("UNREACHABLE", `Cannot reach the Client Profiling Agent at ${API_BASE}.`, ["Start the backend: cd backend, then run the main app."]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail : `HTTP ${res.status}`;
    if (res.status === 403) throw new ClientProfilingError("REJECTED", msg);
    if (res.status === 503 && (json as { historyAvailable?: unknown } | null)?.historyAvailable === false) throw new HistoryUnavailableError();
    if (res.status === 404) throw new ClientProfilingError("NOT_FOUND", msg === "Not Found" ? "The running backend does not have this feature yet. Restart it so it runs the latest code." : msg);
    throw new ClientProfilingError("SERVER", `Geneva returned an error (${msg}).`);
  }
  return json as T;
}

/** IS-75: validate a (possibly hand-edited) proportion; falls back to a local sum when the backend is unreachable. */
export async function validateThreeLProportion(v: { liquidity: number; longevity: number; legacy: number }): Promise<ThreeLValidation> {
  const total = v.liquidity + v.longevity + v.legacy;
  try {
    const r = await cpJson<Partial<ThreeLValidation>>("/ips-proportion/validate", { method: "POST", body: JSON.stringify(v) });
    if (typeof r.ok === "boolean") return { ok: r.ok, total: r.total ?? total, message: r.message ?? (r.ok ? "Total is 100%." : `Total is ${total}%, not 100%.`) };
  } catch { /* use local check */ }
  return { ok: total === 100, total, message: total === 100 ? "Total is 100%." : `Total is ${total}%, not 100%.` };
}

/** Strategy table A-F (asset-class mix, return, volatility, drawdown). */
export async function getStrategies(): Promise<{ strategies: Strategy[]; liquidityAllowed: string[] }> {
  const r = await cpJson<{ strategies?: Strategy[]; liquidityAllowed?: string[] }>("/strategies");
  return { strategies: r.strategies ?? [], liquidityAllowed: r.liquidityAllowed ?? [] };
}

/** RM challenges or asks about the 3L allocation; the agent agrees or disagrees with reasons from the notes. */
export async function discussAllocation(input: {
  clientId: string; message: string; history: { role: "user" | "assistant"; text: string }[];
  allocation?: { buckets: { id: string; strategy: string }[] };
}): Promise<IpsDiscussResult> {
  const r = await cpJson<Partial<IpsDiscussResult>>("/ips-allocation/discuss", {
    method: "POST",
    body: JSON.stringify({ client_id: input.clientId, clientId: input.clientId, message: input.message, history: input.history, allocation: input.allocation }),
  });
  return { answer: "", stance: "info", citations: [], ...r } as IpsDiscussResult;
}

/** Log an RM strategy choice that differs from Geneva's proposal, with the reason (audit log, Liquidity A/B only). Best effort: never blocks saving. */
export async function logStrategyOverride(input: { clientId: string; bucket: string; proposed?: string; chosen: string; reason: string }): Promise<boolean> {
  const portfolio = input.bucket ? input.bucket[0].toUpperCase() + input.bucket.slice(1).toLowerCase() : "";
  try {
    await cpJson<unknown>("/ips-allocation/override", { method: "POST", body: JSON.stringify({ clientId: input.clientId, portfolio, from: input.proposed ?? "", to: input.chosen, reason: input.reason }) });
    return true;
  } catch { return false; }
}

export interface IpsChatPage { messages: IpsChatMessage[]; truncated: boolean; message: string; historyAvailable: boolean }
export async function listIpsChat(clientId: string): Promise<IpsChatMessage[]> {
  return (await listIpsChatPage(clientId)).messages;
}
/** Messages plus the backend's `truncated` flag and `message` (oldest dropped at the cap). `historyAvailable:false` when the database is down. */
export async function listIpsChatPage(clientId: string): Promise<IpsChatPage> {
  try {
    const r = await cpJson<{ messages?: IpsChatMessage[]; truncated?: boolean; message?: string }>(`/ips-chat/${encodeURIComponent(clientId)}`);
    return { messages: r.messages ?? [], truncated: Boolean(r.truncated), message: r.message ?? "", historyAvailable: true };
  } catch (e) {
    if (e instanceof HistoryUnavailableError) return { messages: [], truncated: false, message: e.message, historyAvailable: false };
    throw e;
  }
}
export async function appendIpsChat(clientId: string, msg: { role: "user" | "assistant"; text: string; kind?: IpsChatMessage["kind"]; meta?: Record<string, unknown> | null }): Promise<{ truncated?: boolean; message?: string; historyAvailable: boolean }> {
  try {
    const r = await cpJson<{ truncated?: boolean; message?: string }>(`/ips-chat/${encodeURIComponent(clientId)}`, { method: "POST", body: JSON.stringify(msg) });
    return { truncated: r.truncated, message: r.message, historyAvailable: true };
  } catch (e) {
    if (e instanceof HistoryUnavailableError) return { historyAvailable: false, message: e.message };
    throw e;
  }
}
export async function clearIpsChat(clientId: string): Promise<void> {
  await cpJson<unknown>(`/ips-chat/${encodeURIComponent(clientId)}`, { method: "DELETE" });
}

const shortS = (n: number) => `S$${(n / 1_000_000).toFixed(2)}m`;

/**
 * Turn what the RM and PM have captured into the agent's client profile.
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

/** Shared by the Portfolio Agent and the Product Recommender so both agents see the same client. */
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
  const profile: PaClientProfile = {
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

async function buildPortfolioInputs(clientId: string): Promise<PaInputs> {
  const [{ client, risk, liquidity, near, later, alloc, profile }, inbox] = await Promise.all([buildClientProfile(clientId), arcApi.getInbox("pm")]);
  const request = inbox.find((i) => i.clientId === clientId);

  const fields: PaInputField[] = [
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

/** One fetch path for every Portfolio Agent call: same timeouts, error kinds and messages. */
async function paJson(path: string, init: RequestInit, timeoutMs = PA_TIMEOUT_MS, signal?: AbortSignal): Promise<unknown> {
  let res: Response;
  try {
    const timeout = AbortSignal.timeout(timeoutMs);
    res = await fetch(`${PA_URL}${path}`, { ...init, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  } catch (err) {
    if (signal?.aborted) throw err; // superseded by a newer request; callers ignore it
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new PortfolioAgentError("TIMEOUT", "The Portfolio Agent did not respond in time.");
    }
    throw new PortfolioAgentError("UNREACHABLE", `Cannot reach the Portfolio Agent at ${API_BASE}.`, [
      "Start the backend: cd backend, then python -m app.agents.portfolio_agent serve",
    ]);
  }
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail;
    if (res.status === 422 && Array.isArray(detail)) {
      throw new PortfolioAgentError("REJECTED", "The Portfolio Agent rejected the inputs.",
        detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).filter((x) => x !== "body").join(" › ")}: ${d.msg ?? "invalid"}`));
    }
    if (res.status === 404 || res.status === 409) {
      throw new PortfolioAgentError(res.status === 404 ? "NOT_FOUND" : "REJECTED", typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    throw new PortfolioAgentError("SERVER", `The Portfolio Agent returned an error (${typeof detail === "string" ? detail : `HTTP ${res.status}`}).`);
  }
  return json;
}

function asProposal(json: unknown): PaResponse {
  const r = json as Partial<PaResponse> | null;
  const ok = !!r && typeof r.request_id === "string" && Array.isArray(r.portfolio_options) && Array.isArray(r.comparison_matrix)
    && Array.isArray(r.candidate_products) && !!r.market_context_summary && r.requires_rm_review === true && r.execution_status === "NOT_EXECUTED"
    && r.portfolio_options.every((o) => typeof o?.option_id === "string" && Array.isArray(o?.asset_allocation) && Array.isArray(o?.product_selections));
  if (!ok) throw new PortfolioAgentError("INVALID_RESPONSE", "The Portfolio Agent's response did not match the expected format.");
  return r as PaResponse;
}

async function generatePortfolioProposals(req: PaRequest): Promise<PaResponse> {
  const body: PaRequest = { ...req, request_id: req.request_id ?? `IC-${req.client_id}-${Date.now()}` };
  return asProposal(await paJson("/portfolio/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
}

async function getPortfolioProposal(requestId: string): Promise<PaResponse> {
  return asProposal(await paJson(`/portfolio/${encodeURIComponent(requestId)}`, { method: "GET" }, 15_000));
}

async function evaluatePortfolioWeights(requestId: string, optionId: string, weights: Record<string, number>, signal?: AbortSignal): Promise<PaWeightEvaluation> {
  const json = await paJson(`/portfolio/${encodeURIComponent(requestId)}/options/${encodeURIComponent(optionId)}/evaluate`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ weights }) }, 20_000, signal);
  const e = json as Partial<PaWeightEvaluation> | null;
  if (!e || !Array.isArray(e.lines) || !Array.isArray(e.checks) || !e.original || !e.adjusted || typeof e.valid !== "boolean") {
    throw new PortfolioAgentError("INVALID_RESPONSE", "The weight check response did not match the expected format.");
  }
  return e as PaWeightEvaluation;
}

/* ---------- 3L buckets ---------- */

export const BUCKET_LABEL: Record<PaBucketId, string> = { liquidity: "Liquidity", longevity: "Longevity", legacy: "Legacy" };
const BUCKET_WORDS: [PaBucketId, RegExp][] = [
  ["liquidity", /\bliquidity\b/i], ["longevity", /\blongevity\b|retire/i], ["legacy", /\blegacy\b|inherit|bequest|next generation/i],
];
/** Goals that belong to Legacy rather than Longevity (anything due within 3 years is Liquidity's). */
const LEGACY_GOAL = /legacy|inherit|bequest|philanthrop|gift|estate|next generation|grandchild/i;
const MIN_GOAL_YEARS = 0.5;

/**
 * One entry per 3L bucket: its amount (the 3L step), purpose, the goals it funds and the request to send.
 * Goals due within 3 years fund Liquidity; legacy-type goals fund Legacy; the rest fund Longevity.
 * The default horizon is the bucket's nearest goal; the PM can change it before running the agent.
 */
async function buildBucketInputs(clientId: string): Promise<PaBucketInputs[]> {
  const [{ client, near, later }, { request }, buckets] = await Promise.all([
    buildClientProfile(clientId), buildPortfolioInputs(clientId), arcApi.get3L(clientId),
  ]);
  const total = buckets.reduce((s, b) => s + b.amountSgd, 0);
  const goalsFor: Record<PaBucketId, { label: string; year: number; years: number }[]> = {
    liquidity: near, legacy: later.filter((g) => LEGACY_GOAL.test(g.label)), longevity: later.filter((g) => !LEGACY_GOAL.test(g.label)),
  };
  return PA_BUCKETS.map((id) => {
    const b = buckets.find((x) => x.id === id);
    const amount = b?.amountSgd ?? 0;
    const goals = goalsFor[id].map((g) => ({ label: g.label, year: g.year, years: Math.max(MIN_GOAL_YEARS, g.years) }));
    const nearest = goals.length ? Math.min(...goals.map((g) => g.years)) : null;
    return {
      id, label: BUCKET_LABEL[id], amount, sharePct: total ? Math.round((amount / total) * 1000) / 10 : 0,
      objective: b?.purpose ?? "", horizonHint: b?.horizon ?? "",
      defaultHorizon: nearest ?? (id === "liquidity" ? 3 : null), goals, clientRiskLevel: client.riskCap,
      request: {
        ...request,
        client_profile: {
          ...request.client_profile,
          financial_goals: goals.map((g) => ({ goal: g.label, years_to_goal: g.years, priority: /retire/i.test(g.label) ? "High" : "Medium", currency: "SGD" })),
        },
        bucket: { bucket: id, amount, objective: b?.purpose || null, total_3l_amount: total || null },
      },
    };
  });
}

async function reviewCombined(choices: PaBucketChoice[], clientTotal: number | null): Promise<PaCombinedReview> {
  const json = await paJson("/portfolio/combined",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_total: clientTotal, buckets: choices }) }, 30_000);
  const r = json as Partial<PaCombinedReview> | null;
  if (!r || !Array.isArray(r.buckets) || !Array.isArray(r.classes) || !Array.isArray(r.checks) || typeof r.valid !== "boolean" || r.execution_status !== "NOT_EXECUTED") {
    throw new PortfolioAgentError("INVALID_RESPONSE", "The combined review did not match the expected format.");
  }
  return r as PaCombinedReview;
}

/** Chat-only proposals per client, so a chat runs the Portfolio Agent once, not every question. */
const chatProposalIds = new Map<string, string>();

async function askAbout(requestId: string, body: object): Promise<PaAnswer> {
  let json: unknown;
  try {
    json = await paJson(`/portfolio/${encodeURIComponent(requestId)}/ask`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, 60_000);
  } catch (e) {
    // FastAPI's bare "Not Found" means the route is missing (a backend started before the chat endpoint
    // existed), not an expired proposal: say so instead of re-running the agent for nothing.
    if (e instanceof PortfolioAgentError && e.kind === "NOT_FOUND" && e.message === "Not Found") {
      throw new PortfolioAgentError("SERVER", "The running backend does not have the Portfolio Agent chat yet. Restart it so it runs the latest code.", [
        "Stop the backend (Ctrl+C), then: cd backend, then python -m app.agents.portfolio_agent serve",
      ]);
    }
    throw e;
  }
  const a = json as Partial<PaAnswer> | null;
  if (!a || typeof a.answer !== "string" || typeof a.source !== "string" || a.execution_status !== "NOT_EXECUTED") {
    throw new PortfolioAgentError("INVALID_RESPONSE", "The Portfolio Agent's answer did not match the expected format.");
  }
  return a as PaAnswer;
}

async function askPortfolioAgent(clientId: string, question: string, history: PaChatTurn[]): Promise<PaChatReply> {
  const progress = loadPmProgress(clientId);
  const holdings = await arcApi.getHoldings(clientId);
  const base = {
    question: question.slice(0, 1000),
    history: history.slice(-3).map((t) => ({ question: t.question.slice(0, 1000), answer: t.answer.slice(0, 1500) })),
  };
  const current = holdings.slice(0, 100).map((h) => ({ name: h.name, asset_class: h.assetClass, weight_pct: h.weightPct }));
  const notFound = (e: unknown) => e instanceof PortfolioAgentError && e.kind === "NOT_FOUND";

  // 0. 3L-based SAA: the bucket the question names, else the main one the PM has worked on.
  const named = BUCKET_WORDS.find(([, rx]) => rx.test(question))?.[0];
  const order: PaBucketId[] = named ? [named] : ["longevity", "legacy", "liquidity"];
  const bucketId = order.find((b) => progress.saaBuckets?.[b]?.requestId);
  const draft = bucketId ? progress.saaBuckets?.[bucketId] : undefined;
  if (bucketId && draft?.requestId) {
    try {
      const a = await askAbout(draft.requestId, { ...base, workspace: {
        selected_option: draft.optionId ?? null,
        adjusted_weights: draft.optionId && draft.weights ? draft.weights : null,
        sent_to_rm: isIpsReturned(clientId),
        holdings: current,
      } });
      return { ...a, basis: "pm", bucketLabel: BUCKET_LABEL[bucketId] };
    } catch (e) {
      if (!notFound(e)) throw e;
    }
  }
  // 1. The PM's own proposal for this client, with the portfolio they picked and any edited weights.
  if (progress.paRequestId) {
    try {
      const a = await askAbout(progress.paRequestId, { ...base, workspace: {
        selected_option: progress.saaTemplate ?? null,
        adjusted_weights: progress.saaTemplate && progress.saaWeights ? progress.saaWeights : null,
        sent_to_rm: isIpsReturned(clientId),
        holdings: current,
      } });
      return { ...a, basis: "pm" };
    } catch (e) {
      if (!notFound(e)) throw e; // backend restarted: fall through to a chat run
    }
  }
  // 2. A chat-only run, made once per client and reused while the backend keeps it.
  const workspace = { holdings: current };
  const cached = chatProposalIds.get(clientId);
  if (cached) {
    try { return { ...(await askAbout(cached, { ...base, workspace })), basis: "chat" }; } catch (e) { if (!notFound(e)) throw e; }
  }
  const { request } = await buildPortfolioInputs(clientId);
  const proposal = await generatePortfolioProposals({ ...request, request_id: `CHAT-${clientId}-${Date.now()}` });
  chatProposalIds.set(clientId, proposal.request_id);
  return { ...(await askAbout(proposal.request_id, { ...base, workspace })), basis: "chat" };
}

/* ---------- Product Recommender agent (real backend) ---------- */

const PR_URL = `${API_BASE}/agents/product-recommender`;
const PR_TIMEOUT_MS = 30_000;

/** No mock fallback: the PM must never approve a list the agent did not produce. */
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
  /** Allocation rows with the PM's saved new TAA applied. */
  allocation: AllocationRow[];
  /** The finalised product list (names; matched to the shelf by the agent). */
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
