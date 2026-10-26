/** Pure helpers for the Geneva IPS conversation history (kept free of React so they can be unit-tested). */
export const HISTORY_CAP = 100;

export const HISTORY_UNAVAILABLE_NOTICE = "History unavailable. This conversation continues for this session but is not saved.";
export const HISTORY_TRUNCATED_NOTICE = `This conversation is limited to ${HISTORY_CAP} messages, so the oldest message was removed from the saved history.`;
export const NO_MODEL_NOTICE = "No model is available right now, so the IPS could not be drafted. No draft was produced.";

/** The notice to show after loading or appending, or null. `truncated` comes from the backend flag. */
export function historyNotice(state: { failed?: boolean; truncated?: boolean }): string | null {
  if (state.failed) return HISTORY_UNAVAILABLE_NOTICE;
  if (state.truncated) return HISTORY_TRUNCATED_NOTICE;
  return null;
}

/** Stance label chip text for an allocation answer. */
export const STANCE_CHIP: Record<string, string> = { agree: "Agrees", disagree: "Disagrees", partial: "Partly agrees", info: "Information" };
/** A change may be applied only when the agent agrees (fully or partly) and proposes at least one change. */
export const canApplyChange = (stance: string, changes: readonly string[]) => (stance === "agree" || stance === "partial") && changes.length > 0;

/** Text for the model chip. `unavailable` shows no model name at all (nothing produced the draft). */
export function modelChipLabel(model?: string | null, unavailable?: boolean): string | null {
  if (unavailable) return null;
  const m = model?.trim();
  return m ? `Model: ${m}` : null;
}
