import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Bullets, Cell, IpsGrid, LABEL, SubHead, WRAP } from "./parts";
import { GOAL_SECTIONS, parseGoals, serializeGoals, type GoalGroup, type GoalKey } from "./goals";
import { type IpsTarget } from "./ipsTypes";
import { TargetsBlock } from "./TargetsBlock";

const EMPTY = "Not yet completed";

/** One editable bullet: renders exactly like a view-mode `li`; contentEditable in place. */
function EditableLi({ value, onText, onEnter, onBackspaceEmpty, onPasteLines, id }: {
  value: string; onText: (v: string) => void; onEnter: () => void; onBackspaceEmpty: () => void; onPasteLines: (lines: string[]) => void; id: string;
}) {
  const ref = useRef<HTMLLIElement>(null);
  useLayoutEffect(() => { const el = ref.current; if (el && el.textContent !== value) el.textContent = value; }, [value]);
  return (
    <li ref={ref} data-goal-li={id} contentEditable suppressContentEditableWarning role="textbox" aria-label="Goal bullet" data-placeholder="Not yet completed" data-empty={value.trim() === "" ? "true" : "false"}
      className={`${WRAP} cursor-text rounded-sm outline-none data-[empty=true]:before:text-ink-muted data-[empty=true]:before:content-[attr(data-placeholder)] focus:ring-1 focus:ring-ink/20 print:ring-0`}
      onInput={(e) => { e.currentTarget.dataset.empty = (e.currentTarget.textContent ?? "").trim() === "" ? "true" : "false"; onText((e.currentTarget.textContent ?? "").replace(/\s*\n\s*/g, " ")); }}
      onKeyDown={(e) => {
        if (e.key === "Enter") { e.preventDefault(); onEnter(); }
        else if (e.key === "Backspace" && !(e.currentTarget.textContent ?? "")) { e.preventDefault(); onBackspaceEmpty(); }
      }}
      onPaste={(e) => {
        e.preventDefault();
        const lines = e.clipboardData.getData("text/plain").split(/\r?\n/).map((l) => l.replace(/^\s*(?:[-*\u2022]\s+)?/, "").trim()).filter(Boolean);
        if (lines.length > 1) onPasteLines(lines);
        else if (lines.length === 1) document.execCommand("insertText", false, lines[0]);
      }}
    />
  );
}

interface Props {
  /** Part 1 body ("Heading: bullet" lines) or already-structured groups. */
  body?: string; groups?: GoalGroup[];
  editing?: boolean; onBody?: (v: string) => void;
  clientId?: string; targets?: IpsTarget[]; onTargets?: (t: IpsTarget[]) => void;
  /** Sentences Geneva could not safely turn into third person: a review list for the RM (editor only, never printed). */
  notIncluded?: string[]; onNotIncluded?: (n: string[]) => void;
}

/** IPS section 3: the 7 fixed subheadings, each with bullets beneath ("Not yet completed" when empty). Same markup in preview and editor. */
export function GoalsSection({ body = "", groups, editing = false, onBody, clientId, targets = [], onTargets, notIncluded = [], onNotIncluded }: Props) {
  const [local, setLocal] = useState<GoalGroup[]>(() => groups ?? parseGoals(body));
  const emitted = useRef(serializeGoals(local));
  const focusNext = useRef<string | null>(null);

  // External replacement (Geneva edit, regeneration): re-parse only when the body differs from what we last emitted.
  useEffect(() => {
    if (groups) { setLocal(groups); return; }
    if (body !== emitted.current) { const g = parseGoals(body); emitted.current = serializeGoals(g); setLocal(g); }
  }, [body, groups]);
  useEffect(() => {
    if (!focusNext.current) return;
    document.querySelector<HTMLElement>(`[data-goal-li="${focusNext.current}"]`)?.focus();
    focusNext.current = null;
  });

  const view = editing ? local : groups ?? parseGoals(body);
  const update = (next: GoalGroup[]) => { setLocal(next); const s = serializeGoals(next); emitted.current = s; onBody?.(s); };
  const patch = (k: GoalKey, fn: (b: string[]) => string[]) => update(local.map((g) => (g.key === k ? { ...g, bullets: fn(g.bullets) } : g)));
  const caret = (el: Element | null) => { if (!el) return; const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); const s = window.getSelection(); s?.removeAllRanges(); s?.addRange(r); };

  return (
    <div data-ips-part={editing ? 1 : undefined} className="space-y-6">
      <TargetsBlock clientId={clientId} targets={targets} editing={editing} onChange={onTargets} />
      <IpsGrid data-testid="ips-goals-table">
        {GOAL_SECTIONS.map((s, idx) => {
          const g = view.find((x) => x.key === s.key)!;
          const filled = g.bullets.length > 0;
          const wide = s.key === "unique" || (idx === GOAL_SECTIONS.length - 1 && GOAL_SECTIONS.length % 2 === 1);
          return (
            <Cell key={s.key} as="section" wide={wide} aria-label={s.title} data-testid={`goal-${s.key}`}>
              <SubHead>{s.title}</SubHead>
              <div className="mt-1 min-w-0">
                {editing ? (
                  <ul className="list-disc space-y-1 pl-5">
                    {(filled ? g.bullets : [""]).map((b, i) => (
                      <EditableLi key={`${s.key}-${i}`} id={`${s.key}-${i}`} value={b}
                        onText={(v) => patch(s.key, (bs) => (bs.length ? bs : [""]).map((x, j) => (j === i ? v : x)))}
                        onEnter={() => { focusNext.current = `${s.key}-${i + 1}`; patch(s.key, (bs) => { const base = bs.length ? bs : [""]; return [...base.slice(0, i + 1), "", ...base.slice(i + 1)]; }); }}
                        onPasteLines={(lines) => { focusNext.current = `${s.key}-${i + lines.length - 1}`; patch(s.key, (bs) => { const base = bs.length ? bs : [""]; return [...base.slice(0, i), ...(base[i] ? [base[i]] : []), ...lines, ...base.slice(i + 1)]; }); }}
                        onBackspaceEmpty={() => {
                          if (!filled || g.bullets.length === 1) { patch(s.key, () => []); return; }
                          focusNext.current = i > 0 ? `${s.key}-${i - 1}` : `${s.key}-0`;
                          patch(s.key, (bs) => bs.filter((_, j) => j !== i));
                          setTimeout(() => caret(document.querySelector(`[data-goal-li="${s.key}-${Math.max(i - 1, 0)}"]`)), 0);
                        }} />
                    ))}
                  </ul>
                ) : filled
                  ? <Bullets items={g.bullets} />
                  : <p className="text-ink-muted">{EMPTY}</p>}
              </div>
            </Cell>
          );
        })}
      </IpsGrid>
      {editing && notIncluded.length > 0 && (
        <div className="min-w-0 border-t border-hairline pt-4 print:hidden" data-testid="ips-not-included">
          <p className={LABEL}>Not included</p>
          <p className="mt-1 text-[13px] leading-5 text-ink-muted">Lines from the meeting notes that could not be safely written in the third person. Review each one, add it to a goal above if it belongs, then dismiss it.</p>
          <ul className="mt-2 space-y-2">
            {notIncluded.map((n, i) => (
              <li key={`${i}-${n}`} className={`flex items-start gap-3 ${WRAP}`}>
                <span className="min-w-0 flex-1 text-ink-muted">{n}</span>
                <button type="button" className="shrink-0 text-[13px] text-ink underline" onClick={() => onNotIncluded?.(notIncluded.filter((_, j) => j !== i))}>Dismiss</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
