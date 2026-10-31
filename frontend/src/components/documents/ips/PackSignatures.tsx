import { useRef } from "react";
import { Upload, X } from "lucide-react";
import { ROLE_PEOPLE } from "../../../layouts/navConfig";
import { LABEL } from "./parts";
import { ROLE_LABEL, type Role } from "../../../types/arc";
import { saveSignature, type PackSignatures as Sigs } from "../../../services/packDraftStore";

type Slot = "client" | "rm" | "pm";
const ORDER: Slot[] = ["client", "rm", "pm"];
const SLOT_LABEL: Record<Slot, string> = { client: "Client", rm: ROLE_LABEL.rm, pm: ROLE_LABEL.pm };
const SLOT_PERSON = (r: Slot) => (r === "client" ? "Client" : ROLE_PEOPLE[r as Role].person);
const RM_SIGNATURE = "/signature-isabel.png";
const PM_SIGNATURE = "/signatures/pm-weilun.png";
const MAX_BYTES = 1_500_000;
const fmtWhen = (iso: string) => new Date(iso).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

interface Props { sigs: Sigs; /** Persists to the shared pack signature store (all three slots editable by anyone). */ clientId?: string; /** Preview: show images and dates, no buttons. */ readOnly?: boolean; onUpload?: (role: Slot, sig: { name: string; dataUrl: string; signedAt: string }) => void; onRemove?: (role: Slot) => void; /** Do not fall back to the default RM signature: unsigned roles stay blank. */ noDefault?: boolean; /** The pack has reached the PM: show the PM signature on file unless one was uploaded. */ pmDefault?: boolean }

/** Digital signature slots (Client, RM, PM). Any viewer may upload/replace/remove any slot unless readOnly. */
export function PackSignatures({ sigs, clientId, readOnly, onUpload, onRemove, noDefault, pmDefault }: Props) {
  const refs = useRef<Record<string, HTMLInputElement | null>>({});
  const editable = !readOnly && !!(clientId || onUpload);
  const pick = (role: Slot, file?: File) => {
    if (!file || !editable || file.size > MAX_BYTES || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      const sig = { name: file.name, dataUrl: String(reader.result), signedAt: new Date().toISOString() };
      if (clientId) saveSignature(clientId, role, sig);
      onUpload?.(role, sig);
    };
    reader.readAsDataURL(file);
  };
  const remove = (role: Slot) => { if (clientId) saveSignature(clientId, role, null); onRemove?.(role); };
  return (
    <div className="@container mt-8"><div className="grid grid-cols-1 gap-8 @xl:grid-cols-3">
      {ORDER.map((r) => {
        // The RM's signature defaults to the Isabel signature on file, dated today (display only; nothing is stored).
        const sig = sigs[r] ?? (r === "rm" && !noDefault ? { name: "signature-isabel.png", dataUrl: RM_SIGNATURE, signedAt: new Date().toISOString() } : r === "pm" && pmDefault ? { name: "pm-weilun.png", dataUrl: PM_SIGNATURE, signedAt: new Date().toISOString() } : undefined);
        return (
          <div key={r} className="avoid-break min-w-0">
            <p className={LABEL}>{SLOT_LABEL[r]}</p>
            <div className={`mt-3 flex h-28 items-center justify-center overflow-hidden border ${sig ? "border-hairline bg-surface-100" : "border-dashed border-hairline-strong bg-surface-200"}`}>
              {sig
                ? <img src={sig.dataUrl} alt={`${SLOT_PERSON(r)} signature`} className="max-h-full max-w-full object-contain p-2" />
                : <span className="text-[13px] italic text-ink-muted">Digital signature pending</span>}
            </div>
            <p className="mt-3 text-[15px] leading-6 text-ink">{SLOT_PERSON(r)}</p>
            <p className="text-[13px] leading-5 text-ink-muted">{sig ? `Signed ${fmtWhen(sig.signedAt)}` : "Signed on: ____________"}</p>
            {editable && (
              <div className="no-print mt-3 flex items-center gap-2">
                <input ref={(el) => { refs.current[r] = el; }} type="file" accept="image/*" className="hidden" onChange={(e) => { pick(r, e.target.files?.[0]); e.target.value = ""; }} />
                <button type="button" onClick={() => refs.current[r]?.click()}
                  className="inline-flex min-h-9 items-center gap-2 border border-ink px-3 text-[13px] text-ink hover:bg-surface-300">
                  <Upload size={14} />{sig ? "Replace" : "Upload signature"}
                </button>
                {sigs[r] && <button type="button" onClick={() => remove(r)} aria-label="Remove signature" title="Remove" className="p-2 text-ink-muted hover:text-negative"><X size={16} /></button>}
              </div>
            )}
          </div>
        );
      })}
    </div></div>
  );
}
