import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ArrowUp, MessageSquarePlus, Search, Trash2 } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { Client } from "../../types/arc";
import { pathForClient, setActiveClientId } from "../../layouts/navConfig";
import { arcApi, bookToClient, assetClassSlug, GenevaBackendError, ClientProfilingError, PortfolioAgentError, ProductRecommenderError, PR_ROLE_LABELS, shortlistRow } from "../../services/arcApi";
import { ClientProfilingCard } from "./ClientProfilingCard";
import type { AllocationDialogue, AllocationProposal, ClientProfilingResult, ClientProfilingSourceChoice } from "../../types/clientProfiling";
import { profileApi } from "../../services/profileApi";
import type { PaBucketId, PaChatReply, PaChatTurn } from "../../types/portfolio";
import { RefLine, ViewHeadline } from "../ps/AssetViewParts";
import type { PrAssetView } from "../../types/productRecommender";
import { findProducts } from "../../utils/productMatch";
import { saveIpsDraftExtras, toggleSelection, useActiveIps, useSelection, loadSelection, saveSelection, getIpsDraftExtras, appendIpsDraftNote } from "../../services/workflowStore";
import { IPS_GEN_SECTIONS, type IpsGenSectionResult,type IpsChatMessage, type IpsDiscussResult } from "../../types/arc";
import { historyNotice, STANCE_CHIP, NO_MODEL_NOTICE } from "../../services/ipsChatHistory";
import { subscribeIpsGen, type IpsGenEvent } from "../../services/ipsGenBus";
import { getIpsRun } from "../../services/ipsGenStore";
import type { GenevaPendingAction, GenevaReply, MacroView, MarketAnswer, MarketRow, Role } from "../../types/arc";
import { Badge, BulletList, Button, CitationTag, DirectionArrow, Table, toBulletItems } from "../ui";
import { savePackDraft } from "../../services/packDraftStore";
import { appendChatContext } from "../../services/chatContextStore";
import { MeetingNoteModal } from "./MeetingNoteModal";
import { GenevaMarkdown, Tagged, type SourceRef } from "./GenevaMarkdown";
import { GenevaArticlePanel } from "./GenevaArticlePanel";
import { CHAT_HISTORY_UNAVAILABLE, DEFAULT_CHAT_TITLE, chatDate, listSavedChats, loadSavedMessages, saveChatMessage, shortTitle } from "../../services/genevaChats";

/** Plain-text digest of an answer (no markup) for the research context store. */
function answerPlainText(a: MarketAnswer): string {
  const parts = [a.summary];
  if (a.market) parts.push(`Economic cycle ${a.market.phase}. ${a.market.views.map((v) => `${v.assetClass} ${v.view}`).join(", ")}.`);
  if (a.rows.length) parts.push(`Products considered: ${a.rows.map((r) => r.product).join(", ")}.`);
  if (a.draft) parts.push(a.draft.text);
  return parts.join(" ").replace(/<[^>]*>/g, "").replace(/\[[^\]]*\]/g, "").replace(/[*_`#]+/g, "").replace(/\s+/g, " ").trim();
}

const MATCH_PROMPT = "Read client IPS, and research market, match products most suited to client via risk appetite and preferences and current market condition";
const SEEDED: Record<Role, string[]> = {
  ps: [
    MATCH_PROMPT,
    "Tell me if the Global Quality Dividend ETF suits the client's profile, explain why, and whether it fits the current macroeconomic status",
    "For fixed income, I want the Asia Investment-Grade Bond Fund, the Singapore Government Bond ETF and the Accredited-Investor Senior Bond Note",
    "What is the CIO House View?",
    "What is the current economic cycle and the CIO view per asset class?",
    "What is the top 5 ranking for equities and why?",
    "What's the view on fixed income?",
    "How does gold look for this client?",
    "How is oil affecting the inflation outlook?",
  ],
  rm: ["Summarise the client's IPS", "What are the client's goals?", "Review the IPS", "Summarise the meeting notes", "What did the client say in the last meeting?", "Write the latest client profile + goals section formally in bullet points", "Why is portfolio health flagged?", "Explain the old vs new TAA", "Are recession risks rising right now?"],
  pm: ["Analyse this client's portfolio strengths and weaknesses", "Which holdings move together?", "Compare the old and new TAA", "Propose a TAA", "Summarise the client's IPS", "How are the markets today, and what is the regime, according to the CIO House View and the web?", "Edit the client's individual holdings", "Why are Treasury yields moving this week?"],
};
const HEADING: Record<Role, string> = { ps: "What would you like to research?", rm: "How can I help with this client?", pm: "How can I help with this portfolio?" };
const PLACEHOLDER: Record<Role, string> = { ps: "Ask about markets or products", rm: "Ask about the IPS, goals or meetings", pm: "Ask about the portfolio or TAA" };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const viewTone = { Buy: "green", Hold: "amber", Sell: "red" } as const;
const label = "text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted";

interface Recommend {
  name: string; riskLevel: number | null; riskCategory: string; profile: string[]; market: string[]; tags: string[];
  /** `reason` is the Product Recommender's cited bullets; `fee` is for information only. */
  shortlist: { row: MarketRow; riskRating: number; reason: string; fee: number | null; notes: string[] }[];
  /** How the shortlist was planned: one line per role with its slots and why. */
  rolePlan: string[];
  excluded: { name: string; reason: string }[];
  /** True when at least one reason was written by the LLM from the engine's facts. */
  llmReasons: boolean;
}
/** `reply` = a LangGraph answer (Markdown); `approval` = a money-moving action the backend paused on, waiting for the user. */
interface Msg {
  from: "user" | "agent"; text: string; answer?: MarketAnswer; finalise?: string[]; recommend?: Recommend; assetView?: PrAssetView;
  reply?: { text: string; runId: string | null };
  profiling?: ClientProfilingResult;
  /** Set when the answer came from a pinned-client ask, so a source choice re-asks for the same client. */
  profilingClient?: string;
  /** IPS draft editor answer: bullets the RM can add to a bucket's explanation box. */
  ipsExplain?: { bullets: string[]; named: PaBucketId | null; buckets: PaBucketId[]; added: PaBucketId[] };
  approval?: { action: GenevaPendingAction | null; status: "pending" | "approved" | "declined" };
  /** AI IPS generation evidence, filled progressively from ipsGenBus events. */
  ipsGen?: { clientName: string; sections: IpsGenSectionResult[]; status: "running" | "done" | "error"; error?: string; model?: string; saved?: boolean; unavailable?: boolean };
  /** Reply to a question about the 3L allocation: stance of the agent, suggested change (if any) and the notes behind it. */
  discuss?: { stance: IpsDiscussResult["stance"]; buckets?: { id: string; strategy: string; strategyName?: string; justification?: string }[]; changes: string[]; citations: IpsDiscussResult["citations"]; applied?: boolean; /** Pending change from the backend: applied only by a confirm turn that echoes it back. */ proposal?: AllocationProposal | null };
}

const BUCKET_LABEL: Record<string, string> = { liquidity: "Liquidity portfolio", longevity: "Longevity portfolio", legacy: "Legacy portfolio" };
const STANCE_LABEL = STANCE_CHIP;
/** Follow-up questions about the written IPS go to the allocation agent when they touch allocation, strategy or justification. */
/** A short reply to a pending proposal ("confirm", "yes", "no"): goes to the allocation agent even without a bucket name. */
const PROPOSAL_REPLY = /^\s*(yes|yep|yeah|ok(ay)?|sure|confirm\w*|apply|go ahead|please do|do it|approve|proceed|no|nope|cancel|never ?mind|keep|don'?t|leave it)\b/i;
const ALLOC_INTENT = /allocation|strateg|liquidity|longevity|legacy|justif|\bwhy\b|growth|fixed income|disagree|\b3l\b|bucket|equit|income|balanced|yield/i;
const bucketLine = (b: { id: string; strategy: string; strategyName?: string }) => `${BUCKET_LABEL[b.id] ?? b.id} - ${b.strategy}${b.strategyName ? ` ${b.strategyName}` : ""}`;

/** The newest allocation known in a chat: a discuss reply that changed it, else the one generated. */
/** The proposal waiting for the RM's answer: only the newest agent message can hold one. */
function pendingProposalOf(msgs: Msg[]): AllocationProposal | null {
  const last = [...msgs].reverse().find((m) => m.from === "agent");
  return last?.discuss?.proposal && !last.discuss.applied ? last.discuss.proposal : null;
}
function latestAllocation(msgs: Msg[]): { id: string; strategy: string; strategyName?: string; justification?: string }[] | undefined {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (m.discuss?.buckets?.length) return m.discuss.buckets;
    const a = m.ipsGen?.sections.find((r) => r.section === "allocation")?.allocation;
    if (a?.buckets?.length) return a.buckets;
  }
  return undefined;
}

/** A saved IPS chat row becomes a chat message again after a reload. */
function restoreMsg(h: IpsChatMessage): Msg {
  if (h.role === "user") return { from: "user", text: h.text };
  const meta = (h.meta ?? {}) as { stance?: IpsDiscussResult["stance"]; buckets?: NonNullable<Msg["discuss"]>["buckets"]; changes?: string[]; proposal?: AllocationProposal | null; applied?: boolean };
  if (h.kind === "discuss") return { from: "agent", text: h.text, discuss: { stance: meta.stance ?? "info", buckets: meta.buckets, changes: meta.changes ?? [], citations: [], proposal: meta.proposal ?? null, applied: meta.applied } };
  return { from: "agent", text: h.text, reply: { text: h.text, runId: null } };
}

/** Geneva's reasoning for one generated section. Open by default for the newest section; the RM can toggle any of them. */
function ReasoningToggle({ lines, latest }: { lines: string[]; latest: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = open ?? latest;
  return (
    <div className="mt-3" data-testid="ips-reasoning">
      <button type="button" aria-expanded={shown} onClick={() => setOpen(!shown)} className="text-[13px] uppercase tracking-[0.06em] text-ink-muted underline-offset-2 hover:underline">
        {shown ? "Hide reasoning" : "Reasoning"}
      </button>
      {shown && <ul className="mt-2 list-disc space-y-1 border-l border-hairline-strong pl-8 text-[15px] leading-6 text-ink-muted">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
    </div>
  );
}

/** Evidence per IPS section: which meeting note each filled item was pulled from. Sections that have not arrived yet show as thinking steps. */
function IpsGenView({ g, clientId }: { g: NonNullable<Msg["ipsGen"]>; clientId: string; role?: Role }) {
  const [note, setNote] = useState<{ id: string; passage?: string; date?: string; title?: string } | null>(null);
  const pending = IPS_GEN_SECTIONS.filter((s) => !g.sections.some((r) => r.section === s.id));
  const running = g.status === "running";
  const model = g.model ?? g.sections.find((r) => r.model)?.model;
  const sub = "mt-1 border-l border-hairline-strong pl-3 text-[14px] leading-6 text-ink-muted";
  return (
    <div className="min-w-0 space-y-8 font-light">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-[22px] leading-9 tracking-tight text-ink">{`AI IPS generation · ${g.clientName}`}</p>
        {model && !g.unavailable && <span className="inline-flex items-center border border-hairline-strong px-3 py-1 text-[12px] tracking-[0.06em] text-ink">{`Model: ${model}`}</span>}
        {g.saved && <span className="inline-flex items-center border border-hairline-strong px-3 py-1 text-[12px] uppercase tracking-[0.14em] text-ink">Saved</span>}
      </div>
      {IPS_GEN_SECTIONS.map((def) => {
        const r = g.sections.find((x) => x.section === def.id);
        if (!r) return null;
        const ev = r.evidence ?? [];
        const latest = IPS_GEN_SECTIONS.filter((s) => g.sections.some((x) => x.section === s.id)).pop()?.id === def.id;
        const reasoning = (r.reasoning ?? []).filter((l) => l?.trim());
        return (
          <section key={def.id} className="animate-geneva-in">
            <h4 className="text-[22px] font-light tracking-tight">{def.label}</h4>
            {r.status !== "ok" ? <p className="mt-3 text-[16px] leading-7 text-ink-700">{r.message}</p> : def.id === "allocation" && r.allocation ? (
              <div className="mt-3 space-y-6">
                {r.allocation.summary && <p className="text-[16px] leading-7 text-ink-700">{r.allocation.summary}</p>}
                {r.proportion ? (
                  <div data-testid="ips-gen-proportion">
                    <h5 className="text-[18px] font-light tracking-tight text-ink">{`3L proportion · ${(["liquidity", "longevity", "legacy"] as const).reduce((n, k) => n + r.proportion![k].pct, 0)}%`}</h5>
                    <ul className="mt-2 list-disc space-y-2 pl-5 text-[16px] leading-7 text-ink-700">
                      {(["liquidity", "longevity", "legacy"] as const).map((k) => <li key={k}>{`${BUCKET_LABEL[k].replace(" portfolio", "")} ${r.proportion![k].pct}%`}{r.proportion![k].reason ? <span className="text-ink-muted">{` — ${r.proportion![k].reason}`}</span> : null}</li>)}
                    </ul>
                  </div>
                ) : !!r.proportionMissing?.length && <p className="text-[16px] leading-7 text-ink-muted">{`3L proportion not generated. Missing: ${r.proportionMissing.join("; ")}.`}</p>}
                {r.allocation.buckets.map((b) => (
                  <div key={b.id}>
                    <h5 className="text-[18px] font-light tracking-tight text-ink">{bucketLine(b)}</h5>
                    <ul className="mt-2 list-disc space-y-3 pl-5 text-[16px] leading-7 text-ink-700">
                      <li>{b.justification}</li>
                      {(b.evidence ?? []).map((e, i) => (
                        <li key={`${e.noteId}-${i}`}>
                          <span>{e.item}</span>
                          <span className="text-ink-muted">{" — from meeting note "}{e.date ?? ""}{e.title ? ` “${e.title}”` : ""} </span>
                          <button type="button" onClick={() => setNote({ id: e.noteId, passage: e.passage, date: e.date, title: e.title })} className="underline-offset-2 hover:underline" aria-label={`Open meeting note ${e.title ?? e.noteId}`}><CitationTag tag={e.noteId} /></button>
                          {e.passage && <p className={sub}>“{e.passage}”</p>}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ) : (
              <ul className="mt-3 list-disc space-y-3 pl-5 text-[16px] leading-7 text-ink-700">
                {ev.length === 0 ? <li>Nothing stated in the meeting notes</li> : ev.map((e, i) => (
                  <li key={`${e.noteId}-${i}`}>
                    <span>{e.item}</span>
                    <span className="text-ink-muted">{" — from meeting note "}{e.date ?? ""}{e.title ? ` “${e.title}”` : ""} </span>
                    <button type="button" onClick={() => setNote({ id: e.noteId, passage: e.passage, date: e.date, title: e.title })} className="underline-offset-2 hover:underline" aria-label={`Open meeting note ${e.title ?? e.noteId}`}><CitationTag tag={e.noteId} /></button>
                    {e.passage && <p className={sub}>“{e.passage}”</p>}
                  </li>
                ))}
              </ul>
            )}
            {reasoning.length > 0 && <ReasoningToggle lines={reasoning} latest={latest} />}
          </section>
        );
      })}
      {running && (
        <div className="min-h-[120px] border-t border-hairline pt-5">
          <p className="text-[26px] font-light tracking-tight"><span className="animate-geneva-flow">Reading the meeting notes</span></p>
          <ol className="mt-4">
            {pending.map((s, i) => (
              <li key={s.id} className="flex items-center gap-5 py-2">
                <span className="animate-geneva-flow w-7 text-xs tabular-nums tracking-[0.12em]">{String(g.sections.length + i + 1).padStart(2, "0")}</span>
                <span className="animate-geneva-flow text-[16px] font-light">{i === 0 ? `Filling ${s.label.toLowerCase()}…` : s.label}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {g.status === "error" && <p className="text-[16px] leading-7 text-negative">{g.error}</p>}
      {g.status === "done" && !g.unavailable && <p className="text-[17px] leading-7 text-ink-700">{g.saved ? "Draft saved automatically to the IPS versions. Open it to review and edit before sending." : "Draft ready in the IPS editor."} Please ascertain these facts against the meeting notes before sending.</p>}
      {g.unavailable && <p className="text-[17px] leading-7 text-ink-700">{NO_MODEL_NOTICE}</p>}
      {note && <MeetingNoteModal clientId={clientId} noteId={note.id} passage={note.passage} fallbackLabel={note.title} fallbackDate={note.date} onClose={() => setNote(null)} />}
    </div>
  );
}

/* ---- PS asset-class view: "What's the view on fixed income?" (one class named, view wording, no product wording) ---- */
const ASSET_WORDS: [RegExp, string][] = [
  [/\bfixed income\b|\bbonds?\b/i, "Fixed income"], [/\bequit(?:y|ies)\b|\bstocks?\b/i, "Equities"], [/\bcash\b|\bmoney market\b/i, "Cash"],
  [/\bgold\b/i, "Gold"], [/\breal estate\b|\breits?\b|\bproperty\b/i, "Real estate"], [/\bhedge funds?\b/i, "Hedge funds"],
  [/\bprivate (?:markets?|equity|credit)\b/i, "Private markets"],
];
const ASSET_VIEW_WORDS = /\b(view|outlook|look(?:s|ing)?|good time|stance|think|attractive|analysis|analy[sz]e)\b/i;
const NOT_ASSET_VIEW = /\b(products?|etfs?|shortlist|top \d|ranking|recommend|finali[sz]e|suits?)\b|house view|cio view/i;
function askedAssetClass(text: string): string | null {
  if (!ASSET_VIEW_WORDS.test(text) || NOT_ASSET_VIEW.test(text)) return null;
  const hits = ASSET_WORDS.filter(([re]) => re.test(text));
  return hits.length === 1 ? hits[0][1] : null;
}

function AssetViewCard({ v, clientId }: { v: PrAssetView; clientId: string }) {
  return (
    <div className="min-w-0 space-y-6 font-light">
      <p className="text-[22px] leading-9 tracking-tight text-ink">{`${v.asset_class}: the agent's own view beside the CIO house view.`}</p>
      <ViewHeadline v={v} compact />
      {v.agent_view && (
        <>
          <p className="text-[17px] leading-7 text-ink-700">{v.agent_view.thesis}</p>
          <ul className="list-disc space-y-2 pl-5 text-[16px] leading-7 text-ink-700">{v.agent_view.thesis_points.slice(0, 3).map((p) => <li key={p.text}><RefLine r={p} /></li>)}</ul>
        </>
      )}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-sm border border-hairline-strong px-5 py-3">
        <p className="text-sm text-ink-700">Segments, market snapshot, scenarios, risks and products are in the full analysis, with Accept and Edit.</p>
        <Button variant="primary" size="sm" to={`/ps/asset-views/${assetClassSlug(v.asset_class)}?client=${clientId}`}>Open full analysis</Button>
      </div>
    </div>
  );
}

/* ---- IPS draft editor: "why is this allocation right for her?" ---- */
const IPS_BUCKET_LABEL: Record<PaBucketId, string> = { liquidity: "Liquidity", longevity: "Longevity", legacy: "Legacy" };
const IPS_BUCKETS: PaBucketId[] = ["liquidity", "longevity", "legacy"];
/** Highlight only: which bucket the question names. Not used for routing. */
const namedBucket = (q: string): PaBucketId | null => IPS_BUCKETS.find((b) => q.toLowerCase().includes(b)) ?? null;
/** Question + the draft's proposed weights + the client's profile facts, so the Portfolio Agent answers from them. */
async function buildIpsDraftQuestion(clientId: string, question: string): Promise<{ q: string; buckets: PaBucketId[] }> {
  const saa = getIpsDraftExtras(clientId).saaPortfolios ?? {};
  const buckets = IPS_BUCKETS.filter((b) => saa[b]);
  const prof = await profileApi.getClientProfile(clientId).catch(() => null);
  const w = buckets.map((b) => `${IPS_BUCKET_LABEL[b]} ${saa[b]!.optionName ?? saa[b]!.optionId}: ${Object.entries(saa[b]!.weights).filter(([, v]) => v > 0).map(([k, v]) => `${k} ${Math.round(v * 10) / 10}%`).join(", ")}`).join("; ");
  const facts = prof ? `Client: age ${prof.age}; horizon ${prof.timeHorizon}; income ${prof.incomeSource}; liquidity ${prof.liquidityNeeds}; loss tolerance ${prof.lossTolerance.join(" / ")}; goals ${prof.goals.join(" / ")}.` : "";
  const brief = `${question}\n\nProposed portfolios on the IPS draft (answer only from these and the client facts, short bullets): ${w || "none yet"}. ${facts}`;
  return { q: brief, buckets };
}
/** Short bullet lines from an agent answer. */
function answerBullets(md: string): string[] {
  const clean = (t: string) => t.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_`#>]+/g, "").replace(/\s+/g, " ").trim();
  const body = md.split(/\n\s*_Portfolio Agent/)[0];
  const lines = body.split("\n").map((l) => l.trim()).filter(Boolean);
  const listed = lines.filter((l) => /^([-*•]|\d+[.)])\s+/.test(l)).map((l) => clean(l.replace(/^([-*•]|\d+[.)])\s+/, "")));
  const out = listed.length ? listed : clean(body).split(/(?<=[.!?])\s+/);
  return out.filter((x) => x.length > 3).slice(0, 5);
}
function IpsExplainCard({ x, onAdd }: { x: NonNullable<Msg["ipsExplain"]>; onAdd: (b: PaBucketId) => void }) {
  return (
    <div className="space-y-6 font-light">
      <ul className="list-disc space-y-2 pl-5 text-[17px] leading-7 text-ink-700">{x.bullets.map((b) => <li key={b}>{b}</li>)}</ul>
      {x.buckets.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          {x.buckets.map((b) => x.added.includes(b) ? (
            <span key={b} className="inline-flex items-center gap-2 rounded-sm border border-hairline px-4 py-2 text-[14px] text-ink-muted"><Check size={14} />Added to {IPS_BUCKET_LABEL[b]} explanation</span>
          ) : (
            <Button key={b} variant={x.named === b ? "primary" : "secondary"} size="sm" onClick={() => onAdd(b)}>Add to {IPS_BUCKET_LABEL[b]} explanation</Button>
          ))}
        </div>
      )}
      <p className="text-sm text-ink-muted">Drafted by the Portfolio Agent. Nothing is added until you press a button, and you can edit it in the editor.</p>
    </div>
  );
}

const MATCH_INTENT = /read client ips.*(research market|match products)/i;
/** Agent failures are shown, never replaced with mock answers. */
/** The user text that prompted the agent message at index i. */
const lastUserBefore = (msgs: Msg[], i: number) => { for (let j = i - 1; j >= 0; j--) if (msgs[j].from === "user") return msgs[j].text; return ""; };
const failText = (e: unknown) => e instanceof ProductRecommenderError || e instanceof PortfolioAgentError || e instanceof ClientProfilingError
  ? [e.message, ...e.details].join(" ")
  : e instanceof GenevaBackendError ? e.message
  : `Something went wrong: ${e instanceof Error ? e.message : String(e)}`;
/** Thinking steps for a backend turn: the backend reports no progress, so only the order is shown, not agents. */
const BACKEND_STEPS = ["Intent parser is reading your request…", "Thinking…", "Consolidating…"];
/**
 * RM/PM questions about the client's portfolio go to the Portfolio Agent. Holdings analytics, TAA,
 * pack drafting, meetings and market questions stay with their own agents.
 */
const PORTFOLIO_INTENT = /portfolio|allocat|\bweights?\b|asset class|\bsaa\b|\b(option|template) [a-f]\b|equit|fixed income|\bbonds?\b|hedge funds?|private markets?|real estate|\bgold\b|drawdown|volatil|expected return|frontier|\bfees?\b|rebalanc|proposal|preferred|scenario|risk level/i;
const OTHER_AGENT_INTENT = /\btaa\b|move together|correlat|cluster|\bedit\b.*holdings?|holdings?.*\bedit\b|\b(write|draft|rewrite|redraft|compose)\b|meeting|notes|regime|strength|weakness|sharpe|diversif|portfolio health/i;
const PA_STEPS = ["Intent parser is reading your request…", "Portfolio Agent fired", "Reading the portfolio proposal…", "Consolidating…"];
/** The answer plus one line saying where it came from; the reader must never mistake it for verified or executed. */
const paReplyText = (r: PaChatReply) => {
  const from = r.basis === "pm" ? `the PM's ${r.bucketLabel ? `${r.bucketLabel} bucket ` : ""}SAA proposal` : "a Portfolio Agent run for this chat (not saved to the SAA request)";
  const how = r.source === "LLM" ? "checked against the proposal's figures" : "assembled from the proposal's figures";
  return `${r.answer}

_Portfolio Agent · from ${from} · ${how}. Illustrative data and house assumptions, not guarantees. Nothing is executed._`;
};
/** Plain text of a Markdown answer for the research context store. */
const markdownPlain = (md: string) => md.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_`#>|]+/g, "").replace(/\s+/g, " ").trim();
const pause = (min: number, max: number) => sleep(min + Math.random() * (max - min));
/** Profile from the IPS, CIO house view, then the Product Recommender's suitability gate and ranking (backend). Nothing is ranked here. */
async function buildRecommendation(clientId: string, ipsVersion: number | null): Promise<{ steps: string[]; rec: Recommend }> {
  const [client, ips, cycle, res] = await Promise.all([
    arcApi.getClient(clientId), arcApi.getIps(clientId), arcApi.getMarketCycle(), arcApi.recommendProducts(clientId, { top_n: 5 }),
  ]);
  const name = client?.name ?? "the client";
  const cs = res.client_summary;
  const goals = ips.find((x) => x.part === 1)?.body?.trim() || "Goals not yet written in the IPS";
  const eligible = res.shortlist.length + res.eligible_not_shortlisted.length;
  const total = eligible + res.excluded.length;
  const hv = res.house_view;
  const profile = [
    `${name}, ${client?.riskCategory ?? "risk category unknown"}, risk level ${cs.risk_level ?? "not established"} of 5${ipsVersion ? `, IPS v${ipsVersion}` : ", no active IPS yet"}`,
    `Objective used for ranking: ${cs.objective}${cs.shortest_horizon_years != null ? `; shortest goal horizon ${cs.shortest_horizon_years} years` : ""}`,
    `Goals: ${goals.replace(/\.$/, "")}`,
    ...(res.missing_information.length ? [`Missing from the profile: ${res.missing_information.join(", ")}`] : []),
  ];
  const basisNote = { rated: "", interpreted: ", read from the report", not_covered: ", not covered by the report" } as const;
  const market = [
    `${cycle.phase} as of ${cycle.asOf} [${cycle.tag}]`,
    ...hv.views.map((v) => `${v.asset_class}: ${v.view} (${v.cio_term}${basisNote[v.basis]}) [${v.citation_id}]`),
  ];
  const steps = [
    "Client profiling agent fired",
    `Reading ${name}'s active IPS${ipsVersion ? ` v${ipsVersion}` : ""}: risk limit, capacity, drawdown, goals…`,
    `Profile ready: risk level ${cs.risk_level ?? "not established"}, ${cs.objective} objective`,
    `Reading the CIO House View (${hv.as_of})…`,
    "Product Recommender fired",
    `Suitability gate: ${eligible} of ${total} products pass, ${res.excluded.length} excluded with reasons`,
    `Ranking ${eligible} by fit with the client's objective and the house view; fees not used…`,
    "Writing the reasons from the engine's facts…",
    "Consolidating…",
  ];
  return {
    steps,
    rec: {
      name, riskLevel: cs.risk_level, riskCategory: client?.riskCategory ?? "", profile, market,
      tags: [cycle.tag, ...new Set(hv.views.map((v) => v.citation_id)), ...(ipsVersion ? [`IPS-v${ipsVersion}`] : [])],
      shortlist: res.shortlist.map((s) => ({ row: shortlistRow(s), riskRating: s.product.risk_rating ?? 0, reason: s.reason.text, fee: s.costs.management_fee_pct, notes: s.notes })),
      rolePlan: (res.role_plan ?? []).map((p) => p.slots === 0
        ? `${PR_ROLE_LABELS[p.role]}: ${p.filled} product${p.filled === 1 ? "" : "s"}, taking over slots other roles had no eligible product for.`
        : `${PR_ROLE_LABELS[p.role]}: ${p.filled} of ${p.slots} slot${p.slots === 1 ? "" : "s"} filled, as ${p.why}${p.passed_on
          ? `; ${p.passed_on} passed on because no eligible product fills this role` : ""}.`),
      excluded: res.excluded.map((x) => ({ name: x.product_name, reason: x.reason })),
      llmReasons: res.shortlist.some((s) => s.reason.source === "llm"),
    },
  };
}

/** Reason bullets for display: the trailing full stop after a closing tag would wrap onto its own line. */
// Source tags like [MOCK-CORP-001] are dropped: the shortlist reasons read as plain bullets.
const reasonLines = (text: string) => toBulletItems(text).map((l) => l.replace(/\s*\[[A-Za-z0-9-]+\]/g, "").replace(/\.$/, "").trim()).filter(Boolean);

function RecommendView({ r, picked, onToggle, clientId }: { r: Recommend; picked: string[]; onToggle: (m: MarketRow) => void; clientId: string }) {
  const h = "text-[26px] font-light tracking-tight";
  const ul = "mt-3 list-disc space-y-2 pl-5 text-[17px] leading-7 text-ink-700";
  return (
    <div className="min-w-0 space-y-10 font-light">
      <p className="text-[22px] leading-9 tracking-tight text-ink">{r.shortlist.length
        ? `For ${r.name} (${r.riskCategory}, risk level ${r.riskLevel ?? "not established"} of 5), the Product Recommender shortlisted ${r.shortlist.length} products that pass the suitability gate, ranked by fit with the client's objective and the CIO house view. Tick the ones you want, or tell me which you are happy with.`
        : `No product passes the suitability gate for ${r.name}. The reasons are listed below.`}</p>
      <section><h4 className={h}>Client profile</h4><ul className={ul}>{r.profile.map((x) => <li key={x}>{x}</li>)}</ul></section>
      <section><h4 className={h}>CIO house view and market</h4><ul className={ul}>{r.market.map((x) => <li key={x}><Tagged text={x} /></li>)}</ul></section>
      {r.shortlist.length > 0 && <section>
        <h4 className={h}>Ranked shortlist</h4>
        {r.rolePlan.length > 0 && <ul className={ul}>{r.rolePlan.map((x) => <li key={x}>{x}</li>)}</ul>}
        <div className="mt-3">
          <Table
            head={["Select", "Rank", "Product", "Why it suits this client"]}
            rows={r.shortlist.map((s, i) => [
              <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={picked.includes(s.row.product)} onChange={() => onToggle(s.row)} aria-label={`Select ${s.row.product}`} />,
              String(i + 1),
              <span className="block min-w-36 max-w-48">
                <span className="block font-semibold">{s.row.product}</span>
                {s.row.role && <span className="mt-2 block text-[14px] font-semibold text-ink-700">{s.row.role} · {s.row.assetClass}</span>}
                <span className="mt-2 block text-[14px] text-ink-muted">Risk {s.riskRating} of 5</span>
                <span className="block text-[14px] text-ink-muted">{s.fee === null ? "Fee not available" : `Fee ${s.fee.toFixed(2)}%`}, information only</span>
              </span>,
              <ul className="block list-disc space-y-1.5 pl-5 text-ink-700 marker:text-ink-muted">
                {reasonLines(s.reason).map((line) => <li key={line}>{line}</li>)}
                {s.notes.map((n) => <li key={n} className="text-ink-muted">{n}</li>)}
              </ul>,
            ])}
          />
        </div>
        <p className="mt-3 text-[15px] text-ink-muted">Fees are shown for transparency and were not used to rank. {r.llmReasons
          ? "Reasons are written by AI from the engine's facts and checked against them; the ranking is the engine's."
          : "Reasons are rule-based."}</p>
      </section>}
      {r.excluded.length > 0 && (
        <details className="text-[15px] text-ink-700">
          <summary className="cursor-pointer text-ink-muted">{`Excluded by the suitability gate (${r.excluded.length})`}</summary>
          <ul className="mt-3 list-disc space-y-1.5 pl-5">{r.excluded.map((x) => <li key={x.name}><span className="font-semibold">{x.name}</span>: {x.reason}</li>)}</ul>
        </details>
      )}
      <section>
        {picked.length > 0 && (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-sm border border-hairline-strong px-5 py-3">
            <p className="text-sm text-ink-700">{picked.length} product{picked.length === 1 ? "" : "s"} ticked. They also show in the Product Shelf.</p>
            <Button variant="primary" size="sm" to={`/ps/cases/${clientId}/finalise`}>Finalise list</Button>
          </div>
        )}
      </section>
      <p>{r.tags.map((t) => <CitationTag key={t} tag={t} />)}</p>
    </div>
  );
}

/* ---- PS finalise-by-prompt: detect "I'm happy with X and Y" and match product names ---- */
const FINALISE_INTENT = /\b(finali[sz]e|happy with|ok with|okay with|fine with|good with|comfortable with|go with|going with|proceed with|shortlist|i like|i(?:'|’)ll take|i want to (?:take|go|proceed|keep)|i(?:'|’)m (?:ok|ok?ay|happy|fine) )/i;
interface Chat { id: number; title: string; messages: Msg[]; sessionId: string; /** Last activity (ms), for newest-first order and the date beside the title. */ at: number; /** Saved on the server (IS-98) but its messages are fetched only when opened. */ remote?: boolean; loaded?: boolean; /** Dedicated AI IPS chat: saved to the server and answers allocation questions. */ ips?: boolean }

function Direction({ d }: { d: MacroView["direction"] }) {
  return <DirectionArrow d={d === "Up" ? "up" : d === "Down" ? "down" : "flat"} size={16} />;
}

function DraftCard({ a, clientId, role }: { a: MarketAnswer; clientId: string; role: Role }) {
  const d = a.draft!;
  const [applied, setApplied] = useState(false);
  return (
    <section className="rounded-sm border border-hairline-strong p-6">
      <p className={label}>Draft for section {d.section}</p>
      <h4 className="mt-2 text-[22px] tracking-tight">{d.title}</h4>
      <BulletList text={d.text} className="mt-4 !space-y-2 !text-[17px] font-light !leading-7 text-ink-700" />
      <div className="mt-6 flex flex-wrap items-center gap-4">
        {applied
          ? <><span className="text-[15px] text-ink-muted">Applied to review pack</span><Button variant="primary" to={`/rm/clients/${clientId}/review/pack`}>Open review pack</Button></>
          : <Button variant="primary" onClick={() => { savePackDraft(clientId, d.section, d.text, role); setApplied(true); }}>{`Replace section ${d.section} text`}</Button>}
      </div>
    </section>
  );
}

function AnswerView({ a, picked, onToggle, clientId, role }: { a: MarketAnswer; picked: string[]; onToggle: (r: MarketRow) => void; clientId: string; role: Role }) {
  return (
    <div className="min-w-0 space-y-10 font-light">
      <p className="whitespace-pre-line text-[22px] leading-9 tracking-tight text-ink">{a.summary}</p>

      {a.draft && <DraftCard a={a} clientId={clientId} role={role} />}

      {a.market && (
        <section>
          <div className="flex flex-wrap items-center gap-3">
            <h4 className="text-[26px] font-light tracking-tight">Economic cycle: {a.market.phase}</h4>
            <span className="text-sm text-ink-muted">As of {a.market.asOf}</span>
          </div>
          <p className={`${label} mt-5`}>Macroeconomic events found online</p>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-[17px] leading-7 text-ink-700">{a.market.events.map((e) => <li key={e}>{e}</li>)}</ul>
          <p className={`${label} mb-3 mt-6`}>CIO view per asset class</p>
          <Table
            head={["Asset class", "View", "Industry focus", "Direction", "Why"]}
            rows={a.market.views.map((v) => [
              <span className="font-semibold">{v.assetClass}</span>,
              <Badge tone={viewTone[v.view]}>{v.view}</Badge>,
              v.industry,
              <Direction d={v.direction} />,
              <span className="block max-w-56 text-ink-700">{v.note}</span>,
            ])}
          />
        </section>
      )}

      {a.rows.length > 0 && (
        <section className="space-y-10">
          {/* Recommendations are grouped by the role each product fills; other rows by asset class. */}
          {[...new Set(a.rows.map((r) => r.role ?? r.assetClass))].map((group) => (
            <div key={group}>
              <h4 className="mb-3 text-[26px] font-light tracking-tight">{group}</h4>
              <Table
                head={["Select", "Product", "What it offers", "Why it suits this client"]}
                rows={a.rows.filter((r) => (r.role ?? r.assetClass) === group).map((r) => [
                  <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={picked.includes(r.product)} onChange={() => onToggle(r)} aria-label={`Select ${r.product}`} />,
                  <span className="block max-w-56 font-semibold">{r.product}</span>,
                  <span className="block max-w-48">{r.role ? `${r.assetClass} · ${r.industryFocus}` : r.industryFocus}</span>,
                  <ul className="block space-y-1.5 text-ink-700">
                    {(r.agentReason ? reasonLines(r.agentReason) : r.ranking).map((line) => <li key={line}><Tagged text={line} /></li>)}
                  </ul>,
                ])}
              />
            </div>
          ))}
          {picked.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-sm border border-hairline-strong px-5 py-3">
              <p className="text-sm text-ink-700">{picked.length} product{picked.length === 1 ? "" : "s"} ticked. They also show in the Product Shelf.</p>
              <Button variant="primary" size="sm" to={`/ps/cases/${clientId}/finalise`}>Finalise list</Button>
            </div>
          )}
        </section>
      )}

      <p>{a.tags.map((t) => <CitationTag key={t} tag={t} />)}</p>
    </div>
  );
}

/** The only client switcher in the app: the green-dot pill opens a small menu of clients. */
function ClientSwitcher({ clientId, name, role }: { clientId: string; name: string | null; role: Role }) {
  const [open, setOpen] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  // The RM's chat reads the client book DB (the same ids the profiling agent checks access against); PM/PS still use the mock list.
  useEffect(() => {
    let on = true;
    const load = role === "rm" ? arcApi.listBook().then((b) => b.clients.map(bookToClient)) : arcApi.listClients();
    load.then((c) => { if (on) setClients(c); }, () => { if (on) setClients([]); });
    return () => { on = false; };
  }, [role]);
  // A stale or mock active client (e.g. the old default `jfr`) is not in the RM's book: move to the first real book client.
  useEffect(() => {
    if (role !== "rm" || clients.length === 0 || clients.some((c) => c.id === clientId)) return;
    setActiveClientId(clients[0].id);
    const next = pathForClient(pathname, clients[0].id);
    if (next) navigate(next + search, { replace: true });
  }, [role, clients, clientId, pathname, search, navigate]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const choose = (id: string) => {
    setOpen(false);
    if (id === clientId) return;
    setActiveClientId(id);
    const next = pathForClient(pathname, id);
    if (next) navigate(next + search);
  };
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open} title="Switch client"
        className="inline-flex max-w-full items-center gap-2.5 rounded-full border border-hairline-strong bg-surface-100 px-4 py-1.5 text-[13px] text-ink hover:bg-surface-300">
        <span className="size-2 shrink-0 rounded-full bg-[#2e8b57]" />
        <span className="truncate">{name ?? "Client"}</span>
        <ChevronDown size={14} className={`shrink-0 text-ink-muted transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul role="listbox" aria-label="Clients" className="absolute right-0 top-full z-30 mt-2 min-w-56 rounded-sm border border-hairline-strong bg-surface-100 py-1 shadow-card">
          {clients.map((c) => (
            <li key={c.id} role="option" aria-selected={c.id === clientId}>
              <button type="button" onClick={() => choose(c.id)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-[14px] text-ink hover:bg-surface-300">
                <span className={`size-2 shrink-0 rounded-full ${c.id === clientId ? "bg-[#2e8b57]" : "bg-hairline-strong"}`} />
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                {c.id === clientId && <Check size={14} className="shrink-0 text-ink-muted" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The one Geneva chat. Used full-page (AI Assistant) and inside the floating launcher (compact). Style rules: AGENTS.md "Chatbot style". */
export function GenevaChat({ role, clientId, compact = false }: { role: Role; clientId: string; compact?: boolean }) {
  const { pathname: routePath } = useLocation();
  const onIpsDraft = role === "rm" && /\/clients\/[^/]+\/ips-draft\/?$/.test(routePath);
  const blank = (id: number): Chat => ({ id, title: DEFAULT_CHAT_TITLE, messages: [], sessionId: arcApi.newChatSession(role, clientId), at: Date.now() });
  const [chats, setChats] = useState<Chat[]>(() => [blank(1)]);
  const [source, setSource] = useState<SourceRef | null>(null);
  const closeSource = useCallback(() => setSource(null), []);
  const [activeId, setActiveId] = useState(1);
  const [draft, setDraft] = useState("");
  const [working, setWorking] = useState<{ chatId: number; steps: string[]; shown: number; model?: string } | null>(null);
  const picked = useSelection(clientId);
  const pickedNames = picked.map((r) => r.product);
  const toggle = (r: MarketRow) => toggleSelection(clientId, r);
  const activeIps = useActiveIps(clientId);
  const [clientIps, setClientIps] = useState<number | null | undefined>(undefined);
  const [clientName, setClientName] = useState<string | null>(null);
  useEffect(() => { let on = true; arcApi.getClient(clientId).then((c) => { if (on) { setClientIps(c?.ipsVersion ?? null); setClientName(c?.name ?? null); } }); return () => { on = false; }; }, [clientId]);
  // Active client changed (page switch or client select): start clean so answers never mix clients.
  const [seenClient, setSeenClient] = useState(clientId);
  if (seenClient !== clientId) {
    setSeenClient(clientId); setClientName(null); setClientIps(undefined);
    setChats([blank(1)]); setActiveId(1); setWorking(null); setDraft(""); setSource(null);
  }
  const ipsVersion = activeIps ?? clientIps ?? null;
  /** IS-98: named chats persisted per RM. The list loads on mount; a chat's messages load when it is opened. */
  const [chatsNote, setChatsNote] = useState<string | null>(null);
  const [chatsLoaded, setChatsLoaded] = useState(false);
  const chatQueue = useRef(new Map<number, Promise<unknown>>());
  const savedChat = useRef(new WeakSet<Msg>());
  useEffect(() => {
    let on = true;
    setChatsLoaded(false);
    listSavedChats().then((list) => {
      if (!on) return;
      setChatsLoaded(true);
      if (list === null) { setChatsNote(CHAT_HISTORY_UNAVAILABLE); return; }
      setChatsNote(null);
      setChats((cs) => {
        const have = new Set(cs.map((c) => c.sessionId));
        const add: Chat[] = list.filter((s) => !have.has(s.id)).map((s) => ({ id: nextId.current++, title: s.title, messages: [], sessionId: s.id, at: Date.parse(s.updatedAt) || 0, remote: true, loaded: false }));
        return add.length ? [...cs, ...add] : cs;
      });
    });
    return () => { on = false; };
  }, [clientId]);
  const nextId = useRef(2);
  const nameRef = useRef<string | null>(null);
  nameRef.current = clientName;
  /** AI IPS generation: one dedicated chat per run. Events replay for 5s, so handled ones are tracked by identity. */
  const genChat = useRef<number | null>(null);
  const handled = useRef(new WeakSet<IpsGenEvent>());
  const genSections = useRef<IpsGenSectionResult[]>([]);
  /** Messages already on the server (restored or saved); everything else in an IPS chat is saved once. */
  const saved = useRef(new WeakSet<Msg>());
  /** Notices about the saved IPS conversation (history unavailable, 100-message cap). Shown above the composer. */
  const [historyNote, setHistoryNote] = useState<string | null>(null);
  // Saved IPS chat survives closing the sidebar and reloads: load it when the client chat mounts.
  useEffect(() => {
    let on = true;
    setHistoryNote(null);
    arcApi.listIpsChatPage(clientId).then(({ messages: h, truncated, historyAvailable }) => {
      if (!on) return;
      setHistoryNote(historyNotice({ failed: !historyAvailable, truncated }));
      if (h.length === 0) return;
      const messages = h.map(restoreMsg);
      messages.forEach((m) => saved.current.add(m));
      setChats((cs) => cs.some((c) => c.ips && c.messages.every((m) => saved.current.has(m))) ? cs
        : cs.map((c) => c.id === 1 && c.messages.length === 0 ? { ...c, title: "IPS chat", messages, ips: true } : c));
    }).catch(() => { if (on) setHistoryNote(historyNotice({ failed: true })); });
    return () => { on = false; };
  }, [clientId]);
  useEffect(() => {
    chats.forEach((c) => {
      if (!c.ips) return;
      c.messages.forEach((m) => {
        if (m.ipsGen || m.approval || saved.current.has(m) || !m.text) return;
        saved.current.add(m);
        arcApi.appendIpsChat(clientId, m.from === "user" ? { role: "user", text: m.text, kind: "chat" }
          : { role: "assistant", text: m.text, kind: m.discuss ? "discuss" : "chat", meta: m.discuss ? { stance: m.discuss.stance, buckets: m.discuss.buckets, changes: m.discuss.changes, proposal: m.discuss.proposal ?? null, applied: !!m.discuss.applied } : null })
          .then((r) => { if (r && r.historyAvailable === false) setHistoryNote(historyNotice({ failed: true })); else if (r?.truncated) setHistoryNote(historyNotice({ truncated: true })); })
          .catch(() => setHistoryNote(historyNotice({ failed: true })));
      });
    });
  }, [chats, clientId]);
  // Every turn of a normal chat is saved in order; after Geneva's first reply the backend names the chat.
  useEffect(() => {
    chats.forEach((c) => {
      if (c.ips || (c.remote && !c.loaded)) return;
      c.messages.forEach((m) => {
        if (m.ipsGen || m.approval || savedChat.current.has(m) || !m.text) return;
        savedChat.current.add(m);
        const prev = chatQueue.current.get(c.id) ?? Promise.resolve();
        chatQueue.current.set(c.id, prev.then(async () => {
          const title = await saveChatMessage(c.sessionId, m.from === "user" ? "user" : "assistant", m.text);
          if (title === null) { setChatsNote(CHAT_HISTORY_UNAVAILABLE); return; }
          setChats((cs) => cs.map((x) => x.id === c.id ? { ...x, title, at: Date.now() } : x));
        }));
      });
    });
  }, [chats]);
  const selectChat = (id: number) => {
    setActiveId(id);
    const c = chats.find((x) => x.id === id);
    if (!c?.remote || c.loaded) return;
    setChats((cs) => cs.map((x) => x.id === id ? { ...x, loaded: true } : x));
    loadSavedMessages(c.sessionId).then((rows) => {
      if (rows === null) { setChatsNote(CHAT_HISTORY_UNAVAILABLE); setChats((cs) => cs.map((x) => x.id === id ? { ...x, loaded: false } : x)); return; }
      const messages: Msg[] = rows.map((r) => r.role === "user" ? { from: "user", text: r.text } : { from: "agent", text: r.text, reply: { text: r.text, runId: null } });
      messages.forEach((m) => savedChat.current.add(m));
      nearBottom.current = true;
      setChats((cs) => cs.map((x) => x.id === id ? { ...x, messages: [...messages, ...x.messages] } : x));
    });
  };
  const clearHistory = async () => {
    if (!window.confirm("Clear the saved IPS conversation for this client? This removes it for good.")) return;
    try { await arcApi.clearIpsChat(clientId); } catch { setHistoryNote(historyNotice({ failed: true })); return; }
    setHistoryNote(null);
    setChats((cs) => cs.map((c) => c.ips ? { ...c, messages: c.messages.filter((m) => m.ipsGen) } : c));
  };
  useEffect(() => {
    genChat.current = null;
    const apply = (id: number, fn: (g: NonNullable<Msg["ipsGen"]>) => NonNullable<Msg["ipsGen"]>) =>
      setChats((cs) => cs.map((c) => c.id !== id ? c : { ...c, messages: c.messages.map((m) => m.ipsGen ? { ...m, ipsGen: fn(m.ipsGen) } : m) }));
    const open = (name: string) => {
      const id = nextId.current++;
      genChat.current = id;
      genSections.current = [];
      const msg: Msg = { from: "agent", text: "", ipsGen: { clientName: name, sections: [], status: "running" } };
      setChats((cs) => [...cs, { ...blank(id), title: "AI IPS generation", messages: [msg], ips: true }]);
      setActiveId(id);
      return id;
    };
    // A run may already be going (or just have finished) while the sidebar was closed: rebuild its view from the store.
    const existing = getIpsRun(clientId);
    if (existing) {
      const id = nextId.current++;
      genChat.current = id;
      genSections.current = existing.sections;
      const msg: Msg = { from: "agent", text: "", ipsGen: { clientName: existing.clientName, sections: existing.sections, status: existing.status, error: existing.error, model: existing.unavailable ? undefined : existing.model, saved: existing.status === "done" ? existing.saved : undefined, unavailable: existing.unavailable } };
      setChats((cs) => [...cs, { ...blank(id), title: "AI IPS generation", messages: [msg], ips: true }]);
      setActiveId(id);
    }
    return subscribeIpsGen((e) => {
      if (e.clientId !== clientId || handled.current.has(e)) return;
      handled.current.add(e);
      // Replayed events of a run already restored from the store would only duplicate it.
      if (existing && e.type === "start") return;
      nearBottom.current = true;
      if (e.type === "model") { apply(genChat.current ?? open(nameRef.current ?? "Client"), (g) => ({ ...g, model: e.model, unavailable: e.unavailable })); return; }
      if (e.type === "start") { open(e.clientName ?? nameRef.current ?? "Client"); apply(genChat.current!, (g) => ({ ...g, model: e.model })); return; }
      const id = genChat.current ?? open(nameRef.current ?? "Client");
      if (e.type === "section") {
        genSections.current = [...genSections.current.filter((r) => r.section !== e.result.section), e.result];
        apply(id, (g) => ({ ...g, model: g.model ?? e.result.model ?? undefined, sections: [...g.sections.filter((r) => r.section !== e.result.section), e.result] }));
      } else if (e.type === "done") {
        apply(id, (g) => ({ ...g, status: "done", model: e.unavailable ? undefined : e.model ?? g.model, saved: e.saved, unavailable: e.unavailable }));
        // The generation line in the saved IPS chat is written by ipsGenStore (works with the sidebar closed).
      }
      else apply(id, (g) => ({ ...g, status: "error", error: e.message }));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);
  const chat = chats.find((c) => c.id === activeId) ?? chats[0];
  const ordered = [...chats].sort((a, b) => b.at - a.at);
  const noChatsYet = chatsLoaded && !chatsNote && chats.every((c) => c.ips ? false : !c.remote && c.messages.length === 0);
  const shownNote = historyNote ?? chatsNote;
  const busy = working?.chatId === chat.id;
  /** What produced the latest agent answer: a local model, a hosted API model, or plain rules. */
  const engine = (() => {
    const last = [...chat.messages].reverse().find((m) => m.from === "agent" && !m.approval);
    const rt = (last?.profiling?.data as { routing?: { method?: string; model?: string | null } } | undefined)?.routing;
    if (rt?.method === "local_llm") return { label: `Local LLM · ${rt.model ?? ""}`, dot: "bg-positive" };
    if (rt?.method === "regex") return { label: "Regex", dot: "bg-ink-muted" };
    if (last?.reply) return { label: "API model · Groq", dot: "bg-link" };
    if (last) return { label: "Rules", dot: "bg-ink-muted" };
    return { label: "No model yet", dot: "bg-ink-muted" };
  })();
  /** A paused money-moving action must be approved or declined before the chat can continue. */
  const awaitingApproval = chat.messages.some((m) => m.approval?.status === "pending");

  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const onScroll = () => {
    const el = scrollRef.current;
    if (el) nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
  };
  /** Follow new content only while the reader is already at the bottom; never yank them back. */
  useEffect(() => {
    const el = scrollRef.current;
    if (el && nearBottom.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [chat.messages, working?.shown]);

  const patch = (id: number, fn: (c: Chat) => Chat) => setChats((cs) => cs.map((c) => (c.id === id ? fn(c) : c)));
  const newChat = () => {
    const empty = chats.find((c) => !c.ips && !c.remote && c.messages.length === 0);
    if (empty) { setActiveId(empty.id); return; }
    const id = nextId.current++;
    setChats((cs) => [...cs, blank(id)]);
    setActiveId(id);
  };
  const removeChat = (id: number) => {
    const left = chats.filter((c) => c.id !== id);
    if (left.length === 0) { const nid = nextId.current++; setChats([blank(nid)]); setActiveId(nid); return; }
    setChats(left);
    if (activeId === id) setActiveId(left[0].id);
  };

  /** Run a backend call under the thinking card; "Thinking…" appears if it takes a moment, "Consolidating…" once it lands. */
  const withThinking = async <T,>(id: number, call: Promise<T>, steps: string[] = BACKEND_STEPS, detect?: (r: T) => string | null): Promise<T> => {
    setWorking({ chatId: id, steps, shown: 1 });
    const timer = setTimeout(() => setWorking((w) => (w?.chatId === id && w.shown < steps.length - 1 ? { ...w, shown: steps.length - 1 } : w)), 1700);
    try {
      const r = await call;
      clearTimeout(timer);
      const model = detect?.(r) ?? undefined;
      setWorking({ chatId: id, steps, shown: steps.length, model });
      await sleep(model ? 1100 : 600);
      return r;
    } finally {
      clearTimeout(timer);
    }
  };
  const addReply = (id: number, r: GenevaReply, q: string) => {
    const msg: Msg = r.requiresConfirmation
      ? { from: "agent", text: r.text, approval: { action: r.pendingAction, status: "pending" } }
      : { from: "agent", text: r.text, reply: { text: r.text, runId: r.runId } };
    patch(id, (c) => ({ ...c, messages: [...c.messages, msg] }));
    if (!r.requiresConfirmation) appendChatContext(clientId, role, { q, a: markdownPlain(r.text) });
  };
  /** Approve or decline a paused action; the backend resumes the same session and answers. */
  const decide = async (id: number, index: number, approved: boolean) => {
    const target = chats.find((c) => c.id === id);
    if (!target || working) return;
    patch(id, (c) => ({ ...c, messages: c.messages.map((m, i) => (i === index && m.approval ? { ...m, approval: { ...m.approval, status: approved ? "approved" : "declined" } } : m)) }));
    nearBottom.current = true;
    try {
      addReply(id, await withThinking(id, arcApi.confirmBackendAction(target.sessionId, approved)), approved ? "Approved the proposed action" : "Declined the proposed action");
    } catch (e) {
      patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
    } finally {
      setWorking((w) => (w?.chatId === id ? null : w));
    }
  };

  const addIpsNote = (msgIndex: number, b: PaBucketId) => {
    const x = chat.messages[msgIndex]?.ipsExplain;
    if (!x || x.added.includes(b)) return;
    appendIpsDraftNote(clientId, b, x.bullets.map((t) => `- ${t}`).join("\n"));
    patch(chat.id, (c) => ({ ...c, messages: c.messages.map((m, j) => j === msgIndex && m.ipsExplain ? { ...m, ipsExplain: { ...m.ipsExplain, added: [...m.ipsExplain.added, b] } } : m) }));
  };

  /** The allocation the backend should reason about: the live IPS editor values, else the newest one in this chat; otherwise the backend reads the saved IPS. */
  const currentAllocation = (msgs: Msg[]): { buckets: { id: string; strategy: string; justification?: string }[] } | undefined => {
    const x = getIpsDraftExtras(clientId);
    const ids = ["liquidity", "longevity", "legacy"] as const;
    if (x.allocation && ids.some((b) => x.allocation?.[b])) return { buckets: ids.filter((b) => x.allocation?.[b]).map((b) => ({ id: b, strategy: x.allocation![b]!, justification: x.allocationNotes?.[b] })) };
    const l = latestAllocation(msgs);
    return l ? { buckets: l.map((b) => ({ id: b.id, strategy: b.strategy, justification: b.justification })) } : undefined;
  };
  /** One 3L allocation turn through the Client Profiling /chat (stance, proposal, applied). History is stored server-side per RM, so none is sent; a pending proposal is echoed back for the confirm turn. */
  const runAllocationTurn = async (id: number, text: string, pending: AllocationProposal | null) => {
    const msgs = chats.find((c) => c.id === id)?.messages ?? [];
    const current = currentAllocation(msgs);
    try {
      const r = await withThinking(id, arcApi.clientProfilingChat(clientId, text, null, { allocation: current, pending_proposal: pending }), ["Allocation agent fired", "Reading the meeting notes and strategy table…", "Weighing your point…", "Consolidating…"]);
      const d = r.tool === "allocation_dialogue" ? (r.data?.allocation_dialogue as AllocationDialogue | undefined) : undefined;
      if (!d) {
        // Not an allocation turn after all: show it like any profiling answer.
        if (r.tool !== "out_of_scope" && r.data?.routing?.method !== "unavailable") patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: r.message, profiling: r }] }));
        else patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: r.message || "I can only answer questions about this client's meeting notes or IPS here." }] }));
        return;
      }
      const now = d.allocation?.buckets ?? current?.buckets ?? [];
      const changes = (d.proposal?.changes ?? []).map((bid) => {
        const to = d.proposal?.buckets.find((b) => b.id === bid);
        return `${BUCKET_LABEL[bid] ?? bid}: ${now.find((b) => b.id === bid)?.strategy ?? "-"} to ${to?.strategy ?? "-"} ${to?.strategyName ?? ""}`.trim();
      });
      const msg: Msg = { from: "agent", text: d.text.replace(/^(Agrees|Disagrees|Partly agrees)\.\s*/, ""), discuss: {
        stance: d.stance ?? "info", buckets: now, changes, applied: d.applied, proposal: d.proposal ?? null,
        citations: (d.sources ?? []).map((x) => ({ noteId: x.id, date: x.date, title: x.label, passage: x.passage })) } };
      // A new answer settles any earlier pending proposal (applied, rejected or replaced): its Apply button goes away.
      patch(id, (c) => ({ ...c, messages: [...c.messages.map((m) => m.discuss?.proposal ? { ...m, discuss: { ...m.discuss, proposal: null, applied: m.discuss.applied || (d.applied && !!pending) } } : m), msg] }));
      if (d.applied) afterApplied(d);
    } catch (e) {
      patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
    } finally {
      setWorking((w) => (w?.chatId === id ? null : w));
    }
  };
  /** The backend confirmed a change: put it in the IPS draft (the open editor autosaves it); with no editor open, save it into the Draft IPS and refresh the versions list. */
  const afterApplied = (d: AllocationDialogue) => {
    const buckets = d.allocation?.buckets ?? [];
    if (!buckets.length) return;
    const allocation: Record<string, string> = {}; const allocationNotes: Record<string, string> = {};
    buckets.forEach((b) => { allocation[b.id] = b.strategy; if (b.justification) allocationNotes[b.id] = b.justification; });
    saveIpsDraftExtras(clientId, { allocation, allocationNotes });
    if (!document.querySelector("[data-ips-editor]")) {
      void arcApi.applyAllocationToIps(clientId, buckets).then((ok) => { if (ok) window.dispatchEvent(new CustomEvent("ips-versions-changed", { detail: { clientId } })); });
    }
  };
  /** "Apply change": the confirm turn. Only the backend applies it, and only for the proposal echoed back. */
  const applyChange = (chatId: number, idx: number) => {
    const c = chats.find((x) => x.id === chatId); const proposal = c?.messages[idx]?.discuss?.proposal;
    if (!proposal || busy) return;
    nearBottom.current = true;
    patch(chatId, (cc) => ({ ...cc, messages: [...cc.messages, { from: "user", text: "confirm" }] }));
    setWorking({ chatId, steps: [], shown: 0 });
    void runAllocationTurn(chatId, "confirm", proposal);
  };
  const send = async (raw: string, profilingClient?: string, source?: ClientProfilingSourceChoice, resend = false) => {
    const text = raw.trim();
    if (!text || busy || awaitingApproval) return;
    const id = chat.id;
    const sessionId = chat.sessionId;
    nearBottom.current = true;
    setDraft("");
    patch(id, (c) => ({ ...c, messages: resend ? c.messages : [...c.messages, { from: "user", text }] }));
    setWorking({ chatId: id, steps: [], shown: 0 });
    if (chat.ips && !profilingClient) {
      const pending = pendingProposalOf(chat.messages);
      if (ALLOC_INTENT.test(text) || (pending && PROPOSAL_REPLY.test(text))) { await runAllocationTurn(id, text, pending); return; }
    }
    if (onIpsDraft && !profilingClient) {
      // On the IPS draft editor every question is about the proposed portfolios; answered by the Portfolio Agent from the draft weights + client profile.
      const history: PaChatTurn[] = [];
      chat.messages.forEach((m, i) => {
        const next = chat.messages[i + 1];
        if (m.from === "user" && next?.from === "agent" && next.text) history.push({ question: m.text, answer: next.text });
      });
      try {
        const { q, buckets } = await buildIpsDraftQuestion(clientId, text);
        const r = await withThinking(id, arcApi.askPortfolioAgent(clientId, q, history), PA_STEPS);
        const bullets = answerBullets(r.answer);
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: bullets.join(" "), ipsExplain: { bullets, named: namedBucket(text), buckets, added: [] } }] }));
      } catch (e) {
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
      } finally {
        setWorking((w) => (w?.chatId === id ? null : w));
      }
      return;
    }
    if (profilingClient || role === "rm" || role === "pm") {
      // Every rm/pm message is probed; the backend's local LLM decides. Out of scope, model off, or probe failure => fall through silently.
      let r: ClientProfilingResult | null = null;
      try {
        const opts = { source };
        r = profilingClient
          ? await withThinking(id, arcApi.clientProfilingChat(profilingClient, text, null, opts), ["Choosing the right tool…", "Reading this client's records…", "Writing a sourced answer…"], (x) => x?.data?.routing?.method === "local_llm" ? (x.data.routing.model ?? null) : null)
          : await (async () => {
            const steps = ["Client Profiling Agent fired", "Reading this client's meeting notes…", "Checking the answer against the notes…", "Consolidating…"];
            setWorking({ chatId: id, steps, shown: 1 });
            const tick = setInterval(() => setWorking((w) => (w?.chatId === id && w.shown < steps.length ? { ...w, shown: w.shown + 1 } : w)), 1500);
            try { return await arcApi.clientProfilingChat(clientId, text, ipsVersion, opts); } finally { clearInterval(tick); }
          })();
      } catch (e) {
        if (profilingClient) patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
      }
      const usedModel = r?.data?.routing?.method === "local_llm" ? (r.data.routing.model ?? undefined) : undefined;
      if (usedModel && !profilingClient) {
        setWorking((w) => (w?.chatId === id ? { ...w, shown: w.steps.length, model: usedModel } : w));
        await sleep(1100);
      }
      const mine = !!r && r.tool !== "out_of_scope" && r.data?.routing?.method !== "unavailable";
      if (r && mine) {
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: r.message, profiling: r, profilingClient }] }));
        appendChatContext(clientId, role, { q: text, a: markdownPlain(r.message) });
      }
      if (profilingClient && r && !mine) {
        // Pinned client: never swallow the result; say plainly why there is no answer.
        const tool = String(r.tool);
        const down = tool === "routing_unavailable" || tool === "unavailable" || r.data?.routing?.method === "unavailable";
        const msg = down
          ? (r.message?.trim() || "The local model is unavailable, so I couldn't answer. Please try again once it is running.")
          : "I can only answer questions about this client's meeting notes or IPS here.";
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: msg }] }));
      }
      if (profilingClient || mine) {
        setWorking((w) => (w?.chatId === id ? null : w));
        return;
      }
    }
    if (role === "ps" && MATCH_INTENT.test(text)) {
      try {
        const { steps, rec } = await buildRecommendation(clientId, ipsVersion);
        setWorking({ chatId: id, steps, shown: 0 });
        for (let i = 1; i <= steps.length; i++) { setWorking({ chatId: id, steps, shown: i }); await pause(700, 1200); }
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: "", recommend: rec }] }));
        appendChatContext(clientId, role, { q: text, a: `Shortlist for ${rec.name} (risk level ${rec.riskLevel ?? "not established"}): ${rec.shortlist.map((x) => x.row.product).join(", ")}.` });
      } catch (e) {
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
      } finally {
        setWorking((w) => (w?.chatId === id ? null : w));
      }
      return;
    }
    const assetClass = role === "ps" ? askedAssetClass(text) : null;
    if (assetClass) {
      try {
        const v = await arcApi.getAssetClassView(assetClass, clientId);
        const steps = [
          "Intent parser is reading your request…",
          "Product Recommender fired",
          `Reading the CIO House View on ${assetClass.toLowerCase()}…`,
          `Scoring ${v.agent_view?.coverage.available ?? 0} market series from the latest Market Researcher run…`,
          "Checking segments, scenarios and risks…",
          "Consolidating…",
        ];
        setWorking({ chatId: id, steps, shown: 0 });
        for (let i = 1; i <= steps.length; i++) { setWorking({ chatId: id, steps, shown: i }); await pause(600, 1000); }
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: "", assetView: v }] }));
        appendChatContext(clientId, role, { q: text, a: `${v.asset_class}: CIO ${v.cio_view.view} (${v.cio_view.cio_term}); agent ${v.agent_view?.view ?? "unavailable"}. ${v.agent_view?.thesis ?? ""}` });
      } catch (e) {
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
      } finally {
        setWorking((w) => (w?.chatId === id ? null : w));
      }
      return;
    }
    if (role === "ps" && FINALISE_INTENT.test(text)) {
      let reply: string; let names: string[] | undefined;
      try {
        const products = await arcApi.getProducts(clientId);
        const named = findProducts(text, products, (p) => p.name, (p) => p.id);
        if (named.length === 0) {
          reply = "I could not tell which products you mean. Please name the products you are happy with, for example \"finalise the Global Quality Dividend ETF and the Singapore Government Bond ETF\".";
        } else {
          // Named products go through the suitability gate first; only those that pass can be finalised.
          const [res] = await Promise.all([
            arcApi.recommendProducts(clientId, { named_products: named.map((p) => p.id), top_n: 20, max_per_asset_class: 20 }), sleep(500),
          ]);
          const ok = res.shortlist.filter((s) => named.some((p) => p.id === s.product.product_id)).map(shortlistRow);
          const refused = res.named_products.filter((n) => n.status === "excluded")
            .map((n) => `${products.find((p) => p.id === n.product_id)?.name ?? n.query}: ${n.reason}`);
          if (ok.length) {
            saveSelection(clientId, ok);
            names = ok.map((r) => r.product);
          }
          reply = [
            ok.length ? `Noted. I have put ${ok.length} product${ok.length === 1 ? "" : "s"} on your finalise list. Review them and add your reasons on the next page. Nothing is approved until you confirm.` : "",
            refused.length ? `Not added, because ${refused.length === 1 ? "it fails" : "they fail"} the suitability gate: ${refused.join(" ")}` : "",
          ].filter(Boolean).join(" ");
        }
      } catch (e) {
        reply = failText(e);
      }
      patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: reply, finalise: names ?? [] }] }));
      setWorking(null);
      return;
    }
    if ((role === "rm" || role === "pm") && PORTFOLIO_INTENT.test(text) && !OTHER_AGENT_INTENT.test(text)) {
      const history: PaChatTurn[] = [];
      chat.messages.forEach((m, i) => {
        const next = chat.messages[i + 1];
        if (m.from === "user" && next?.from === "agent" && next.text) history.push({ question: m.text, answer: next.text });
      });
      try {
        const r = await withThinking(id, arcApi.askPortfolioAgent(clientId, text, history), PA_STEPS);
        addReply(id, { text: paReplyText(r), runId: null, requiresConfirmation: false, pendingAction: null }, text);
      } catch (e) {
        patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
      } finally {
        setWorking((w) => (w?.chatId === id ? null : w));
      }
      return;
    }
    try {
      // Client-data and workflow intents are answered from the workspace; anything else goes to the LangGraph backend.
      const a = await arcApi.answerLocally(role, clientId, text, ipsVersion);
      if (!a) {
        addReply(id, await withThinking(id, arcApi.askBackend(role, clientId, sessionId, text, ipsVersion), BACKEND_STEPS, () => "Groq"), text);
        return;
      }
      setWorking({ chatId: id, steps: a.steps, shown: 0 });
      for (let i = 1; i <= a.steps.length; i++) { setWorking({ chatId: id, steps: a.steps, shown: i }); await sleep(i === 2 ? 1200 : 900); }
      await sleep(400);
      if (a.autoTick) {
        const cur = loadSelection(clientId);
        saveSelection(clientId, [...cur, ...a.rows.filter((r) => !cur.some((x) => x.product === r.product))]);
      }
      patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: a.summary, answer: a }] }));
      appendChatContext(clientId, role, { q: text, a: answerPlainText(a) });
    } catch (e) {
      patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: failText(e) }] }));
    } finally {
      setWorking((w) => (w?.chatId === id ? null : w));
    }
  };

  const composer = (
    <form className="mx-auto flex w-full max-w-4xl items-center gap-3 rounded-full border border-hairline-strong bg-surface-100 py-2 pl-6 pr-2" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
      <input value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Message Geneva" disabled={awaitingApproval}
        placeholder={awaitingApproval ? "Approve or decline the proposed action first" : PLACEHOLDER[role]}
        className="min-h-10 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-muted" />
      <button type="submit" disabled={busy || awaitingApproval || !draft.trim()} aria-label="Send" title="Send"
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-brand text-white disabled:opacity-40"><ArrowUp size={18} /></button>
    </form>
  );

  return (
    <div className={`geneva-light ${compact ? "flex h-full min-h-0 flex-col overflow-hidden bg-surface-200" : "flex min-h-[640px] flex-col overflow-hidden rounded-lg border border-hairline bg-surface-200 lg:h-[calc(100vh-18rem)] lg:min-h-[640px] lg:flex-row"}`}>
      {compact && (
        <div className="flex items-center gap-3 border-b border-hairline px-6 py-3">
          <select value={chat.id} onChange={(e) => selectChat(Number(e.target.value))} aria-label="Chats" className="min-w-0 flex-1 truncate rounded-sm border border-hairline bg-surface-100 px-3 py-2 text-[14px] text-ink">
            {ordered.map((c) => <option key={c.id} value={c.id} title={c.title}>{shortTitle(c.title)} · {chatDate(c.at)}</option>)}
          </select>
          <button type="button" onClick={newChat} aria-label="New chat" title="New chat" className="inline-flex size-9 items-center justify-center rounded-sm border border-hairline-strong text-ink hover:bg-surface-300"><MessageSquarePlus size={16} /></button>
          {(chat.ips || (!chat.remote && chat.messages.length === 0)) && <button type="button" onClick={() => removeChat(chat.id)} aria-label="Delete chat" title="Delete chat" className="inline-flex size-9 items-center justify-center rounded-sm border border-hairline text-ink-muted hover:text-negative"><Trash2 size={16} /></button>}
        </div>
      )}
      <aside className={`${compact ? "hidden" : "flex"} w-full shrink-0 flex-col border-b border-hairline p-4 lg:w-80 lg:border-b-0 lg:border-r`}>
        <button type="button" onClick={newChat} className="flex w-full items-center gap-3 rounded-sm px-3 py-2.5 text-left text-[15px] hover:bg-surface-300">
          <MessageSquarePlus size={18} /> New chat
        </button>
        <p className="mt-5 px-3 text-[13px] text-ink-muted">Chats</p>
        <ul className="mt-2 flex-1 space-y-1 overflow-y-auto">
          {ordered.map((c) => (
            <li key={c.id} className={`group flex items-center gap-2 rounded-sm px-3 py-2.5 ${c.id === chat.id ? "bg-surface-300" : "hover:bg-surface-300"}`}>
              <button type="button" onClick={() => selectChat(c.id)} title={c.title} className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[15px]">{shortTitle(c.title)}</span>
                <span className="block text-[12px] font-light text-ink-muted">{chatDate(c.at)}</span>
              </button>
              {(c.ips || (!c.remote && c.messages.length === 0)) && <button type="button" onClick={() => removeChat(c.id)} aria-label="Delete chat" title="Delete chat" className="text-ink-muted opacity-0 hover:text-negative focus:opacity-100 group-hover:opacity-100"><Trash2 size={15} /></button>}
            </li>
          ))}
        </ul>
        {noChatsYet && <p role="status" className="px-3 pb-2 text-[13px] font-light text-ink-muted">No chats yet</p>}
      </aside>

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-end gap-3 border-b border-hairline px-6 py-3 sm:px-10">
          <ClientSwitcher clientId={clientId} name={clientName} role={role} />
          <Link to={`/${role}/clients/${clientId}/documents`} title="Open the client's IPS" className="inline-flex items-center gap-2.5 rounded-full border border-hairline-strong bg-surface-100 px-4 py-1.5 text-[13px] text-ink hover:bg-surface-300">
            <span className={`size-2 rounded-full ${ipsVersion ? "bg-positive" : "bg-ink-muted"}`} />
            {ipsVersion ? `Using IPS v${ipsVersion}` : "No active IPS"}
          </Link>
          <button type="button" title="Model used for the last answer"
            className="inline-flex items-center gap-2.5 rounded-full border border-hairline-strong bg-surface-100 px-4 py-1.5 text-[13px] text-ink hover:bg-surface-300">
            <span className={`size-2 rounded-full ${engine.dot}`} />
            {engine.label}
          </button>
        </div>
        {chat.messages.length === 0 && !busy ? (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center-safe overflow-y-auto px-8 py-10">
            <img src="/ubs-logo.png" alt="Geneva" className="ubs-logo mb-5 h-10 w-auto" />
            <h2 className="mb-8 text-center text-3xl font-light">{HEADING[role]}</h2>
            {noChatsYet && compact && <p role="status" className="mb-3 text-[13px] font-light text-ink-muted">No chats yet</p>}
            {shownNote && <p role="status" className="mb-3 border-l border-hairline-strong pl-3 text-[13px] font-light text-ink-muted">Geneva: {shownNote}</p>}
            {composer}
            <ul className="mt-6 w-full max-w-4xl">
              {SEEDED[role].map((q) => (
                <li key={q}>
                  <button type="button" onClick={() => send(q)} className="flex w-full items-start gap-4 rounded-sm px-4 py-3 text-left text-[15px] leading-6 text-ink-700 hover:bg-surface-300 hover:text-ink">
                    <Search size={18} className="mt-0.5 shrink-0 text-ink-muted" /> {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <>
            <div ref={scrollRef} onScroll={onScroll} role="log" aria-live="polite" className="flex min-h-0 flex-1 flex-col gap-8 overflow-y-auto [&>*]:shrink-0 overflow-x-hidden px-6 py-8 text-[15px] leading-6 sm:px-10 sm:py-10">
              {chat.messages.map((m, i) => m.from === "user" ? (
                <div key={i} className="max-w-[80%] self-end rounded-sm bg-surface-300 px-5 py-3.5">{m.text}</div>
              ) : (
                <div key={i} className="animate-geneva-in w-full rounded-sm border border-hairline bg-surface-100 px-8 py-7">
                  <p className="mb-4 flex items-center gap-2 text-[13px] font-medium text-ink-muted"><img src="/ubs-logo.png" alt="" className="ubs-logo h-4 w-auto" />Geneva</p>
                  {m.finalise && (
                    <div className="space-y-6 font-light">
                      <p className="text-[19px] leading-8 tracking-tight text-ink">{m.text}</p>
                      {m.finalise.length > 0 && (
                        <>
                          <ul className="list-disc space-y-1 pl-5 text-[17px] leading-7 text-ink-700">{m.finalise.map((n) => <li key={n}>{n}</li>)}</ul>
                          <div><Button variant="primary" size="sm" to={`/ps/cases/${clientId}/finalise`}>Finalise list</Button></div>
                        </>
                      )}
                    </div>
                  )}
                  {m.recommend && <RecommendView r={m.recommend} picked={pickedNames} onToggle={toggle} clientId={clientId} />}
                  {m.ipsExplain && <IpsExplainCard x={m.ipsExplain} onAdd={(b) => addIpsNote(i, b)} />}
                  {m.assetView && <AssetViewCard v={m.assetView} clientId={clientId} />}
                  {m.answer && <AnswerView a={m.answer} picked={pickedNames} onToggle={toggle} clientId={clientId} role={role} />}
                  {m.profiling && <ClientProfilingCard r={m.profiling} role={role} onAsk={(cid) => send(chat.messages[i - 1]?.text ?? "", cid)} onSource={(src) => send(lastUserBefore(chat.messages, i), m.profilingClient, src, true)} />}
                  {m.discuss && (
                    <div className="space-y-5 font-light">
                      <span className="inline-flex items-center border border-hairline-strong px-3 py-1 text-[12px] uppercase tracking-[0.14em] text-ink">{STANCE_LABEL[m.discuss.stance] ?? m.discuss.stance}</span>
                      <p className="text-[17px] leading-7 text-ink-700">{m.text}</p>
                      {m.discuss.changes.length > 0 && (
                        <div>
                          <p className={label}>Suggested change to the allocation</p>
                          <ul className="mt-2 list-disc space-y-1 pl-5 text-[16px] leading-7 text-ink-700">{m.discuss.changes.map((c) => <li key={c}>{c}</li>)}</ul>
                          {m.discuss.proposal && !m.discuss.applied ? (
                            <div className="mt-4 flex items-center gap-4">
                              <Button variant="primary" size="sm" disabled={busy} onClick={() => applyChange(chat.id, i)}>Apply change</Button>
                              <span className="text-[14px] text-ink-muted">Nothing changes until you confirm.</span>
                            </div>
                          ) : m.discuss.applied ? <p className="mt-3 text-[14px] text-ink-muted">Applied to the IPS draft.</p>
                            : <p className="mt-2 text-[14px] text-ink-muted">Not applied.</p>}
                        </div>
                      )}
                      {m.discuss.changes.length === 0 && m.discuss.applied && <p className="text-[14px] text-ink-muted">Applied to the IPS draft.</p>}
                      {m.discuss.citations.length > 0 && (
                        <ul className="space-y-1 text-[14px] leading-6 text-ink-muted">
                          {m.discuss.citations.map((c, k) => <li key={k}>{c.noteId && <CitationTag tag={c.noteId} />}{` ${c.date ?? ""} ${c.title ?? ""}`}{c.passage && <span>{` “${c.passage}”`}</span>}</li>)}
                        </ul>
                      )}
                    </div>
                  )}
                  {m.ipsGen && <IpsGenView g={m.ipsGen} clientId={clientId} role={role} />}
                  {m.reply && <GenevaMarkdown text={m.reply.text} runId={m.reply.runId} onOpenSource={setSource} />}
                  {m.approval && (
                    <div className="space-y-6 font-light">
                      <p className={label}>Action needs your approval</p>
                      <p className="text-[19px] leading-8 tracking-tight text-ink">{m.text}</p>
                      {m.approval.status === "pending" ? (
                        <div className="flex flex-wrap items-center gap-4">
                          <Button variant="primary" size="sm" disabled={busy} onClick={() => decide(chat.id, i, true)}>Approve</Button>
                          <Button variant="secondary" size="sm" disabled={busy} onClick={() => decide(chat.id, i, false)}>Decline</Button>
                          <span className="text-[14px] text-ink-muted">Nothing happens until you approve.</span>
                        </div>
                      ) : <p className="text-[15px] text-ink-muted">{m.approval.status === "approved" ? "You approved this action." : "You declined this action."}</p>}
                    </div>
                  )}
                </div>
              ))}
              {busy && working && (
                <div className="animate-geneva-in min-h-[320px] rounded-sm border border-hairline bg-surface-100 px-10 py-9">
                  <p className="flex items-center gap-2 text-[13px] font-medium"><img src="/ubs-logo.png" alt="" className="ubs-logo h-4 w-auto" /><span className="animate-geneva-flow">Geneva</span></p>
                  <p className="mt-6 text-[26px] font-light tracking-tight text-ink"><span className="animate-geneva-flow">Preparing your analysis</span></p>
                  <div className="mt-6 h-px bg-hairline-strong" />
                  <ol className="mt-8 space-y-0">
                    {working.steps.slice(0, working.shown).map((st, i) => {
                      const current = i === working.shown - 1;
                      const fired = / fired$/.test(st) ? st.replace(/ fired$/, "").split(" and ") : null;
                      return (
                        <li key={i} className="animate-geneva-in flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hairline py-4 first:border-t-0">
                          <span className="animate-geneva-flow w-7 text-xs tabular-nums tracking-[0.12em]">{String(i + 1).padStart(2, "0")}</span>
                          {fired ? (
                            <>
                              {fired.map((n) => (
                                <span key={n} className="inline-flex items-center gap-2.5 border border-hairline-strong px-3.5 py-1.5 text-[12px] font-medium uppercase tracking-[0.14em] text-ink">
                                  <span className="size-1 rounded-full bg-ink-muted" /><span className="animate-geneva-flow">{n}</span>
                                </span>
                              ))}
                              <span className="animate-geneva-flow text-[15px] font-light">engaged</span>
                            </>
                          ) : <span className="animate-geneva-flow text-[16px] font-light">{st}</span>}
                          {!current && <Check size={14} strokeWidth={1.5} className="ml-auto text-ink-muted" />}
                        </li>
                      );
                    })}
                    {working.model && (
                      <li className="animate-geneva-in flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hairline py-4">
                        <span className="animate-geneva-flow w-7 text-xs tabular-nums tracking-[0.12em]">{String(working.shown + 1).padStart(2, "0")}</span>
                        <span className="animate-geneva-flow text-[16px] font-light">Answered with</span>
                        <span className="inline-flex items-center border border-hairline-strong px-3.5 py-1.5 text-[12px] font-medium tracking-[0.06em] text-ink">{working.model}</span>
                      </li>
                    )}
                  </ol>
                </div>
              )}
              
            </div>
            <div className="px-10 pb-8 pt-2">
              {chat.ips && chat.messages.some((m) => !m.ipsGen) && (
                <div className="mx-auto mb-2 flex w-full max-w-4xl justify-end">
                  <button type="button" onClick={clearHistory} className="inline-flex items-center gap-1.5 text-[13px] font-light text-ink-muted hover:text-ink"><Trash2 size={13} strokeWidth={1.5} />Clear history</button>
                </div>
              )}
              {shownNote && <p role="status" className="mx-auto mb-3 w-full max-w-4xl border-l border-hairline-strong pl-3 text-[13px] font-light text-ink-muted">Geneva: {shownNote}</p>}
              {composer}
            </div>
          </>
        )}
      </section>
      <GenevaArticlePanel source={source} onClose={closeSource} />
    </div>
  );
}
