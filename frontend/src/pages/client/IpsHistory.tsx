import { useMemo, useState } from "react";
import { ArrowLeft, Eye, Pencil } from "lucide-react";
import { Badge, Button, Card, Loading, Section, useAsync } from "../../components/ui";
import { useRole } from "../../layouts/AppShell";
import { DocumentPreviewModal } from "../../components/documents/DocumentPreviewModal";
import { IpsDocument } from "../../components/documents/IpsDocument";
import { SortByDate, type SortOrder } from "../../components/documents/SortByDate";
import { arcApi } from "../../services/arcApi";
import IpsDraft from "../rm/IpsDraft";
import type { IpsVersion } from "../../types/arc";

const statusTone = { Active: "green", Superseded: "grey", Draft: "gold" } as const;
const iconBtn = "inline-flex size-10 items-center justify-center rounded-sm border border-ink text-ink hover:bg-surface-300";

function VersionCard({ v, clientName, canEdit, onEdit }: { v: IpsVersion; clientName: string; canEdit: boolean; onEdit: () => void }) {
  const [preview, setPreview] = useState(false);
  const editable = canEdit;
  return (
    <Card className="!p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-2xl">IPS v{v.version}</h3>
        <Badge tone={statusTone[v.status]}>{v.status}</Badge>
      </div>
      <p className="mt-2 text-sm text-ink-muted">Issued {v.issuedOn} · Author: {v.author}</p>
      <p className="mt-5 max-w-3xl text-base leading-relaxed text-ink">{v.summary}</p>
      {(
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button type="button" aria-label="Preview" title="Preview" onClick={() => setPreview(true)} className={iconBtn}><Eye size={18} /></button>
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
    <Section title="IPS versions" hint="Every Investment Policy Statement issued for this client.">
      {versions.length === 0 ? (
        <Card className="!p-8"><p className="text-base text-ink-muted">No IPS has been issued yet. It will appear here once the first IPS is approved.</p></Card>
      ) : (
        <div>
          <div className="mb-6 flex justify-end"><SortByDate value={order} onChange={setOrder} /></div>
          <div className="flex flex-col gap-8">
            {sorted.map((v) => <VersionCard key={v.version} v={v} clientName={name} canEdit={role === "rm" && (v.status === "Active" || v.status === "Draft")} onEdit={() => setEditing(true)} />)}
          </div>
        </div>
      )}
    </Section>
  );
}
