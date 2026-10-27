import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Eye, Pencil, Sparkles, Trash2 } from "lucide-react";
import { Badge, Button, Card, Loading, Section, useAsync, useAsyncResult } from "../../components/ui";
import { useRole } from "../../layouts/AppShell";
import { DocumentPreviewModal } from "../../components/documents/DocumentPreviewModal";
import { IpsDocument } from "../../components/documents/IpsDocument";
import { SortByDate, type SortOrder } from "../../components/documents/SortByDate";
import { IpsGenerationTimeline } from "../../components/documents/IpsGenerationTimeline";
import { dismissIpsRun, startIpsGeneration, useIpsRun } from "../../services/ipsGenStore";
import { arcApi } from "../../services/arcApi";
import { activateIps, setActiveIps, useActiveIps, useIpsReturned } from "../../services/workflowStore";
import IpsDraft from "../rm/IpsDraft";
import { IpsStatusBadge } from "../rm/IpsSendUi";
import { formatSentAt, useIpsSendStatus, type IpsStatusLabel } from "../rm/ipsSendUtil";
import type { IpsGenerated, IpsVersion } from "../../types/arc";

const statusTone = { Active: "green", Superseded: "grey", Draft: "gold" } as const;
const iconBtn = "inline-flex size-10 items-center justify-center rounded-sm border border-ink text-ink hover:bg-surface-300";

function VersionCard({ v, clientName, canEdit, onEdit, onDelete, isActive, canActivate, onActivate, returned }: { v: IpsVersion; clientName: string; canEdit: boolean; onEdit: () => void; onDelete?: () => void; isActive: boolean; canActivate: boolean; onActivate: () => void; returned: boolean }) {
  const [preview, setPreview] = useState(false);
  const editable = canEdit;
  return (
    <Card className="!p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-2xl">IPS v{v.version}</h3>
          {(v.clientName || clientName) && <p className="mt-1 text-sm text-ink-muted">{v.clientName || clientName}</p>}
        </div>
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
            <span title={v.status === "Draft" && !returned ? "Draft versions cannot be made active until the PM returns the IPS." : "Make this the IPS the AI assistant uses"}>
              <Button variant="ghost" disabled={v.status === "Draft" && !returned} onClick={onActivate}>Make active</Button>
            </span>
          )}
          {editable && <button type="button" aria-label="Edit" title="Edit" onClick={onEdit} className={iconBtn}><Pencil size={18} /></button>}
          {onDelete && <button type="button" aria-label="Delete IPS" title="Delete IPS" onClick={onDelete} className={iconBtn}><Trash2 size={18} /></button>}
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
  const [creating, setCreating] = useState(false);  // a brand-new, empty IPS (no version issued yet)
  const [generated, setGenerated] = useState<IpsGenerated | undefined>(undefined);
  const [editVersion, setEditVersion] = useState<number | undefined>(undefined);
  const [deleteError, setDeleteError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {  // Geneva applied an allocation change to a saved IPS while no editor was open
    const h = (e: Event) => { if ((e as CustomEvent<{ clientId?: string }>).detail?.clientId === clientId) setReload((n) => n + 1); };
    window.addEventListener("ips-versions-changed", h);
    return () => window.removeEventListener("ips-versions-changed", h);
  }, [clientId]);
  const { data: versions, error: loadError } = useAsyncResult(() => arcApi.getIpsHistory(clientId), [clientId, editing, reload]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [order, setOrder] = useState<SortOrder>("latest");
  const sorted = useMemo(
    () => [...(versions ?? [])].sort((a, b) => (order === "latest" ? b.issuedOn.localeCompare(a.issuedOn) : a.issuedOn.localeCompare(b.issuedOn))),
    [versions, order],
  );
  const { status: sendStatus } = useIpsSendStatus(clientId);
  const explicit = useActiveIps(clientId);
  const returned = useIpsReturned(clientId);
  const activeVersion = explicit ?? [...(versions ?? [])].filter((v) => v.status !== "Draft").sort((a, b) => b.version - a.version)[0]?.version ?? null;
  const name = clientName || client?.name || "Client";
  const removeVersion = async (v: IpsVersion) => {
    if (!window.confirm(`Delete IPS v${v.version} for ${name}? This cannot be undone.`)) return;
    setDeleteError("");
    try { await arcApi.deleteIps(clientId, v.version); setReload((n) => n + 1); }
    catch (e) { setDeleteError(e instanceof Error ? e.message : "The IPS could not be deleted."); }
  };
  const run = useIpsRun(clientId);
  const gen = run ? { steps: run.steps, message: run.message, error: run.status === "error" ? run.error : undefined, model: run.model, modelMessage: run.modelMessage, saved: run.saved, unavailable: run.unavailable } : null;
  const startGeneration = () => { startIpsGeneration(clientId, name); };
  // Finished runs: show the completion flourish (timestamp based, so it also works after returning from another page or tab), then reveal the result once.
  useEffect(() => {
    if (!run || run.status !== "done" || !run.finishedAt) return;
    const finishedAt = run.finishedAt;
    const calm = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const hold = run.saved ? (calm ? 600 : 2600) : 0;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      if (run.saved) setReload((n) => n + 1);
      else if (run.draft) { setGenerated(run.draft); setCreating(true); setEditing(true); }
      dismissIpsRun(clientId);
    };
    const check = () => { if (Date.now() - finishedAt >= hold) finish(); };
    const timer = setTimeout(finish, Math.max(0, hold - (Date.now() - finishedAt)));
    document.addEventListener("visibilitychange", check);
    check();
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", check); };
  }, [run, clientId]);
  if (editing) {
    return (
      <div>
        <Button variant="ghost" onClick={() => { setEditing(false); setCreating(false); setGenerated(undefined); setEditVersion(undefined); }}><ArrowLeft size={16} /> Back To IPS Versions</Button>
        <div className="mt-8"><IpsDraft embedded clientId={clientId} blank={creating} generated={generated} version={editVersion} /></div>
      </div>
    );
  }
  if (loadError) {
    return (
      <Section title="IPS versions">
        <div className="border border-hairline bg-surface-100 p-8" role="alert">
          <p className="text-base text-ink">The IPS versions could not be loaded.</p>
          <p className="mt-2 text-sm text-ink-muted">Check your connection and try again.</p>
          <div className="mt-5"><Button variant="ghost" onClick={() => setReload((n) => n + 1)}>Retry</Button></div>
        </div>
      </Section>
    );
  }
  if (!versions) return <Loading />;
  return (
    <Section title="IPS versions">
      {versions.length === 0 ? (
        <Card className="!p-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <p className="text-base text-ink-muted">No IPS yet. {role === "rm" ? "Use the pencil to create one, or let Geneva draft it from the meeting notes." : "It will appear here once the RM generates one."}</p>
            {role === "rm" && !gen && (
              <div className="flex items-center gap-3">
                <Button variant="ghost" onClick={startGeneration}><Sparkles size={16} /> AI IPS generation</Button>
                <button type="button" aria-label="Create IPS" title="Create IPS" onClick={() => { setCreating(true); setEditing(true); }} className={iconBtn}><Pencil size={18} /></button>
              </div>
            )}
          </div>
          {gen && (
            <div className="mt-10">
              <IpsGenerationTimeline sections={gen.steps} message={gen.error ? undefined : gen.message} model={gen.model} saved={gen.saved} modelUnavailable={!gen.model && !!gen.modelMessage} />
              {!gen.model && gen.modelMessage && !gen.error && <p className="mt-4 text-center text-sm text-ink-muted" role="status">{gen.modelMessage}</p>}
              {gen.error && (
                <div className="mt-8 flex flex-col items-center gap-4 text-center" role="alert">
                  <p className="text-base text-ink">{gen.error}</p>
                  <div className="flex gap-3">
                    <Button variant="ghost" onClick={startGeneration}>Retry</Button>
                    <Button variant="ghost" onClick={() => dismissIpsRun(clientId)}>Dismiss</Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      ) : (
        <div>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            {sendStatus && sendStatus.status !== "No IPS" ? <IpsStatusBadge status={sendStatus.status as IpsStatusLabel} detail={sendStatus.status !== "Draft" ? formatSentAt(sendStatus.sentAt) || undefined : undefined} /> : <span />}
            <SortByDate value={order} onChange={setOrder} />
          </div>
          {deleteError && <p role="alert" className="mb-4 text-sm text-negative">{deleteError}</p>}
          <div className="flex flex-col gap-8">
            {sorted.map((v) => <VersionCard key={v.version} v={v} clientName={name} canEdit={role === "rm" && (v.status === "Active" || v.status === "Draft")} onEdit={() => { setEditVersion(v.status === "Draft" ? v.version : undefined); setEditing(true); }} onDelete={role === "rm" ? () => removeVersion(v) : undefined} isActive={v.version === activeVersion} canActivate={role === "rm"} onActivate={() => { if (v.status === "Draft") activateIps(clientId, v.version); else setActiveIps(clientId, v.version); }} returned={returned} />)}
          </div>
        </div>
      )}
    </Section>
  );
}
