import { savePmProgress } from "../../services/workflowStore";
import { ASSETS } from "./pmHelpers";

/**
 * Save the PM's SAA draft: the chosen portfolio, its weights by asset class (dynamic
 * classes), the proposal's weights (for Reset) and the legacy seven-class array that
 * older readers of `saa` still expect.
 */
export function saveSaaDraft(clientId: string, optionId: string, weights: Record<string, number>, original: Record<string, number>) {
  savePmProgress(clientId, {
    saaTemplate: optionId,
    saaWeights: weights,
    saaOriginal: original,
    saa: ASSETS.map((a) => weights[a] ?? 0),
  });
}

/** True when the draft weights differ from the proposal's. */
export function isEdited(weights?: Record<string, number>, original?: Record<string, number>): boolean {
  if (!weights || !original) return false;
  const keys = new Set([...Object.keys(weights), ...Object.keys(original)]);
  return [...keys].some((k) => Math.abs((weights[k] ?? 0) - (original[k] ?? 0)) > 1e-9);
}
