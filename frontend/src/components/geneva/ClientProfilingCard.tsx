import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, FileText } from "lucide-react";
import type { Role } from "../../types/arc";
import { bothOf, clarifyOptions, routingSource } from "../../types/clientProfiling";
import type { ClientProfilingSourceChoice, ClientProfilingAnswer, ClientProfilingResult, ClientProfilingSummary, ClientProfilingSection, ClientProfilingSource } from "../../types/clientProfiling";
import { MeetingNoteModal } from "./MeetingNoteModal";

const label = "text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted";
const KINDS = ["documented", "calculated", "inferred", "missing"];
const TAG = { calculated: "calculated", inferred: "unconfirmed", missing: "to confirm" } as const;
const BUCKETS = ["liquidity", "longevity", "legacy"] as const;
const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === "object" && !Array.isArray(v); // eslint-disable-line @typescript-eslint/no-explicit-any
const fmtDate = (d?: string) => { const t = d ? new Date(d) : null; return t && !isNaN(+t) ? t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : d ?? ""; };

/** First array or object found under any of the keys, anywhere in `data` (one level deep). */
function pick(data: Record<string, any>, keys: string[]): unknown { // eslint-disable-line @typescript-eslint/no-explicit-any
  for (const k of keys) if (data[k] != null) return data[k];
  for (const v of Object.values(data)) if (isObj(v)) for (const k of keys) if (v[k] != null) return v[k];
  return undefined;
}
function threeL(data: Record<string, any>): { key: string; pct: number }[] { // eslint-disable-line @typescript-eslint/no-explicit-any
  const t = pick(data, ["three_l", "3L", "allocation_3l", "buckets", "template", "proposal", "split"]);
  if (!isObj(t)) return [];
  const src = isObj(t.buckets) ? t.buckets : isObj(t.allocation) ? t.allocation : t;
  const rows = BUCKETS.map((b) => {
    const raw = src[b] ?? src[b[0].toUpperCase() + b.slice(1)] ?? src[`${b}_pct`];
    const n = isObj(raw) ? Number(raw.pct ?? raw.percent ?? raw.percentage ?? raw.weight) : Number(raw);
    return { key: b, pct: n <= 1 && n > 0 && Object.values(src).every((x) => Number(x) <= 1) ? n * 100 : n };
  });
  return rows.every((r) => Number.isFinite(r.pct)) ? rows : [];
}
function sectionsOf(data: Record<string, any>): ClientProfilingSection[] | null { // eslint-disable-line @typescript-eslint/no-explicit-any
  const s = data.sections;
  return Array.isArray(s) ? s.filter((x): x is ClientProfilingSection => isObj(x) && typeof x.heading === "string") : null;
}
const dedupe = (l: ClientProfilingSource[] = []) => l.filter((s, i) => l.findIndex((t) => t.type === s.type && t.id === s.id) === i);
const shortLabel = (s: ClientProfilingSource) =>
  s.type === "meeting_note" ? `Meeting note${s.date ? ` · ${fmtDate(s.date)}` : s.label ? ` · ${s.label}` : ""}` : s.label && s.label.length <= 22 ? s.label : `IPS${s.version != null ? ` v${s.version}` : ""}`;

function SourceChip({ s, role, onOpenNote }: { s: ClientProfilingSource; role: Role; onOpenNote: (s: ClientProfilingSource) => void }) {
  const cls = "inline-flex items-center gap-1 rounded-sm border border-hairline-strong px-2 py-0.5 text-[12px] text-ink-700 hover:bg-surface-300 hover:border-ink cursor-pointer";
  const tip = [s.label || s.id, s.passage].filter(Boolean).join(" — ");
  const inner = <><FileText size={11} strokeWidth={1.5} />{shortLabel(s)}</>;
  return s.type === "meeting_note"
    ? <button type="button" onClick={() => onOpenNote(s)} className={cls} title={tip}>{inner}</button>
    : <Link to={`/${role}/clients/${s.client_id}/documents`} className={cls} title={tip}>{inner}</Link>;
}

export function SourceRow({ sources, role, onOpenNote }: { sources?: ClientProfilingSource[]; role: Role; onOpenNote: (s: ClientProfilingSource) => void }) {
  const l = dedupe(sources);
  return l.length ? <div className="flex flex-wrap items-center gap-1.5"><span className="text-[12px] text-ink-muted">Sources</span>{l.map((s) => <SourceChip key={`${s.type}-${s.id}`} s={s} role={role} onOpenNote={onOpenNote} />)}</div> : null;
}

/** Original meeting note in a centred modal (cited passage highlighted). */
export function NoteModal({ source, onClose }: { source: ClientProfilingSource; onClose: () => void }) {
  return <MeetingNoteModal clientId={source.client_id} noteId={source.id} passage={source.passage} fallbackLabel={source.label} fallbackDate={source.date} onClose={onClose} />;
}

function SectionBlock({ sec, role, onOpenNote }: { sec: ClientProfilingSection; role: Role; onOpenNote: (s: ClientProfilingSource) => void }) {
  const lines = sec.lines ?? [];
  return (
    <section className="space-y-1.5">
      <h3 className="text-[16px] font-semibold text-ink">{sec.heading}</h3>
      {lines.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-[15px] leading-6 text-ink marker:text-ink-muted">
          {lines.map((ln, i) => {
            const k = KINDS.includes(ln.kind) ? ln.kind : "missing";
            return (
              <li key={i}>{ln.text}{k !== "documented" && <span className="ml-2 rounded-sm bg-surface-300 px-1.5 py-px align-middle text-[11px] text-ink-muted">{TAG[k as keyof typeof TAG]}</span>}</li>
            );
          })}
        </ul>
      )}
      <SourceRow sources={sec.sources} role={role} onOpenNote={onOpenNote} />
    </section>
  );
}

function SummaryView({ sm, role, onOpenNote }: { sm: ClientProfilingSummary; role: Role; onOpenNote: (s: ClientProfilingSource) => void }) {
  const pc = sm.profile_card;
  const trunc = sm.coverage?.truncated ?? [];
  return (
    <div className="space-y-5">
      {sm.degraded && sm.notice && <p className="rounded-sm bg-surface-300 px-3 py-2 text-[14px] leading-6 text-ink-muted">{sm.notice}</p>}
      {pc && pc.items?.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-[16px] font-semibold text-ink">{pc.title}</h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px]">
            {pc.items.map((it, i) => <div key={i} className="min-w-0"><dt className="text-ink-muted">{it.label}</dt><dd className="text-ink">{it.value}</dd></div>)}
          </dl>
        </section>
      )}
      {(sm.sections ?? []).filter((sec) => (sec.bullets ?? []).length > 0).map((sec, si) => {
        const seen = new Set<string>();
        const srcs = sec.bullets.flatMap((b) => b.sources ?? []).filter((s) => { const k = `${s.type}:${s.id}`; if (seen.has(k)) return false; seen.add(k); return true; });
        return (
          <section key={`${sec.heading}-${si}`} className="space-y-1.5">
            <h3 className="text-[16px] font-normal text-ink">{sec.heading}</h3>
            <ul className="list-disc space-y-0.5 pl-5 text-[15px] leading-6 text-ink marker:text-ink-muted">{sec.bullets.map((t, i) => <li key={i}>{t.text}</li>)}</ul>
            <SourceRow sources={srcs} role={role} onOpenNote={onOpenNote} />
          </section>
        );
      })}
      {trunc.map((t) => <p key={t.note_id} className="text-[13px] text-ink-muted">Part of this note was not covered: {t.not_covered}</p>)}
    </div>
  );
}

function AnswerText({ text, sources, role, onOpenNote }: { text: string; sources?: ClientProfilingSource[]; role: Role; onOpenNote: (s: ClientProfilingSource) => void }) {
  return (
    <div className="space-y-2.5">
      {text.split(/\n\s*\n/).filter(Boolean).map((p, i) => <p key={i} className="text-[16px] leading-7 text-ink">{p}</p>)}
      <SourceRow sources={sources} role={role} onOpenNote={onOpenNote} />
    </div>
  );
}

export function ClientProfilingCard({ r, role, onAsk, onSource }: { r: ClientProfilingResult; role: Role; onAsk: (clientId: string) => void; onSource?: (source: ClientProfilingSourceChoice) => void }) {
  const [note, setNote] = useState<ClientProfilingSource | null>(null);
  const d = r.data ?? {};
  const sm = isObj(d.summary) ? (d.summary as ClientProfilingSummary) : null;
  const secs = sectionsOf(d);
  const bars = threeL(d);
  const [open, setOpen] = useState(false);
  const a = isObj(d.answer) && typeof d.answer.text === "string" ? (d.answer as ClientProfilingAnswer) : null;
  const sectionEls = secs?.map((sec, i) => <SectionBlock key={`${sec.heading}-${i}`} sec={sec} role={role} onOpenNote={setNote} />);
  const both = r.tool === "compare_sources" ? bothOf(d) : null;
  const src = routingSource(d);
  if (r.tool === "clarify_source") {
    const opts = clarifyOptions(d);
    return (
      <div className="min-w-0 space-y-4 font-light">
        <p className="text-[17px] leading-7 text-ink">{r.message}</p>
        <div className="flex flex-wrap gap-3">
          {opts.map((o) => <button key={o.source} type="button" disabled={!onSource} onClick={() => onSource?.(o.source)} className="rounded-sm border border-ink px-4 py-2 text-[15px] text-ink hover:bg-surface-300 disabled:opacity-50">{o.label}</button>)}
        </div>
      </div>
    );
  }
  if (r.tool === "source_unavailable") return <p className="min-w-0 text-[16px] leading-7 text-ink">{(typeof d.message === "string" && d.message) || r.message}</p>;
  if (both) {
    return (
      <div className="min-w-0 space-y-6 font-light">
        {([both.notes, both.ips] as const).map((b, i) => {
          const txt = b.answer?.text?.trim();
          return (
            <section key={i} className="space-y-2 border-t border-hairline pt-4 first:border-t-0 first:pt-0">
              <p className={label}>{b.label}</p>
              {txt ? <AnswerText text={txt} sources={b.answer?.sources} role={role} onOpenNote={setNote} />
                : <p className="text-[15px] leading-6 text-ink-muted">{b.message || "No answer is available from this source."}</p>}
            </section>
          );
        })}
        {note && <NoteModal source={note} onClose={() => setNote(null)} />}
      </div>
    );
  }
  if (r.tool === "get_ips" && !(a && a.text.trim())) return <p className="min-w-0 text-[16px] leading-7 text-ink">{r.message}</p>;
  if (r.tool === "invalid_question" || r.tool === "access_denied" || (sm && sm.status === "no_notes" && !(sm.covered_meetings ?? []).length)) {
    return <p className="min-w-0 text-[17px] font-semibold leading-7 text-ink">{(sm && sm.message) || r.message}</p>;
  }

  return (
    <div className="min-w-0 space-y-5 font-light">
      {!a && !sm && <p className="text-[17px] leading-7 text-ink">{r.message}</p>}
      {!sm && typeof d.summary_error === "string" && !(a && a.text.trim()) && (
        <p className="rounded-sm bg-surface-300 px-3 py-2 text-[14px] leading-6 text-ink-muted">{r.message || "The summary could not be generated. Please try again."}</p>
      )}

      {a && a.text.trim() && (
        <div className="space-y-2.5">
          {a.text.split(/\n\s*\n/).filter(Boolean).map((p, i) => <p key={i} className="text-[16px] leading-7 text-ink">{p}</p>)}
          {a.inference?.text && <p className="text-[15px] italic leading-6 text-ink-muted"><span className="font-semibold not-italic">{a.inference.label}: </span>{a.inference.text}</p>}
          {isObj(a.explanation) && typeof a.explanation.text === "string" && (
            <section className="space-y-1.5">
              <h3 className="text-[16px] font-semibold text-ink">Client overview</h3>
              {a.explanation.risk_category && <p className="text-[13px] text-ink-muted">Risk category: {a.explanation.risk_category}</p>}
              <p className="text-[16px] leading-7 text-ink">{a.explanation.text}</p>
              {(a.explanation.recommended_asset_classes ?? []).length > 0 && (
                <div className="space-y-1">
                  <p className="text-[14px] font-semibold text-ink">Suggested asset classes</p>
                  <div className="flex flex-wrap gap-1.5">{a.explanation.recommended_asset_classes.map((c) => <span key={c} className="rounded-sm bg-surface-300 px-2 py-0.5 text-[12px] text-ink-700">{c}</span>)}</div>
                </div>
              )}
              <span className="inline-block rounded-sm bg-surface-300 px-1.5 py-px text-[11px] text-ink-muted">agent suggestion · not confirmed with the client</span>
              <SourceRow sources={a.explanation.sources} role={role} onOpenNote={setNote} />
            </section>
          )}
          {(a.sections ?? []).map((sec, i) => <SectionBlock key={`a-${sec.heading}-${i}`} sec={sec} role={role} onOpenNote={setNote} />)}
          {!(a.sections ?? []).length && <SourceRow sources={a.sources} role={role} onOpenNote={setNote} />}
        </div>
      )}

      {src && (a || sm) && <p className="text-[12px] text-ink-muted">Source: {src === "ips" ? "IPS" : "Meeting notes"}</p>}
      {sm && <SummaryView sm={sm} role={role} onOpenNote={setNote} />}

      {r.status === "needs_clarification" && (
        <div className="space-y-4 rounded-sm border border-hairline-strong px-5 py-4">
          <p className={label}>Which client do you mean?</p>
          <div className="flex flex-wrap gap-3">
            {r.candidates.map((c) => (
              <button key={c.id} type="button" onClick={() => onAsk(c.id)} className="rounded-sm border border-ink px-4 py-2 text-[15px] text-ink hover:bg-surface-300">{c.name}</button>
            ))}
            {r.candidates.length === 0 && <span className="text-[15px] text-ink-muted">Please name the client.</span>}
          </div>
        </div>
      )}
      {r.status === "insufficient_information" && (
        <p className="rounded-sm border border-hairline-strong px-5 py-4 text-[15px] leading-6 text-ink-700">There is not enough information in the meeting notes to answer this. Nothing has been assumed.</p>
      )}
      {r.status === "not_found" && <p className="rounded-sm border border-hairline-strong px-5 py-4 text-[15px] leading-6 text-ink-700">No matching client, IPS version or meeting note was found.</p>}

      {a ? (
        secs && secs.length > 0 && (
          <div className="space-y-5">
            <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1 text-[13px] font-semibold text-ink-muted hover:text-ink">
              <ChevronRight size={14} strokeWidth={1.5} className={open ? "rotate-90" : ""} />Retrieved facts
            </button>
            {open && sectionEls}
          </div>
        )
      ) : sectionEls}

      {bars.length > 0 && (
        <div className="space-y-3">
          <p className={label}>Proposed 3L allocation</p>
          <div className="flex h-3 w-full overflow-hidden rounded-sm bg-scale-track" role="img" aria-label={bars.map((b) => `${b.key} ${b.pct}%`).join(", ")}>
            {bars.map((b, i) => <span key={b.key} style={{ width: `${Math.max(0, b.pct)}%` }} className={i === 0 ? "bg-chart-liquidity" : i === 1 ? "bg-chart-bonds" : "bg-chart-alternatives"} />)}
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-1 text-[15px] text-ink-700">{bars.map((b) => <span key={b.key} className="capitalize">{b.key} {Math.round(b.pct * 10) / 10}%</span>)}</div>
        </div>
      )}

      {!secs && <SourceRow sources={r.sources} role={role} onOpenNote={setNote} />}

      {note && <NoteModal source={note} onClose={() => setNote(null)} />}
    </div>
  );
}
