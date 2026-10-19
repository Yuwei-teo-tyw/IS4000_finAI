import { useState } from "react";
import { useParams } from "react-router-dom";
import { Lock } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, BulletList, Button, Card, GateChip, Loading, NextAction, PageHeader, Stepper, useAsync } from "../../components/ui";
import { onboardingSteps, ipsToSections, fmtDate } from "./rmShared";
import { ContributionsPanel } from "../../components/export/ContributionsPanel";
import { ExportActions } from "../../components/export/ExportActions";

export default function IpsApproval() {
  const { clientId = "" } = useParams();
  const parts = useAsync(() => arcApi.getIps(clientId), [clientId]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [confirming, setConfirming] = useState(false);
  const [name, setName] = useState("");
  const [approvedBy, setApprovedBy] = useState<string | null>(null);
  if (!parts) return <Loading />;
  const sections = ipsToSections(parts);

  return (
    <div>
      <PageHeader eyebrow="Gate G1" title="Approve the IPS"
        actions={<GateChip id="G1" state={approvedBy ? "approved" : "pending"} />} />
      <Stepper steps={onboardingSteps} current={approvedBy ? 5 : 4} />

      {approvedBy ? (
        <NextAction title="IPS approved" body={`Approved by ${approvedBy}. The IPS is now active.`}
          action={<Button to={`/rm/clients/${clientId}/documents`}>View client's documents</Button>} />
      ) : (
        <NextAction title="Review, then approve" body="The agent never approves on your behalf."
          action={<Button onClick={() => setConfirming(true)}>Approve G1</Button>} />
      )}

      {confirming && !approvedBy && (
        <Card accent className="mb-12">
          <h3 className="text-xl">Confirm approval</h3>
          <p className="mt-2 mb-5 text-sm text-ink-500">Type your name to log this approval.</p>
          <div className="flex flex-wrap gap-3">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your full name"
              className="min-w-64 flex-1 rounded-md border border-ink-200 px-4 py-3 text-sm outline-none focus:border-ink" />
            <Button disabled={!name.trim()} onClick={() => setApprovedBy(`${name.trim()} on ${new Date().toLocaleString("en-SG")}`)}>Confirm</Button>
            <Button variant="secondary" onClick={() => setConfirming(false)}>Cancel</Button>
          </div>
        </Card>
      )}

      <div className="mb-10 flex flex-col gap-8 lg:flex-row lg:items-start">
        <aside className="w-full shrink-0 lg:sticky lg:top-6 lg:w-80">
          <ContributionsPanel sections={sections} className="" />
        </aside>
        <div className="flex min-w-0 flex-1 flex-col gap-8">
          {parts.map((p) => (
            <Card key={p.part}>
              <div className="mb-3 flex items-center justify-between gap-4">
                <h2 className="min-w-0 break-words text-xl">{p.title}</h2>
                <Badge tone={p.owner === "ic" ? "sky" : "grey"}><Lock size={12} className="mr-1" />{p.owner === "ic" ? "Filled by IC" : "Filled by RM"}</Badge>
              </div>
              <BulletList text={p.body} className="!text-base" />
            </Card>
          ))}
        </div>
      </div>

      <div className="mb-10 flex flex-wrap justify-end">
        <ExportActions docTitle="Investment Policy Statement" clientName={client?.name ?? clientId} version={approvedBy ? "Approved" : "For Approval"} date={fmtDate(new Date().toISOString())} sections={sections} />
      </div>
    </div>
  );
}
