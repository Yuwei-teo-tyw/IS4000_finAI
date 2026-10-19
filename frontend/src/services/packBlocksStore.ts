/** Block-based pack section content (text / image / chart / table), per client + section. Same reactive sessionStorage pattern as packDraftStore; legacy section text is kept in sync. */
import { useSyncExternalStore } from "react";
import type { PackBlock, Role } from "../types/arc";
import { BLOCKS_EVENT, blocksKey, loadPackDrafts, loadRawBlocks, savePackDraft, writeRawBlocks } from "./packDraftStore";

export const newBlockId = () => `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

/** Concatenation of all text blocks: the legacy string body. */
export const blocksToText = (blocks: PackBlock[]): string =>
  blocks.flatMap((b) => (b.type === "text" && b.text.trim() ? [b.text.trim()] : [])).join("\n\n");

const cache = new Map<string, { raw: string | null; draft: string; value: PackBlock[] }>();
const fallbackIds = new Map<string, string>();

/** Blocks for a section. Nothing saved: one text block derived from the legacy draft text (stable id). */
export function getSectionBlocks(clientId: string, n: number, fallbackText?: string): PackBlock[] {
  let raw: string | null = null;
  try { raw = sessionStorage.getItem(blocksKey(clientId)); } catch { /* ignore */ }
  const draft = loadPackDrafts(clientId)[n] ?? fallbackText ?? "";
  const ck = `${clientId}:${n}`;
  const c = cache.get(ck);
  if (c && c.raw === raw && c.draft === draft) return c.value;
  const saved = raw ? loadRawBlocks(clientId)[n] : undefined;
  let value: PackBlock[];
  if (saved && saved.length) value = saved;
  else {
    let id = fallbackIds.get(ck);
    if (!id) { id = newBlockId(); fallbackIds.set(ck, id); }
    value = [{ id, type: "text", text: draft }];
  }
  cache.set(ck, { raw, draft, value });
  return value;
}

/** Saves blocks and mirrors the concatenated text blocks into the legacy draft (history, done-reopen, packSync readers keep working). */
export function saveSectionBlocks(clientId: string, n: number, blocks: PackBlock[], by?: Role) {
  writeRawBlocks(clientId, { ...loadRawBlocks(clientId), [n]: blocks });
  savePackDraft(clientId, n, blocksToText(blocks), by, { skipBlocks: true, force: true });
}

function subscribe(fn: () => void) {
  window.addEventListener(BLOCKS_EVENT, fn); window.addEventListener("geneva:packdraft", fn);
  return () => { window.removeEventListener(BLOCKS_EVENT, fn); window.removeEventListener("geneva:packdraft", fn); };
}

/** Reactive blocks. `fallbackText` (e.g. the mock section body) seeds the single text block when no draft exists. */
export function useSectionBlocks(clientId: string, n: number, fallbackText?: string): PackBlock[] {
  return useSyncExternalStore(
    subscribe,
    () => getSectionBlocks(clientId, n, fallbackText),
  );
}
