import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, CitationTag, GateChip, Loading, NextAction, PageHeader, Section, Stepper, Table, useAsync } from "../../components/ui";
import { BackLink, Msg, NumInput, splitCitations, sum } from "./icHelpers";
import { CASE_STEPS } from "./PortfolioInsights";

export default function TaaWorkspace() {
  const { clientId = "ser" } = useParams();
  const rows = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const [vals, setVals] = useState<number[]>([]);
  const [approved, setApproved] = useState(false);
  useEffect(() => { if (rows) setVals(rows.map((r) => r.newTaa)); }, [rows]);
  if (!rows) return <Loading />;

  const out = rows.filter((r, i) => Math.abs(vals[i] - r.saa) > r.band);
  const total = sum(vals);
  const ok = out.length === 0 && total === 100;
  const state = approved ? "approved" : "pending";

  return (
    <div>
      <PageHeader eyebrow="Quarterly review" title="Tactical asset allocation" subtitle="Each class must stay within 5 points of the SAA." actions={<GateChip id="G2" state={state} />} />
      <Stepper steps={CASE_STEPS} current={2} />
      <Section title="Old vs new TAA" hint="Edit the new column. Checks update as you type.">
        <Table head={["Class", "SAA", "Old TAA", "New TAA", "Band check", "Why"]} rows={rows.map((r, i) => {
          const inBand = Math.abs(vals[i] - r.saa) <= r.band;
          const { text, tags } = splitCitations(r.reason);
          return [r.assetClass, `${r.saa}%`, `${r.oldTaa}%`,
            <NumInput key="n" value={vals[i] ?? 0} suffix="%" width="w-24" onChange={(n) => { setVals(vals.map((v, j) => (j === i ? n : v))); setApproved(false); }} />,
            <Badge key="b" tone={inBand ? "green" : "red"}>{inBand ? "Within ±5" : "Out of band"}</Badge>,
            <div key="w" className="max-w-xs text-sm">{text} {tags.map((t) => <CitationTag key={t} tag={t} />)}</div>];
        })} />
        <div className="mt-8 flex flex-col gap-4">
          <Msg ok={total === 100}>{total === 100 ? "Total is 100." : `Total is ${total}. It must be 100.`}</Msg>
          {out.length > 0 && <Msg ok={false}>Out of band: {out.map((r) => r.assetClass).join(", ")}.</Msg>}
        </div>
      </Section>
      {approved ? <Msg ok>TAA approved at G2. Continue to the pack.</Msg> : null}
      <div className="mt-10" />
      <NextAction title={ok ? "Approve the TAA" : "Blocked: fix the band check"} body={ok ? "You decide. Approval moves this to the pack." : "Approve stays off while any class is out of band or the total is not 100."}
        action={approved ? <Button to={`/ic/cases/${clientId}/pack`}>Go to pack</Button> : <Button variant="gold" disabled={!ok} onClick={() => setApproved(true)}>Approve TAA (G2)</Button>} />
      <BackLink to={`/ic/cases/${clientId}/insights`}>Back to insights</BackLink>
    </div>
  );
}
