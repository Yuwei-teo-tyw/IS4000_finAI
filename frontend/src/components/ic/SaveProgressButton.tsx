import { Save } from "lucide-react";
import { Button } from "../ui";

/** Explicit save for IC pages. `dirty` = edits not yet saved; `savedAt` = ISO time of the last save (from useIcProgress). */
export function SaveProgressButton({ onSave, dirty, savedAt }: { onSave: () => void; dirty: boolean; savedAt?: string }) {
  const when = savedAt ? new Date(savedAt).toLocaleTimeString("en-SG", { hour: "2-digit", minute: "2-digit" }) : null;
  return (
    <div className="flex items-center gap-4">
      <Button variant="secondary" onClick={onSave} disabled={!dirty}><Save size={16} />Save progress</Button>
      <span className="text-sm text-ink-muted" role="status">{dirty ? "Unsaved changes" : when ? `Saved at ${when}` : "Nothing to save yet"}</span>
    </div>
  );
}
