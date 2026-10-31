import { useState, type ReactNode } from "react";
import { Button, NextAction } from "../ui";
import { BulletTextarea } from "../documents/BulletTextarea";
import { SEED_RM_PACK_COMMENTS } from "../pm/RmCommentsPanel";
import { loadPmNote, sendPackToPm, withdrawPackFromPm } from "../../services/packHandover";
import { usePackStates } from "../../pages/rm/generatedPackStore";

const fmt = (iso?: string | null) => { const d = iso ? new Date(iso) : null; return d && !isNaN(+d) ? d.toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" }) : ""; };

/** Shared send step, placed at the bottom of the page after the pack: editable note, then send. After sending the note stays visible read-only with Withdraw. */
export function NoteToPm({ clientId, title = "Send to Portfolio Manager", body, label = "Send to Portfolio Manager", disabled, rmContext, extra }:
  { clientId: string; title?: string; body?: string; label?: string; disabled?: boolean; rmContext?: string; extra?: ReactNode }) {
  const [note, setNote] = useState(() => loadPmNote(clientId) || SEED_RM_PACK_COMMENTS.join("\n"));
  const h = usePackStates()[clientId]?.handover;
  if (h?.status) {
    const back = h.status === "returned_to_rm";
    const sentNote = (h.note ?? note).split("\n").map((l) => l.replace(/^\s*[-•*]\s*/, "").trim()).filter(Boolean);
    return (
      <div className="mx-auto mb-4 mt-12 w-full max-w-[1400px]">
        {sentNote.length > 0 && (
          <div className="mb-4">
            <span className="block text-sm text-ink-muted">Note sent to Portfolio Manager{fmt(h.sentAt) ? ` · sent ${fmt(h.sentAt)}` : ""}</span>
            <ul className="mt-2 list-disc space-y-1 border border-hairline bg-surface-100 py-4 pl-8 pr-4 text-sm text-ink-700">{sentNote.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
        )}
        <NextAction title={back ? "Portfolio Manager has handed back" : "Sent to Portfolio Manager"} body={back ? "Review the pack and proceed to final approval." : "Waiting for the Portfolio Manager."}
          action={back ? undefined : <span className="flex flex-wrap gap-3">{extra}<Button variant="secondary" onClick={() => withdrawPackFromPm(clientId)}>Withdraw request</Button></span>} />
      </div>
    );
  }
  return (
    <div className="mx-auto mb-4 mt-12 w-full max-w-[1400px]">
      <div className="mb-4">
        <span className="block text-sm text-negative">Note to Portfolio Manager (one point per line, edit freely)</span>
        <div className="mt-2 text-negative [&_*]:!text-negative [&_*]:!bg-[#fdecec]"><BulletTextarea label="Note to Portfolio Manager" value={note} onChange={setNote} /></div>
      </div>
      <NextAction title={title} body={body}
        action={<Button disabled={disabled} onClick={() => sendPackToPm(clientId, rmContext, note)}>{label}</Button>} />
    </div>
  );
}
