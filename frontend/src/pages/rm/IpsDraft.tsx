import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Check, Lock, X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Button, Card, GateChip, Loading, NextAction, PageHeader, Stepper, useAsync, BulletTextarea, BulletList } from "../../components/ui";
import { onboardingSteps, ipsToSections, fmtDate } from "./rmShared";
import { sendIpsToIc, useIpsSent } from "../../services/workflowStore";
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
  const sent = !!useIpsSent(clientId);
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
      <div className="mb-10 grid gap-8 md:grid-cols-[300px_1fr] md:items-start">
        <Card className="!p-5">
          <h2 className="text-base">Sections</h2>
          <p className="mt-1 text-xs text-ink-muted">{sections.filter((x) => x.complete).length} of {sections.length} complete</p>
          <p className="mt-3 flex items-center gap-2 text-xs text-ink-muted"><span className="inline-block h-3 w-5 border border-brand" />Sections you fill in</p>
          <nav className="mt-4 flex flex-col gap-2">
            {parts.map((x, idx) => {
              const done = sections.find((y) => y.n === x.part)?.complete;
              return (
                <button key={x.part} onClick={() => setActive(x.part)}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-sm border px-4 py-3.5 text-left text-sm transition-colors duration-300 ${active === x.part ? "bg-surface-inverse text-ink-inverse" : "bg-surface-100 text-ink-700 hover:bg-surface-300"} ${RM_PARTS.includes(x.part) ? "border-brand" : active === x.part ? "border-transparent" : "border-hairline"}`}>
                  <span className="min-w-0">{idx + 1}. {x.title}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    {done ? <Check size={16} className={`shrink-0 ${active === x.part ? "text-ink-inverse" : "text-positive"}`} aria-label="Done" /> : <X size={16} className={`shrink-0 ${active === x.part ? "text-ink-inverse" : "text-negative"}`} aria-label="Not done" />}
                  </span>
                </button>
              );
            })}
          </nav>
        </Card>

        <Card className={`min-h-96 !p-10 ${RM_PARTS.includes(active) ? "!border-brand" : ""}`}>
          <div key={active} className="animate-geneva-in space-y-8">
            <div className="min-w-0">
              <h2 className="text-[28px] font-light tracking-tight">{parts.findIndex((x) => x.part === active) + 1}. {p.title}</h2>
              {RM_PARTS.includes(active) && !sent && <p className="mt-2 text-xs uppercase tracking-[0.14em] text-brand">You fill in this section</p>}
              {(!RM_PARTS.includes(active) || sent) && <p className="mt-2 flex items-center gap-1.5 text-xs uppercase tracking-[0.14em] text-ink-muted"><Lock size={12} />{RM_PARTS.includes(active) ? "Locked" : "To be filled by the Investment Counsellor"}</p>}
            </div>
            {editable ? (
              <BulletTextarea value={text[active] ?? ""} onChange={(v) => { setText({ ...text, [active]: v }); setSaved(false); }} rows={8} />
            ) : (
              <div className="text-[17px] leading-8 text-ink-700">
                {(text[active] ?? "").trim() ? <BulletList text={text[active]} className="!text-base" /> : <p className="text-sm text-ink-muted">Not yet completed.</p>}
              </div>
            )}
          </div>
        </Card>
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
          {polished && <Button onClick={() => sendIpsToIc(clientId)}>Send to IC</Button>}
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
