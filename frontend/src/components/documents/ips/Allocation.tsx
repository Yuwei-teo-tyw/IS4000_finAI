import { useState } from "react";
import { arcApi } from "../../../services/arcApi";
import { Badge, useAsync } from "../../ui";
import type { Strategy } from "../../../types/arc";
import { CELL, EDIT_BOX, IPS_FRAME, LABEL, SMALL, SubHead, WRAP } from "./parts";
import { StrategyDonut } from "./charts";

export type AllocBucketId = "liquidity" | "longevity" | "legacy";
/** Tolerant shape of backend threeL[] items: {portfolio,strategy,reason,source,default,conflict}. */
export interface ThreeLMeta {
  strategy?: string; reason?: string;
  source?: string | { date?: string; title?: string; id?: string };
  default?: boolean;
  conflict?: string | { dates?: string[]; note?: string } | boolean;
  eligible?: string[]; boundary?: string;
  /** Backend sentence: expected portfolio rate of return for this strategy. */
  rateOfReturn?: string;
}
const BUCKETS: { id: AllocBucketId; label: string }[] = [
  { id: "liquidity", label: "Liquidity" }, { id: "longevity", label: "Longevity" }, { id: "legacy", label: "Legacy" },
];
const FALLBACK: Strategy[] = [
  ["A", "Fixed Income"], ["B", "Income"], ["C", "Yield"], ["D", "Balanced"], ["E", "Growth"], ["F", "Equities"],
].map(([code, name]) => ({ code, name, allocation: {} }));
export type AllocWeights = Partial<Record<"longevity" | "legacy", { strategy: string; weights: Record<string, number> }>>;
/** Max deviation (percentage points) from the chosen strategy's model weight, per asset class. */
export const SAA_TOL = 10;
export const sumW = (w: Record<string, number>) => Math.round(Object.values(w).reduce((s, v) => s + (Number(v) || 0), 0) * 100) / 100;
/** True when the edited weights are inside the tolerance of the model and add to 100. */
export const weightsOk = (w: Record<string, number>, model: Record<string, number>) =>
  sumW(w) === 100 && Object.keys({ ...model, ...w }).every((k) => Math.abs((w[k] ?? 0) - (model[k] ?? 0)) <= SAA_TOL + 1e-9);
const edited = (w: Record<string, number>, model: Record<string, number>) => Object.keys({ ...model, ...w }).some((k) => Math.abs((w[k] ?? 0) - (model[k] ?? 0)) > 1e-9);

/** Editable (PM) or read-only percent fields per asset class for one bucket, clamped to +/-10pp of the model on blur. */
function WeightFields({ code, model, value, onChange }: { code: string; model: Record<string, number>; value: Record<string, number>; onChange?: (w: Record<string, number>) => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const keys = Object.keys(model);
  const total = sumW(value), isEdited = edited(value, model);
  const commit = (k: string, raw: string) => {
    const n = Number(raw), lo = Math.max(0, (model[k] ?? 0) - SAA_TOL), hi = (model[k] ?? 0) + SAA_TOL;
    const v = Number.isFinite(n) && raw.trim() !== "" ? Math.round(Math.min(hi, Math.max(lo, n)) * 100) / 100 : model[k] ?? 0;
    setDraft((d) => { const { [k]: _x, ...r } = d; return r; });
    onChange?.({ ...value, [k]: v });
  };
  return (
    <div className="mt-6 min-w-0" data-testid="saa-weights">
      <div className="flex flex-wrap items-center gap-2">
        <p className={LABEL}>SAA weights (%)</p>
        <Badge tone="grey">{isEdited ? "Edited vs model" : "Model weights"}</Badge>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-3 @xl:grid-cols-3">
        {keys.map((k) => (
          <label key={k} className={`block ${SMALL}`}>
            <span className="text-ink-muted">{k}{onChange ? ` (model ${model[k]})` : ""}</span>
            {onChange
              ? <input type="number" step="0.1" value={draft[k] ?? String(value[k] ?? 0)} aria-label={`${k} percent`}
                  onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))} onBlur={(e) => commit(k, e.target.value)}
                  className={`mt-1 block w-full px-2 py-1 text-[15px] ${EDIT_BOX}`} />
              : <span className="mt-1 block text-[15px]">{value[k] ?? 0}%{isEdited && value[k] !== model[k] ? <span className="text-ink-muted"> (model {model[k]}%)</span> : null}</span>}
          </label>
        ))}
      </div>
      <p className={`mt-2 ${SMALL} ${total === 100 ? "text-ink-muted" : "text-negative"}`} role={total === 100 ? undefined : "alert"}>
        Total {total}%{total === 100 ? "" : ". Weights must add to 100%."}{onChange ? ` Each class stays within +/-${SAA_TOL}pp of Strategy ${code}.` : ""}
      </p>
    </div>
  );
}

/** Liquidity has no SAA: the backend returns strategy "NA" / "No SAA". */
export const NA_STRATEGY = "NA";

const sourceText = (s: ThreeLMeta["source"]) =>
  !s ? "" : typeof s === "string" ? s : [s.title ?? s.id, s.date].filter(Boolean).join(", ");
const conflictText = (c: ThreeLMeta["conflict"]) =>
  !c ? "" : typeof c === "string" ? c
    : c === true ? "Meeting notes disagree on this strategy."
      : c.note ?? (c.dates?.length ? `Meeting notes of ${c.dates.join(" and ")} give different strategies.` : "Meeting notes disagree on this strategy.");

/** Strategy boxes A-F. Disabled boxes are inert for click AND keyboard. Read-only mode renders the same boxes without interaction. */
export function StrategyBoxes({ bucket, label, strategies, value, editing, onPick }: {
  bucket: AllocBucketId; label: string; strategies: Strategy[]; value?: string; editing: boolean; onPick?: (code: string) => void;
}) {
  if (bucket === "liquidity") {
    return (
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={`${label} strategy`}>
        <div role="radio" aria-checked="true" aria-disabled="true" data-strategy="NA" className="flex size-[84px] flex-col items-center justify-center border-2 border-ink bg-surface-100 px-1 text-center text-ink">
          <span className="text-[15px] leading-5">NA</span><span className="mt-0.5 text-[12px] leading-4 text-ink-muted">No SAA</span>
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={`${label} strategy`}>
        {strategies.map((st) => {
          const c = st.code;
          const disabled = false;
          const on = value === c;
          const cls = `flex size-[84px] flex-col items-center justify-center border px-1 text-center ${on ? "border-2 border-ink bg-surface-100 text-ink" : "border-hairline-strong text-ink"} ${disabled ? "cursor-not-allowed bg-surface-200 text-ink-muted opacity-50" : editing ? "bg-surface-100 hover:border-ink" : "bg-surface-100"}`;
          const inner = (<><span className="text-[15px] leading-5">{c}</span><span className="mt-0.5 text-[12px] leading-4 text-ink-muted">{st.name}</span></>);
          if (!editing) return <div key={c} role="radio" aria-checked={on} aria-disabled="true" data-strategy={c} className={cls}>{inner}</div>;
          return (
            <button key={c} type="button" role="radio" aria-checked={on} data-strategy={c}
              aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : undefined}
              onKeyDown={disabled ? (e) => { if (e.key === "Enter" || e.key === " ") e.preventDefault(); } : undefined}
              onClick={() => { if (!disabled) onPick?.(c); }}
              className={cls}>{inner}</button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Three 3L portfolios. Per portfolio: row 1 = strategy boxes + donut of the selected strategy, row 2 = reason box.
 * Same layout in preview (read-only) and editor. `proposed` is Geneva's strategy; a different pick requires a reason, which is logged.
 */
export function AllocationBuckets({ allocation, notes, editing, blank, onPick, onNote, proposed, meta, outOfDate, weights, onWeights }: {
  weights?: AllocWeights; onWeights?: (bucket: AllocBucketId, w: Record<string, number> | undefined) => void;
  allocation: Partial<Record<AllocBucketId, string>>; notes?: Record<string, string>;
  editing: boolean; blank: boolean; onPick?: (bucket: AllocBucketId, code: string) => void;
  onNote?: (bucket: AllocBucketId, v: string) => void;
  proposed?: Partial<Record<AllocBucketId, string>>; meta?: Partial<Record<AllocBucketId, ThreeLMeta>>; clientId?: string;
  /** Message when the stored recommendation is out of date (profile or notes changed since it was generated). */
  outOfDate?: string;
}) {
  const table = useAsync(() => arcApi.getStrategies().then((r) => r.strategies).catch(() => [] as Strategy[]), []);
  const strategies = table && table.length ? table : FALLBACK;
  const [local, setLocal] = useState<Record<string, string>>({});
  if (!editing && !blank && !Object.values(allocation).some(Boolean) && !Object.values(meta ?? {}).some((m) => m?.strategy))
    return <p className="text-ink-muted">3L's Strategic Asset Allocations not yet completed.</p>;

  return (
    <div className="space-y-6">
      <SubHead>3L's Strategic Asset Allocations</SubHead>
      {outOfDate && (
        <p role="alert" className={`flex flex-wrap items-center gap-2 border-l-2 border-hairline-strong pl-3 ${SMALL} text-ink-muted`} data-testid="out-of-date">
          <Badge tone="grey">Out of date</Badge>{outOfDate.replace(/^Out of date:\s*/, "")}
        </p>
      )}
      {BUCKETS.map(({ id, label }) => {
        if (id === "liquidity") return <p key={id} data-bucket={id} className="text-sm italic text-brand">Liquidity Portfolio has no SAA, due to immediate funding requirements for the client.</p>;
        const m = meta?.[id];
        const code = blank && !editing ? undefined : allocation[id] ?? m?.strategy;
        const s = strategies.find((x) => x.code === code);
        const rorText = (m?.rateOfReturn && code === m.strategy ? m.rateOfReturn : s?.rateOfReturnText)?.trim();
        const wEntry = weights?.[id];
        const model = s?.allocation ?? {};
        const hasModel = Object.keys(model).length > 0;
        const w = wEntry && wEntry.strategy === code ? wEntry.weights : undefined;
        const showW = hasModel && (!!onWeights || (!!w && edited(w, model)));
        const reason = local[id] ?? notes?.[id] ?? m?.reason ?? "";
        const prop = proposed?.[id] ?? m?.strategy;
        const differs = editing && !!code && !!prop && code !== prop;
        const needReason = differs && (!reason.trim() || reason.trim() === (m?.reason ?? "").trim());  // Geneva's own reason does not explain a different pick; the override is logged on save
        const src = sourceText(m?.source);
        const conflict = conflictText(m?.conflict);
        return (
          <section key={id} data-bucket={id} className={`@container ${CELL} ${IPS_FRAME}`}>
            <div className="flex flex-wrap items-center gap-2">
              <SubHead>{label} portfolio{code ? <span className="font-light"> · {code} - {s?.name ?? ""}</span> : null}</SubHead>
              {m?.default && <Badge tone="grey">Default</Badge>}
            </div>
            {m?.boundary && <p className={`mt-2 border-l-2 border-hairline-strong pl-3 ${SMALL} text-ink-muted`} data-testid="boundary-note">{m.boundary}{m.eligible && m.eligible.length > 1 ? ` Eligible: ${m.eligible.join(" or ")}.` : ""}</p>}
            {conflict && <p className={`mt-2 border-l-2 border-hairline-strong pl-3 ${SMALL} text-ink-muted`} data-testid="conflict-note">{conflict}</p>}
            <div className="mt-4 grid min-w-0 grid-cols-1 gap-6 @xl:grid-cols-2">
              <StrategyBoxes bucket={id} label={label} strategies={strategies} value={code} editing={editing} onPick={(c) => onPick?.(id, c)} />
              <StrategyDonut allocation={w ?? s?.allocation} label={`${label} strategic asset allocation${s ? `, Strategy ${s.code}` : ""}`} />
            </div>
            {showW && code && <WeightFields key={`${id}-${code}`} code={code} model={model} value={w ?? model} onChange={onWeights ? (nw) => onWeights(id, nw) : undefined} />}
            {rorText && (
              <div className="avoid-break mt-6 min-w-0" data-testid={`ror-${id}`}>
                <p className={LABEL}>Portfolio rate of return</p>
                <p className={`mt-1 ${WRAP}`}>{rorText}</p>
              </div>
            )}
            <div className="mt-6 min-w-0">
              <label htmlFor={`reason-${id}`} className={LABEL}>Reason for {label} strategy</label>
              {src && <p className={`mt-1 ${SMALL} text-ink-muted`}>Source: {src}</p>}
              {!src && m?.default && <p className={`mt-1 ${SMALL} text-ink-muted`}>Default: no meeting note states this strategy.</p>}
              {editing ? (
                <>
                  <textarea id={`reason-${id}`} value={reason} rows={3}
                    onChange={(e) => { setLocal((l) => ({ ...l, [id]: e.target.value })); onNote?.(id, e.target.value); }}
                    placeholder={differs ? `Why Strategy ${code} instead of Geneva's Strategy ${prop}` : "Why this strategy suits the client"}
                    className={`mt-1 block w-full px-2 py-2 text-[15px] leading-6 placeholder:text-ink-muted ${EDIT_BOX}`} />
                  {needReason && <p role="alert" className={`mt-1 ${SMALL} text-negative`}>A reason is required: you chose Strategy {code}, Geneva proposed Strategy {prop}. The change is logged when you save.</p>}
                </>
              ) : (
                <div id={`reason-${id}`} className={`mt-1 min-h-[72px] whitespace-pre-wrap px-2 py-2 text-[15px] leading-6 ${EDIT_BOX} ${WRAP}`}>
                  {reason || <span className="text-ink-muted">No reason recorded.</span>}
                </div>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
