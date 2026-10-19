import { useMemo, useState } from "react";
import { ArrowLeft, Eye, Pencil } from "lucide-react";
import { Badge, Button, Card, Loading, Section, useAsync } from "../../components/ui";
import { useRole } from "../../layouts/AppShell";
import { DocumentPreviewModal } from "../../components/documents/DocumentPreviewModal";
import { IpsDocument } from "../../components/documents/IpsDocument";
import { SortByDate, type SortOrder } from "../../components/documents/SortByDate";
import { arcApi } from "../../services/arcApi";
import { activateClient, setActiveIps, useActiveIps, useIpsReturned } from "../../services/workflowStore";
import IpsDraft from "../rm/IpsDraft";
import type { IpsVersion } from "../../types/arc";

const statusTone = { Active: "green", Superseded: "grey", Draft: "gold" } as const;
const iconBtn = "inline-flex size-10 items-center justify-center rounded-sm border border-ink text-ink hover:bg-surface-300";

function VersionCard({ v, clientName, canEdit, onEdit, isActive, canActivate, onActivate, returned }: { v: IpsVersion; clientName: string; canEdit: boolean; onEdit: () => void; isActive: boolean; canActivate: boolean; onActivate: () => void; returned: boolean }) {
  const [preview, setPreview] = useState(false);
  const editable = canEdit;
  return (
    <Card className="!p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-2xl">IPS v{v.version}</h3>
        <div className="flex flex-wrap items-center gap-3">
          {isActive && (
            <span className="inline-flex items-center gap-2 rounded-sm border border-hairline px-3 py-1 text-sm text-ink">
              <span aria-hidden className="size-2 rounded-full bg-green-600" /> Active
            </span>
          )}
          <Badge tone={v.status === "Active" && !isActive ? "grey" : statusTone[v.status]}>{v.status === "Active" && !isActive ? "Approved" : v.status}</Badge>
        </div>
      </div>
      <p className="mt-2 text-sm text-ink-muted">Issued {v.issuedOn} · Author: {v.author}</p>
      <p className="mt-5 max-w-3xl text-base leading-relaxed text-ink">{v.summary}</p>
      {(
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button type="button" aria-label="Preview" title="Preview" onClick={() => setPreview(true)} className={iconBtn}><Eye size={18} /></button>
          {canActivate && !isActive && (
            <span title={v.status === "Draft" && !returned ? "Draft versions cannot be made active until the IC returns the IPS." : "Make this the IPS the AI assistant uses"}>
              <Button variant="ghost" disabled={v.status === "Draft" && !returned} onClick={onActivate}>Make active</Button>
            </span>
          )}
          {editable && <button type="button" aria-label="Edit" title="Edit" onClick={onEdit} className={iconBtn}><Pencil size={18} /></button>}
        </div>
      )}
      {preview && (
        <DocumentPreviewModal title={`IPS v${v.version}`} onClose={() => setPreview(false)}>
          <IpsDocument version={v} clientName={clientName} />
        </DocumentPreviewModal>
      )}
    </Card>
  );
}

export function IpsHistory({ clientId, clientName = "" }: { clientId: string; clientName?: string }) {
  const role = useRole();
  const [editing, setEditing] = useState(false);
  const versions = useAsync(() => arcApi.getIpsHistory(clientId), [clientId, editing]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [order, setOrder] = useState<SortOrder>("latest");
  const sorted = useMemo(
    () => [...(versions ?? [])].sort((a, b) => (order === "latest" ? b.issuedOn.localeCompare(a.issuedOn) : a.issuedOn.localeCompare(b.issuedOn))),
    [versions, order],
  );
  const explicit = useActiveIps(clientId);
  const returned = useIpsReturned(clientId);
  const activeVersion = explicit ?? [...(versions ?? [])].filter((v) => v.status !== "Draft").sort((a, b) => b.version - a.version)[0]?.version ?? null;
  const name = clientName || client?.name || "Client";
  if (editing) {
    return (
      <div>
        <Button variant="ghost" onClick={() => setEditing(false)}><ArrowLeft size={16} /> Back To IPS Versions</Button>
        <div className="mt-8"><IpsDraft embedded clientId={clientId} /></div>
      </div>
    );
  }
  if (!versions) return <Loading />;
  return (
    <Section title="IPS versions">
      {versions.length === 0 ? (
        <Card className="!p-8"><p className="text-base text-ink-muted">No IPS issued yet.</p></Card>
      ) : (
        <div>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <span />
            <SortByDate value={order} onChange={setOrder} />
          </div>
          <div className="flex flex-col gap-8">
            {sorted.map((v) => <VersionCard key={v.version} v={v} clientName={name} canEdit={role === "rm" && (v.status === "Active" || v.status === "Draft")} onEdit={() => setEditing(true)} isActive={v.version === activeVersion} canActivate={role === "rm"} onActivate={() => { setActiveIps(clientId, v.version); activateClient(clientId); }} returned={returned} />)}
          </div>
        </div>
      )}
    </Section>
  );
}
