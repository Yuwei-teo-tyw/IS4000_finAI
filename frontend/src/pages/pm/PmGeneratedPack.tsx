import { GeneratedPackDocument } from "../../components/documents/GeneratedPackDocument";
import { PackPreviewButton } from "../../components/documents/PackPreviewDialog";
import { RmCommentsPanel } from "../../components/pm/RmCommentsPanel";
import { useSyncError, type GeneratedPack } from "../rm/generatedPackStore";

/** The RM's generated pack as the shared editable document. The PM edits in place, adds commentary on D to F, and signs in G. */
export function PmGeneratedPack({ clientId, clientName, pack }: { clientId: string; clientName: string; pack: GeneratedPack }) {
  const syncErr = useSyncError();
  return (
    <div className="flex flex-col gap-8 xl:flex-row xl:items-start">
      <div className="min-w-0 flex-1 xl:order-1 order-2">
      {syncErr && <p role="status" className="mb-6 text-sm text-ink-muted">{syncErr}</p>}
      <div className="mb-6 flex justify-end print:hidden"><PackPreviewButton clientId={clientId} clientName={clientName} pack={pack} role="pm" /></div>
      <GeneratedPackDocument clientId={clientId} clientName={clientName} pack={pack} role="pm" notice="Drafted by the agent, edited by the RM. You can edit any section and add commentary" />
      </div>
      <aside className="order-1 xl:order-2 xl:sticky xl:top-6 xl:w-80 xl:shrink-0"><RmCommentsPanel clientId={clientId} pack={pack} /></aside>
    </div>
  );
}
