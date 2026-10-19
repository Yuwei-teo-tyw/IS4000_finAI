import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Lock } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, Stepper, useAsync, BulletTextarea } from "../../components/ui";
import { onboardingSteps, ipsToSections, fmtDate } from "./rmShared";
import { ContributionsPanel } from "../../components/export/ContributionsPanel";
import { IpsDocument } from "../../components/documents/IpsDocument";
import { ProfessionaliseButton } from "../../components/geneva/ProfessionaliseButton";
import { getChatContext } from "../../services/chatContextStore";
import { ExportActions } from "../../components/export/ExportActions";

const RM_PARTS = [1, 3, 5, 6];

export default function IpsDraft({ embedded = false, clientId: clientIdProp }: { embedded?: boolean; clientId?: string }) {
  const params = useParams();
  const clientId = clientIdProp ?? params.clientId ?? "";
  const nav = useNavigate();
  const parts = useAsync(() => arcApi.getIps(clientId), [clientId]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [active, setActive] = useState(1);
  const [text, setText] = useState<Record<number, string>>({});
  const [sent, setSent] = useState(false);
  const [saved, setSaved] = useState(false);
  const [stage, setStage] = useState<"edit" | "polish">("edit");
  const [busy, setBusy] = useState(false);
  const [polished, setPolished] = useState(false);
  useEffect(() => {
    if (parts) setText(Object.fromEntries(parts.map((p) => [p.part, p.body])));
  }, [parts]);
  if (!parts) return <Loading />;
  const p = parts.find((x) => x.part === active)!;
  const sections = ipsToSections(parts, text);
  const subtitle = `You fill ${RM_PARTS.map((n) => parts.find((x) => x.part === n)?.title ?? "").filter(Boolean).join(", ")}.`;
  const editable = RM_PARTS.includes(active) && !sent;

  const runPolish = async () => {
    setBusy(true);
    const out = await arcApi.professionalise({ clientId, role: "rm", context: "ips", chat: getChatContext(clientId, "rm"),
      items: RM_PARTS.map((n) => ({ id: String(n), label: parts.find((x) => x.part === n)?.title ?? `Part ${n}`, text: text[n] ?? "" })) });
    setText((t) => ({ ...t, ...Object.fromEntries(out.map((o) => [Number(o.id), o.text])) }));
    setBusy(false); setPolished(true);
  };
  const bottomOnly = stage === "polish" && !sent;

  return (
    <div>
      {!bottomOnly && (<>
      {embedded ? (
        <div className="mb-10 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h2 className="text-3xl">Edit IPS</h2>
            <p className="mt-2 text-base text-ink-500">{subtitle}</p>
          </div>
          <GateChip id="G1" state={sent ? "pending" : "not_started"} />
        </div>
      ) : (
        <>
          <PageHeader eyebrow="Investment Policy Statement" title="Draft the IPS" subtitle={subtitle}
            actions={<GateChip id="G1" state={sent ? "pending" : "not_started"} />} />
          <Stepper steps={onboardingSteps} current={sent ? 3 : 2} />
        </>
      )}

      </>)}
      <div className="mb-10 flex flex-col gap-8 lg:flex-row lg:items-start">
      <aside className="w-full shrink-0 lg:sticky lg:top-6 lg:w-80">
        <ContributionsPanel sections={sections} className="" />
      </aside>
      <div className="min-w-0 flex-1">
      <div className="mb-8 flex flex-wrap gap-3">
        {parts.map((x) => (
          <button key={x.part} onClick={() => setActive(x.part)}
            className={`cursor-pointer rounded-full px-5 py-2 text-sm font-semibold ${active === x.part ? "bg-surface-inverse text-ink-inverse" : "bg-surface-300 text-ink-700"}`}>
            {x.title}
          </button>
        ))}
      </div>

      <Card>
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 className="min-w-0 break-words text-2xl">{p.title}</h2>
          {!RM_PARTS.includes(active) ? <Badge tone="grey"><Lock size={12} className="mr-1" />To be filled by IC</Badge>
            : sent ? <Badge tone="grey"><Lock size={12} className="mr-1" />Locked</Badge> : <Badge tone="gold">You edit</Badge>}
        </div>
        {RM_PARTS.includes(active) ? (
          <div>
            <BulletTextarea value={text[active] ?? ""} disabled={!editable} onChange={(v) => { setText({ ...text, [active]: v }); setSaved(false); }} rows={8} />
          </div>
        ) : (
          <p className="rounded-md bg-surface-200 p-8 text-center text-sm text-ink-500">To be filled by the Investment Counsellor.</p>
        )}
      </Card>
      </div>
      </div>

      <div className="mb-10 flex flex-wrap justify-end">
        <ExportActions docTitle="Investment Policy Statement" clientName={client?.name ?? clientId} version="Draft" date={fmtDate(new Date().toISOString())} sections={sections}
          document={<IpsDocument clientId={clientId} clientName={client?.name ?? clientId} version={{ version: (client?.ipsVersion ?? 0) + 1, issuedOn: new Date().toISOString().slice(0, 10), status: "Draft", author: "Isabel", summary: "", parts: parts.map((x) => ({ ...x, body: text[x.part] ?? x.body })) }} />} />
      </div>

      {sent && embedded ? (
        <Card><p className="text-base text-ink-700">Sent to the Investment Counsellor. Your sections are now locked.</p></Card>
      ) : sent ? (
        <NextAction title="Sent to the Investment Counsellor" body="Sections are locked until the IC returns the IPS."
          action={<Button to={`/rm/clients/${clientId}/ips-approval`}>Preview IC return</Button>} />
      ) : stage === "polish" ? (
        <div className="flex flex-wrap items-center justify-end gap-3">
          <ProfessionaliseButton onClick={runPolish} loading={busy} disabled={polished} label="Professionalise" />
          <Button variant="secondary" onClick={() => setStage("edit")}>Back</Button>
          {polished && <Button onClick={() => setSent(true)}>Send to IC</Button>}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-3">
          {embedded && saved && <span className="text-sm text-ink-500" role="status">Saved</span>}
          {embedded
            ? <Button onClick={() => setSaved(true)}>Save</Button>
            : <Button variant="secondary" onClick={() => nav(-1)}>Back</Button>}
          <Button onClick={() => { setPolished(false); setStage("polish"); }}>Review wording and send</Button>
        </div>
      )}
    </div>
  );
}
