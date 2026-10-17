import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, useAsync } from "../../components/ui";
import { Tagged, packToSections, fmtDate } from "./rmShared";
import { ContributionsPanel } from "../../components/export/ContributionsPanel";
import { ExportActions } from "../../components/export/ExportActions";

export default function PackReview({ embedded = false, clientId: clientIdProp }: { embedded?: boolean; clientId?: string }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const pack = useAsync(() => arcApi.getPack(clientId), [clientId]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [active, setActive] = useState(1);
  const [body1, setBody1] = useState("");
  const [editing, setEditing] = useState(false);
  const [approved, setApproved] = useState(false);
  useEffect(() => {
    const s = pack?.find((x) => x.n === 1);
    if (s) setBody1(s.body);
  }, [pack]);
  if (!pack) return <Loading />;
  const sections = packToSections(pack, { 1: body1 });
  const s = pack.find((x) => x.n === active)!;
  const body = s.n === 1 ? body1 : s.body;
  const flagged = s.status === "flagged";

  return (
    <div>
      {embedded ? (
        <div className="mb-10 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h2 className="text-3xl">Review pack</h2>
            <p className="mt-2 text-base text-ink-500">Read each of the 8 sections. You can edit section 1; the rest belong to IC and PS.</p>
          </div>
          <GateChip id="G4" state={approved ? "approved" : "pending"} />
        </div>
      ) : (
        <PageHeader eyebrow="Gate G4" title="Review the pack" subtitle="Read each of the 8 sections. You can edit section 1; the rest belong to IC and PS."
          actions={<GateChip id="G4" state={approved ? "approved" : "pending"} />} />
      )}
      <NextAction title={approved ? "Pack approved" : "Approve the final pack"} body={approved ? "G4 is approved. You can export the PDF." : "Approving G4 releases the PDF. The agent never approves for you."}
        action={approved ? undefined : <Button variant="gold" onClick={() => setApproved(true)}>Approve G4</Button>} />

      <ContributionsPanel sections={sections} />
      <div className="mb-12 flex flex-wrap justify-end">
        <ExportActions docTitle="Quarterly Review Pack" clientName={client?.name ?? clientId} version={approved ? "Approved (G4)" : "Awaiting G4"} date={fmtDate(new Date().toISOString())}
          sections={sections} exportBlocked={!approved} blockedReason="Final export unlocks once G4 is approved." />
      </div>

      <div className="grid gap-10 md:grid-cols-[260px_1fr]">
        <nav className="flex flex-col gap-2">
          {pack.map((x) => (
            <button key={x.n} onClick={() => { setActive(x.n); setEditing(false); }}
              className={`cursor-pointer rounded-md px-4 py-3 text-left text-sm ${active === x.n ? "bg-surface-inverse text-ink-inverse" : "bg-surface-100 text-ink-700 border border-ink-200"}`}>
              {x.n}. {x.title}
              {x.status === "flagged" && <AlertTriangle size={14} className="ml-2 inline text-ink-muted" />}
            </button>
          ))}
        </nav>

        <Card className="min-h-96">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-2xl">{s.n}. {s.title}</h2>
            <div className="flex gap-2">
              {s.gate && <GateChip id={s.gate} state={s.status === "approved" ? "approved" : s.status === "ready" ? "pending" : "not_started"} />}
              {s.owner === "ic" && <Badge tone="green">IC reviewed thoroughly</Badge>}
            </div>
          </div>
          {flagged && (
            <div className="mb-6 flex items-start gap-3 rounded-md bg-surface-300 p-5 text-sm text-ink">
              <AlertTriangle size={18} className="mt-0.5 shrink-0" />Flagged line: please read this section closely before approving.
            </div>
          )}
          {editing && s.n === 1 ? (
            <textarea value={body1} onChange={(e) => setBody1(e.target.value)} rows={8}
              className="w-full rounded-md border border-ink-200 p-5 text-base leading-relaxed outline-none focus:border-ink" />
          ) : (
            <p className="text-base leading-loose text-ink-700"><Tagged text={body} /></p>
          )}
          {s.n === 1 && !approved && (
            <div className="mt-6"><Button variant="ghost" onClick={() => setEditing(!editing)}>{editing ? "Done" : "Edit section"}</Button></div>
          )}
        </Card>
      </div>
    </div>
  );
}
