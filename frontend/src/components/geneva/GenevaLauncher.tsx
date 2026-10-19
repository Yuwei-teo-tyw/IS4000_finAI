import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronsRight, ExternalLink } from "lucide-react";
import type { Role } from "../../types/arc";
import { useAsync } from "../ui";
import { arcApi } from "../../services/arcApi";
import { GenevaChat } from "./GenevaChat";

const MIN_W = 420;
const DEFAULT_W = 560;
const maxW = () => Math.max(MIN_W, Math.round(window.innerWidth * 0.6));
const clampW = (w: number) => Math.max(MIN_W, Math.min(maxW(), w));
function loadWidth(): number {
  try { const v = Number(localStorage.getItem("arc.assistantWidth")); return v ? clampW(v) : DEFAULT_W; } catch { return DEFAULT_W; }
}
function loadOpen(): boolean {
  try { return localStorage.getItem("arc.assistantOpen") === "true"; } catch { return false; }
}

/** Liquid glass: translucent, blurred, light highlight, soft shadow. Works on Lux tokens in both themes. */
const GLASS = "border border-white/40 bg-[color-mix(in_srgb,var(--surface-100)_55%,transparent)] backdrop-blur-xl backdrop-saturate-150 shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_8px_24px_rgba(0,0,0,0.12)]";

/** Geneva launcher, bottom right. Opens the same chat as the AI Assistant page in a docked, resizable side panel that pushes the page left (never covers it). */
export default function GenevaLauncher({ role, clientId }: { role: Role; clientId: string }) {
  const [open, setOpen] = useState(loadOpen);
  const [width, setWidth] = useState(loadWidth);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; w: number } | null>(null);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
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

  const down = (e: React.PointerEvent<HTMLDivElement>) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, w: width }; setDragging(true); };
  const move = (e: React.PointerEvent<HTMLDivElement>) => { if (drag.current) setWidth(clampW(drag.current.w + (drag.current.x - e.clientX))); };
  const up = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    drag.current = null; setDragging(false);
    setWidth((w) => { save(w); return w; });
  };

  return (
    <div className="contents print:hidden">
      <button type="button" onClick={() => set(true)} aria-label="Open Geneva assistant" title="Open Geneva assistant" tabIndex={open ? -1 : 0}
        style={{ transition: "opacity 350ms ease, transform 350ms ease", opacity: open ? 0 : 1, transform: open ? "scale(0.4)" : "scale(1)", pointerEvents: open ? "none" : "auto" }}
        className={`${GLASS} fixed bottom-6 right-6 z-40 flex size-14 items-center justify-center rounded-full hover:brightness-95`}>
        <img src="/ubs-logo.png" alt="" className="ubs-logo h-6 w-auto" />
      </button>
      {/* Kept mounted while closed so chats survive. Outer width animates the page push; inner panel shrinks into the icon. */}
      <aside aria-label="Geneva assistant" aria-hidden={!open}
        style={{ width: open ? width : 0, transition: dragging ? "none" : "width 350ms ease" }}
        className="sticky top-0 h-screen shrink-0 max-w-[60vw]">
        <div style={{
            width, transformOrigin: "calc(100% - 52px) calc(100% - 52px)",
            transition: "transform 350ms ease, opacity 350ms ease, visibility 0s linear " + (open ? "0s" : "350ms"),
            transform: open ? "none" : "translate(8px, 8px) scale(0.05)", opacity: open ? 1 : 0, visibility: open ? "visible" : "hidden",
          }}
          className="absolute inset-y-0 right-0 flex max-w-[60vw] flex-col border-l border-hairline bg-surface-200">
        <div role="separator" aria-orientation="vertical" aria-label="Resize assistant" aria-valuemin={MIN_W} aria-valuemax={maxW()} aria-valuenow={width} tabIndex={0}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
          onKeyDown={(e) => { if (e.key === "ArrowLeft") { e.preventDefault(); apply(width + 24); } else if (e.key === "ArrowRight") { e.preventDefault(); apply(width - 24); } }}
          className="group absolute inset-y-0 -left-2 z-10 flex w-4 cursor-col-resize touch-none select-none items-center justify-center focus-visible:outline-none">
          <span className={`pointer-events-none h-full w-px transition-colors group-hover:w-0.5 group-hover:bg-ink-muted group-focus-visible:bg-ink-muted ${dragging ? "w-0.5 bg-ink-muted" : ""}`} />
          <span className={`pointer-events-none absolute top-1/2 h-12 w-1.5 -translate-y-1/2 rounded-full bg-ink-muted transition-opacity ${dragging ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"}`} />
        </div>
        <header className={`${GLASS} geneva-light flex items-center justify-between gap-3 border-b px-6 py-4`}>
          <div className="flex min-w-0 items-center gap-3">
            <img src="/ubs-logo.png" alt="" className="ubs-logo h-6 w-auto" />
            <div className="min-w-0">
              <h2 className="text-[20px] font-light leading-6 tracking-tight">Geneva</h2>
              <p className="truncate text-[13px] text-ink-muted">{client?.name ?? "Client"}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {fullPage && <Link to={fullPage} title="Open full page" aria-label="Open full page" className="p-2 text-ink-muted hover:text-ink"><ExternalLink size={18} /></Link>}
            <button type="button" onClick={() => set(false)} aria-label="Collapse Geneva" title="Collapse" className="inline-flex items-center gap-1.5 p-2 text-[13px] text-ink-muted hover:text-ink"><ChevronsRight size={18} />Collapse</button>
          </div>
        </header>
        <div className="min-h-0 flex-1"><GenevaChat key={clientId} role={role} clientId={clientId} compact /></div>
        </div>
      </aside>
    </div>
  );
}
