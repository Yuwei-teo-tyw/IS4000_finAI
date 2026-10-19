import { useParams } from "react-router-dom";
import { IcStepper } from "../../components/ic/IcStepper";
import PackReview from "../rm/PackReview";
import { Button, GateChip, NextAction } from "../../components/ui";
import { useSectionDone } from "../../services/packDraftStore";
import { sendIcToRm, useIcHandover, useIcProgress, withdrawIcToRm } from "../../services/workflowStore";
import { BackLink } from "./icHelpers";

const fmt = (iso: string) => new Date(iso).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
export default function IcPack() {
  const { clientId = "jfr" } = useParams();
  const handover = useIcHandover(clientId);
  const progress = useIcProgress(clientId);
  const done = useSectionDone(clientId);
  const ready = [2, 3, 4, 8].every((n) => done[n]?.done);
  const hint = !ready && <p className="mt-3 text-sm text-ink-muted" role="status">Mark sections 2, 3, 4 and 5 as done to send</p>;
  const changed = !!handover && !!progress.savedAt && progress.savedAt > handover.sentAt;

  return (
    <div>
      <IcStepper clientId={clientId} current={4} />
      <BackLink to={`/ic/cases/${clientId}/holdings`}>Back to individual holdings</BackLink>
      <PackReview embedded clientId={clientId} />
      <div className="mt-16">
        {!handover ? (
          <NextAction title="Send to Relationship Manager" body="Sections 2 to 5 are ready for the RM."
            action={<span className="inline-flex flex-wrap items-center gap-4"><GateChip id="G2" state="pending" /><Button disabled={!ready} onClick={() => sendIcToRm(clientId)}>Send to Relationship Manager</Button></span>} />
        ) : (
          <NextAction title={`Sent to RM on ${fmt(handover.sentAt)}`}
            body={changed ? "Changed since sent. Re-send so the RM sees your latest edits." : "You can withdraw until the RM acts."}
            action={<span className="inline-flex flex-wrap items-center gap-4"><GateChip id="G2" state="pending" />
              {changed && <Button disabled={!ready} onClick={() => sendIcToRm(clientId)}>Re-send to RM</Button>}
              <Button variant="secondary" onClick={() => withdrawIcToRm(clientId)}>Withdraw</Button></span>} />
        )}
        {hint}
      </div>
    </div>
  );
}
