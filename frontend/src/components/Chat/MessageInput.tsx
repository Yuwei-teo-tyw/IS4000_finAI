import { useState } from "react";

interface MessageInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function MessageInput({ onSend, disabled }: MessageInputProps) {
  const [input, setInput] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !disabled) {
      onSend(input);
      setInput("");
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="p-6 border-t border-white/10 backdrop-blur-lg"
    >
      <div className="flex gap-3 items-end">
        <div className="flex-1 relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={disabled}
            placeholder="Ask me anything... 🤖"
            className="w-full px-6 py-4 glass-effect rounded-2xl text-white placeholder-white/60 focus:outline-none focus:ring-2 focus:ring-cyan-400/50 disabled:opacity-50 shadow-lg text-base"
          />
          <div className="absolute inset-y-0 right-4 flex items-center pointer-events-none">
            <div className="text-white/40 text-sm">
              {input.length > 0 && `${input.length}/500`}
            </div>
          </div>
        </div>
        <button
          type="submit"
          disabled={disabled || !input.trim()}
          className={`px-6 py-4 rounded-2xl font-medium shadow-lg transition-all duration-200 transform ${
            disabled || !input.trim()
              ? "bg-white/10 text-white/40 cursor-not-allowed"
              : "bg-gradient-to-r from-cyan-400 to-blue-500 hover:from-cyan-500 hover:to-blue-600 text-white hover:scale-105 hover:shadow-xl btn-hover"
          }`}
        >
          <div className="flex items-center gap-2">
            <span>Send</span>
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          </div>
        </button>
      </div>
      <div className="mt-2 text-xs text-white/50 text-center">
        Ask about coding, finance, or anything else • Enhanced with web search
      </div>
    </form>
  );
}
