import { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { FileText, UploadCloud } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Button, Card, GateChip, Loading, PageHeader, Stepper, useAsync } from "../../components/ui";
import { onboardingSteps } from "./rmShared";

export default function OnboardingNotes() {
  const { clientId = "" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [files, setFiles] = useState<string[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  if (!client) return <Loading />;

  const add = (list: FileList | null) => {
    if (list) setFiles((f) => [...f, ...Array.from(list).map((x) => x.name)]);
  };

  return (
    <div>
      <PageHeader eyebrow={client.name} title="Upload meeting notes" subtitle="Drop in your notes from the first client meeting. The agent will read them and prepare a summary for you to confirm."
        actions={<GateChip id="G1" state="not_started" />} />
      <Stepper steps={onboardingSteps} current={0} />

      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
        className={`mb-10 flex cursor-pointer flex-col items-center gap-4 rounded-lg border-2 border-dashed px-8 py-24 text-center transition ${over ? "border-hairline-strong bg-surface-300" : "border-ink-200 bg-surface-100"}`}
      >
        <UploadCloud size={48} className="text-ink" />
        <p className="text-2xl text-ink">Drag and drop your notes here</p>
        <p className="text-sm text-ink-500">or click to browse. PDF, Word or plain text.</p>
        <input ref={input} type="file" multiple hidden onChange={(e) => add(e.target.files)} />
      </div>

      {files.length > 0 && (
        <Card className="mb-10">
          <ul className="flex flex-col gap-3">
            {files.map((f, i) => (
              <li key={i} className="flex items-center gap-3 text-sm"><FileText size={18} className="text-ink-muted" />{f}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="flex justify-end">
        <Button to={`/rm/clients/${clientId}/onboarding/summary`}>Continue to summary</Button>
      </div>
    </div>
  );
}
