import { useRef, useState } from "react";
import { CheckCircle2, FileText, UploadCloud, X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Button, Card, Loading, useAsync } from "../../components/ui";
import { useClient } from "../../components/client/useClient";
import { MeetingNotesList } from "../../components/documents/MeetingNotesList";

const ACCEPT = ".pdf,.docx,.txt,.m4a";

export default function ClientUploadNotes() {
  const { clientId, client } = useClient();
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<number | null>(null);
  const [drag, setDrag] = useState(false);
  const [version, setVersion] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const notes = useAsync(() => arcApi.getMeetingNotes(clientId), [clientId, version]);

  const add = (list: FileList | null) => {
    if (!list) return;
    const ok = Array.from(list).filter((f) => ACCEPT.split(",").some((e) => f.name.toLowerCase().endsWith(e)));
    setFiles((p) => [...p, ...ok]);
    setDone(null);
  };

  const upload = async () => {
    setBusy(true);
    const n = files.length;
    for (const f of files) await arcApi.uploadMeetingNote(clientId, f.name);
    setFiles([]);
    setDone(n);
    setBusy(false);
    setVersion((v) => v + 1);
  };

  return (
    <div className="flex flex-col gap-12">
      <Card className="!p-8">
        <h2 className="text-2xl font-light">Meeting Notes</h2>
        <p className="mt-2 text-sm text-ink-muted">PDF, DOCX, TXT or M4A recordings.</p>
        <div
          role="button" tabIndex={0} data-clickable
          onClick={() => input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
          className={`mt-8 flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed px-8 py-14 text-center transition ${drag ? "border-ink bg-surface-300" : "border-hairline-strong bg-surface-200"}`}
        >
          <UploadCloud size={32} className="text-ink-muted" />
          <p className="text-ink">Drag and drop files here, or click to browse</p>
          <p className="text-xs text-ink-muted">.pdf  .docx  .txt  .m4a</p>
          <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
        </div>

        {files.length > 0 && (
          <ul className="mt-8 flex flex-col gap-3">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-4 rounded-sm border border-hairline px-5 py-3 text-sm">
                <span className="inline-flex items-center gap-3 text-ink"><FileText size={16} className="text-ink-muted" />{f.name}</span>
                <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((p) => p.filter((_, j) => j !== i))} className="text-ink-muted hover:text-ink"><X size={16} /></button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-8 flex flex-wrap items-center gap-6">
          <Button variant="gold" onClick={upload} disabled={!files.length || busy}>{busy ? "Uploading…" : "Upload Notes"}</Button>
          {done !== null && (
            <p className="inline-flex items-center gap-2 text-sm font-semibold text-positive">
              <CheckCircle2 size={18} /> {done} {done === 1 ? "file" : "files"} uploaded successfully
            </p>
          )}
        </div>
      </Card>

      <section>
        <h2 className="mb-6 text-2xl font-light">Notes history</h2>
        {!notes ? <Loading /> : notes.length === 0 ? (
          <p className="text-sm text-ink-muted">No meeting notes yet.</p>
        ) : (
          <MeetingNotesList notes={notes} clientName={client?.name} onChanged={() => setVersion((v) => v + 1)} />
        )}
      </section>
    </div>
  );
}
