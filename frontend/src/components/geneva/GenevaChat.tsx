import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ArrowUp, MessageSquarePlus, Search, Trash2 } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { Client } from "../../types/arc";
import { pathForClient, setActiveClientId } from "../../layouts/navConfig";
import { arcApi } from "../../services/arcApi";
import { toggleSelection, useActiveIps, useSelection, loadSelection, saveSelection } from "../../services/workflowStore";
import type { MacroView, MarketAnswer, MarketRow, Role } from "../../types/arc";
import { Badge, BulletList, Button, CitationTag, DirectionArrow, Table } from "../ui";
import { loadSystemPrompt } from "../settings/SettingsDialog";
import { savePackDraft } from "../../services/packDraftStore";
import { appendChatContext } from "../../services/chatContextStore";

/** Plain-text digest of an answer (no markup) for the research context store. */
function answerPlainText(a: MarketAnswer): string {
  const parts = [a.summary];
  if (a.market) parts.push(`Economic cycle ${a.market.phase}. ${a.market.views.map((v) => `${v.assetClass} ${v.view}`).join(", ")}.`);
  if (a.rows.length) parts.push(`Products considered: ${a.rows.map((r) => `${r.product} (${r.confidencePct}%)`).join(", ")}.`);
  if (a.draft) parts.push(a.draft.text);
  return parts.join(" ").replace(/<[^>]*>/g, "").replace(/\[[^\]]*\]/g, "").replace(/[*_`#]+/g, "").replace(/\s+/g, " ").trim();
}

const MATCH_PROMPT = "Read client IPS, and research market, match products most suited to client via risk appetite and preferences and current market condition";
const SEEDED: Record<Role, string[]> = {
  ps: [
    MATCH_PROMPT,
    "Tell me if PIMCO Balanced Income & Growth Fund suits the client's profile, explain why, and whether it fits the current macroeconomic status",
    "For fixed income, I want PIMCO Balanced Income & Growth, BlackRock iShares, and an equity-linked note on DBS",
    "What is the CIO House View?",
    "What is the current economic cycle and the CIO view per asset class?",
    "What is the top 5 ranking for equities and why?",
  ],
  rm: ["Summarise the client's IPS", "What are the client's goals?", "Review the IPS", "Summarise the meeting notes", "What did the client say in the last meeting?", "Write the latest client profile + goals section formally in bullet points", "Why is portfolio health flagged?", "Explain the old vs new TAA"],
  ic: ["Analyse this client's portfolio strengths and weaknesses", "Which holdings move together?", "Compare the old and new TAA", "Propose a TAA", "Summarise the client's IPS", "How are the markets today, and what is the regime, according to the CIO House View and the web?", "Edit the client's individual holdings"],
};
const HEADING: Record<Role, string> = { ps: "What would you like to research?", rm: "How can I help with this client?", ic: "How can I help with this portfolio?" };
const PLACEHOLDER: Record<Role, string> = { ps: "Ask about markets or products", rm: "Ask about the IPS, goals or meetings", ic: "Ask about the portfolio or TAA" };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const viewTone = { Buy: "green", Hold: "amber", Sell: "red" } as const;
const label = "text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted";

interface Recommend {
  name: string; riskCap: number; riskCategory: string; profile: string[]; market: string[]; tags: string[];
  shortlist: { row: MarketRow; riskRating: number; reason: string; tags: string[] }[]; excluded: string[];
}
interface Msg { from: "user" | "agent"; text: string; answer?: MarketAnswer; finalise?: string[]; recommend?: Recommend }

const MATCH_INTENT = /read client ips.*(research market|match products)/i;
const pause = (min: number, max: number) => sleep(min + Math.random() * (max - min));
/** Synthetic three-agent run (profiling, market research, recommender), built only from arcApi data for the active client. Replace with a LangGraph run. */
async function buildRecommendation(clientId: string, ipsVersion: number | null): Promise<{ steps: string[]; rec: Recommend }> {
  const [client, ips, products, views, cycle] = await Promise.all([arcApi.getClient(clientId), arcApi.getIps(clientId), arcApi.getProducts(clientId), arcApi.getMarketViews(clientId), arcApi.getMarketCycle()]);
  const name = client?.name ?? "the client", cap = client?.riskCap ?? 3, cat = client?.riskCategory ?? "Balanced";
  const part = (n: number) => ips.find((x) => x.part === n)?.body?.trim() ?? "";
  const goals = part(1) || `Goals not yet written in the IPS. Working assumption for a ${cat.toLowerCase()} profile: grow wealth steadily within a risk limit of ${cap} of 5.`;
  const risk = part(3);
  const dd = /(\d+)%\s*drawdown/i.exec(risk)?.[1] ?? String(Math.max(4, cap * 6 - 6));
  const liq = /liquidity[^.]*\./i.exec(risk)?.[0]?.trim() ?? (cap <= 3 ? "Needs ready access to cash for near-term spending." : "Can hold longer-dated, less liquid assets.");
  const wantsIncome = /income|retire/i.test(goals), wantsLegacy = /legacy|children|estate/i.test(goals);
  const pref = wantsIncome ? "income and capital stability" : wantsLegacy ? "long-term growth and legacy" : cap >= 4 ? "growth with diversification" : "capital preservation with steady income";
  const view = (cls: string) => views.find((v) => v.assetClass === cls);
  const viewOf = (cls: string) => view(cls)?.view ?? "Hold";
  const tagOf = (cls: string) => view(cls)?.tags.find((t) => t.startsWith("CIO-")) ?? "CIO-2026Q4-03";
  const within = products.filter((p) => p.riskRating <= cap), above = products.filter((p) => p.riskRating > cap);
  const score = (p: typeof products[number]) => p.stars * 10 + ({ Buy: 8, Hold: 3, Sell: -6 }[viewOf(p.assetClass)] ?? 0) + (p.riskRating / cap) * (cap >= 4 ? 8 : 3) - p.feePct * 3 + (wantsIncome && /income|dividend|yield|bond/i.test(p.name + p.whyBuy) ? 5 : 0);
  const top = [...within].sort((a, b) => score(b) - score(a)).slice(0, 5);
  const shortlist = top.map((p) => ({
    row: { assetClass: p.assetClass, product: p.name, industryFocus: p.tags[0] ?? "", top5: [], confidencePct: Math.round(p.stars * 20), ranking: [] } as MarketRow,
    riskRating: p.riskRating,
    reason: `Risk ${p.riskRating} of 5 is within ${name}'s limit of ${cap} (${cat.toLowerCase()}), suits a preference for ${pref}, and the CIO is ${viewOf(p.assetClass)} on ${p.assetClass.toLowerCase()}. ${p.suitability}.`,
    tags: [tagOf(p.assetClass), ...p.tags.filter((t) => !t.startsWith("CIO-")).slice(0, 1)],
  }));
  const profile = [
    `${name}, ${cat}, risk limit ${cap} of 5${ipsVersion ? `, IPS v${ipsVersion}` : ", no active IPS yet"}`,
    `Loss tolerance: about ${dd}% drawdown`,
    `Liquidity: ${liq.replace(/\.$/, "")}`,
    `Goals and preferences: ${goals.replace(/\.$/, "")}. Preference leans to ${pref}`,
  ];
  const market = [
    `${cycle.phase} as of ${cycle.asOf}. Rates are expected to ease as growth slows [${cycle.tag}]`,
    `Equities ${viewOf("Equities")}, fixed income ${viewOf("Fixed income")} [${tagOf("Fixed income")}]`,
    `Credit: high-grade preferred, high yield only at a modest weight [CIO-2026Q4-03]`,
    `FX: SGD firm, unhedged foreign bonds carry currency risk [MKT-0142]`,
    `Cash ${viewOf("Cash")}, gold ${viewOf("Gold")} [${tagOf("Cash")}] [${tagOf("Gold")}]`,
  ];
  const excluded = above.map((p) => `${p.name} (risk ${p.riskRating})`);
  const steps = [
    "Client profiling agent fired",
    `Reading ${name}'s active IPS${ipsVersion ? ` v${ipsVersion}` : ""}: risk limit, loss tolerance, liquidity, goals…`,
    `Profile summary ready: ${cat}, limit ${cap} of 5, ${dd}% drawdown`,
    "Market research agent fired",
    "Reading the CIO House View on rates, equities, credit and FX…",
    `Market summary ready: ${cycle.phase.toLowerCase()}, fixed income ${viewOf("Fixed income")}`,
    "Product recommender agent fired",
    `Screening ${products.length} products against ${name}'s risk limit of ${cap}${excluded.length ? `, excluding ${excluded.length} above it` : ""}…`,
    `Ranking ${within.length} eligible products by risk appetite, preference and market view…`,
    "Consolidating…",
  ];
  return { steps, rec: { name, riskCap: cap, riskCategory: cat, profile, market, tags: [cycle.tag, "CIO-2026Q4-03", ...(ipsVersion ? [`IPS-v${ipsVersion}`] : [])], shortlist, excluded } };
}

/** Render "[TAG]" markers in plain strings as citation tags. */
function Tagged({ text }: { text: string }) {
  return <>{text.split(/(\[[A-Za-z0-9-]+\])/).map((p, i) => /^\[[A-Za-z0-9-]+\]$/.test(p) ? <CitationTag key={i} tag={p.slice(1, -1)} /> : <span key={i}>{p}</span>)}</>;
}

function RecommendView({ r, picked, onToggle, clientId }: { r: Recommend; picked: string[]; onToggle: (m: MarketRow) => void; clientId: string }) {
  const h = "text-[26px] font-light tracking-tight";
  const ul = "mt-3 list-disc space-y-2 pl-5 text-[17px] leading-7 text-ink-700";
  return (
    <div className="min-w-0 space-y-10 font-light">
      <p className="text-[22px] leading-9 tracking-tight text-ink">{`For ${r.name} (${r.riskCategory}, risk limit ${r.riskCap} of 5), I matched ${r.shortlist.length} products to the IPS and today's market view. Tick the ones you want, or tell me which you are happy with.`}</p>
      <section><h4 className={h}>Client profile</h4><ul className={ul}>{r.profile.map((x) => <li key={x}>{x}</li>)}</ul></section>
      <section><h4 className={h}>Current market conditions</h4><ul className={ul}>{r.market.map((x) => <li key={x}><Tagged text={x} /></li>)}</ul></section>
      <section>
        <h4 className={h}>Ranked shortlist</h4>
        <div className="mt-3">
          <Table
            head={["Select", "Rank", "Product", "Risk", "Why it suits this client"]}
            rows={r.shortlist.map((s, i) => [
              <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={picked.includes(s.row.product)} onChange={() => onToggle(s.row)} aria-label={`Select ${s.row.product}`} />,
              String(i + 1),
              <span className="block max-w-56 font-semibold">{s.row.product}</span>,
              `${s.riskRating} of ${r.riskCap}`,
              <span className="block max-w-80 text-ink-700">{s.reason} {s.tags.map((t) => <CitationTag key={t} tag={t} />)}</span>,
            ])}
          />
        </div>
        {r.excluded.length > 0 && <p className="mt-4 text-[15px] text-ink-muted">{`Excluded as above ${r.name}'s risk limit of ${r.riskCap}: ${r.excluded.join(", ")}.`}</p>}
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
const STOP = new Set(["the", "and", "fund", "funds", "etf", "etfs", "of", "a", "an", "for", "fixed", "income", "plc", "ltd", "inc", "note", "class"]);
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
const stem = (w: string) => w.replace(/s$/, "");
/** Product matches when its full name appears, or most of its distinctive words do (at least two, or its only one). */
function matchesProduct(text: string, name: string): boolean {
  const t = norm(text), n = norm(name);
  if (t.includes(n)) return true;
  const words = new Set(t.split(" ").map(stem));
  const sig = n.split(" ").filter((w) => !STOP.has(w));
  if (sig.length === 0) return false;
  const hit = sig.filter((w) => words.has(stem(w))).length;
  return sig.length === 1 ? hit === 1 : hit >= 2 && hit / sig.length >= 0.6;
}
interface Chat { id: number; title: string; messages: Msg[] }

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
                head={["Select", "Product", "Industry focus", "Confidence", "Why ranked and justification"]}
                rows={a.rows.filter((r) => r.assetClass === cls).map((r, idx) => [
                  <input type="checkbox" className="h-5 w-5 cursor-pointer" checked={picked.includes(r.product)} onChange={() => onToggle(r)} aria-label={`Select ${r.product}`} />,
                  <span className="block max-w-56 font-semibold">{r.product}</span>,
                  <span className="block max-w-48">{r.industryFocus}</span>,
                  `${r.confidencePct}%`,
                  <span className="block max-w-72 text-ink-700">
                    {`Ranked ${idx + 1} in ${cls.toLowerCase()} at ${r.confidencePct}% confidence for its focus on ${r.industryFocus.toLowerCase()}. Top pick inside: ${(r.ranking[0] ?? "").replace(/^\d+\.\s*/, "")} `}
                    {a.tags.slice(0, 2).map((t) => <CitationTag key={t} tag={t} />)}
                  </span>,
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
  const [chats, setChats] = useState<Chat[]>([{ id: 1, title: "New chat", messages: [] }]);
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
    setChats([{ id: 1, title: "New chat", messages: [] }]); setActiveId(1); setWorking(null); setDraft("");
  }
  const ipsVersion = activeIps ?? clientIps ?? null;
  const nextId = useRef(2);
  const chat = chats.find((c) => c.id === activeId) ?? chats[0];
  const busy = working?.chatId === chat.id;

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
    setChats((cs) => [...cs, { id, title: "New chat", messages: [] }]);
    setActiveId(id);
  };
  const removeChat = (id: number) => {
    const left = chats.filter((c) => c.id !== id);
    if (left.length === 0) { const nid = nextId.current++; setChats([{ id: nid, title: "New chat", messages: [] }]); setActiveId(nid); return; }
    setChats(left);
    if (activeId === id) setActiveId(left[0].id);
  };

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    const id = chat.id;
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
        appendChatContext(clientId, role, { q: text, a: `Shortlist for ${rec.name} (limit ${rec.riskCap}): ${rec.shortlist.map((x) => x.row.product).join(", ")}.` });
      } finally {
        setWorking((w) => (w?.chatId === id ? null : w));
      }
      return;
    }
    if (role === "ps" && FINALISE_INTENT.test(text)) {
      const [products] = await Promise.all([arcApi.getProducts(clientId), sleep(500)]);
      const lastRows = [...chat.messages].reverse().find((m) => m.answer?.rows.length)?.answer?.rows ?? [];
      const cand: MarketRow[] = [
        ...products.map((p): MarketRow => ({ assetClass: p.assetClass, product: p.name, industryFocus: p.tags[0] ?? "", top5: [], confidencePct: Math.round(p.stars * 20), ranking: [] })),
        ...lastRows.filter((r) => !products.some((p) => p.name === r.product)),
      ];
      const found = cand.filter((r) => matchesProduct(text, r.product));
      let reply: string; let names: string[] | undefined;
      if (found.length === 0) reply = "I could not tell which products you mean. Please name the products you are happy with, for example \"finalise Global Equity ETF and the green bond fund\".";
      else {
        saveSelection(clientId, found);
        names = found.map((r) => r.product);
        reply = `Noted. I have put ${names.length} product${names.length === 1 ? "" : "s"} on your finalise list. Review them and add your reasons on the next page. Nothing is approved until you confirm.`;
      }
      patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: reply, finalise: names ?? [] }] }));
      setWorking(null);
      return;
    }
    try {
      const a = role === "ps"
        ? await arcApi.askMarketResearch(clientId, text, loadSystemPrompt(role), ipsVersion)
        : await arcApi.askAgent(role, clientId, text, ipsVersion).then((r): MarketAnswer => ({
            summary: r.reply, draft: r.draft, market: null, rows: [], autoTick: false, tags: r.tags,
            steps: ["Intent parser is reading your request…", `${r.agent} fired`, ...r.steps, "Consolidating…"],
          }));
      setWorking({ chatId: id, steps: a.steps, shown: 0 });
      for (let i = 1; i <= a.steps.length; i++) { setWorking({ chatId: id, steps: a.steps, shown: i }); await sleep(i === 2 ? 1200 : 900); }
      await sleep(400);
      if (a.autoTick) {
        const cur = loadSelection(clientId);
        saveSelection(clientId, [...cur, ...a.rows.filter((r) => !cur.some((x) => x.product === r.product))]);
      }
      patch(id, (c) => ({ ...c, messages: [...c.messages, { from: "agent", text: a.summary, answer: a }] }));
      appendChatContext(clientId, role, { q: text, a: answerPlainText(a) });
    } finally {
      setWorking((w) => (w?.chatId === id ? null : w));
    }
  };

  const composer = (
    <form className="mx-auto flex w-full max-w-4xl items-center gap-3 rounded-full border border-hairline-strong bg-surface-100 py-2 pl-6 pr-2" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
      <input value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Message Geneva" placeholder={PLACEHOLDER[role]}
        className="min-h-10 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-muted" />
      <button type="submit" disabled={busy || !draft.trim()} aria-label="Send" title="Send"
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

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-end gap-3 border-b border-hairline px-6 py-3 sm:px-10">
          <ClientSwitcher clientId={clientId} name={clientName} />
          <Link to={`/${role}/clients/${clientId}/documents`} title="Open the client's IPS" className="inline-flex items-center gap-2.5 rounded-full border border-hairline-strong bg-surface-100 px-4 py-1.5 text-[13px] text-ink hover:bg-surface-300">
            <span className={`size-2 rounded-full ${ipsVersion ? "bg-[#2e8b57]" : "bg-ink-muted"}`} />
            {ipsVersion ? `Using IPS v${ipsVersion}` : "No active IPS"}
          </Link>
        </div>
        {chat.messages.length === 0 && !busy ? (
          <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-8 py-10">
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
            <div ref={scrollRef} onScroll={onScroll} role="log" aria-live="polite" className="flex flex-1 flex-col gap-8 overflow-y-auto [&>*]:shrink-0 overflow-x-hidden px-6 py-8 text-[15px] leading-6 sm:px-10 sm:py-10">
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
                  {m.answer && <AnswerView a={m.answer} picked={pickedNames} onToggle={toggle} clientId={clientId} role={role} />}
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
    </div>
  );
}
