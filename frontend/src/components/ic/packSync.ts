import { arcApi } from "../../services/arcApi";
import { loadIcProgress } from "../../services/workflowStore";
import { getSectionDone, loadPackDrafts, savePackDraft, setSectionDone } from "../../services/packDraftStore";
import type { AllocationRow, Holding } from "../../types/arc";

const r1 = (n: number) => Math.round(n * 10) / 10;
const sgn = (n: number) => `${n > 0 ? "+" : ""}${r1(n)}`;

function build(clientId: string, alloc: AllocationRow[]): string {
  const p = loadIcProgress(clientId);
  const taa = p.taa && p.taa.length === alloc.length ? p.taa : alloc.map((r) => r.newTaa);
  const lines: string[] = [];
  const outOfBand: string[] = [];
  alloc.forEach((r, i) => {
    const d = r1(taa[i] - r.oldTaa);
    if (Math.abs(taa[i] - r.saa) > r.band) outOfBand.push(r.assetClass);
    if (d === 0) return;
    const reason = (p.taaReasons?.[r.assetClass] ?? r.reason).replace(/^\s*[•\-*]\s*/gm, "").replace(/\s*\n\s*/g, " ").trim();
    lines.push(`• ${r.assetClass}: ${r.oldTaa}% to ${taa[i]}% (${d > 0 ? "▲" : "▼"} ${sgn(d)} pts).${reason ? ` Reason: ${reason}` : " Reason: not yet recorded by the IC."}`);
  });
  if (lines.length === 0) lines.push("• No change to the tactical asset allocation versus the previous TAA.");
  const total = taa.reduce((a, b) => a + b, 0);
  lines.push(outOfBand.length === 0 && total === 100
    ? "• Band compliance: all asset classes remain within the SAA bands and the TAA totals 100%."
    : `• Band compliance: ${outOfBand.length ? `${outOfBand.join(", ")} outside the SAA band` : "all classes within band"}${total !== 100 ? `; TAA totals ${total}%, not 100%` : ""}. IC confirms this is intended.`);
  return lines.join("\n");
}

function buildHoldings(clientId: string, holdings: Holding[]): string {
  const p = loadIcProgress(clientId);
  const lines: string[] = [];
  holdings.forEach((h) => {
    const nw = p.holdings?.[h.id];
    if (nw === undefined || r1(nw) === r1(h.weightPct)) return;
    const d = r1(nw - h.weightPct);
    lines.push(`• Holding ${h.name} (${h.assetClass}): ${h.weightPct}% to ${r1(nw)}% (${d > 0 ? "▲" : "▼"} ${sgn(d)} pts).`);
  });
  if (lines.length === 0) lines.push("• No individual holding adjustments versus the current portfolio.");
  return lines.join("\n");
}

const lastKey = (clientId: string, n = 4) => `arc.packSync.last.${n === 4 ? "" : n + "."}${clientId}`;
const lastMem = new Map<string, string>();
const seq = new Map<string, number>();

function getLast(clientId: string, n = 4): string | undefined {
  try { const v = localStorage.getItem(lastKey(clientId, n)); if (v !== null) return v; } catch { /* ignore */ }
  return lastMem.get(`${n}.${clientId}`);
}
function setLast(clientId: string, text: string, n = 4) {
  lastMem.set(`${n}.${clientId}`, text);
  try { localStorage.setItem(lastKey(clientId, n), text); } catch { /* ignore */ }
}

/** Writes pack section 4 (TAA lines + band compliance) and section 8 (Individual holding adjustments) from the IC's saved progress.
 *  Fire-and-forget; never overwrites a hand-edited draft per section, and drops stale out-of-order results. */
export function syncPackFromIc(clientId: string): void {
  const my = (seq.get(clientId) ?? 0) + 1;
  seq.set(clientId, my);
  Promise.all([arcApi.getAllocation(clientId), arcApi.getHoldings(clientId)])
    .then(([alloc, holdings]) => {
      if (seq.get(clientId) !== my) return;
      const drafts = loadPackDrafts(clientId);
      ([[4, build(clientId, alloc)], [8, buildHoldings(clientId, holdings)]] as [number, string][]).forEach(([n, text]) => {
        const current = drafts[n];
        if (current && current.trim() && current !== getLast(clientId, n)) return; // hand-edited
        // savePackDraft reopens a done section; first-time materialisation of unchanged seed content must not undo the IC's tick.
        const wasDone = !!getSectionDone(clientId)[n]?.done && !(current && current.trim());
        savePackDraft(clientId, n, text, "ic");
        if (wasDone && !getSectionDone(clientId)[n]?.done) setSectionDone(clientId, n, true, "ic");
        setLast(clientId, text, n);
      });
    })
    .catch(() => { /* ignore */ });
}
