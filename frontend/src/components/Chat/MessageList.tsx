import type { Message } from "../../types";
import { AgentBadge } from "./AgentBadge";
import { SearchIndicator } from "./SearchIndicator";
import { TypingIndicator } from "./TypingIndicator";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  isSearching?: boolean;
}

export function MessageList({
  messages,
  isTyping,
  isSearching,
}: MessageListProps) {
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-gradient-to-b from-transparent to-black/5">
      {messages.length === 0 ? (
        <div className="text-center mt-20">
          <div className="bg-gradient-to-br from-white/20 to-white/5 backdrop-blur-xl rounded-2xl p-8 mx-auto max-w-md border border-white/30 shadow-2xl">
            <div className="w-16 h-16 bg-gradient-to-r from-purple-400 to-pink-400 rounded-full flex items-center justify-center mx-auto mb-4 shadow-lg">
              💬
            </div>
            <h3 className="text-white font-semibold text-lg mb-2">
              Welcome to AI Assistant
            </h3>
            <p className="text-white/70 text-sm leading-relaxed">
              Start a conversation below. I can help with technical questions,
              financial advice, or general chat!
            </p>
          </div>
        </div>
      ) : (
        <>
          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-in slide-in-from-bottom duration-300`}
            >
              <div
                className={`max-w-[75%] px-6 py-4 rounded-2xl shadow-lg transform hover:scale-[1.02] transition-all duration-200 ${
                  msg.role === "user"
                    ? "bg-gradient-to-r from-indigo-500 to-blue-600 text-white shadow-blue-500/30 border border-blue-400/20"
                    : "bg-gradient-to-r from-white/15 to-white/10 backdrop-blur-xl text-white shadow-black/30 border border-white/20"
                }`}
              >
                {msg.agent_name && (
                  <div className="mb-3 flex items-center gap-2 flex-wrap">
                    <AgentBadge
                      agentName={msg.agent_name}
                      enhanced={msg.search_used}
                    />
                    {msg.role === "assistant" && (
                      <SearchIndicator searchUsed={msg.search_used || false} />
                    )}
                  </div>
                )}
                <div
                  className={`prose prose-sm max-w-none ${
                    msg.role === "user" ? "prose-invert" : "prose-white"
                  }`}
                >
                  <Markdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      table: ({ children }) => (
                        <div className="overflow-x-auto">
                          <table>{children}</table>
                        </div>
                      ),
                    }}
                  >
                    {msg.content}
                  </Markdown>
                </div>
              </div>
            </div>
          ))}
          {isTyping && <TypingIndicator isSearching={isSearching} />}
        </>
      )}
    </div>
  );
}
