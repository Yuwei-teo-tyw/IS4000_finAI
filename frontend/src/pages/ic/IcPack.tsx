import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, CitationTag, GateChip, Loading, NextAction, PageHeader, Stepper, useAsync } from "../../components/ui";
import { BackLink, Msg, splitCitations } from "./icHelpers";
import { CASE_STEPS } from "./PortfolioInsights";

export default function IcPack() {
  const { clientId = "ser" } = useParams();
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const [texts, setTexts] = useState<Record<number, string>>({});
  const [idx, setIdx] = useState(0);
  const [reviewed, setReviewed] = useState(false);
  const [sent, setSent] = useState(false);
  const mine = (pack ?? []).filter((s) => s.owner === "ic" && s.n >= 2 && s.n <= 5);
  useEffect(() => { if (pack) setTexts(Object.fromEntries(pack.map((s) => [s.n, s.body]))); }, [pack]);
  if (!pack) return <Loading />;
  const s = mine[idx];
  const last = idx === mine.length - 1;
  const { tags } = splitCitations(texts[s.n] ?? "");

  return (
    <div>
      <PageHeader eyebrow="Quarterly review" title="IC pack sections 2 to 5" subtitle="Review each section, edit if needed, then sign." actions={<GateChip id="G2" state={sent ? "approved" : "pending"} />} />
      <Stepper steps={CASE_STEPS} current={3} />
      <Card accent className="mb-12">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-2xl">Section {s.n}. {s.title}</h2>
          <span className="flex gap-2">{s.status === "flagged" && <Badge tone="amber">Flagged</Badge>}<Badge tone="grey">{idx + 1} of {mine.length}</Badge></span>
        </div>
        {s.status === "flagged" && <div className="mb-5 rounded-md bg-surface-300 px-4 py-3 text-sm text-ink">The agent flagged a line here: check the concentration claim against the holdings before you sign.</div>}
        <textarea value={texts[s.n] ?? ""} onChange={(e) => setTexts({ ...texts, [s.n]: e.target.value })} rows={6} className="w-full rounded-md border border-ink-200 p-4 text-sm leading-relaxed text-ink-700 focus:border-ink focus:outline-none" />
        <p className="mt-4 text-xs text-ink-500">Sources: {tags.map((t) => <CitationTag key={t} tag={t} />)}</p>
        <div className="mt-6 flex gap-3">
          <Button variant="ghost" disabled={idx === 0} onClick={() => setIdx(idx - 1)}>Previous</Button>
          <Button disabled={last} onClick={() => setIdx(idx + 1)}>Next section</Button>
        </div>
      </Card>
      {last && (
        <Card className="mb-12">
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="h-5 w-5" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />I reviewed sections 2 to 5 thoroughly and sign as Investment Counsellor.</label>
        </Card>
      )}
      {sent ? <Msg ok>Signed and sent to the RM for final review (G4).</Msg> : (
        <NextAction title={last ? "Sign and send to RM" : "Review every section"} body="Agents draft; you sign. Sending needs the box ticked on the last section." action={<Button variant="gold" disabled={!last || !reviewed} onClick={() => setSent(true)}>Sign and send to RM</Button>} />
      )}
      <BackLink to={`/ic/cases/${clientId}/taa`}>Back to TAA</BackLink>
    </div>
  );
}
