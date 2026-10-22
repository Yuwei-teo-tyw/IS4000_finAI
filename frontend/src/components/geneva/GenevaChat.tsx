import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ArrowUp, MessageSquarePlus, Search, Trash2 } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { Client } from "../../types/arc";
import { pathForClient, setActiveClientId } from "../../layouts/navConfig";
import { arcApi, assetClassSlug, GenevaBackendError, PortfolioAgentError, ProductRecommenderError, shortlistRow } from "../../services/arcApi";
import type { PaChatReply, PaChatTurn } from "../../types/portfolio";
import { RefLine, ViewHeadline } from "../ps/AssetViewParts";
import type { PrAssetView } from "../../types/productRecommender";
import { findProducts } from "../../utils/productMatch";
import { toggleSelection, useActiveIps, useSelection, loadSelection, saveSelection } from "../../services/workflowStore";
import type { GenevaPendingAction, GenevaReply, MacroView, MarketAnswer, MarketRow, Role } from "../../types/arc";
import { Badge, BulletList, Button, CitationTag, DirectionArrow, Table, toBulletItems } from "../ui";
import { savePackDraft } from "../../services/packDraftStore";
import { appendChatContext } from "../../services/chatContextStore";
import { GenevaMarkdown, Tagged, type SourceRef } from "./GenevaMarkdown";
import { GenevaArticlePanel } from "./GenevaArticlePanel";

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
  excluded: { name: string; reason: string }[];
  /** True when at least one reason was written by the LLM from the engine's facts. */
  llmReasons: boolean;
}
/** `reply` = a LangGraph answer (Markdown); `approval` = a money-moving action the backend paused on, waiting for the user. */
interface Msg {
  from: "user" | "agent"; text: string; answer?: MarketAnswer; finalise?: string[]; recommend?: Recommend; assetView?: PrAssetView;
  reply?: { text: string; runId: string | null };
  approval?: { action: GenevaPendingAction | null; status: "pending" | "approved" | "declined" };
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

const MATCH_INTENT = /read client ips.*(research market|match products)/i;
/** Agent failures are shown, never replaced with mock answers. */
const failText = (e: unknown) => e instanceof ProductRecommenderError || e instanceof PortfolioAgentError
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
  const from = r.basis === "pm" ? "the PM's SAA proposal" : "a Portfolio Agent run for this chat (not saved to the SAA request)";
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
      excluded: res.excluded.map((x) => ({ name: x.product_name, reason: x.reason })),
      llmReasons: res.shortlist.some((s) => s.reason.source === "llm"),
    },
  };
}

/** Reason bullets for display: the trailing full stop after a closing tag would wrap onto its own line. */
const reasonLines = (text: string) => toBulletItems(text).map((l) => l.replace(/\]\.$/, "]"));

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
        <div className="mt-3">
          <Table
            head={["Select", "Rank", "Product", "Why it suits this client"]}
            rows={r.shortlist.map((s, i) => [
              <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={picked.includes(s.row.product)} onChange={() => onToggle(s.row)} aria-label={`Select ${s.row.product}`} />,
              String(i + 1),
              <span className="block min-w-36 max-w-48">
                <span className="block font-semibold">{s.row.product}</span>
                <span className="mt-2 block text-[14px] text-ink-muted">Risk {s.riskRating} of 5</span>
                <span className="block text-[14px] text-ink-muted">{s.fee === null ? "Fee not available" : `Fee ${s.fee.toFixed(2)}%`}, information only</span>
              </span>,
              <ul className="block space-y-1.5 text-ink-700">
                {reasonLines(s.reason).map((line) => <li key={line}><Tagged text={line} /></li>)}
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
interface Chat { id: number; title: string; messages: Msg[]; sessionId: string }

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
          {[...new Set(a.rows.map((r) => r.assetClass))].map((cls) => (
            <div key={cls}>
              <h4 className="mb-3 text-[26px] font-light tracking-tight">{cls}</h4>
              <Table
                head={["Select", "Product", "What it offers", "Why it suits this client"]}
                rows={a.rows.filter((r) => r.assetClass === cls).map((r) => [
                  <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={picked.includes(r.product)} onChange={() => onToggle(r)} aria-label={`Select ${r.product}`} />,
                  <span className="block max-w-56 font-semibold">{r.product}</span>,
                  <span className="block max-w-48">{r.industryFocus}</span>,
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
function ClientSwitcher({ clientId, name }: { clientId: string; name: string | null }) {
  const [open, setOpen] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  useEffect(() => { let on = true; arcApi.listClients().then((c) => { if (on) setClients(c); }); return () => { on = false; }; }, []);
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
  const blank = (id: number): Chat => ({ id, title: "New chat", messages: [], sessionId: arcApi.newChatSession(role, clientId) });
  const [chats, setChats] = useState<Chat[]>(() => [blank(1)]);
  const [source, setSource] = useState<SourceRef | null>(null);
  const closeSource = useCallback(() => setSource(null), []);
  const [activeId, setActiveId] = useState(1);
  const [draft, setDraft] = useState("");
  const [working, setWorking] = useState<{ chatId: number; steps: string[]; shown: number } | null>(null);
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
  const nextId = useRef(2);
  const chat = chats.find((c) => c.id === activeId) ?? chats[0];
  const busy = working?.chatId === chat.id;
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
  }, [chat.messages.length, working?.shown]);

  const patch = (id: number, fn: (c: Chat) => Chat) => setChats((cs) => cs.map((c) => (c.id === id ? fn(c) : c)));
  const newChat = () => {
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
  const withThinking = async <T,>(id: number, call: Promise<T>, steps: string[] = BACKEND_STEPS): Promise<T> => {
    setWorking({ chatId: id, steps, shown: 1 });
    const timer = setTimeout(() => setWorking((w) => (w?.chatId === id && w.shown < steps.length - 1 ? { ...w, shown: steps.length - 1 } : w)), 1700);
    try {
      const r = await call;
      clearTimeout(timer);
      setWorking({ chatId: id, steps, shown: steps.length });
      await sleep(600);
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

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy || awaitingApproval) return;
    const id = chat.id;
    const sessionId = chat.sessionId;
    nearBottom.current = true;
    setDraft("");
    patch(id, (c) => ({ ...c, title: c.messages.length === 0 ? text.slice(0, 40) : c.title, messages: [...c.messages, { from: "user", text }] }));
    setWorking({ chatId: id, steps: [], shown: 0 });
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
        addReply(id, await withThinking(id, arcApi.askBackend(role, clientId, sessionId, text, ipsVersion)), text);
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
          <select value={chat.id} onChange={(e) => setActiveId(Number(e.target.value))} aria-label="Chats" className="min-w-0 flex-1 truncate rounded-sm border border-hairline bg-surface-100 px-3 py-2 text-[14px] text-ink">
            {chats.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
          <button type="button" onClick={newChat} aria-label="New chat" title="New chat" className="inline-flex size-9 items-center justify-center rounded-sm border border-hairline-strong text-ink hover:bg-surface-300"><MessageSquarePlus size={16} /></button>
          <button type="button" onClick={() => removeChat(chat.id)} aria-label="Delete chat" title="Delete chat" className="inline-flex size-9 items-center justify-center rounded-sm border border-hairline text-ink-muted hover:text-negative"><Trash2 size={16} /></button>
        </div>
      )}
      <aside className={`${compact ? "hidden" : "flex"} w-full shrink-0 flex-col border-b border-hairline p-4 lg:w-80 lg:border-b-0 lg:border-r`}>
        <button type="button" onClick={newChat} className="flex w-full items-center gap-3 rounded-sm px-3 py-2.5 text-left text-[15px] hover:bg-surface-300">
          <MessageSquarePlus size={18} /> New chat
        </button>
        <p className="mt-5 px-3 text-[13px] text-ink-muted">Chats</p>
        <ul className="mt-2 flex-1 space-y-1 overflow-y-auto">
          {chats.map((c) => (
            <li key={c.id} className={`group flex items-center gap-2 rounded-sm px-3 py-2.5 ${c.id === chat.id ? "bg-surface-300" : "hover:bg-surface-300"}`}>
              <button type="button" onClick={() => setActiveId(c.id)} className="min-w-0 flex-1 truncate text-left text-[15px]">{c.title}</button>
              <button type="button" onClick={() => removeChat(c.id)} aria-label="Delete chat" title="Delete chat" className="text-ink-muted opacity-0 hover:text-negative focus:opacity-100 group-hover:opacity-100"><Trash2 size={15} /></button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-end gap-3 border-b border-hairline px-6 py-3 sm:px-10">
          <ClientSwitcher clientId={clientId} name={clientName} />
          <Link to={`/${role}/clients/${clientId}/documents`} title="Open the client's IPS" className="inline-flex items-center gap-2.5 rounded-full border border-hairline-strong bg-surface-100 px-4 py-1.5 text-[13px] text-ink hover:bg-surface-300">
            <span className={`size-2 rounded-full ${ipsVersion ? "bg-[#2e8b57]" : "bg-ink-muted"}`} />
            {ipsVersion ? `Using IPS v${ipsVersion}` : "No active IPS"}
          </Link>
        </div>
        {chat.messages.length === 0 && !busy ? (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center-safe overflow-y-auto px-8 py-10">
            <img src="/ubs-logo.png" alt="Geneva" className="ubs-logo mb-5 h-10 w-auto" />
            <h2 className="mb-8 text-center text-3xl font-light">{HEADING[role]}</h2>
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
                  {m.assetView && <AssetViewCard v={m.assetView} clientId={clientId} />}
                  {m.answer && <AnswerView a={m.answer} picked={pickedNames} onToggle={toggle} clientId={clientId} role={role} />}
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
                  </ol>
                </div>
              )}
              
            </div>
            <div className="px-10 pb-8 pt-2">
              {composer}
            </div>
          </>
        )}
      </section>
      <GenevaArticlePanel source={source} onClose={closeSource} />
    </div>
  );
}
