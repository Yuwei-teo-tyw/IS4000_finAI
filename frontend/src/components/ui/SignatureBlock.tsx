import { useRef, useState } from "react";
import { saveSignature, useSignatures } from "../../services/packDraftStore";
import { Button } from "./index";

type Mode = "type" | "draw" | "upload";
export type SignatureRole = "ic" | "ps" | "rm";
const MODES: { id: Mode; label: string }[] = [{ id: "type", label: "Type" }, { id: "draw", label: "Draw" }, { id: "upload", label: "Upload" }];
const ROLE_LABEL: Record<SignatureRole, string> = { ic: "Investment Counsellor", ps: "Product Specialist", rm: "Relationship Manager" };
/** Dancing Script is loaded once in styles/tokens.css. */
export const SCRIPT_FONT = "'Dancing Script','Snell Roundhand','Segoe Script',cursive";
/** Uploaded images above this size are ignored, so a signature cannot fill session storage. */
const MAX_UPLOAD_BYTES = 1_500_000;
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });

/** Shared signature block (Type / Draw / Upload), used by every role. Saves to the pack signature store under `role`. */
export function SignatureBlock({ clientId, role, defaultName = "", title = "Sign before sending" }: { clientId: string; role: SignatureRole; defaultName?: string; title?: string }) {
  const sig = useSignatures(clientId)[role];
  const [mode, setMode] = useState<Mode>("type");
  const [name, setName] = useState(defaultName);
  const [img, setImg] = useState("");
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const today = new Date().toISOString();

  const pos = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * e.currentTarget.width, y: ((e.clientY - r.top) / r.height) * e.currentTarget.height };
  };
  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const ctx = e.currentTarget.getContext("2d"); if (!ctx) return;
    drawing.current = true; e.currentTarget.setPointerCapture(e.pointerId);
    ctx.lineWidth = 2.5; ctx.lineCap = "round"; ctx.strokeStyle = "#1a1a1a";
    const p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y);
  };
  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return;
    const ctx = e.currentTarget.getContext("2d"); if (!ctx) return;
    const p = pos(e); ctx.lineTo(p.x, p.y); ctx.stroke();
  };
  const up = () => { drawing.current = false; if (canvas.current) setImg(canvas.current.toDataURL("image/png")); };
  const clear = () => { const c = canvas.current; c?.getContext("2d")?.clearRect(0, 0, c.width, c.height); setImg(""); };
  const onFile = (f?: File) => {
    if (!f || f.size > MAX_UPLOAD_BYTES || !f.type.startsWith("image/")) return;
    const r = new FileReader(); r.onload = () => setImg(String(r.result)); r.readAsDataURL(f);
  };
  const switchMode = (m: Mode) => { setMode(m); setImg(""); };

  const ready = name.trim().length > 1 && (mode === "type" || !!img);
  const sign = () => saveSignature(clientId, role, mode === "type"
    ? { name: name.trim(), dataUrl: "", signedAt: new Date().toISOString(), typed: true }
    : { name: name.trim(), dataUrl: img, signedAt: new Date().toISOString() });

  if (sig) {
    return (
      <div className="border border-hairline bg-surface-100 p-8">
        <p className="text-xs text-ink-muted">Signed by the {ROLE_LABEL[role]}</p>
        <div className="mt-4 min-h-16 border-b border-hairline-strong pb-2">
          {sig.typed || !sig.dataUrl
            ? <span className="text-[34px] leading-tight text-ink" style={{ fontFamily: SCRIPT_FONT }}>{sig.name}</span>
            : <img src={sig.dataUrl} alt={`Signature of ${sig.name}`} className="h-16 max-w-full object-contain object-left" />}
        </div>
        <p className="mt-3 flex flex-wrap items-center justify-between gap-4 text-sm text-ink-muted">
          <span>{sig.name} · {fmtDate(sig.signedAt)}</span>
          <Button variant="secondary" onClick={() => saveSignature(clientId, role, null)}>Remove signature</Button>
        </p>
      </div>
    );
  }

  return (
    <div className="border border-hairline bg-surface-100 p-8">
      <h3 className="text-xl font-normal">{title}</h3>
      <div className="mt-6 inline-flex border border-hairline" role="tablist">
        {MODES.map((m) => (
          <button key={m.id} role="tab" aria-selected={mode === m.id} onClick={() => switchMode(m.id)}
            className={`min-h-10 px-6 text-[15px] ${mode === m.id ? "bg-surface-300 font-normal text-ink" : "font-light text-ink-muted hover:bg-surface-200"}`}>{m.label}</button>
        ))}
      </div>
      <label className="mt-6 block text-sm text-ink-muted">Full name
        <input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 block w-full max-w-sm border border-hairline bg-white px-3 py-2 text-[15px] text-ink" />
      </label>
      <div className="mt-6 border-b border-hairline-strong pb-2">
        {mode === "type" && <div className="flex min-h-16 items-end text-[34px] leading-tight text-ink" style={{ fontFamily: SCRIPT_FONT }}>{name || <span className="text-[15px] text-ink-muted" style={{ fontFamily: "inherit" }}>Your signature appears here</span>}</div>}
        {mode === "draw" && <canvas ref={canvas} width={600} height={140} onPointerDown={down} onPointerMove={move} onPointerUp={up} className="h-24 w-full max-w-xl touch-none bg-white" aria-label="Draw your signature" />}
        {mode === "upload" && (img
          ? <img src={img} alt="Uploaded signature" className="h-16 max-w-full object-contain object-left" />
          : <input type="file" accept="image/*" onChange={(e) => onFile(e.target.files?.[0])} className="min-h-16 text-sm text-ink-muted" aria-label="Upload signature image" />)}
      </div>
      <p className="mt-3 flex flex-wrap items-center justify-between gap-4 text-sm text-ink-muted">
        <span>{fmtDate(today)}</span>
        <span className="inline-flex gap-3">
          {mode === "draw" && <Button variant="secondary" onClick={clear}>Clear</Button>}
          {mode === "upload" && img && <Button variant="secondary" onClick={() => setImg("")}>Replace</Button>}
          <Button variant="secondary" disabled={!ready} onClick={sign}>Apply signature</Button>
        </span>
      </p>
    </div>
  );
}
