import { useNavigate, useParams } from "react-router-dom";
import { Button, GateChip, Loading, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { usePackHandover, usePackStatus, sendPmToRm, withdrawPmToRm } from "../../services/packHandover";
import { PmGeneratedPack } from "./PmGeneratedPack";
import { BackLink } from "./pmHelpers";

const fmt = (iso: string) => new Date(iso).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });

/** The single PM page: the Review Pack the RM generated and sent, edited in place, then sent back. */
export default function PmReview() {
  const { clientId = "jfr" } = useParams();
  const nav = useNavigate();
  const sent = usePackHandover(clientId);
  const returned = usePackStatus(clientId) === "returned_to_rm";
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  if (!client) return <Loading />;
  if (!sent?.pack) {
    return (
      <div>
        <BackLink to="/pm/inbox">Back to inbox</BackLink>
        <p className="mt-8 text-base text-ink-muted" role="status">No review pack has been sent to you for {client.name} yet.</p>
      </div>
    );
  }
  return (
    <div>
      <BackLink to="/pm/inbox">Back to inbox</BackLink>
      <PmGeneratedPack clientId={clientId} clientName={client.name} pack={sent.pack} />
      <div className="mt-16 flex flex-wrap items-center gap-4 border-t border-hairline pt-8">
        <GateChip id="G2" state="pending" />
        {returned
          ? <><span className="text-sm text-up" role="status">Sent to the Relationship Manager.</span><Button variant="secondary" onClick={() => withdrawPmToRm(clientId)}>Withdraw</Button></>
          : <Button onClick={() => { sendPmToRm(clientId); nav("/pm/inbox"); }}>Send to Relationship Manager</Button>}
        <span className="text-sm text-ink-muted">Pack received {fmt(sent.sentAt)}</span>
      </div>
    </div>
  );
}
