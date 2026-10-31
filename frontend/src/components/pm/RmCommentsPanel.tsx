import { loadPmNote, usePackHandover } from "../../services/packHandover";
import type { GeneratedPack } from "../../pages/rm/generatedPackStore";

/** SEED DATA: default RM comments shown when the RM attached no note, so the panel is never empty. */
export const SEED_RM_PACK_COMMENTS: string[] = [
  "I need this by 4 Nov 2026.",
  "The client stated that he prefers a safer approach now: less concentration in the Tech industry, more in defensive stocks and blue-chip equities, with more short-term allocation to safer assets, given the current market conditions.",
];

const lines = (t?: string) => (t ?? "").split("\n").map((l) => l.replace(/^[-*\s]+/, "").trim()).filter(Boolean);
const fmt = (iso: string) => (iso ? new Date(iso).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" }) : "");

/** Read-only RM comments for the PM, beside the pack. Source: Note to PM, else RM generation context, else seeds. */
export function RmCommentsPanel({ clientId, pack }: { clientId: string; pack: GeneratedPack }) {
  const sent = usePackHandover(clientId);
  const note = lines(loadPmNote(clientId));
  const ctx = lines(pack.rmContext);
  const items = note.length ? note : ctx.length ? ctx : SEED_RM_PACK_COMMENTS;
  const rm = "Relationship Manager";
  return (
    <section aria-label="Comments from RM" className="border border-negative bg-surface p-6">
      <h2 className="text-[18px] font-light text-ink">Comments from RM</h2>
      <span className="mt-2 block h-px w-8 bg-brand" />
      <div className="mt-5 flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center border border-hairline-strong text-[12px] text-ink-muted">RM</span>
        <span className="text-sm text-ink">{rm}<span className="block text-[12px] text-ink-muted">{fmt(sent?.sentAt ?? "")}</span></span>
      </div>
      <ul className="mt-5 flex list-disc flex-col gap-3 pl-5 text-sm font-light leading-6 text-negative">
        {items.map((c) => <li key={c}>{c}</li>)}
      </ul>
    </section>
  );
}
