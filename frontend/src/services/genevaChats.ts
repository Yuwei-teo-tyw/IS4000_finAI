/** IS-98: named Geneva chats, persisted in the backend per RM (header X-RM-Id). Global per RM, separate from the per-client IPS chat. */
import { chatOwnerId } from "./arcApi";

const BASE = `${((import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "")}/geneva/chats`;
const headers = () => ({ "Content-Type": "application/json", "X-RM-Id": chatOwnerId() });

export const CHAT_HISTORY_UNAVAILABLE = "Chat history is unavailable. You can keep chatting in this session, but it will not be saved.";
export const DEFAULT_CHAT_TITLE = "New chat";
export const TITLE_DISPLAY_MAX = 32;

export interface SavedChat { id: string; title: string; createdAt: string; updatedAt: string }
export interface SavedMessage { role: "user" | "assistant"; text: string }

/** Null means the history database (or the backend) could not be reached. */
async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${BASE}${path}`, { headers: headers(), ...init });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch { return null; }
}

export const listSavedChats = async (): Promise<SavedChat[] | null> => (await call<{ chats: SavedChat[] }>(""))?.chats ?? null;
export const loadSavedMessages = async (id: string): Promise<SavedMessage[] | null> =>
  (await call<{ messages: SavedMessage[] }>(`/${encodeURIComponent(id)}/messages`))?.messages ?? null;
/** Saves one turn; resolves with the chat's current (possibly newly generated) title, or null when it could not be saved. */
export const saveChatMessage = async (id: string, role: "user" | "assistant", text: string): Promise<string | null> =>
  (await call<{ title: string }>(`/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify({ role, text }) }))?.title ?? null;

/** Sidebar label: long titles end in an ellipsis (the full title goes in the tooltip). */
export const shortTitle = (t: string): string => (t.length > TITLE_DISPLAY_MAX ? `${t.slice(0, TITLE_DISPLAY_MAX - 1).trimEnd()}…` : t);
/** Short date beside a title so equal titles can be told apart. */
export const chatDate = (iso: string | number): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};
