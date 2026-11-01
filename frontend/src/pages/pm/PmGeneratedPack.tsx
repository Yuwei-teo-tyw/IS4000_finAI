import { useEffect, useRef, useState } from "react";
import { GeneratedPackDocument } from "../../components/documents/GeneratedPackDocument";
import { PackPreviewButton } from "../../components/documents/PackPreviewDialog";
import { RmCommentsPanel } from "../../components/pm/RmCommentsPanel";
import { Button } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { saveGeneratedPack, useSyncError, type GeneratedPack, type GenSection, type GenShift, type GenTaaRow } from "../rm/generatedPackStore";

/** The RM's generated pack as the shared editable document. The PM edits in place, adds commentary on D to F, and signs in G.
 *  The RM's pack holds no new TAA or holding shifts; on first open the PM's are proposed by the agents and written into the pack. */
export function PmGeneratedPack({ clientId, clientName, pack }: { clientId: string; clientName: string; pack: GeneratedPack }) {
  const syncErr = useSyncError();
  const needsProposals = (pack.taa_stage ?? "pm") !== "pm";
  const [proposing, setProposing] = useState<{ busy: boolean; error?: string }>({ busy: false });
  const started = useRef(false);

  const propose = () => {
    started.current = true;
    setProposing({ busy: true });
    arcApi.reviewPackPmProposals(clientId).then((p) => {
      const byId = new Map(p.sections.map((s) => [s.id, s as GenSection]));
      // The RM could not edit D's TAA or F's shifts, so only those keys are reset; RM commentary on D and F is kept.
      const edits = Object.fromEntries(Object.entries(pack.edits).filter(([k]) => !["D.taa", "F.shifts", "F.prodNew"].includes(k)));
      saveGeneratedPack(clientId, {
        ...pack, edits, taa_stage: "pm", taa_note: null,
        taa: p.taa as GeneratedPack["taa"] & Record<string, GenTaaRow[]>, holdings_shifts: p.holdings_shifts as GenShift[],
        sections: pack.sections.map((s) => byId.get(s.id) ?? s),
      });
      setProposing({ busy: false });
    }).catch((e) => setProposing({ busy: false, error: e instanceof Error ? e.message : String(e) }));
  };
  useEffect(() => { if (needsProposals && !started.current) propose(); }, [needsProposals]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-8 xl:flex-row xl:items-start">
      <div className="min-w-0 flex-1 xl:order-1 order-2">
      {syncErr && <p role="status" className="mb-6 text-sm text-ink-muted">{syncErr}</p>}
      {needsProposals && (
        <div role="status" className="mb-6 border border-hairline bg-surface-200 px-4 py-3 text-sm" data-testid="pm-proposals">
          {proposing.busy ? <p className="animate-geneva-flow">Proposing the new TAA and holding shifts from the Market Analysis Agent, the CIO house view, the Client Portfolio Agent's holdings and the Product Specialist's shortlist…</p>
            : proposing.error ? <div className="flex flex-wrap items-center gap-3"><p className="text-negative">The new TAA could not be proposed: {proposing.error}</p><Button variant="secondary" size="sm" onClick={propose}>Retry</Button></div>
            : <p className="text-ink-muted">The new TAA and holding shifts will be proposed here.</p>}
        </div>
      )}
      <div className="mb-6 flex justify-end print:hidden"><PackPreviewButton clientId={clientId} clientName={clientName} pack={pack} role="pm" /></div>
      <GeneratedPackDocument clientId={clientId} clientName={clientName} pack={pack} role="pm" notice="Drafted by the agent, edited by the RM. You can edit any section and add commentary" />
      </div>
      <aside className="order-1 xl:order-2 xl:sticky xl:top-6 xl:w-80 xl:shrink-0"><RmCommentsPanel clientId={clientId} pack={pack} /></aside>
    </div>
  );
}
