import { Fragment, useState } from "react";
import { Check, ChevronDown, ChevronRight } from "lucide-react";
import { BulletList, Card } from "../ui";
import { useFinalised } from "../../services/workflowStore";

interface Props {
  clientId: string;
  /** Enables the checkbox column. Product names currently ticked. */
  selected?: string[];
  onToggle?: (product: string) => void;
  /** Rows expand on click to show the PS reason and industry focus detail. */
  expandable?: boolean;
}

/** View of the list the Product Specialist sent to the IC (G3). Read-only unless selected/expandable are passed. */
export function FinalisedTable({ clientId, selected, onToggle, expandable = false }: Props) {
  const list = useFinalised(clientId);
  const [open, setOpen] = useState<string | null>(null);
  if (!list || list.items.length === 0) {
    return <Card className="!p-8"><p className="text-base text-ink-muted">No finalised list yet.</p></Card>;
  }
  const pick = selected !== undefined && !!onToggle;
  const head = [...(pick ? ["Include"] : []), ...(expandable ? [""] : []), "Product", "Asset class", "Industry focus", "Confidence", ...(expandable ? [] : ["PS reason"])];
  const span = head.length;
  return (
    <div>
      <p className="mb-5 text-sm text-ink-muted">Sent {new Date(list.sentAt).toLocaleString()}</p>
      <div className="overflow-x-auto rounded-lg border border-hairline bg-surface-100">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface-200 text-ink-muted">
            <tr>{head.map((h, i) => <th key={i} className="px-6 py-4 text-xs font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {list.items.map((p) => {
              const isOpen = expandable && open === p.product;
              const on = pick && selected!.includes(p.product);
              return (
                <Fragment key={p.product}>
                  <tr className={`border-t border-hairline ${expandable ? "cursor-pointer hover:bg-surface-200" : ""}`} onClick={expandable ? () => setOpen(isOpen ? null : p.product) : undefined}>
                    {pick && (
                      <td className="px-6 py-5 align-top" onClick={(e) => e.stopPropagation()}>
                        <button type="button" role="checkbox" aria-checked={on} aria-label={`Include ${p.product}`} onClick={() => onToggle!(p.product)}
                          className={`flex h-5 w-5 items-center justify-center rounded-sm border ${on ? "border-ink bg-ink text-surface-100" : "border-ink-200 bg-surface-100"}`}>
                          {on && <Check size={14} />}
                        </button>
                      </td>
                    )}
                    {expandable && <td className="px-6 py-5 align-top text-ink-muted">{isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</td>}
                    <td className="px-6 py-5 align-top"><span className="font-semibold">{p.product}</span></td>
                    <td className="px-6 py-5 align-top">{p.assetClass}</td>
                    <td className="px-6 py-5 align-top">{p.industryFocus}</td>
                    <td className="px-6 py-5 align-top">{p.confidencePct}%</td>
                    {!expandable && <td className="px-6 py-5 align-top"><BulletList text={p.reason} empty="" /></td>}
                  </tr>
                  {isOpen && (
                    <tr className="bg-surface-200">
                      <td colSpan={span} className="px-6 py-6">
                        <p className="mb-2 text-xs font-semibold text-ink-muted">PS reason</p>
                        <div className="mb-5"><BulletList text={p.reason} /></div>
                        <p className="mb-2 text-xs font-semibold text-ink-muted">Industry focus</p>
                        <p className="text-sm leading-relaxed">{p.industryFocus}{p.top5?.length ? ` · Top holdings: ${p.top5.join(", ")}` : ""}</p>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
