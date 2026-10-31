import { ArrowLeft, Trash2 } from "lucide-react";
import { Button } from "../../components/ui";
import { GeneratedPackDocument } from "../../components/documents/GeneratedPackDocument";
import { PackPreviewButton } from "../../components/documents/PackPreviewDialog";
import { NoteToPm } from "../../components/rm/NoteToPm";
import { withdrawPackFromPm } from "../../services/packHandover";
import { deleteCurrentPack, getPackState, packStatusLabel, useSyncError, type GeneratedPack } from "./generatedPackStore";

/** The generated review pack in the IPS document style, sections A-G. The RM edits, then sends to the Portfolio Manager. */
export function GeneratedPackView({ clientId, clientName, pack, onBack }: { clientId: string; clientName: string; pack: GeneratedPack; onBack?: () => void }) {
  const syncErr = useSyncError();
  const st = getPackState(clientId);
  const status = st ? packStatusLabel(st) : "Draft";
  const del = () => {
    if (!window.confirm("Delete this review pack? This cannot be undone.")) return;
    if (status === "Sent to PM") withdrawPackFromPm(clientId);
    deleteCurrentPack(clientId);
    onBack?.();
  };
  return (
    <div>
      {onBack && <div className="mb-8"><Button variant="ghost" onClick={onBack}><ArrowLeft size={16} /> Back To Review Pack History</Button></div>}
      <div className="mb-10 flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <h2 className="text-3xl">Review pack</h2>
          <p className="mt-2 text-base text-ink-500">AI draft from the active IPS. Edit any section, then send it to the Portfolio Manager.</p>
        </div>
        {status !== "Approved" && <button type="button" aria-label="Delete review pack" title="Delete review pack" onClick={del} className="inline-flex size-10 items-center justify-center rounded-sm border border-ink text-ink hover:bg-surface-300"><Trash2 size={18} /></button>}
      </div>
      {syncErr && <p role="status" className="mb-4 text-sm text-ink-muted">{syncErr}</p>}
      <div className="mt-10 flex justify-end print:hidden"><PackPreviewButton clientId={clientId} clientName={clientName} pack={pack} role="rm" /></div>
      <div className="mt-6"><GeneratedPackDocument clientId={clientId} clientName={clientName} pack={pack} role="rm" /></div>
      <NoteToPm clientId={clientId} rmContext={pack.rmContext} body="The agent drafted this pack; you decide. Sending hands the pack to the Portfolio Manager for allocation and product work." />
    </div>
  );
}
