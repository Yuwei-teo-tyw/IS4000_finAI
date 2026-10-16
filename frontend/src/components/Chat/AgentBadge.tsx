interface AgentBadgeProps {
  agentName?: string;
  enhanced?: boolean; // Whether the response was enhanced with search
}

export function AgentBadge({ agentName, enhanced }: AgentBadgeProps) {
  if (!agentName) return null;

  const getAgentColor = (name: string) => {
    if (name.toLowerCase().includes("finance")) {
      return enhanced
        ? "bg-gradient-to-r from-emerald-400/90 to-teal-500/90 text-white shadow-lg shadow-emerald-500/25"
        : "bg-gradient-to-r from-green-400/80 to-emerald-500/80 text-white shadow-md";
    }
    if (name.toLowerCase().includes("market")) {
      return "bg-gradient-to-r from-amber-400/90 to-orange-500/90 text-white shadow-md";
    }
    return enhanced
      ? "bg-gradient-to-r from-purple-400/90 to-pink-500/90 text-white shadow-lg shadow-purple-500/25"
      : "bg-gradient-to-r from-purple-400/80 to-pink-500/80 text-white shadow-md";
  };

  const getIcon = (name: string) => {
    if (name.toLowerCase().includes("finance")) {
      return enhanced ? "💰🌐" : "💰";
    }
    if (name.toLowerCase().includes("market")) {
      return "📈";
    }
    return enhanced ? "🤖🌐" : "🤖";
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getAgentColor(
        agentName,
      )}`}
    >
      <span className="mr-1">{getIcon(agentName)}</span>
      {agentName}
      {enhanced && <span className="ml-1 text-xs opacity-75">+Search</span>}
    </span>
  );
}
