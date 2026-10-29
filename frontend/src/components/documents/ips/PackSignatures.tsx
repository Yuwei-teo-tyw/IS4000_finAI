import { useRef } from "react";
import { Upload, X } from "lucide-react";
import { ROLE_PEOPLE } from "../../../layouts/navConfig";
import { LABEL } from "./parts";
import { ROLE_LABEL, type Role } from "../../../types/arc";
import type { PackSignatures as Sigs } from "../../../services/packDraftStore";

const ORDER: Role[] = ["ps", "pm", "rm"];
const RM_SIGNATURE = "/signature-isabel.png";
const MAX_BYTES = 1_500_000;
const fmtWhen = (iso: string) => new Date(iso).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

interface Props { sigs: Sigs; onUpload?: (role: Role, sig: { name: string; dataUrl: string; signedAt: string }) => void; onRemove?: (role: Role) => void }

/** Digital signature slots. Interactive when onUpload is given (review page), read-only in the compiled preview. */
export function PackSignatures({ sigs, onUpload, onRemove }: Props) {
  const refs = useRef<Record<string, HTMLInputElement | null>>({});
  const pick = (role: Role, file?: File) => {
    if (!file || !onUpload || file.size > MAX_BYTES || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => onUpload(role, { name: file.name, dataUrl: String(reader.result), signedAt: new Date().toISOString() });
    reader.readAsDataURL(file);
  };
  return (
    <div className="mt-8 grid grid-cols-1 gap-8 sm:grid-cols-3">
      {ORDER.map((r) => {
        // The RM's signature defaults to the Isabel signature on file, dated today (display only; nothing is stored).
        const sig = sigs[r] ?? (r === "rm" ? { name: "signature-isabel.png", dataUrl: RM_SIGNATURE, signedAt: new Date().toISOString() } : undefined);
        return (
          <div key={r} className="avoid-break min-w-0">
            <p className={LABEL}>{ROLE_LABEL[r]}</p>
            <div className={`mt-3 flex h-28 items-center justify-center overflow-hidden border ${sig ? "border-hairline bg-surface-100" : "border-dashed border-hairline-strong bg-surface-200"}`}>
              {sig
                ? <img src={sig.dataUrl} alt={`${ROLE_PEOPLE[r].person} signature`} className="max-h-full max-w-full object-contain p-2" />
                : <span className="text-[13px] italic text-ink-muted">Digital signature pending</span>}
            </div>
            <p className="mt-3 text-[15px] leading-6 text-ink">{ROLE_PEOPLE[r].person}</p>
            <p className="text-[13px] leading-5 text-ink-muted">{sig ? `Signed ${fmtWhen(sig.signedAt)}` : "Signed on: ____________"}</p>
            {onUpload && (
              <div className="no-print mt-3 flex items-center gap-2">
                <input ref={(el) => { refs.current[r] = el; }} type="file" accept="image/*" className="hidden" onChange={(e) => { pick(r, e.target.files?.[0]); e.target.value = ""; }} />
                <button type="button" onClick={() => refs.current[r]?.click()}
                  className="inline-flex min-h-9 items-center gap-2 border border-ink px-3 text-[13px] text-ink hover:bg-surface-300">
                  <Upload size={14} />{sig ? "Replace" : "Upload signature"}
                </button>
                {sig && <button type="button" onClick={() => onRemove?.(r)} aria-label="Remove signature" title="Remove" className="p-2 text-ink-muted hover:text-negative"><X size={16} /></button>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
