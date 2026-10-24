import { Link } from "react-router-dom";
import { Lock } from "lucide-react";
import { Badge, sgd } from "../../components/ui";
import type { BucketSaa } from "../../services/workflowStore";
import { PA_BUCKETS, type PaBucketId, type PaBucketInputs } from "../../types/portfolio";
import { bucketStatus, isDone, isUnlocked, STATUS_LABEL, STATUS_TONE } from "./saaState";

/**
 * Liquidity -> Longevity -> Legacy -> Combined review, done in that order. A step opens only once the one
 * before it is confirmed (portfolio picked and weights confirmed), so there is one thing to do at a time.
 * Finished steps stay open, so the PM can go back; each bucket keeps its own proposal and draft.
 */
export function BucketTabs({ clientId, inputs, drafts, current }: {
  clientId: string; inputs: PaBucketInputs[]; drafts: Partial<Record<PaBucketId, BucketSaa>>; current: PaBucketId | "review";
}) {
  const tab = (active: boolean, locked: boolean) =>
    `flex min-w-[11rem] flex-1 flex-col gap-2 border-b-2 px-5 py-4 text-left ${active ? "border-hairline-strong bg-surface-100" : "border-transparent"} ${locked ? "cursor-not-allowed opacity-60" : active ? "" : "hover:bg-surface-200"}`;
  /** The first earlier bucket that is not done yet: the one holding this step back. */
  const previous = (b: PaBucketId | "review") => {
    const earlier = b === "review" ? PA_BUCKETS : PA_BUCKETS.slice(0, PA_BUCKETS.indexOf(b));
    const input = earlier.map((x) => inputs.find((i) => i.id === x)).find((i) => i && !isDone(bucketStatus(i, drafts[i.id])));
    return input?.label ?? "";
  };
  const lockedNote = (b: PaBucketId | "review") => (
    <span className="inline-flex items-center gap-2 text-xs text-ink-muted"><Lock size={12} aria-hidden />Confirm {previous(b)} first</span>
  );

  return (
    <nav className="mb-12 flex flex-wrap border-b border-ink-200" aria-label="3L buckets">
      {inputs.map((i, n) => {
        const s = bucketStatus(i, drafts[i.id]);
        const open = isUnlocked(inputs, drafts, i.id);
        const body = (
          <>
            <span className="text-lg text-ink">{n + 1}. {i.label}</span>
            <span className="text-sm text-ink-muted">{sgd(i.amount)} · {i.sharePct}% of the 3L</span>
            <span>{open ? <Badge tone={STATUS_TONE[s]}>{STATUS_LABEL[s]}</Badge> : lockedNote(i.id)}</span>
          </>
        );
        return open ? (
          <Link key={i.id} to={`/pm/requests/${clientId}/saa/${i.id}`} className={tab(current === i.id, false)} aria-current={current === i.id ? "page" : undefined}>{body}</Link>
        ) : (
          <span key={i.id} className={tab(false, true)} aria-disabled="true" title={`Confirm ${previous(i.id)} first`}>{body}</span>
        );
      })}
      {isUnlocked(inputs, drafts, "review") ? (
        <Link to={`/pm/requests/${clientId}/saa/review`} className={tab(current === "review", false)} aria-current={current === "review" ? "page" : undefined}>
          <span className="text-lg text-ink">4. Combined review</span>
          <span className="text-sm text-ink-muted">All three buckets together</span>
          <span><Badge tone="green">Ready</Badge></span>
        </Link>
      ) : (
        <span className={tab(false, true)} aria-disabled="true" title={`Confirm ${previous("review")} first`}>
          <span className="text-lg text-ink">4. Combined review</span>
          <span className="text-sm text-ink-muted">All three buckets together</span>
          <span>{lockedNote("review")}</span>
        </span>
      )}
    </nav>
  );
}
