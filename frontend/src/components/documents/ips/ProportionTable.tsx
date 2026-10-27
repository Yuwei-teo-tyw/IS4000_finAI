import type { ThreeLBucketKey, ThreeLProportion } from "../../../types/arc";
import { EDIT_BOX, IPS_FRAME, LABEL, SMALL, SubHead } from "./parts";

const ROWS: { id: ThreeLBucketKey; label: string }[] = [
  { id: "liquidity", label: "Liquidity" }, { id: "longevity", label: "Longevity" }, { id: "legacy", label: "Legacy" },
];

const proportionTotal = (p: ThreeLProportion) => ROWS.reduce((n, r) => n + (Number.isFinite(p[r.id].pct) ? p[r.id].pct : 0), 0);
const proportionWarning = (p?: ThreeLProportion | null) => {
  if (!p) return "";
  const t = proportionTotal(p);
  return t === 100 ? "" : `Total is ${t}%, not 100%.`;
};

/** IS-75: the base 3L proportion produced during AI generation, as Bucket | % | Reason with a total row. Percentages are editable whole numbers in edit mode. */
export function ProportionTable({ proportion, message, missing, editing, onChange }: {
  proportion?: ThreeLProportion | null; message?: string; missing?: string[]; editing?: boolean; onChange?: (k: ThreeLBucketKey, pct: number) => void;
}) {
  if (!proportion) {
    if (!message && !missing?.length) return null;
    return (
      <div role="note" className={`border-l-2 border-hairline-strong pl-3 ${SMALL} text-ink-muted`} data-testid="proportion-missing">
        <p>{message || "The base 3L proportion was not generated. This information is missing:"}</p>
        {!!missing?.length && <ul className="mt-1 list-disc pl-5">{missing.map((x) => <li key={x}>{x}</li>)}</ul>}
      </div>
    );
  }
  const total = proportionTotal(proportion);
  const warn = proportionWarning(proportion);
  return (
    <div className="avoid-break min-w-0" data-testid="proportion-table">
      <SubHead>Base 3L proportion</SubHead>
      <div className={`mt-2 overflow-x-auto ${IPS_FRAME}`}>
      <table className="w-full border-collapse text-left text-[15px] font-light text-ink">
        <thead>
          <tr className={LABEL}>
            <th className="px-5 py-4 font-normal">Bucket</th><th className="w-28 border-l border-hairline px-5 py-4 font-normal">%</th><th className="border-l border-hairline px-5 py-4 font-normal">Reason</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(({ id, label }) => (
            <tr key={id} className="border-t border-hairline align-top">
              <td className="px-5 py-4">{label}</td>
              <td className="border-l border-hairline px-5 py-4">
                {editing && onChange
                  ? <input type="number" min={0} max={100} step={1} inputMode="numeric" aria-label={`${label} percentage`} value={Number.isFinite(proportion[id].pct) ? proportion[id].pct : ""}
                      onChange={(e) => onChange(id, e.target.value === "" ? 0 : Math.round(Number(e.target.value)))} className={`w-20 px-2 py-1 text-[15px] ${EDIT_BOX}`} />
                  : `${proportion[id].pct}%`}
              </td>
              <td className="border-l border-hairline px-5 py-4 leading-6 text-ink-muted">{proportion[id].reason}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-hairline">
            <td className="px-5 py-4">Total</td>
            <td className="border-l border-hairline px-5 py-4" data-testid="proportion-total">{total}%</td>
            <td className="border-l border-hairline px-5 py-4 text-ink-muted">{warn ? <span role="alert" className="text-negative" data-testid="proportion-warning">{warn}</span> : "Total is 100%."}</td>
          </tr>
        </tfoot>
      </table>
      </div>
    </div>
  );
}
