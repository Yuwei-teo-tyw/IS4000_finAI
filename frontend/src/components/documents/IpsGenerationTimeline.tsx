import { modelChipLabel } from "../../services/ipsChatHistory";
import { IPS_GEN_SECTIONS, type IpsGenSectionId } from "../../types/arc";

export type IpsGenStepState = "pending" | "active" | "done";
export interface IpsGenStep { id: IpsGenSectionId; state: IpsGenStepState; note?: string }
/** Generic step state for other generation runs (e.g. the review pack A-G). */
export interface GenStepState { id: string; state: IpsGenStepState; note?: string }

/** Prestige step wording, one per backend section; the last row ("Composing the IPS") is the save/assemble phase. */
const STEP_LABEL: Record<IpsGenSectionId, string> = {
  demographics: "Reading meeting notes",
  philosophy: "Distilling investment philosophy",
  goals: "Clarifying goals and objectives",
  risk: "Establishing risk profile",
  allocation: "Selecting strategies",
};
const COMPOSE_LABEL = "Composing the IPS";

const CSS = `
.ipsg{--g:var(--brand);--g-soft:color-mix(in srgb,var(--brand) 22%,transparent);font-family:var(--font-body)}
@keyframes ipsg-rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes ipsg-breathe{0%,100%{opacity:.6;transform:scale(.97)}50%{opacity:1;transform:scale(1.03)}}
@keyframes ipsg-shimmer{0%{background-position:130% 0}100%{background-position:-130% 0}}
@keyframes ipsg-sweep{0%{transform:translateY(-120%)}100%{transform:translateY(120%)}}
@keyframes ipsg-draw{from{stroke-dashoffset:24}to{stroke-dashoffset:0}}
@keyframes ipsg-halo{0%{opacity:0;transform:scale(.6)}40%{opacity:.9}100%{opacity:0;transform:scale(1.7)}}
.ipsg-step{animation:ipsg-rise 1.1s cubic-bezier(.22,1,.36,1) both}
.ipsg-mark{animation:ipsg-breathe 5.5s ease-in-out infinite}
.ipsg-shimmer{background-image:linear-gradient(100deg,var(--ink) 0%,var(--ink) 40%,var(--g) 50%,var(--ink) 60%,var(--ink) 100%);background-size:250% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;animation:ipsg-shimmer 4.2s linear infinite}
.ipsg-fill{transition:transform 1.4s cubic-bezier(.22,1,.36,1)}
.ipsg-sweepbar{position:relative;overflow:hidden}
.ipsg-sweepbar::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent,color-mix(in srgb,var(--brand) 85%,white),transparent);animation:ipsg-sweep 1.8s cubic-bezier(.45,0,.2,1) 1 both}
.ipsg-check{stroke-dasharray:24;animation:ipsg-draw .9s cubic-bezier(.22,1,.36,1) .2s both}
.ipsg-halo{animation:ipsg-halo 1.8s cubic-bezier(.22,1,.36,1) both}
@media (prefers-reduced-motion:reduce){
  .ipsg-step,.ipsg-mark,.ipsg-shimmer,.ipsg-sweepbar::after,.ipsg-check,.ipsg-halo{animation:none!important}
  .ipsg-shimmer{background-image:none;color:var(--ink);-webkit-text-fill-color:var(--ink)}
  .ipsg-fill{transition:none}
}`;

const BRAND = "var(--brand)";

function Mark({ done }: { done: boolean }) {
  return (
    <span className="relative inline-flex size-16 items-center justify-center" aria-hidden>
      {done && <span className="ipsg-halo absolute inset-0 rounded-full border" style={{ borderColor: BRAND }} />}
      <span className={`inline-flex size-16 items-center justify-center rounded-full border bg-surface-100 ${done ? "" : "ipsg-mark"}`} style={{ borderColor: done ? BRAND : "var(--hairline-strong)" }}>
        <img src="/ubs-logo.png" alt="" className="ubs-logo h-7 w-auto" />
      </span>
    </span>
  );
}

/**
 * Luxury progress view of the IPS generation. Vertical brand-red hairline rail, steps reveal one by one, Geneva mark breathes,
 * and when every step is done a fine red sweep and a drawn check close the run. All motion stops under prefers-reduced-motion.
 * `saved` shows the Saved chip once the backend has stored the generated IPS; `modelUnavailable` hides the producer.
 */
export function IpsGenerationTimeline({ sections, message, model, saved, modelUnavailable, steps, composeLabel, title, readyTitle, savedLabel }: {
  sections: GenStepState[]; message?: string; model?: string; saved?: boolean; modelUnavailable?: boolean;
  /** Optional custom steps (default: the IPS sections). */
  steps?: { id: string; label: string }[];
  /** Label of the final assemble row; null hides it. Default "Composing the IPS". */
  composeLabel?: string | null;
  title?: string; readyTitle?: string; savedLabel?: string;
}) {
  const STEPS: { id: string; label: string }[] = steps ?? IPS_GEN_SECTIONS.map((s) => ({ id: s.id, label: STEP_LABEL[s.id] }));
  const rawOf = (id: string): IpsGenStepState => sections.find((x) => x.id === id)?.state ?? "pending";
  // Ordered progress index: number of leading steps that are done. Later "done" flags never count until all earlier steps are done.
  let doneCount = 0;
  while (doneCount < STEPS.length && rawOf(STEPS[doneCount].id) === "done") doneCount++;
  const allDone = doneCount === STEPS.length;
  const complete = allDone && !!saved;
  const compose = composeLabel === undefined ? COMPOSE_LABEL : composeLabel;
  const extra = compose === null ? 0 : 1;
  const progressIdx = complete ? STEPS.length + extra : doneCount;
  const total = STEPS.length + extra;
  const progress = progressIdx / total;
  const chip = modelChipLabel(model, modelUnavailable);
  const rows = [
    ...STEPS.map((s) => ({ id: s.id, label: s.label, note: sections.find((x) => x.id === s.id)?.note })),
    ...(compose === null ? [] : [{ id: "compose", label: compose, note: undefined as string | undefined }]),
  ].map((r, i) => ({ ...r, state: (i < progressIdx ? "done" : i === progressIdx ? "active" : "pending") as IpsGenStepState }));
  return (
    <div className="ipsg mx-auto max-w-xl py-4">
      <style>{CSS}</style>
      <div className="flex flex-col items-center text-center">
        <Mark done={complete} />
        <h3 className="mt-6 text-[32px] font-light leading-[1.2] text-ink">{complete ? (readyTitle ?? "Your IPS is ready") : (title ?? "Preparing the Investment Policy Statement")}</h3>
        <span aria-hidden className="mt-4 block h-px w-24" style={{ background: BRAND }} />
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2" aria-live="polite">
          {chip && <span className="inline-block border px-3 py-1 text-[12px] tracking-[0.08em] text-ink" style={{ borderColor: BRAND }}>{chip}</span>}
          {complete && <span className="inline-block border px-3 py-1 text-[12px] uppercase tracking-[0.14em] text-ink" style={{ borderColor: BRAND }}>{savedLabel ?? "Saved"}</span>}
        </div>
      </div>
      <div className="relative mt-10 pl-12">
        <span aria-hidden className="absolute bottom-3 left-[15px] top-3 w-px" style={{ background: "var(--hairline)" }} />
        <span aria-hidden className="absolute bottom-3 left-[15px] top-3 w-px">
          <span className={`ipsg-fill absolute inset-0 origin-top ${complete ? "ipsg-sweepbar" : ""}`} style={{ background: BRAND, transform: `scaleY(${progress})` }} />
        </span>
        <ol className="space-y-7">
          {rows.map((r, i) => (
            <li key={r.id} className="ipsg-step relative" style={{ animationDelay: `${i * 140}ms` }} aria-current={r.state === "active" ? "step" : undefined}>
              <span className="absolute -left-12 top-0 inline-flex size-[31px] items-center justify-center rounded-full border bg-surface-100 transition-colors duration-700"
                style={{ borderColor: r.state === "pending" ? "var(--hairline)" : BRAND }}>
                {r.state === "done" ? <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke={BRAND} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-label="Done"><path className="ipsg-check" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
                  : r.state === "active" ? <span aria-hidden className="ipsg-mark size-2 rounded-full" style={{ background: BRAND }} /> : null}
              </span>
              <p className={`text-[20px] font-light leading-[31px] transition-colors duration-700 ${r.state === "pending" ? "text-ink-muted" : "text-ink"}`}>
                {r.state === "active" ? <span className="ipsg-shimmer">{r.label}</span> : r.label}
              </p>
              {r.note && <p className="mt-1 text-[14px] font-light text-ink-muted">{r.note}</p>}
            </li>
          ))}
        </ol>
      </div>
      {message && <p className="mt-10 text-center text-[15px] font-light text-ink-muted" aria-live="polite">{message}</p>}
    </div>
  );
}
