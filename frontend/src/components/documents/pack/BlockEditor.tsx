import { useRef, useState } from "react";
import { BulletTextarea, Button } from "../../ui";
import { newBlockId } from "../../../services/packBlocksStore";
import type { PackBlock } from "../../../types/arc";
import { BlockItem } from "./BlockView";
import { fileToDataUrl, imageFromClipboard } from "./imageUtil";
import { CHART_LABEL, liveSlices, TABLE_LABEL, useBlockData, type ChartBlock } from "./useBlockData";

export interface BlockEditorProps {
  clientId: string; section: number; blocks: PackBlock[]; onChange: (blocks: PackBlock[]) => void; readOnly?: boolean;
}

const link = "text-[13px] text-ink underline-offset-4 hover:underline disabled:text-ink-muted disabled:no-underline";
const field = "block w-full rounded-sm border border-hairline-strong bg-surface-100 px-3 py-2 text-sm font-light text-ink";

function ChartControls({ block, clientId, set }: { block: ChartBlock; clientId: string; set: (b: PackBlock) => void }) {
  const d = useBlockData(block.clientId ?? clientId);
  const frozen = !!block.snapshot;
  return (
    <span className="flex gap-4">
      <span className="text-[13px] text-ink-muted">{CHART_LABEL[block.chart]} · {frozen ? "frozen values" : "live data"}</span>
      <button type="button" className={link} disabled={!d.ready}
        onClick={() => set({ ...block, snapshot: frozen ? undefined : liveSlices(block.chart, d) })}>{frozen ? "Use live data" : "Freeze values"}</button>
    </span>
  );
}

/** Editable block list for a pack section: text (bullets), image, chart, table. Insert / reorder / remove / captions. */
export function BlockEditor({ clientId, section, blocks, onChange, readOnly }: BlockEditorProps) {
  const [menu, setMenu] = useState(false);
  const [pick, setPick] = useState<"chart" | "table" | null>(null);
  const [err, setErr] = useState("");
  const file = useRef<HTMLInputElement>(null);

  const update = (id: string, next: PackBlock) => onChange(blocks.map((b) => (b.id === id ? next : b)));
  const remove = (id: string) => onChange(blocks.filter((b) => b.id !== id));
  const move = (i: number, d: -1 | 1) => { const a = [...blocks]; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; onChange(a); };
  const add = (b: PackBlock, after?: number) => { const a = [...blocks]; a.splice(after === undefined ? a.length : after + 1, 0, b); onChange(a); setMenu(false); setPick(null); };

  const addImage = async (f: Blob, after?: number) => {
    setErr("");
    try { add({ id: newBlockId(), type: "image", src: await fileToDataUrl(f), alt: "" }, after); }
    catch { setErr("That image could not be read."); }
  };

  if (readOnly) return <div className="space-y-8">{blocks.map((b) => <BlockItem key={b.id} block={b} clientId={clientId} />)}</div>;

  return (
    <div className="space-y-6" data-section={section}>
      {blocks.map((b, i) => (
        <div key={b.id} className="space-y-3 border border-hairline p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">{b.type === "text" ? "Text" : b.type === "image" ? "Image" : b.type === "chart" ? "Chart" : "Table"}</span>
            <span className="flex gap-4">
              <button type="button" className={link} disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">Up</button>
              <button type="button" className={link} disabled={i === blocks.length - 1} onClick={() => move(i, 1)} aria-label="Move down">Down</button>
              <button type="button" className={link} onClick={() => remove(b.id)} aria-label="Remove block">Remove</button>
            </span>
          </div>
          {b.type === "text" && (
            <div onPaste={(e) => { const f = imageFromClipboard(e); if (f) { e.preventDefault(); void addImage(f, i); } }}>
              <BulletTextarea value={b.text} rows={6} aria-label="Section text" onChange={(text) => update(b.id, { ...b, text })} />
              <p className="mt-2 text-[12px] text-ink-muted">Paste an image here to add it below this text.</p>
            </div>
          )}
          {b.type === "image" && (
            <div className="space-y-3">
              <BlockItem block={{ ...b, caption: undefined }} clientId={clientId} />
              <input className={field} placeholder="Alt text (describe the image)" aria-label="Alt text" value={b.alt} onChange={(e) => update(b.id, { ...b, alt: e.target.value })} />
            </div>
          )}
          {b.type === "chart" && (<><BlockItem block={{ ...b, caption: undefined }} clientId={clientId} /><ChartControls block={b} clientId={clientId} set={(n) => update(b.id, n)} /></>)}
          {b.type === "table" && (<><BlockItem block={{ ...b, caption: undefined }} clientId={clientId} /><span className="text-[13px] text-ink-muted">{TABLE_LABEL[b.table]} · live data</span></>)}
          {b.type !== "text" && (
            <input className={field} placeholder="Caption (optional)" aria-label="Caption" value={b.caption ?? ""} onChange={(e) => update(b.id, { ...b, caption: e.target.value || undefined })} />
          )}
        </div>
      ))}

      <div className="relative inline-block">
        <Button variant="secondary" size="sm" onClick={() => { setMenu((m) => !m); setPick(null); }}>+ Insert</Button>
        {menu && (
          <div className="absolute left-0 z-20 mt-2 w-64 border border-hairline-strong bg-surface-100 p-2 text-sm" role="menu">
            {!pick && (<>
              <button type="button" role="menuitem" className="block w-full px-3 py-2 text-left hover:bg-surface-300" onClick={() => file.current?.click()}>Image (upload)</button>
              <button type="button" role="menuitem" className="block w-full px-3 py-2 text-left hover:bg-surface-300" onClick={() => setPick("chart")}>Chart</button>
              <button type="button" role="menuitem" className="block w-full px-3 py-2 text-left hover:bg-surface-300" onClick={() => setPick("table")}>Table</button>
              <p className="px-3 pb-1 pt-2 text-[12px] text-ink-muted">Or paste an image into a text block.</p>
            </>)}
            {pick === "chart" && (Object.keys(CHART_LABEL) as ChartBlock["chart"][]).map((c) => (
              <button key={c} type="button" role="menuitem" className="block w-full px-3 py-2 text-left hover:bg-surface-300" onClick={() => add({ id: newBlockId(), type: "chart", chart: c })}>{CHART_LABEL[c]}</button>
            ))}
            {pick === "table" && (Object.keys(TABLE_LABEL) as (keyof typeof TABLE_LABEL)[]).map((t) => (
              <button key={t} type="button" role="menuitem" className="block w-full px-3 py-2 text-left hover:bg-surface-300" onClick={() => add({ id: newBlockId(), type: "table", table: t })}>{TABLE_LABEL[t]}</button>
            ))}
            {pick && <button type="button" className="block w-full px-3 py-2 text-left text-ink-muted hover:bg-surface-300" onClick={() => setPick(null)}>Back</button>}
          </div>
        )}
        <input ref={file} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void addImage(f); }} />
      </div>
      {err && <p className="text-[13px] text-ink-muted" role="status">{err}</p>}
    </div>
  );
}
