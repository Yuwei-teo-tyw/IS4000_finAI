import type { Session } from "../../types";

interface SidebarProps {
  sessions: Session[];
  activeSessionId: string;
  loading: boolean;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function Sidebar({
  sessions,
  activeSessionId,
  loading,
  onSelectSession,
  onNewChat,
  onDeleteSession,
}: SidebarProps) {
  return (
    <div className="w-72 shrink-0 h-screen flex flex-col bg-black/20 border-r border-white/10 backdrop-blur-lg">
      <div className="p-4">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-medium text-sm bg-gradient-to-r from-cyan-400 to-blue-500 hover:from-cyan-500 hover:to-blue-600 text-white shadow-lg hover:shadow-xl transform hover:scale-[1.02] transition-all duration-200"
        >
          <span>+</span>
          <span>New chat</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4 space-y-1">
        {loading && (
          <div className="px-3 py-2 text-xs text-white/40">Loading…</div>
        )}

        {!loading && sessions.length === 0 && (
          <div className="px-3 py-6 text-center text-xs text-white/40">
            No conversations yet.
            <br />
            Start one above.
          </div>
        )}

        {sessions.map((session) => {
          const isActive = session.id === activeSessionId;
          return (
            <div
              key={session.id}
              onClick={() => onSelectSession(session.id)}
              className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors duration-150 ${
                isActive
                  ? "bg-white/15 text-white"
                  : "text-white/70 hover:bg-white/5 hover:text-white"
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm truncate">
                  {session.title || "New chat"}
                </div>
                <div className="text-[11px] text-white/40">
                  {formatTimestamp(session.updated_at)}
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteSession(session.id);
                }}
                title="Delete conversation"
                className="opacity-0 group-hover:opacity-100 shrink-0 w-6 h-6 flex items-center justify-center rounded text-white/40 hover:text-rose-300 hover:bg-white/10 transition-all duration-150"
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
