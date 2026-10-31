import { useEffect, useState } from "react";
import { Eye, Trash2 } from "lucide-react";
import { Badge, Button, Card, Section } from "../../components/ui";
import { PackBackBubble } from "../../components/rm/PackBackBubble";
import { ackPackReturned, usePackReturnedUnseen } from "../../services/packHandover";
import { PackGenerate } from "./PackGenerate";
import { GeneratedPackView } from "./GeneratedPackView";
import { discardHistoryPack, getPackHistory, loadGeneratedPack, openHistoryPack, packStatusLabel, usePackStates, type PackStatusLabel } from "./generatedPackStore";

const tone: Record<PackStatusLabel, "gold" | "amber" | "grey" | "green"> = { Draft: "gold", "Sent to PM": "amber", "Returned by PM": "grey", Approved: "green" };
const iconBtn = "inline-flex size-10 items-center justify-center rounded-sm border border-ink text-ink hover:bg-surface-300 disabled:cursor-not-allowed disabled:opacity-40";
const when = (iso?: string) => (iso ? new Date(iso).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Unknown date");

interface Row { id: string | null; generatedAt?: string; status: PackStatusLabel; current: boolean }

/** RM Review Pack tab for a Monitoring client: AI generation, then the pack history. Same layout as the IPS tab. */
export function PackHistory({ clientId, clientName }: { clientId: string; clientName: string }) {
  const states = usePackStates();
  const st = states[clientId];
  const [open, setOpen] = useState(false);
  // Keep the bubble on screen for this visit, then mark the hand-back as seen so the Client Book bubble clears.
  const unseen = usePackReturnedUnseen(clientId);
  const [showBack, setShowBack] = useState(false);
  useEffect(() => { if (unseen) { setShowBack(true); ackPackReturned(clientId); } }, [unseen, clientId]);
  const withPm = st?.handover?.status === "sent_to_pm";
  const current = st?.pack ? { pack: loadGeneratedPack(clientId) ?? { ...st.pack, edits: st.edits ?? {} }, edits: st.edits ?? {} } : null;
  if (open && current) return (
    <div>
      <GeneratedPackView clientId={clientId} clientName={clientName} pack={{ ...current.pack, edits: current.edits }} onBack={() => setOpen(false)} />
    </div>
  );
  const rows: Row[] = [
    ...(st?.pack ? [{ id: null, generatedAt: st.pack.generated_at, status: packStatusLabel(st), current: true }] : []),
    ...[...getPackHistory(st)].reverse().map((h) => ({ id: h.id, generatedAt: h.pack.generated_at, status: packStatusLabel(h), current: false })),
  ];
  const total = rows.length;
  return (
    <div>
      <div className="mb-10 flex flex-wrap items-center gap-4"><h2 className="text-3xl">Review pack</h2>{showBack && <PackBackBubble clientId={clientId} force text="The Portfolio Manager has returned this pack" />}</div>
      {withPm
        ? <p className="mb-14 text-sm text-ink-muted">The current pack is with the Portfolio Manager. Withdraw it before generating a new one.</p>
        : <PackGenerate clientId={clientId} onDone={() => setOpen(true)} />}
      {total > 0 && (
        <Section title="Review pack history">
          <div className="flex flex-col gap-8">
            {rows.map((r, i) => (
              <Card key={r.id ?? "current"} className="!p-8">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-2xl">Review pack v{total - i}</h3>
                    <p className="mt-1 text-sm text-ink-muted">Generated {when(r.generatedAt)}{r.current ? " · Current" : ""}</p>
                  </div>
                  <Badge tone={tone[r.status]}>{r.status}</Badge>
                </div>
                <div className="mt-6 flex flex-wrap items-center gap-3">
                  <button type="button" aria-label="Open" title={r.current || !withPm ? "Open" : "Withdraw the pack with the Portfolio Manager first"} disabled={!r.current && withPm}
                    onClick={() => { if (!r.current && r.id) openHistoryPack(clientId, r.id); setOpen(true); }} className={iconBtn}><Eye size={18} /></button>
                  {!r.current && r.id && r.status === "Draft" && (
                    <button type="button" aria-label="Discard draft" title="Discard draft" onClick={() => { if (window.confirm("Discard this draft pack? This cannot be undone.")) discardHistoryPack(clientId, r.id!); }} className={iconBtn}><Trash2 size={18} /></button>
                  )}
                  {r.current && r.status === "Sent to PM" && <Button variant="ghost" onClick={() => setOpen(true)}>Open to withdraw</Button>}
                </div>
              </Card>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
