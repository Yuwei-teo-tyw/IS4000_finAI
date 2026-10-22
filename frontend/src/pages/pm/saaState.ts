import { savePmBucket, type BucketSaa } from "../../services/workflowStore";
import { PA_BUCKETS, type PaBucketId, type PaBucketInputs } from "../../types/portfolio";

/** Where a 3L bucket's SAA stands. "stale" = the 3L amount changed after the proposal was built. */
export type BucketStatus = "empty" | "not_started" | "stale" | "proposed" | "selected" | "confirmed";

export const STATUS_LABEL: Record<BucketStatus, string> = {
  empty: "No amount", not_started: "Not started", stale: "Re-run needed", proposed: "Pick a portfolio",
  selected: "Check weights", confirmed: "Confirmed",
};
export const STATUS_TONE: Record<BucketStatus, "grey" | "amber" | "red" | "sky" | "green"> = {
  empty: "grey", not_started: "grey", stale: "red", proposed: "amber", selected: "sky", confirmed: "green",
};

export function bucketStatus(input: PaBucketInputs, draft?: BucketSaa): BucketStatus {
  if (input.amount <= 0) return "empty";
  if (!draft?.requestId) return "not_started";
  if (draft.amount !== input.amount) return "stale";
  if (!draft.optionId) return "proposed";
  return draft.confirmed ? "confirmed" : "selected";
}

/** A bucket is done when it is confirmed, or has no money to invest. */
export const isDone = (s: BucketStatus) => s === "confirmed" || s === "empty";

/** The first bucket that still needs the PM, else null (everything is ready for the combined review). */
export function nextBucket(inputs: PaBucketInputs[], drafts: Partial<Record<PaBucketId, BucketSaa>> = {}, after?: PaBucketId): PaBucketId | null {
  const start = after ? PA_BUCKETS.indexOf(after) + 1 : 0;
  const order = [...PA_BUCKETS.slice(start), ...PA_BUCKETS.slice(0, start)];
  return order.find((b) => {
    const input = inputs.find((i) => i.id === b);
    return input && !isDone(bucketStatus(input, drafts[b]));
  }) ?? null;
}

/**
 * Buckets are done in order: Liquidity, then Longevity, then Legacy, then the combined review. A bucket
 * opens only once every bucket before it is confirmed (or has no money), so the PM never has the next
 * bucket and an unfinished Edit weights open at the same time.
 */
export function isUnlocked(inputs: PaBucketInputs[], drafts: Partial<Record<PaBucketId, BucketSaa>> = {}, target: PaBucketId | "review"): boolean {
  const before = target === "review" ? PA_BUCKETS : PA_BUCKETS.slice(0, PA_BUCKETS.indexOf(target));
  return before.every((b) => {
    const input = inputs.find((i) => i.id === b);
    return !input || isDone(bucketStatus(input, drafts[b]));
  });
}

/** Where the PM should be: the first bucket not yet done, else the combined review. */
export const currentStep = (inputs: PaBucketInputs[], drafts: Partial<Record<PaBucketId, BucketSaa>> = {}): PaBucketId | "review" =>
  PA_BUCKETS.find((b) => !isUnlocked(inputs, drafts, b) || !isDone(bucketStatus(inputs.find((i) => i.id === b)!, drafts[b]))) ?? "review";

/** Whole-portfolio class weights: each bucket's weights scaled by its amount. */
export function combinedWeights(inputs: PaBucketInputs[], drafts: Partial<Record<PaBucketId, BucketSaa>> = {}): Record<string, number> {
  const total = inputs.reduce((s, i) => s + (drafts[i.id]?.weights ? i.amount : 0), 0);
  const out: Record<string, number> = {};
  for (const i of inputs) {
    const w = drafts[i.id]?.weights;
    if (!w || !total) continue;
    for (const [ac, pct] of Object.entries(w)) out[ac] = (out[ac] ?? 0) + (pct * i.amount) / total;
  }
  return Object.fromEntries(Object.entries(out).map(([ac, v]) => [ac, Math.round(v * 100) / 100]));
}

/** Select a portfolio for one bucket (resets its weights to the proposal's and its confirmation). */
export function selectBucketPortfolio(clientId: string, bucket: PaBucketId, optionId: string, optionName: string, weights: Record<string, number>) {
  savePmBucket(clientId, bucket, { optionId, optionName, weights, original: weights, confirmed: false });
}

/** Save edited weights for one bucket; any change needs confirming again. */
export function saveBucketWeights(clientId: string, bucket: PaBucketId, weights: Record<string, number>) {
  savePmBucket(clientId, bucket, { weights, confirmed: false });
}

/** True when the draft weights differ from the proposal's. */
export function isEdited(weights?: Record<string, number>, original?: Record<string, number>): boolean {
  if (!weights || !original) return false;
  const keys = new Set([...Object.keys(weights), ...Object.keys(original)]);
  return [...keys].some((k) => Math.abs((weights[k] ?? 0) - (original[k] ?? 0)) > 1e-9);
}
