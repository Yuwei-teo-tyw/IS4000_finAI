import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Button, GateChip, Loading, NextAction, PageHeader, Section, useAsync } from "../../components/ui";
import { FinalisedTable } from "../../components/ps/FinalisedTable";
import { SavedStatus, useAutoSave } from "../../components/ic/SavedStatus";
import { saveIcProgress, useFinalised, useIcProgress } from "../../services/workflowStore";
import { IcStepper } from "../../components/ic/IcStepper";
import { BackLink } from "./icHelpers";

export default function ProductRecommendations() {
  const { clientId = "jfr" } = useParams();
  const nav = useNavigate();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const list = useFinalised(clientId);
  const progress = useIcProgress(clientId);
  const all = (list?.items ?? []).map((i) => i.product);
  const [sel, setSel] = useState<string[] | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { setSel(null); setDirty(false); }, [clientId]);
  const selected = sel ?? progress.products ?? all;
  useAutoSave(() => { saveIcProgress(clientId, { products: selected }); setDirty(false); }, dirty, selected);
  if (!client) return <Loading />;
  const toggle = (p: string) => { setSel(selected.includes(p) ? selected.filter((x) => x !== p) : [...selected, p]); setDirty(true); };
  return (
    <div>
      <SavedStatus dirty={dirty} savedAt={progress.savedAt} />
      <IcStepper clientId={clientId} current={0} />
      <BackLink to="/ic/inbox">Back to inbox</BackLink>
      <PageHeader eyebrow={`${client.name} · Quarterly review`} title="Product recommendations" subtitle="Tick products to carry into the TAA." actions={<GateChip id="G3" state="approved" />} />
      <Section title="Finalised by the Product Specialist" hint={`${selected.length} of ${all.length} products included in the TAA.`}>
        <FinalisedTable clientId={clientId} expandable selected={selected} onToggle={toggle} />
      </Section>
      <NextAction title="Review the market and portfolio health" action={<Button variant="primary" onClick={() => nav(`/ic/cases/${clientId}/market-health`)}>Continue to market view</Button>} />
    </div>
  );
}
