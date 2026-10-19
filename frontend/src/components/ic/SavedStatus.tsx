import { useEffect, useRef } from "react";

/**
 * Debounced auto-save for IC pages. Runs `save` ~400ms after the last edit (`token` changes while `dirty`),
 * and flushes once on unmount so moving to another page never loses an edit.
 */
export function useAutoSave(save: () => void, dirty: boolean, token: unknown, delay = 400) {
  const saveRef = useRef(save);
  const dirtyRef = useRef(dirty);
  saveRef.current = save;
  dirtyRef.current = dirty;
  useEffect(() => {
    if (!dirty) return;
    const t = window.setTimeout(() => saveRef.current(), delay);
    return () => window.clearTimeout(t);
  }, [dirty, token, delay]);
  useEffect(() => () => { if (dirtyRef.current) saveRef.current(); }, []);
}

/** Subtle muted status, top-right of an IC page. Replaces the old Save button. */
export function SavedStatus({ dirty, savedAt }: { dirty: boolean; savedAt?: string }) {
  const text = dirty ? "Saving" : savedAt ? "Saved" : "";
  return <p className="mb-2 h-5 text-right text-xs text-ink-muted" role="status" aria-live="polite">{text}</p>;
}
