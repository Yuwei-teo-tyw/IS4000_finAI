import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Search, X } from "lucide-react";
import { Badge, Button, Card, Loading } from "../ui";
import { arcApi } from "../../services/arcApi";
import { useActiveClientId } from "../../layouts/navConfig";
import type { Product } from "../../types/arc";

export interface ShelfPick { id: string; name: string; assetClass: string; riskLevel?: string; score?: number }

/**
 * Modal picker over the product shelf. Stays open after adding so several products can be added.
 * Products are multi-selected with checkboxes and added together with one primary action.
 * `onAddMany` receives the whole batch in one call (use it when the caller keeps a list, so picks do not overwrite each other).
 * Without `onAddMany`, each selected product is passed to `onAdd` in turn.
 */
export function ProductShelfPicker({ open, onClose, onAdd, onAddMany, onRemove, existingIds }: {
  open: boolean; onClose: () => void; onAdd: (p: ShelfPick) => void; onAddMany?: (ps: ShelfPick[]) => void; onRemove?: (id: string) => void; existingIds: string[];
}) {
  const clientId = useActiveClientId();
  const ref = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const [products, setProducts] = useState<Product[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [cls, setCls] = useState("All");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setProducts(null); setError(null);
    arcApi.getProducts(clientId).then((p) => live && setProducts(p)).catch((e) => live && setError(e instanceof Error ? e.message : "Could not load the product shelf."));
    return () => { live = false; };
  }, [open, clientId]);

  useEffect(() => { const t = setTimeout(() => setQ(input.trim().toLowerCase()), 200); return () => clearTimeout(t); }, [input]);

  // Each time the picker opens, start with an empty selection and no stale confirmation.
  useEffect(() => { if (open) { setSelected(new Set()); setMessage(null); } }, [open]);

  // Confirmation is brief.
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(t);
  }, [message]);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab" && ref.current) {
        const f = Array.from(ref.current.querySelectorAll<HTMLElement>("button:not([disabled]),input:not([disabled]),[href],[tabindex]:not([tabindex='-1'])"));
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; prev?.focus(); };
  }, [open, onClose]);

  const classes = useMemo(() => ["All", ...Array.from(new Set((products ?? []).map((p) => p.assetClass)))], [products]);
  const rows = useMemo(() => (products ?? []).filter((p) =>
    (cls === "All" || p.assetClass === cls) &&
    (!q || [p.name, p.id, p.assetClass, ...p.tags].some((s) => s.toLowerCase().includes(q)))), [products, cls, q]);

  // Products already in the pack show ticked; unticking one removes it from the pack (onRemove).
  const inPack = (id: string) => existingIds.includes(id);
  const visibleSelectable = rows.filter((p) => !inPack(p.id));
  const visibleSelectedCount = visibleSelectable.filter((p) => selected.has(p.id)).length;
  const allVisibleSelected = visibleSelectable.length > 0 && visibleSelectedCount === visibleSelectable.length;
  const someVisibleSelected = visibleSelectedCount > 0 && !allVisibleSelected;

  // Native indeterminate state has no HTML attribute, so it is set on the element.
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someVisibleSelected;
  }, [someVisibleSelected, products, rows.length]);

  const picks: ShelfPick[] = useMemo(() => (products ?? [])
    .filter((p) => selected.has(p.id) && !inPack(p.id))
    .map((p) => ({ id: p.id, name: p.name, assetClass: p.assetClass, riskLevel: `Risk ${p.riskRating} of 5`, score: p.stars })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [products, selected, existingIds]);
  const n = picks.length;

  const toggleOne = (id: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
  };

  const toggleAllVisible = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      visibleSelectable.forEach((p) => (allVisibleSelected ? next.delete(p.id) : next.add(p.id)));
      return next;
    });
  };

  const addSelected = () => {
    if (n === 0) return;
    if (onAddMany) onAddMany(picks);
    else picks.forEach((p) => onAdd(p));
    setSelected(new Set());
    setMessage(`${n} ${n === 1 ? "product" : "products"} added to the review pack.`);
  };

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex flex-col bg-ink-900/60" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label="Add products from the shelf" tabIndex={-1} className="m-4 flex min-h-0 flex-1 flex-col bg-surface-100 outline-none sm:m-8">
        <div className="flex items-center justify-between gap-4 border-b border-hairline bg-white px-6 py-4">
          <h2 className="text-xl">Product shelf</h2>
          <Button variant="ghost" onClick={onClose}><X size={16} /> Close</Button>
        </div>
        <div className="space-y-4 border-b border-hairline bg-white px-6 py-5">
          <label className="flex items-center gap-3 border border-hairline px-4 py-2">
            <Search size={16} className="text-ink-500" aria-hidden="true" />
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Search by name, id, asset class or issuer" aria-label="Search products" className="min-w-0 flex-1 bg-transparent text-base outline-none" />
          </label>
          <div className="flex flex-wrap gap-3" role="group" aria-label="Filter by asset class">
            {classes.map((c) => (
              <button key={c} type="button" onClick={() => setCls(c)} aria-pressed={cls === c}
                className={`cursor-pointer rounded-full px-5 py-2 text-sm font-semibold ${cls === c ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>{c}</button>
            ))}
          </div>
          {products && !error && (
            <div className="flex flex-wrap items-center justify-between gap-4 border-t border-hairline pt-5">
              <label className={`flex items-center gap-3 text-base ${visibleSelectable.length === 0 ? "text-ink-500" : "cursor-pointer"}`}>
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  className="h-5 w-5 cursor-pointer accent-brand disabled:cursor-not-allowed"
                  checked={allVisibleSelected}
                  disabled={visibleSelectable.length === 0}
                  onChange={toggleAllVisible}
                />
                <span>Select all shown{visibleSelectable.length > 0 ? ` (${visibleSelectable.length})` : ""}</span>
              </label>
              <div className="flex flex-wrap items-center gap-4">
                <p role="status" aria-live="polite" className="text-sm text-ink-muted">{message ?? (n > 0 ? `${n} selected` : "")}</p>
                <Button disabled={n === 0} onClick={addSelected}>Add selected to review pack ({n})</Button>
              </div>
            </div>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          {error ? <Card className="!p-8"><h3 className="text-lg">The product shelf is unavailable</h3><p className="mt-3 text-base text-ink-700">{error}</p></Card>
            : !products ? <Loading />
            : rows.length === 0 ? <p className="py-12 text-center text-base text-ink-500">No products match your search.</p>
            : (
              <ul className="grid list-none gap-6 sm:grid-cols-2 xl:grid-cols-3">
                {rows.map((p) => {
                  const added = inPack(p.id);
                  const checked = added || selected.has(p.id);
                  return (
                    <li key={p.id}>
                      <div
                        role="checkbox"
                        aria-checked={checked}
                                                aria-label={`${p.name}${added ? " (in pack, click to remove)" : ""}`}
                        tabIndex={0}
                        onClick={(e) => {
                          // Do not hijack clicks on inner links or buttons.
                          if ((e.target as HTMLElement).closest("a,button")) return;
                          if (added) { onRemove?.(p.id); return; }
                          toggleOne(p.id, !selected.has(p.id));
                        }}
                        onKeyDown={(e) => {
                          if (e.target !== e.currentTarget) return;
                          if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (added) onRemove?.(p.id); else toggleOne(p.id, !selected.has(p.id)); }
                        }}
                        className={`outline outline-1 focus-visible:outline-2 focus-visible:outline-brand cursor-pointer ${selected.has(p.id) && !added ? "bg-surface-300/40 outline-2 outline-brand" : "outline-transparent"}`}
                      >
                      <Card className="!p-6">
                        <div className="flex items-start justify-between gap-3">
                          <h3 className="min-w-0 text-lg">
                            <span className={`flex items-start gap-3 `}>
                              <input
                                type="checkbox"
                                tabIndex={-1}
                                aria-hidden="true"
                                className="pointer-events-none mt-1.5 h-5 w-5 shrink-0 accent-brand"
                                checked={checked}
                                readOnly
                              />
                              <span className="min-w-0">{p.name}</span>
                            </span>
                          </h3>
                          <div className="flex shrink-0 flex-col items-end gap-2">
                            <Badge tone="grey">Risk {p.riskRating} of 5</Badge>
                            {added && <Badge tone="amber">In pack</Badge>}
                          </div>
                        </div>
                        <p className="mt-1 pl-8 text-xs text-ink-500">{p.id} · {p.assetClass}</p>
                        <p className="mt-3 pl-8 text-sm leading-relaxed text-ink-700">{p.whyBuy}</p>
                        <p className="mt-2 pl-8 text-sm text-ink-500">{p.feePct === null ? "Fee not available" : `Fee ${p.feePct.toFixed(2)}%`}{p.stars ? ` · ${p.stars} of 5 stars` : ""}</p>
                      </Card>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
