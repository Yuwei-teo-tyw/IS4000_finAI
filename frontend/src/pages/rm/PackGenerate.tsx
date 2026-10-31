import { useEffect, useRef, useState } from "react";
import { Button, NextAction } from "../../components/ui";
import { IpsGenerationTimeline, type GenStepState } from "../../components/documents/IpsGenerationTimeline";
import { PACK_GEN_STEPS } from "../../services/packGenerate";
import { arcApi } from "../../services/arcApi";
import { startNewPack, type GeneratedPack } from "./generatedPackStore";

const PLACEHOLDER = "Optional. For example: client interest in a sector or asset class, concerns on a holding, themes to cover, changes in circumstances, questions raised in the last meeting, areas to focus on.";

/** RM-only: optional advisory context, then AI generation of the pack with a step A-G loading state. Output is a draft the RM reviews and edits. */
export function PackGenerate({ clientId, onDone }: { clientId: string; onDone?: () => void }) {
  const [ctx, setCtx] = useState("");
  const [phase, setPhase] = useState<"idle" | "running" | "finished">("idle");
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearInterval(timer.current), []);

  const run = async () => {
    setError(null); setPhase("running"); setActive(0);
    // Advance A-F on a timer while the request runs; G completes only when the backend answers.
    timer.current = window.setInterval(() => setActive((i) => Math.min(i + 1, PACK_GEN_STEPS.length - 1)), 2600);
    try {
      const out = await arcApi.generateReviewPack(clientId, ctx.trim());
      startNewPack(clientId, { ...(out as unknown as Omit<GeneratedPack, "edits">), edits: {}, rmContext: ctx.trim() || undefined });
      window.clearInterval(timer.current);
      setActive(PACK_GEN_STEPS.length); setPhase("finished");
      window.setTimeout(() => { setPhase("idle"); onDone?.(); }, 1800);
    } catch (e) {
      window.clearInterval(timer.current);
      setError(e instanceof Error ? e.message : "The pack could not be generated."); setPhase("idle");
    }
  };

  if (phase !== "idle") {
    const sections: GenStepState[] = PACK_GEN_STEPS.map((s, i) => ({ id: s.id, state: i < active ? "done" : i === active ? "active" : "pending" }));
    return (
      <div className="mb-14 border border-hairline bg-surface-100 px-6 py-10">
        <IpsGenerationTimeline sections={sections} steps={PACK_GEN_STEPS} composeLabel={null} saved={phase === "finished"} savedLabel="Draft ready"
          title="Preparing the quarterly review pack" readyTitle="Your review pack draft is ready" modelUnavailable
          message="The agent drafts; you review, edit and decide." />
      </div>
    );
  }
  return (
    <div className="mb-14">
      <NextAction title="AI Generate Review Pack" body="Draft the pack from the active IPS, holdings and market context. You review and edit every section before it goes on."
        action={<Button onClick={run}>AI Generate Review Pack</Button>} />
      <div className="mt-6">
        <label htmlFor="rm-pack-context" className="text-[12px] uppercase tracking-[0.14em] text-ink-muted">RM context (optional)</label>
        <textarea id="rm-pack-context" value={ctx} onChange={(e) => setCtx(e.target.value)} rows={5} placeholder={PLACEHOLDER}
          className="mt-2 w-full border border-hairline bg-surface-100 p-3 text-sm font-light text-ink focus:border-ink focus:outline-none" />
        <p className="mt-2 text-xs text-ink-muted">Advisory context only. It informs the draft but never overrides the IPS, risk limits or suitability checks.</p>
        {error && <p className="mt-3 text-sm text-negative" role="alert">{error}</p>}
      </div>
    </div>
  );
}
