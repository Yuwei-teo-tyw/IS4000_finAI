import { useState, useEffect, useCallback } from "react";
import type { ArticleRef, Message, Session, SystemResponse, PendingAction } from "../../types";
import {
  wsService,
  fetchSessions,
  fetchSessionMessages,
  deleteSession as deleteSessionRequest,
} from "../../services/api";
import { MessageList } from "./MessageList";
import { MessageInput } from "./MessageInput";
import { ApprovalPrompt } from "./ApprovalPrompt";
import { ArticlePanel } from "./ArticlePanel";
import { Sidebar } from "../Sidebar/Sidebar";

// Persisted so the sidebar's "current chat" survives a page reload/app
// restart, matching the backend's Postgres-backed session persistence.
const SESSION_STORAGE_KEY = "fin-ai-current-session";

function loadOrCreateSessionId(): string {
  const stored = localStorage.getItem(SESSION_STORAGE_KEY);
  if (stored) return stored;
  const fresh = crypto.randomUUID();
  localStorage.setItem(SESSION_STORAGE_KEY, fresh);
  return fresh;
}

export function ChatContainer() {
  const [sessionId, setSessionId] = useState<string>(loadOrCreateSessionId);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const [infoMessage, setInfoMessage] = useState<string>("");
  const [isTyping, setIsTyping] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [connectionStatus, setConnectionStatus] =
    useState<string>("Connecting...");
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(
    null,
  );
  const [awaitingApproval, setAwaitingApproval] = useState(false);
  const [openArticle, setOpenArticle] = useState<ArticleRef | null>(null);
  const closeArticle = useCallback(() => setOpenArticle(null), []);

  const refreshSessions = () => {
    fetchSessions()
      .then(setSessions)
      .catch((err) => console.error("Failed to load sessions:", err))
      .finally(() => setSessionsLoading(false));
  };

  const loadHistory = (id: string) => {
    fetchSessionMessages(id)
      .then(setMessages)
      .catch((err) => {
        console.error("Failed to load session history:", err);
        setMessages([]);
      });
  };

  useEffect(() => {
    // Bind the socket to whichever session is active before connecting -
    // the backend resumes that exact LangGraph thread (see
    // backend/app/endpoints), so history and agent state carry over.
    wsService.setSessionId(sessionId);
    setConnectionStatus("Connecting...");
    wsService.connect();
    loadHistory(sessionId);
    refreshSessions();

    const unsubConnect = wsService.onConnect(() => {
      setConnected(true);
      setConnectionStatus("Connected");
    });

    const unsubDisconnect = wsService.onDisconnect(() => {
      setConnected(false);
      setConnectionStatus("Disconnected");
      setIsTyping(false);
      setIsSearching(false);
      setPendingAction(null);
      setAwaitingApproval(false);
    });

    const unsubMessage = wsService.onMessage((data: SystemResponse) => {
      setIsTyping(false);
      setIsSearching(false);

      if (data.info_message) {
        setInfoMessage(data.info_message);
        setTimeout(() => setInfoMessage(""), 3000);

        // Check if the info message indicates searching
        if (data.info_message.toLowerCase().includes("search")) {
          setIsSearching(true);
          setIsTyping(true);
        }
      }

      if (data.message) {
        // Determine if search was used based on the agent type and response data
        let searchUsed = false;
        if (
          data.agent_name?.toLowerCase().includes("finance") &&
          data.finance_response?.data?.search_used
        ) {
          searchUsed = true;
        }

        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.message,
            agent_name: data.agent_name,
            search_used: searchUsed,
          },
        ]);

        // A real turn just completed - the sidebar's title/ordering for
        // this session may have changed (new session, or first message
        // just set its title).
        refreshSessions();
      }

      // The graph paused at the human-approval interrupt (see
      // backend/app/agents/nodes/human_approval.py) - only the Approve/Decline
      // buttons can advance it; a plain typed reply would just re-trigger the
      // same interrupt.
      setAwaitingApproval(Boolean(data.requires_confirmation));
      setPendingAction(
        data.requires_confirmation ? (data.pending_action ?? null) : null,
      );
    });

    // Cleanup function
    return () => {
      unsubConnect();
      unsubDisconnect();
      unsubMessage();
      wsService.destroy(); // Use destroy instead of disconnect for complete cleanup
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const switchToSession = (id: string) => {
    if (id === sessionId) return;
    localStorage.setItem(SESSION_STORAGE_KEY, id);
    setSessionId(id);
    setMessages([]);
    setOpenArticle(null);
    setPendingAction(null);
    setAwaitingApproval(false);
    setIsTyping(false);
    setIsSearching(false);
    wsService.setSessionId(id);
    loadHistory(id);
  };

  const handleNewChat = () => {
    switchToSession(crypto.randomUUID());
  };

  const handleSelectSession = (id: string) => {
    switchToSession(id);
  };

  const handleDeleteSession = async (id: string) => {
    try {
      await deleteSessionRequest(id);
    } catch (err) {
      console.error("Failed to delete session:", err);
    }
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (id === sessionId) {
      handleNewChat();
    }
  };

  const handleSend = (content: string) => {
    if (!connected) {
      setInfoMessage(
        "Not connected. Please wait for reconnection or click Reconnect.",
      );
      return;
    }

    setMessages((prev) => [...prev, { role: "user", content }]);
    setIsTyping(true);
    setIsSearching(false);
    wsService.sendMessage(content);
  };

  const handleConfirm = (approved: boolean) => {
    if (!connected) {
      setInfoMessage(
        "Not connected. Please wait for reconnection or click Reconnect.",
      );
      return;
    }

    setMessages((prev) => [
      ...prev,
      { role: "user", content: approved ? "✅ Approved" : "❌ Declined" },
    ]);
    setPendingAction(null);
    setAwaitingApproval(false);
    setIsTyping(true);
    setIsSearching(false);
    wsService.sendConfirmation(approved);
  };

  const handleReconnect = () => {
    setConnectionStatus("Reconnecting...");
    setIsTyping(false);
    setIsSearching(false);
    wsService.forceReconnect();
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-slate-900 via-gray-900 to-zinc-900">
      <Sidebar
        sessions={sessions}
        activeSessionId={sessionId}
        loading={sessionsLoading}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
      />

      <div className="flex flex-col flex-1 min-w-0">
        <div className="glass-effect backdrop-blur-lg border-b border-white/20 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-r from-cyan-400 to-blue-500 rounded-xl flex items-center justify-center text-white font-bold text-lg shadow-lg">
              AI
            </div>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-white to-gray-200 bg-clip-text text-transparent">
                Multi-Agent Assistant
              </h1>
              <p className="text-xs text-white/70">
                Intelligent routing to specialized experts
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {!connected && (
              <button
                onClick={handleReconnect}
                className="px-4 py-2 bg-gradient-to-r from-emerald-400 to-cyan-400 hover:from-emerald-500 hover:to-cyan-500 text-white rounded-lg text-sm font-medium shadow-lg hover:shadow-xl transform hover:scale-105 transition-all duration-200"
              >
                🔄 Reconnect
              </button>
            )}
            <div className="flex items-center gap-3 bg-white/10 rounded-full px-4 py-2 backdrop-blur-sm">
              <div
                className={`w-3 h-3 rounded-full shadow-lg ${
                  connected ? "bg-emerald-400 pulse-glow" : "bg-red-400"
                }`}
              />
              <span className="text-sm text-white font-medium">
                {connectionStatus}
                {isSearching && (
                  <span className="ml-2 text-cyan-300 animate-pulse">
                    🌐 Searching...
                  </span>
                )}
              </span>
            </div>
          </div>
        </div>

        {infoMessage && (
          <div className="bg-gradient-to-r from-blue-400/20 to-cyan-400/20 backdrop-blur-sm border-b border-white/10 text-white px-6 py-3 text-sm font-medium animate-pulse">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-cyan-400 rounded-full animate-pulse"></div>
              {infoMessage}
            </div>
          </div>
        )}

        <MessageList
          messages={messages}
          isTyping={isTyping}
          isSearching={isSearching}
          onOpenArticle={setOpenArticle}
        />
        {awaitingApproval ? (
          <ApprovalPrompt
            action={pendingAction}
            onConfirm={handleConfirm}
            disabled={!connected}
          />
        ) : (
          <MessageInput onSend={handleSend} disabled={!connected} />
        )}
      </div>

      <ArticlePanel article={openArticle} onClose={closeArticle} />
    </div>
  );
}
