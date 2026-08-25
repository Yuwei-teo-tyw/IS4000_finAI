interface SearchIndicatorProps {
  searchUsed: boolean;
}

export function SearchIndicator({ searchUsed }: SearchIndicatorProps) {
  if (!searchUsed) {
    return (
      <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 text-white/70 text-xs font-medium backdrop-blur-sm border border-white/10">
        <div className="w-2 h-2 rounded-full bg-white/50"></div>
        <span>AI Only</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-gradient-to-r from-orange-400/20 to-yellow-400/20 text-orange-200 text-xs font-semibold backdrop-blur-sm border border-orange-400/30 animate-pulse">
      <div className="w-2 h-2 rounded-full bg-gradient-to-r from-orange-400 to-yellow-400 animate-pulse shadow-lg"></div>
      <span className="flex items-center gap-1">
        <span>🌐</span>
        <span>Web Enhanced</span>
      </span>
    </div>
  );
}
