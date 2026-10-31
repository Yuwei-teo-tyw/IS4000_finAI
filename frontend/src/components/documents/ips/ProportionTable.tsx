import { useEffect, useRef } from "react";
import { NumberInput } from "../../../components/ui/NumberInput";
import type { Bucket3L, ThreeLBucketKey, ThreeLProportion } from "../../../types/arc";
import { sgd } from "../../ui";
import { BUCKET_BG } from "./charts";
import { EDIT_BOX, LABEL, SMALL } from "./parts";

const clampPct = (raw: string) => Math.min(100, Math.max(0, Number.isFinite(Number(raw)) ? Math.round(Number(raw)) : 0));

/**
 * Section 5 in one block: stacked bar, then one row per bucket (colour key, horizon, amount, editable %), each with its AI-written reason in an editable box.
 * Editing a % rescales the bar and the amounts. Read-only when `onBuckets` is absent.
 */
export function BucketAllocation({ buckets, onBuckets, proportion, message, missing, onPct, onReason }: {
  buckets?: Bucket3L[]; onBuckets?: (b: Bucket3L[]) => void;
  proportion?: ThreeLProportion | null; message?: string; missing?: string[];
  onPct?: (k: ThreeLBucketKey, pct: number) => void; onReason?: (k: ThreeLBucketKey, text: string) => void;
}) {
  const list = buckets ?? [];
  const total = list.reduce((s, b) => s + b.pct, 0);
  const amount = list.reduce((s, b) => s + b.amountSgd, 0);
  const portfolio = useRef(amount);
  useEffect(() => { if (total > 0 && amount > 0) portfolio.current = (amount * 100) / total; }, [amount, total]);
  if (!buckets) return <p className="text-ink-muted">Loading…</p>;

  const editing = !!onBuckets;
  const setPct = (id: Bucket3L["id"], raw: string) => {
    const pct = clampPct(raw);
    onBuckets?.(list.map((b) => (b.id === id ? { ...b, pct, amountSgd: Math.round((portfolio.current * pct) / 100) } : b)));
    onPct?.(id, pct);
  };
  const ok = Math.abs(total - 100) < 0.005;
  const head = `py-2 pr-2 font-light ${LABEL}`;

  return (
    <div className="min-w-0" data-testid="proportion-table">
      <div className="flex h-6 w-full overflow-hidden border border-hairline" role="img" aria-label="3L bucket allocation">
        {list.map((b) => <div key={b.id} className={BUCKET_BG[b.id]} style={{ width: `${Math.min(100, b.pct)}%` }} />)}
      </div>
      <table className="mt-4 w-full table-fixed border-collapse text-left text-[15px]">
        <thead>
          <tr className="border-b border-hairline">
            <th className={`w-[14%] ${head}`}>Bucket</th><th className={`w-[14%] ${head}`}>Horizon</th>
            <th className={`w-[16%] ${head} text-right`}>Amount (SGD)</th><th className={`w-24 py-2 pr-4 text-right font-light ${LABEL}`}>%</th>
            <th className={`${head} pl-2`}>Reason</th>
          </tr>
        </thead>
        <tbody>
          {list.map((b) => {
            const reason = proportion?.[b.id]?.reason ?? "";
            return (
              <tr key={b.id} className="avoid-break border-b border-hairline align-top">
                <td className="break-words py-3 pr-2"><i className={`mr-2 inline-block h-3 w-3 ${BUCKET_BG[b.id]}`} />{b.name}</td>
                <td className="break-words py-3 pr-2">{b.horizon}</td>
                <td className="py-3 pr-2 text-right">{sgd(b.amountSgd)}</td>
                <td className="py-2 pr-4 text-right">
                  {editing
                    ? <NumberInput min={0} max={100} step={1} value={b.pct} aria-label={`${b.name} percentage`} onChange={(e) => setPct(b.id, e.target.value)}
                        className={`w-20 px-2 py-1 text-right text-[15px] text-ink ${EDIT_BOX}`} />
                    : <span className="inline-block py-1">{b.pct}%</span>}
                </td>
                <td className="py-2 pl-2">
                  {!proportion ? <span className="text-ink-muted">-</span>
                    : editing && onReason
                      ? <textarea value={reason} rows={3} aria-label={`Reason for ${b.name} proportion`} onChange={(e) => onReason(b.id, e.target.value)}
                          className={`block w-full px-2 py-2 text-[15px] leading-6 ${EDIT_BOX}`} />
                      : <p className="whitespace-pre-wrap leading-6 text-ink-muted">{reason || "No reason recorded."}</p>}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3} className={`py-2 pr-2 text-right ${LABEL}`}>Total</td>
            <td className={`py-2 pr-4 text-right ${ok ? "text-ink" : "text-negative"}`} data-testid="proportion-total">{total}%</td><td />
          </tr>
        </tfoot>
      </table>
      {!ok && <p role="alert" className={`mt-1 text-right text-negative ${SMALL}`} data-testid="proportion-warning">Total is {total}%, not 100%.</p>}
      {!proportion && (message || !!missing?.length) && (
        <div role="note" className={`mt-4 border-l-2 border-hairline-strong pl-3 ${SMALL} text-ink-muted`} data-testid="proportion-missing">
          <p>{message || "The 3L reasons were not generated. This information is missing:"}</p>
          {!!missing?.length && <ul className="mt-1 list-disc pl-5">{missing.map((x) => <li key={x}>{x}</li>)}</ul>}
        </div>
      )}
    </div>
  );
}
