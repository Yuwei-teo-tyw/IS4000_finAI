/** Client Profiling Agent response contract (POST /agents/client-profiling/chat). Proposals only; nothing is saved. */
export type ClientProfilingStatus = "ok" | "needs_clarification" | "insufficient_information" | "not_found";

export interface ClientProfilingSource {
  type: "ips" | "meeting_note";
  /** ips: "<client>:v<version>"; meeting_note: the note id. */
  id: string;
  client_id: string;
  version?: number;
  date?: string;
  label: string;
  passage?: string;
}

/** The adviser's explicit source choice for a question. */
export type ClientProfilingSourceChoice = "notes" | "ips" | "both";
/** One button offered by the clarify_source tool (data.options[]). */
export interface ClientProfilingOption { source: ClientProfilingSourceChoice; label: string }
/** data.both of compare_sources: one labelled block per source. */
export interface ClientProfilingBothBlock { label: string; answer?: { status?: string; text?: string; sources?: ClientProfilingSource[] } | null; message?: string }
export interface ClientProfilingBoth { notes: ClientProfilingBothBlock; ips: ClientProfilingBothBlock }
/** data.answer of get_ips. */
export interface ClientProfilingIpsAnswer { status: "ok" | "cannot_answer" | "no_ips" | "out_of_scope"; text: string; sources: ClientProfilingSource[] }
/** POST /agents/client-profiling/chat request extras. */
export interface ClientProfilingRequestOpts { source?: ClientProfilingSourceChoice; }

/** One row of the backend client book DB. */
export interface BookClient {
  id: string; name: string; surname: string; risk_category: string | null; aum_sgd: number | null; status: string | null;
  /** Steps done of 5. */ onboarding_progress: number;
  /** Review pack percent, 0..100. */ monitoring_progress: number;
}
export interface BookResult { clients: BookClient[]; message?: string }

export interface ClientProfilingCandidate { id: string; name: string }

export type ClientProfilingFactKind = "documented" | "calculated" | "inferred" | "missing";

/** One concise line in a section (data.sections[].lines[]). */
export interface ClientProfilingLine { text: string; kind: ClientProfilingFactKind }

/** A headed block (data.sections[]), built by the backend presentation layer. */
export interface ClientProfilingSection {
  heading: string;
  meaning: string;
  lines: ClientProfilingLine[];
  sources: ClientProfilingSource[];
}

/** Optional model-written grounded answer (data.answer); absent when the local model is unavailable. */
/** Optional agent-suggested overview (data.answer.explanation); never confirmed with the client. */
export interface ClientProfilingExplanation { title: string; risk_category: string; text: string; recommended_asset_classes: string[]; sources: ClientProfilingSource[]; status: "suggestion" }

export interface ClientProfilingInference { label: string; text: string }
export interface ClientProfilingSummary {
  status: "ok" | "no_notes"; message: string;
  /** True when the local model was down and the summary is a basic extractive one; `notice` explains it. */
  degraded?: boolean; notice?: string;
  /** Set when the adviser asked for a specific layout; absent for the default four-heading summary. */
  custom_format?: string;
  profile_card?: { title: string; items: { label: string; value: string }[] };
  /** Merged, de-duplicated summary across meetings. */
  sections?: { heading: string; bullets: { text: string; sources?: ClientProfilingSource[] }[] }[];
  /** Per-meeting summaries (compat only; not rendered), latest first; sections in order Cash Inflow, Cash Outflow, Risk Profile, Asset Class Preference. */
  meetings?: { note_id: string; date: string; title: string; sections: { heading: string; bullets: { text: string }[] }[]; sources?: ClientProfilingSource[] }[];
  /** Latest first. */
  covered_meetings?: { note_id: string; date: string; title: string }[];
  coverage?: { total_notes: number; truncated: { note_id: string; covered_words: number; total_words: number; not_covered: string }[] };
}

export interface ClientProfilingAnswer { status: "ok" | "cannot_answer"; inference?: ClientProfilingInference; text: string; sections?: ClientProfilingSection[]; sources: ClientProfilingSource[]; explanation?: ClientProfilingExplanation }

export interface ClientProfilingResult {
  tool: string;
  status: ClientProfilingStatus;
  client_id?: string;
  message: string;
  /** Shape varies by tool; the card reads it defensively. */
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  sources: ClientProfilingSource[];
  candidates: ClientProfilingCandidate[];
}

export type IpsAssistMode = "auto" | "professionalize" | "write";
export interface IpsAssistResult {
  status: "ok" | "insufficient_information" | "unavailable" | "out_of_scope";
  message: string;
  kind?: "rewrite" | "retrieve" | "none";
  target?: "selection" | "section" | "document";
  original: string;
  revised: string;
  notes: string[];
  sources: ClientProfilingSource[];
}

const isRec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
/** data.options of clarify_source, validated. */
export function clarifyOptions(data: Record<string, unknown> | undefined): ClientProfilingOption[] {
  const o = data?.options;
  return Array.isArray(o) ? o.filter((x): x is ClientProfilingOption => isRec(x) && (x.source === "notes" || x.source === "ips" || x.source === "both") && typeof x.label === "string") : [];
}
/** data.both of compare_sources, or null. */
export function bothOf(data: Record<string, unknown> | undefined): ClientProfilingBoth | null {
  const b = data?.both;
  return isRec(b) && isRec(b.notes) && isRec(b.ips) ? (b as unknown as ClientProfilingBoth) : null;
}
/** data.routing.source ("notes" | "ips"), when the server reports it. */
export function routingSource(data: Record<string, unknown> | undefined): "notes" | "ips" | null {
  const r = data?.routing;
  const s = isRec(r) ? r.source : null;
  return s === "notes" || s === "ips" ? s : null;
}
