interface TypingIndicatorProps {
  isSearching?: boolean;
}

export function TypingIndicator({ isSearching = false }: TypingIndicatorProps) {
  return (
    <div className="flex justify-start animate-in slide-in-from-bottom duration-300">
      <div className="max-w-[75%] px-6 py-4 rounded-2xl glass-effect text-white shadow-lg">
        <div className="flex items-center gap-3">
          {isSearching ? (
            <>
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 bg-gradient-to-r from-orange-400 to-yellow-500 rounded-full typing-dot shadow-lg"></div>
                <div className="w-3 h-3 bg-gradient-to-r from-orange-400 to-yellow-500 rounded-full typing-dot shadow-lg"></div>
                <div className="w-3 h-3 bg-gradient-to-r from-orange-400 to-yellow-500 rounded-full typing-dot shadow-lg"></div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-2xl animate-spin">🌐</span>
                <span className="text-sm font-medium text-orange-200">
                  Searching the web...
                </span>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 bg-gradient-to-r from-cyan-400 to-blue-500 rounded-full typing-dot shadow-lg"></div>
                <div className="w-3 h-3 bg-gradient-to-r from-cyan-400 to-blue-500 rounded-full typing-dot shadow-lg"></div>
                <div className="w-3 h-3 bg-gradient-to-r from-cyan-400 to-blue-500 rounded-full typing-dot shadow-lg"></div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xl animate-pulse">🤖</span>
                <span className="text-sm font-medium text-cyan-200">
                  AI is thinking...
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
