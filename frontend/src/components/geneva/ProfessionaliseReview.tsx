import { useState } from "react";
import type { Role } from "../../types/arc";
import { arcApi } from "../../services/arcApi";
import { getChatContext, useChatContext } from "../../services/chatContextStore";
import { BulletList, Button } from "../ui";
import { ProfessionaliseButton } from "./ProfessionaliseButton";

type Item = { id: string; label: string; text: string };
const label = "text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted";

/**
 * Review what the user typed, let Geneva rewrite it professionally using the research chat as context,
 * then show before/after per item. Nothing is applied until the human accepts (onApply).
 */
export function ProfessionaliseReview({ clientId, role, context, items, onApply }: {
  clientId: string; role: Role; context: "ips" | "pack" | "products"; items: Item[];
  onApply: (items: { id: string; text: string }[]) => void;
}) {
  const notes = useChatContext(clientId, role).length;
  const [phase, setPhase] = useState<"review" | "thinking" | "preview" | "done">("review");
  const [result, setResult] = useState<Record<string, string>>({});
  const [original, setOriginal] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState<string | null>(null);

  const run = async () => {
    setPhase("thinking");
    const out = await arcApi.professionalise({ clientId, role, context, items, chat: getChatContext(clientId, role) });
    setResult(Object.fromEntries(out.map((o) => [o.id, o.text])));
    setOriginal({}); setEditing(null);
    setPhase("preview");
  };
  const accept = () => {
    onApply(items.map((it) => ({ id: it.id, text: original[it.id] ? it.text : result[it.id] ?? it.text })));
    setPhase("done");
  };

  if (phase === "thinking") {
    return (
      <section className="geneva-light animate-geneva-in min-h-[240px] rounded-sm border border-hairline bg-surface-100 px-10 py-9">
        <p className="flex items-center gap-2 text-[13px] font-medium"><img src="/ubs-logo.png" alt="" className="ubs-logo h-4 w-auto" /><span className="animate-geneva-flow">Geneva</span></p>
        <p className="mt-6 text-[26px] font-light tracking-tight"><span className="animate-geneva-flow">Professionalising your wording</span></p>
        <div className="mt-6 h-px bg-hairline-strong" />
        <p className="mt-6 text-[16px] font-light"><span className="animate-geneva-flow">Reading your notes and {notes} research note{notes === 1 ? "" : "s"}…</span></p>
        <div className="mt-8"><ProfessionaliseButton loading label="Professionalise with Geneva" /></div>
      </section>
    );
  }

  if (phase === "preview" || phase === "done") {
    return (
      <section className="geneva-light space-y-8 font-light">
        <div>
          <p className={label}>Geneva draft</p>
          <h3 className="mt-2 text-[26px] font-light tracking-tight">Compare before and after</h3>
        </div>
        <ul className="space-y-6">
          {items.map((it) => (
            <li key={it.id} className="rounded-sm border border-hairline bg-surface-100 p-6">
              <p className={label}>{it.label}</p>
              <div className="mt-4 grid gap-6 md:grid-cols-2">
                <div className="min-w-0">
                  <p className="text-[13px] text-ink-muted">Your wording</p>
                  <p className="mt-2 whitespace-pre-line text-[16px] leading-7 text-ink-700">{it.text}</p>
                </div>
                <div className="min-w-0">
                  <p className="text-[13px] text-ink-muted">{original[it.id] ? "Using your wording" : "Professional"}</p>
                  {editing === it.id ? (
                    <textarea value={result[it.id] ?? ""} onChange={(e) => setResult((r) => ({ ...r, [it.id]: e.target.value }))} rows={7} aria-label={`Edit ${it.label}`}
                      className="mt-2 w-full rounded-sm border border-hairline-strong bg-surface-100 p-3 text-[15px] leading-6 text-ink outline-none" />
                  ) : original[it.id] ? (
                    <p className="mt-2 whitespace-pre-line text-[16px] leading-7 text-ink-700">{it.text}</p>
                  ) : (
                    <BulletList text={result[it.id] ?? ""} className="mt-2 !space-y-2 !text-[16px] !leading-7 text-ink-700" />
                  )}
                </div>
              </div>
              {phase === "preview" && (
                <div className="mt-5 flex flex-wrap gap-3">
                  {editing === it.id
                    ? <Button size="sm" variant="secondary" onClick={() => setEditing(null)}>Done editing</Button>
                    : <Button size="sm" variant="secondary" onClick={() => { setOriginal((o) => ({ ...o, [it.id]: false })); setEditing(it.id); }}>Edit</Button>}
                  <Button size="sm" variant="secondary" onClick={() => { setOriginal((o) => ({ ...o, [it.id]: true })); setEditing(null); }}>Back to my wording</Button>
                </div>
              )}
            </li>
          ))}
        </ul>
        {phase === "preview"
          ? <Button variant="primary" onClick={accept}>Accept all</Button>
          : <p className="text-[15px] text-ink-muted">Applied.</p>}
      </section>
    );
  }

  return (
    <section className="geneva-light space-y-8 font-light">
      <div>
        <h3 className="text-[26px] font-light tracking-tight">Review what you entered</h3>
        <p className="mt-2 text-[15px] text-ink-muted">Geneva will use your research chat ({notes} note{notes === 1 ? "" : "s"}) as context</p>
      </div>
      <ul className="rounded-sm border border-hairline bg-surface-100">
        {items.map((it) => (
          <li key={it.id} className="border-t border-hairline px-6 py-5 first:border-t-0">
            <p className={label}>{it.label}</p>
            <p className="mt-2 whitespace-pre-line text-[16px] leading-7 text-ink-700">{it.text || "Nothing entered yet"}</p>
          </li>
        ))}
      </ul>
      <ProfessionaliseButton onClick={run} disabled={items.every((i) => !i.text.trim())} label="Professionalise with Geneva" />
    </section>
  );
}
export default ProfessionaliseReview;
