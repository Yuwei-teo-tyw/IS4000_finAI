import { useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, GateChip, NextAction, PageHeader, Section, Stepper, Table, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { ClientStrip, PS_STEPS, loadSelection, saveSelection } from "./psShared";

export default function FinaliseProducts() {
  const { clientId = "ser" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [confirm, setConfirm] = useState(false);
  const [sent, setSent] = useState(false);

  const [all] = useState(() => loadSelection(clientId));
  const [ticked, setTicked] = useState<string[]>(() => all.map((r) => r.product));
  const list = all.filter((r) => ticked.includes(r.product));
  const toggle = (name: string) => setTicked((cur) => {
    const next = cur.includes(name) ? cur.filter((x) => x !== name) : [...cur, name];
    saveSelection(clientId, all.filter((r) => next.includes(r.product)));
    return next;
  });

  if (sent) {
    return (
      <div>
        <PageHeader eyebrow="Product review · Done" title="Sent to the Investment Counsellor" actions={<GateChip id="G3" state="approved" />} />
        <Stepper steps={PS_STEPS} current={2} />
        <Card accent className="mb-12 !p-10">
          <h2 className="text-2xl">{list.length} products approved for {client?.name ?? "the client"}</h2>
          <p className="mt-3 max-w-2xl text-base text-ink-700">The IC can now propose the tactical allocation. If you edit this list after sending, G3 reopens and G2 and G4 are reset, so the IC and RM approve again.</p>
          <div className="mt-8"><Button to="/ps/inbox">Back to inbox</Button></div>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader eyebrow="Product review" title="Finalise & send" subtitle="Tick or untick products one last time before sending." actions={<GateChip id="G3" state="pending" />} />
      <Stepper steps={PS_STEPS} current={1} />
      <ClientStrip client={client} />

      <Section title="Ticked products" hint={`${list.length} selected.`}>
        {all.length === 0 ? (
          <Card className="!p-8"><p className="text-base text-ink-muted">No products ticked yet. Go to Market Research, ask a question and tick products in the table.</p><div className="mt-5"><Button variant="ghost" to={`/ps/cases/${clientId}/market`}>Back to Market Research</Button></div></Card>
        ) : (
          <Table
            head={["Include", "Product", "Asset class", "Industry focus", "Confidence"]}
            rows={all.map((p) => [<input type="checkbox" className="h-5 w-5 cursor-pointer" checked={ticked.includes(p.product)} onChange={() => toggle(p.product)} aria-label={`Include ${p.product}`} />, <span className="font-semibold">{p.product}</span>, p.assetClass, p.industryFocus, `${p.confidencePct}%`])}
          />
        )}
      </Section>

      <Card className="mb-12 !p-8">
        <h2 className="text-xl">What the IC will receive</h2>
        <p className="mt-3 text-base text-ink-700">The approved product list with fees, risk ratings and citations, plus the market views behind it. The IC uses it to propose the tactical allocation for the quarterly pack.</p>
        <label className="mt-6 flex items-start gap-3 text-sm text-ink-700">
          <input type="checkbox" className="mt-0.5 h-5 w-5" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
          I have reviewed this list and confirm every product suits the client's IPS and risk limit.
        </label>
      </Card>

      <NextAction title="Approve and send" body="You are the approver for G3. The agent never approves for you." action={<Button variant="gold" disabled={!confirm || list.length === 0} onClick={() => setSent(true)}>Approve list & send to IC (G3)</Button>} />
    </div>
  );
}
