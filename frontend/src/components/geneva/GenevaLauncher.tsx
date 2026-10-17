import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Maximize2, Minimize2, X } from "lucide-react";
import type { Role } from "../../types/arc";
import { useAsync } from "../ui";
import { arcApi } from "../../services/arcApi";
import { GenevaChat } from "./GenevaChat";

const MIN_W = 420;
const DEFAULT_W = 560;
const WIDE_W = 960;
const maxW = () => Math.max(MIN_W, Math.round(window.innerWidth * 0.9));
const clampW = (w: number) => Math.max(MIN_W, Math.min(maxW(), w));
function loadWidth(): number {
  try { const v = Number(localStorage.getItem("arc.assistantWidth")); return v ? clampW(v) : DEFAULT_W; } catch { return DEFAULT_W; }
}
function loadOpen(): boolean {
  try { return localStorage.getItem("arc.assistantOpen") === "true"; } catch { return false; }
}

/** Geneva launcher, bottom right. Opens the same chat as the AI Assistant page in a resizable side panel. */
export default function GenevaLauncher({ role, clientId }: { role: Role; clientId: string }) {
  const [open, setOpen] = useState(loadOpen);
  const [width, setWidth] = useState(loadWidth);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; w: number } | null>(null);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const expanded = width >= WIDE_W - 40;
  const fullPage = role === "rm" || role === "ps" ? `/${role}/assistant` : null;

  const set = (o: boolean) => { setOpen(o); try { localStorage.setItem("arc.assistantOpen", String(o)); } catch { /* ignore */ } };
  const save = (w: number) => { try { localStorage.setItem("arc.assistantWidth", String(w)); } catch { /* ignore */ } };
  const apply = (w: number) => { const c = clampW(w); setWidth(c); save(c); };

  useEffect(() => {
    const onResize = () => setWidth((w) => clampW(w));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") set(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const down = (e: React.PointerEvent<HTMLDivElement>) => { e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, w: width }; setDragging(true); };
  const move = (e: React.PointerEvent<HTMLDivElement>) => { if (drag.current) setWidth(clampW(drag.current.w + (drag.current.x - e.clientX))); };
  const up = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    drag.current = null; setDragging(false);
    setWidth((w) => { save(w); return w; });
  };

  return (
    <div className="print:hidden">
      {!open && (
        <button type="button" onClick={() => set(true)} aria-label="Open Geneva assistant" title="Open Geneva assistant"
          className="fixed bottom-6 right-6 z-40 flex items-center gap-3 rounded-full border border-hairline-strong bg-surface-100 py-3 pl-4 pr-6 shadow-card hover:bg-surface-300">
          <img src="/ubs-logo.png" alt="" className="ubs-logo h-6 w-auto" />
          <span className="text-[16px] font-light tracking-tight text-ink">Geneva</span>
        </button>
      )}
      {/* Kept mounted while closed so chats survive. */}
      <aside hidden={!open} style={{ width }} aria-label="Geneva assistant"
        className="animate-geneva-in fixed inset-y-0 right-0 z-40 flex max-w-[100vw] flex-col border-l border-hairline bg-surface-200 shadow-card">
        <div role="separator" aria-orientation="vertical" aria-label="Resize assistant" aria-valuemin={MIN_W} aria-valuemax={maxW()} aria-valuenow={width} tabIndex={0}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
          onKeyDown={(e) => { if (e.key === "ArrowLeft") { e.preventDefault(); apply(width + 24); } else if (e.key === "ArrowRight") { e.preventDefault(); apply(width - 24); } }}
          className={`absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize touch-none hover:bg-hairline-strong focus-visible:bg-hairline-strong focus-visible:outline-none ${dragging ? "bg-hairline-strong" : ""}`} />
        <header className="geneva-light flex items-center justify-between gap-3 border-b border-hairline px-6 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <img src="/ubs-logo.png" alt="" className="ubs-logo h-6 w-auto" />
            <div className="min-w-0">
              <h2 className="text-[20px] font-light leading-6 tracking-tight">Geneva</h2>
              <p className="truncate text-[13px] text-ink-muted">{client?.name ?? "Client"}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {fullPage && <Link to={fullPage} title="Open full page" aria-label="Open full page" className="p-2 text-ink-muted hover:text-ink"><ExternalLink size={18} /></Link>}
            <button type="button" onClick={() => apply(expanded ? DEFAULT_W : WIDE_W)} aria-label={expanded ? "Shrink" : "Expand"} title={expanded ? "Shrink" : "Expand"} className="p-2 text-ink-muted hover:text-ink">
              {expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
            <button type="button" onClick={() => set(false)} aria-label="Close" title="Close" className="p-2 text-ink-muted hover:text-ink"><X size={18} /></button>
          </div>
        </header>
        <div className="min-h-0 flex-1"><GenevaChat key={clientId} role={role} clientId={clientId} compact /></div>
      </aside>
    </div>
  );
}
