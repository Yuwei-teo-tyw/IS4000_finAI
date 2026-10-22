import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Button, GateChip, Loading, NextAction, PageHeader, Section, useAsync } from "../../components/ui";
import { FinalisedTable } from "../../components/ps/FinalisedTable";
import { AutoSaveStatus } from "../../components/pm/SaveProgressButton";
import { savePmProgress, useFinalised, usePmProgress } from "../../services/workflowStore";
import { PmStepper } from "../../components/pm/PmStepper";
import { BackLink } from "./pmHelpers";

export default function ProductRecommendations() {
  const { clientId = "jfr" } = useParams();
  const nav = useNavigate();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const list = useFinalised(clientId);
  const progress = usePmProgress(clientId);
  const all = (list?.items ?? []).map((i) => i.product);
  const [sel, setSel] = useState<string[] | null>(null);
  useEffect(() => { setSel(null); }, [clientId]);
  const selected = sel ?? progress.products ?? all;
  if (!client) return <Loading />;
  const toggle = (p: string) => { const next = selected.includes(p) ? selected.filter((x) => x !== p) : [...selected, p]; setSel(next); savePmProgress(clientId, { products: next }); };
  return (
    <div>
      <PmStepper clientId={clientId} current={0} />
      <BackLink to="/pm/inbox">Back to inbox</BackLink>
      <PageHeader eyebrow={`${client.name} · Quarterly review`} title="Product recommendations" subtitle="Tick products to carry into the TAA." actions={<GateChip id="G3" state="approved" />} />
      <Section title="Finalised by the Product Specialist" hint={`${selected.length} of ${all.length} products included in the TAA.`}>
        <FinalisedTable clientId={clientId} expandable selected={selected} onToggle={toggle} />
        <div className="mt-6"><AutoSaveStatus savedAt={progress.savedAt} /></div>
      </Section>
      <NextAction title="Review the market and portfolio health" action={<Button variant="primary" onClick={() => nav(`/pm/cases/${clientId}/market-health`)}>Continue to market view</Button>} />
    </div>
  );
}
