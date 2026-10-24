import { Check } from "lucide-react";

/** PM pages save automatically on every change; this only reports the last save time. `savedAt` = ISO time (from usePmProgress). */
export function AutoSaveStatus({ savedAt }: { savedAt?: string }) {
  const when = savedAt ? new Date(savedAt).toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit" }) : null;
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink-muted" role="status">
      {when ? <><Check size={14} />Auto-saved at {when}</> : "Changes are saved automatically"}
    </span>
  );
}
