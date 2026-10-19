import { useMemo, useState } from "react";
import { Eye } from "lucide-react";
import { Badge, Card, Loading, PageHeader, Section, useAsync } from "../../components/ui";
import { DocumentPreviewModal } from "../../components/documents/DocumentPreviewModal";
import { SortByDate, type SortOrder } from "../../components/documents/SortByDate";
import { arcApi } from "../../services/arcApi";
import type { HouseView } from "../../types/arc";

const iconBtn = "inline-flex size-10 items-center justify-center rounded-sm border border-ink text-ink hover:bg-surface-300";

function RecordCard({ r }: { r: HouseView }) {
  const [preview, setPreview] = useState(false);
  return (
    <Card className="!p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-2xl">House View {r.month}</h3>
        <Badge tone={r.file ? "green" : "grey"}>{r.file ? "Available" : "Placeholder"}</Badge>
      </div>
      <p className="mt-2 text-sm text-ink-muted">Issued {r.issuedOn} · Author: {r.author}</p>
      <div className="mt-6">
        <button type="button" aria-label="Preview" title="Preview" onClick={() => setPreview(true)} className={iconBtn}><Eye size={18} /></button>
      </div>
      {preview && (
        <DocumentPreviewModal title={`House View ${r.month}`} onClose={() => setPreview(false)}>
          {r.file ? (
            <iframe src={r.file} title={`House View ${r.month}`} className="h-[70vh] w-full border border-hairline bg-surface-100" />
          ) : (
            <div className="border border-hairline bg-surface-100 p-16 text-center">
              <p className="text-xl">House View {r.month}</p>
              <p className="mt-3 text-base text-ink-muted">Not uploaded yet.</p>
            </div>
          )}
        </DocumentPreviewModal>
      )}
    </Card>
  );
}

/** Standalone, not client-specific: usable by RM, IC and PS. */
export default function HouseViewRecords() {
  const records = useAsync(() => arcApi.getHouseViews(""), []);
  const [order, setOrder] = useState<SortOrder>("latest");
  const sorted = useMemo(
    () => [...(records ?? [])].sort((a, b) => (order === "latest" ? b.issuedOn.localeCompare(a.issuedOn) : a.issuedOn.localeCompare(b.issuedOn))),
    [records, order],
  );
  if (!records) return <Loading />;
  return (
    <div>
      <PageHeader eyebrow="Market research" title="House View Records" />
      <Section title="House view records" hint="Past monthly house views.">
        <div className="mb-6 flex justify-end"><SortByDate value={order} onChange={setOrder} /></div>
        <div className="flex flex-col gap-8">{sorted.map((r) => <RecordCard key={r.id} r={r} />)}</div>
      </Section>
    </div>
  );
}
