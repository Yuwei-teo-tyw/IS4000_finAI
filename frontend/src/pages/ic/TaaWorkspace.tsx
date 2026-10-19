import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { syncPackFromIc } from "../../components/ic/packSync";
import { TaaPie } from "../../components/ic/TaaPie";
import { SavedStatus, useAutoSave } from "../../components/ic/SavedStatus";
import { saveIcProgress, useIcProgress } from "../../services/workflowStore";
import { Badge, BulletList, DirectionArrow, BulletTextarea, Button, CitationTag, GateChip, Loading, NextAction, PageHeader, Section, useAsync } from "../../components/ui";
import { IcStepper } from "../../components/ic/IcStepper";
import { BackLink, BULLET_PLACEHOLDER, NumInput, splitCitations, sum } from "./icHelpers";

const toFirst = (t: string) => splitCitations(t.split("\n").map((l) => l.replace(/^\s*[•\-*]\s*/, "").trim()).find(Boolean) ?? "").text;

export default function TaaWorkspace() {
  const { clientId = "jfr" } = useParams();
  const navigate = useNavigate();
  const rows = useAsync(() => arcApi.getAllocation(clientId), [clientId]);
  const [vals, setVals] = useState<number[]>([]);
  const progress = useIcProgress(clientId);
  const saved = progress.taa;
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => { if (rows) setReasons(Object.fromEntries(rows.map((r) => [r.assetClass, progress.taaReasons?.[r.assetClass] ?? r.reason]))); }, [rows]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (rows) setVals(saved && saved.length === rows.length ? saved : rows.map((r) => r.newTaa)); }, [rows]); // eslint-disable-line react-hooks/exhaustive-deps
  const baseNow = rows ? (saved && saved.length === rows.length ? saved : rows.map((r) => r.newTaa)) : [];
  const dirtyNow = !!rows && vals.length > 0 && (vals.some((v, i) => v !== baseNow[i]) || rows.some((r) => (reasons[r.assetClass] ?? r.reason) !== (progress.taaReasons?.[r.assetClass] ?? r.reason)));
  useAutoSave(() => { saveIcProgress(clientId, { taa: vals, taaReasons: reasons }); syncPackFromIc(clientId); }, dirtyNow, [vals, reasons]);
  if (!rows) return <Loading />;

  const out = rows.filter((r, i) => Math.abs(vals[i] - r.saa) > r.band);
  const total = sum(vals);

  return (
    <div>
      <SavedStatus dirty={dirtyNow} savedAt={progress.savedAt} />
      <IcStepper clientId={clientId} current={2} />
      <BackLink to={`/ic/cases/${clientId}/market-health`}>Back to market view and portfolio health</BackLink>
      <PageHeader eyebrow="Quarterly review" title="Tactical asset allocation" actions={<GateChip id="G2" state="pending" />} />
      <div className="mb-8 border border-hairline border-l-4 border-l-brand bg-[color-mix(in_srgb,var(--brand)_5%,var(--surface-100))] p-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-ink-muted">Before you set the TAA</p>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-ink marker:text-ink-muted">
          <li>Review the client's IPS and profile.</li>
          <li>Run market research.</li>
          <li>Analyse portfolio strengths and weaknesses. The AI assistant can help.</li>
        </ul>
      </div>
      {(total !== 100 || out.length > 0) && (
        <div role="alert" className="mb-8 flex items-start gap-4 border border-hairline bg-surface-100 p-6">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-ink" aria-hidden />
          <div className="space-y-1 text-sm">
            <p className="font-semibold">Check before you continue</p>
            {total !== 100 && <p className="text-ink-muted">The total is {total}%, not 100%.</p>}
            {out.length > 0 && <p className="text-ink-muted">Outside the SAA band: {out.map((r) => r.assetClass).join(", ")}.</p>}
            <p className="text-ink-muted">Confirm before continuing.</p>
          </div>
        </div>
      )}
      <Section title="Old vs new TAA">
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[260px_1fr]">
          <TaaPie labels={rows.map((r) => r.assetClass)} values={vals} />
          <div className="min-w-0">
          <div className="overflow-x-auto rounded-lg border border-hairline bg-surface-100">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-200 text-ink-muted">
                <tr>{["Class", "SAA", "Old TAA", "New TAA", "Direction", "Band check", "Reason"].map((h) => <th key={h} className="px-4 py-4 text-xs font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const inBand = Math.abs(vals[i] - r.saa) <= r.band;
                  const d = (vals[i] ?? 0) - r.oldTaa;
                  const changed = d !== 0;
                  const reason = reasons[r.assetClass] ?? r.reason;
                  const isOpen = !!open[r.assetClass];
                  const { tags } = splitCitations(reason);
                  const first = toFirst(reason);
                  return [
                    <tr key={r.assetClass} className="border-t border-hairline">
                      <td className="px-4 py-5 align-top">{r.assetClass}</td>
                      <td className="px-4 py-5 align-top">{r.saa}%</td>
                      <td className="px-4 py-5 align-top">{r.oldTaa}%</td>
                      <td className="px-4 py-5 align-top"><NumInput value={vals[i] ?? 0} suffix="%" width="w-24" onChange={(n) => setVals(vals.map((v, j) => (j === i ? n : v)))} /></td>
                      <td className="px-4 py-5 align-top">
                        <DirectionArrow d={d} />
                      </td>
                      <td className="px-4 py-5 align-top"><Badge tone={inBand ? "green" : "red"}>{inBand ? "Within ±5" : "Out of band"}</Badge></td>
                      <td className="px-4 py-5 align-top">
                        <button type="button" aria-expanded={isOpen} onClick={() => setOpen({ ...open, [r.assetClass]: !isOpen })} className="flex w-full max-w-xs items-start gap-2 text-left text-sm">
                          {isOpen ? <ChevronDown size={16} className="mt-0.5 shrink-0" aria-hidden /> : <ChevronRight size={16} className="mt-0.5 shrink-0" aria-hidden />}
                          <span className="min-w-0">
                            {reason.trim() ? <span className="line-clamp-1 text-ink-muted">{first}</span> : <span className="text-ink-muted">{changed ? "Reason required" : "Edit reason"}</span>}
                            {!isOpen && tags.map((t) => <CitationTag key={t} tag={t} />)}
                          </span>
                        </button>
                        {changed && !reason.trim() && !isOpen && <p className="mt-1 pl-6 text-xs text-negative">Reason required</p>}
                      </td>
                    </tr>,
                    isOpen && (
                      <tr key={`${r.assetClass}-edit`} className="border-t border-hairline bg-surface-200">
                        <td colSpan={7} className="px-6 py-6">
                          <label className="mb-2 block text-xs font-semibold text-ink-muted" htmlFor={`why-${i}`}>Your reason for {r.assetClass}</label>
                          <BulletTextarea id={`why-${i}`} rows={7} value={reason} placeholder={BULLET_PLACEHOLDER} onChange={(t) => setReasons({ ...reasons, [r.assetClass]: t })} />
          {changed && !reason.trim() && <p className="mt-2 text-xs text-negative">Reason required</p>}
                          <div className="mt-3"><BulletList text={reason} empty="" /></div>
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </div>
          </div>
        </div>
      </Section>
      <div className="mt-10" />
      <NextAction title="Next: review client holdings"
        action={<Button variant="primary" onClick={() => { navigate(`/ic/cases/${clientId}/holdings`); }}>Review Client Individual Holdings</Button>} />
    </div>
  );
}
