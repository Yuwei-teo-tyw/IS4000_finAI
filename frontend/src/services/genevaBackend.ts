/**
 * Geneva chat <-> LangGraph backend (backend/app/agents/graph.py, WebSocket /agents/langgraph).
 * Only `arcApi.ts` imports this; components go through arcApi.
 *
 * One short-lived WebSocket per turn: connect with the chat's session id
 * (the backend keeps the conversation per session) and `greet=false` (no intro
 * frame), send one payload, resolve on the first reply, close. A paused
 * money-moving action is resumed the same way with a confirmation payload.
 */
import type { GenevaArticle, GenevaContext, GenevaReply } from "../types/arc";

const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");
const WS_URL = `${API_BASE.replace(/^http/, "ws")}/agents/langgraph`;
/** A cold Market Researcher run can take ~60-90s; leave headroom. */
const TURN_TIMEOUT_MS = 150_000;
const RUN_ID = /mr_\d{8}T\d{6}Z_[0-9a-f]{6}/;

export class GenevaBackendError extends Error {
  kind: "UNREACHABLE" | "TIMEOUT" | "CLOSED" | "INVALID_RESPONSE";
  constructor(kind: GenevaBackendError["kind"], message: string) {
    super(message);
    this.kind = kind;
  }
}

/** A fresh backend session per Geneva chat, so chats never share history. */
export function newSessionId(role: string, clientId: string): string {
  return `geneva-${role}-${clientId}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

type Payload = { message: string; context: GenevaContext } | { action: "confirm_financial_action"; approved: boolean };

function toReply(data: unknown): GenevaReply {
  if (!data || typeof data !== "object" || typeof (data as { message?: unknown }).message !== "string") {
    throw new GenevaBackendError("INVALID_RESPONSE", "The assistant returned an unexpected response.");
  }
  const d = data as { message: string; requires_confirmation?: boolean; pending_action?: GenevaReply["pendingAction"] };
  return {
    text: d.message,
    runId: d.message.match(RUN_ID)?.[0] ?? null,
    requiresConfirmation: Boolean(d.requires_confirmation),
    pendingAction: d.pending_action ?? null,
  };
}

function sendTurn(sessionId: string, payload: Payload): Promise<GenevaReply> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn: () => void) => { if (!settled) { settled = true; clearTimeout(timer); fn(); } };
    let ws: WebSocket;
    try {
      ws = new WebSocket(`${WS_URL}?session_id=${encodeURIComponent(sessionId)}&greet=false`);
    } catch {
      reject(new GenevaBackendError("UNREACHABLE", `Geneva's assistant backend is not reachable at ${API_BASE}.`));
      return;
    }
    const timer = setTimeout(() => finish(() => {
      ws.close();
      reject(new GenevaBackendError("TIMEOUT", "The assistant took too long to answer. Please try again."));
    }), TURN_TIMEOUT_MS);
    ws.onopen = () => ws.send(JSON.stringify(payload));
    ws.onmessage = (event) => finish(() => {
      ws.close(1000, "turn complete");
      try { resolve(toReply(JSON.parse(event.data))); } catch (e) {
        reject(e instanceof GenevaBackendError ? e : new GenevaBackendError("INVALID_RESPONSE", "The assistant returned an unreadable response."));
      }
    });
    ws.onerror = () => finish(() => reject(new GenevaBackendError("UNREACHABLE", `Geneva's assistant backend is not reachable at ${API_BASE}. Check that it is running.`)));
    ws.onclose = () => finish(() => reject(new GenevaBackendError("CLOSED", "The connection to the assistant closed before it answered.")));
  });
}

export const askBackend = (sessionId: string, message: string, context: GenevaContext) =>
  sendTurn(sessionId, { message, context });

/** Resume a session paused at the backend's human-approval gate. */
export const confirmBackendAction = (sessionId: string, approved: boolean) =>
  sendTurn(sessionId, { action: "confirm_financial_action", approved });

/** Reader view of one source article a Market Researcher run cited (the backend only serves that run's sources). */
export async function fetchBackendArticle(runId: string, url: string, signal?: AbortSignal): Promise<GenevaArticle> {
  const params = new URLSearchParams({ run_id: runId, url });
  const res = await fetch(`${API_BASE}/agents/market-researcher/articles?${params}`, { signal });
  if (!res.ok) throw new Error(res.status === 404 ? "This source is not part of that research run." : `Could not load the article (${res.status}).`);
  return res.json();
}
