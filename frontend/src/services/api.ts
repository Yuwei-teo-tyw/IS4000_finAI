import type { ArticleView, Message, Session, SystemResponse } from "../types";

const API_BASE = "http://localhost:8000";

// WebSocket endpoint (single implementation - see backend/app/endpoints)
const WS_ENDPOINTS = {
  langgraph: `${API_BASE.replace("http", "ws")}/agents/langgraph`,
};

// HTTP endpoints for health checks
const HTTP_ENDPOINTS = {
  langgraph: `${API_BASE}/`,
};

// Function to check if backend is available
async function checkBackendHealth(
  endpoint: keyof typeof HTTP_ENDPOINTS,
): Promise<boolean> {
  try {
    const response = await fetch(HTTP_ENDPOINTS[endpoint], {
      method: "GET",
      signal: AbortSignal.timeout(3000), // 3 second timeout
    });
    return response.ok;
  } catch (error) {
    return false;
  }
}

// REST helpers for the sidebar (see backend/app/endpoints - GET/DELETE /sessions...)
export async function fetchSessions(): Promise<Session[]> {
  const res = await fetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error(`Failed to fetch sessions: ${res.status}`);
  return res.json();
}

export async function fetchSessionMessages(
  sessionId: string,
): Promise<Message[]> {
  const res = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/messages`,
  );
  if (!res.ok) throw new Error(`Failed to fetch session messages: ${res.status}`);
  return res.json();
}

// Reader view of a news article a Market Researcher run cited - the backend
// only serves URLs recorded in that run, and extracts the article text when
// the site allows it (status "ok"), otherwise returns the agent's summary.
export async function fetchArticle(
  runId: string,
  url: string,
  signal?: AbortSignal,
): Promise<ArticleView> {
  const params = new URLSearchParams({ run_id: runId, url });
  const res = await fetch(
    `${API_BASE}/agents/market-researcher/articles?${params}`,
    { signal },
  );
  if (!res.ok) throw new Error(`Failed to load article: ${res.status}`);
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`Failed to delete session: ${res.status}`);
}

export class WebSocketService {
  private ws: WebSocket | null = null;
  private messageHandlers: Set<(data: SystemResponse) => void> = new Set();
  private connectHandlers: Set<() => void> = new Set();
  private disconnectHandlers: Set<() => void> = new Set();
  private currentEndpoint: keyof typeof WS_ENDPOINTS = "langgraph";
  private sessionId: string | null = null;

  // Reconnection properties
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 3; // Reduced from 5
  private reconnectDelay: number = 2000; // Start with 2 seconds instead of 1
  private maxReconnectDelay: number = 15000; // Reduced from 30 seconds
  private reconnectTimeoutId: number | null = null;
  private isManuallyDisconnected: boolean = false;
  private isInitialConnection: boolean = true;

  // Method to switch endpoints
  setEndpoint(endpoint: keyof typeof WS_ENDPOINTS) {
    this.currentEndpoint = endpoint;
    this.isManuallyDisconnected = false; // Allow reconnection for endpoint switch
    if (this.ws) {
      this.disconnect();
      setTimeout(() => {
        this.isManuallyDisconnected = false;
        this.connect();
      }, 100);
    }
  }

  // Switches which chat session (LangGraph thread_id) this socket is bound
  // to - reconnects if already connected, so picking a session from the
  // sidebar or starting a new chat takes effect immediately.
  setSessionId(sessionId: string) {
    if (this.sessionId === sessionId) return;
    this.sessionId = sessionId;
    this.isManuallyDisconnected = false;
    if (this.ws) {
      this.disconnect();
      setTimeout(() => {
        this.isManuallyDisconnected = false;
        this.connect();
      }, 100);
    }
  }

  async connect() {
    // Clear any existing reconnection timeout
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
      this.reconnectTimeoutId = null;
    }

    // Don't try to connect if manually disconnected
    if (this.isManuallyDisconnected) {
      console.log("Connection attempt skipped - manually disconnected");
      return;
    }

    // Check backend health before attempting connection
    const isBackendHealthy = await checkBackendHealth(this.currentEndpoint);
    if (!isBackendHealthy) {
      console.log(
        `Backend is not healthy for endpoint ${this.currentEndpoint}, skipping connection attempt`,
      );
      return;
    }

    const baseWsUrl = WS_ENDPOINTS[this.currentEndpoint];
    const wsUrl = this.sessionId
      ? `${baseWsUrl}?session_id=${encodeURIComponent(this.sessionId)}`
      : baseWsUrl;
    console.log(
      `${this.isInitialConnection ? "Initial connection" : "Reconnection"} attempt to ${wsUrl}`,
    );

    try {
      this.ws = new WebSocket(wsUrl);
    } catch (error) {
      console.error("Failed to create WebSocket:", error);
      if (this.isInitialConnection) {
        console.log("Initial connection failed, will retry in 5 seconds...");
        this.isInitialConnection = false;
        setTimeout(() => this.handleReconnect(), 5000);
      } else {
        this.handleReconnect();
      }
      return;
    }

    // Add connection timeout
    const connectionTimeout = setTimeout(() => {
      if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
        console.log("Connection timeout, closing and retrying...");
        this.ws.close();
      }
    }, 8000); // Increased timeout to 8 seconds

    this.ws.onopen = () => {
      clearTimeout(connectionTimeout);
      console.log(`WebSocket connected to ${this.currentEndpoint} endpoint`);
      this.reconnectAttempts = 0; // Reset reconnect attempts on successful connection
      this.reconnectDelay = 2000; // Reset delay
      this.isInitialConnection = false;
      this.connectHandlers.forEach((handler) => handler());
    };

    this.ws.onmessage = (event) => {
      try {
        const data: SystemResponse = JSON.parse(event.data);
        this.messageHandlers.forEach((handler) => handler(data));
      } catch (error) {
        console.error("Failed to parse message:", error);
      }
    };

    this.ws.onclose = (event) => {
      clearTimeout(connectionTimeout);
      console.log(
        `WebSocket disconnected - Code: ${event.code}, Reason: ${event.reason || "Unknown"}`,
      );
      this.ws = null;
      this.disconnectHandlers.forEach((handler) => handler());

      // Be more selective about when to reconnect
      const shouldReconnect =
        !this.isManuallyDisconnected &&
        event.code !== 1000 && // Normal closure
        event.code !== 1001 && // Going away
        this.reconnectAttempts < this.maxReconnectAttempts;

      if (shouldReconnect) {
        console.log(
          `Will attempt reconnection due to unexpected closure (code: ${event.code})`,
        );
        this.handleReconnect();
      } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.log(
          "No more reconnection attempts will be made. Please check the backend and refresh the page.",
        );
      } else {
        console.log("Connection closed normally, no reconnection needed.");
      }
    };

    this.ws.onerror = (error) => {
      clearTimeout(connectionTimeout);
      console.error("WebSocket error occurred:", error);
      // The onclose event will be called after this, so we don't need to handle reconnection here
    };
  }

  private async handleReconnect() {
    // Don't reconnect if manually disconnected or exceeded max attempts
    if (
      this.isManuallyDisconnected ||
      this.reconnectAttempts >= this.maxReconnectAttempts
    ) {
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.log(
          "Maximum reconnection attempts reached. Please check if the backend is running and refresh the page.",
        );
      }
      return;
    }

    this.reconnectAttempts++;
    console.log(
      `Attempting to reconnect... (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${this.reconnectDelay}ms`,
    );

    this.reconnectTimeoutId = window.setTimeout(async () => {
      console.log(`Reconnect attempt ${this.reconnectAttempts} starting...`);
      await this.connect();
    }, this.reconnectDelay);

    // Exponential backoff with jitter - more conservative
    this.reconnectDelay = Math.min(
      this.reconnectDelay * 1.5 + Math.random() * 2000, // Slower growth, more jitter
      this.maxReconnectDelay,
    );
  }

  disconnect() {
    console.log("Manually disconnecting WebSocket...");
    this.isManuallyDisconnected = true;

    // Clear any pending reconnection
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
      this.reconnectTimeoutId = null;
    }

    if (this.ws) {
      this.ws.close(1000, "Manual disconnect"); // Normal closure
      this.ws = null;
    }

    // Reset reconnection state
    this.reconnectAttempts = 0;
    this.reconnectDelay = 2000;
  }

  // Method to manually reconnect (for user-initiated reconnection)
  forceReconnect() {
    console.log("Force reconnecting WebSocket...");
    this.isManuallyDisconnected = false;
    this.reconnectAttempts = 0;
    this.reconnectDelay = 2000;
    this.isInitialConnection = false;

    // Clear any pending reconnection
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
      this.reconnectTimeoutId = null;
    }

    if (this.ws) {
      this.ws.close(1000, "Force reconnect");
      this.ws = null;
    }

    // Wait a moment before reconnecting
    setTimeout(() => {
      this.connect();
    }, 500);
  }

  // Method to completely stop the service (for component cleanup)
  destroy() {
    console.log("Destroying WebSocket service...");
    this.isManuallyDisconnected = true;

    // Clear any pending reconnection
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
      this.reconnectTimeoutId = null;
    }

    if (this.ws) {
      this.ws.close(1000, "Service destroyed");
      this.ws = null;
    }

    // Clear all handlers
    this.messageHandlers.clear();
    this.connectHandlers.clear();
    this.disconnectHandlers.clear();

    // Reset state
    this.reconnectAttempts = 0;
    this.reconnectDelay = 2000;
    this.isInitialConnection = true;
  }

  sendMessage(message: string) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(message);
    } else {
      console.error("WebSocket is not connected");
    }
  }

  // Resumes a graph paused at the human-approval interrupt (see
  // backend/app/agents/nodes/human_approval.py). A plain chat message sent
  // while paused there just re-triggers the same interrupt - the backend
  // only advances on this exact payload shape.
  sendConfirmation(approved: boolean) {
    this.sendMessage(
      JSON.stringify({ action: "confirm_financial_action", approved }),
    );
  }

  onMessage(handler: (data: SystemResponse) => void) {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onConnect(handler: () => void) {
    this.connectHandlers.add(handler);
    return () => this.connectHandlers.delete(handler);
  }

  onDisconnect(handler: () => void) {
    this.disconnectHandlers.add(handler);
    return () => this.disconnectHandlers.delete(handler);
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  getCurrentEndpoint(): string {
    return this.currentEndpoint;
  }
}

export const wsService = new WebSocketService();
