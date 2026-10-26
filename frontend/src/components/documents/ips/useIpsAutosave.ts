import { useEffect, useRef, useState } from "react";

export type AutosaveState = "idle" | "saving" | "saved" | "error";

/**
 * Debounced autosave. `signature` is a string that changes whenever the draft changes.
 * With `immediate`, the first ready render saves once without waiting (a freshly generated IPS appears saved with no click).
 */
export function useIpsAutosave({ ready, signature, save, immediate = false, delay = 1500 }: {
  ready: boolean; signature: string; save: () => Promise<void>; immediate?: boolean; delay?: number;
}): AutosaveState {
  const [state, setState] = useState<AutosaveState>("idle");
  const last = useRef<string | null>(null);
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    if (!ready) return;
    const first = last.current === null;
    if (last.current === signature) return;
    if (first && !immediate) { last.current = signature; return; }  // baseline: nothing edited yet
    last.current = signature;
    const run = async () => {
      setState("saving");
      try { await saveRef.current(); setState("saved"); } catch { setState("error"); }
    };
    if (first) { void run(); return; }
    const t = setTimeout(() => void run(), delay);
    return () => clearTimeout(t);
  }, [ready, signature, immediate, delay]);
  return state;
}
