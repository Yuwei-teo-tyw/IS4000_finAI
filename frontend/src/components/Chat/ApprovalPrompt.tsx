import type { PendingAction } from "../../types";

interface ApprovalPromptProps {
  action: PendingAction | null;
  onConfirm: (approved: boolean) => void;
  disabled?: boolean;
}

export function ApprovalPrompt({
  action,
  onConfirm,
  disabled,
}: ApprovalPromptProps) {
  return (
    <div className="p-6 border-t border-white/10 backdrop-blur-lg">
      <div className="glass-effect rounded-2xl p-5 border border-amber-400/30 shadow-lg">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">⚠️</span>
          <span className="text-white font-semibold text-sm">
            Confirmation required before this action proceeds
          </span>
        </div>
        {action && (
          <div className="mb-4 text-sm text-white/80 space-y-1">
            {action.action_type && (
              <div>
                <span className="text-white/50">Action:</span>{" "}
                {action.action_type}
              </div>
            )}
            {action.amount !== undefined && (
              <div>
                <span className="text-white/50">Amount:</span> $
                {action.amount.toLocaleString()}
              </div>
            )}
            {action.description && (
              <div>
                <span className="text-white/50">Details:</span>{" "}
                {action.description}
              </div>
            )}
          </div>
        )}
        <div className="flex gap-3">
          <button
            onClick={() => onConfirm(true)}
            disabled={disabled}
            className="flex-1 px-4 py-3 rounded-xl font-medium shadow-lg transition-all duration-200 transform bg-gradient-to-r from-emerald-400 to-teal-500 hover:from-emerald-500 hover:to-teal-600 text-white hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            ✅ Approve
          </button>
          <button
            onClick={() => onConfirm(false)}
            disabled={disabled}
            className="flex-1 px-4 py-3 rounded-xl font-medium shadow-lg transition-all duration-200 transform bg-gradient-to-r from-rose-400 to-red-500 hover:from-rose-500 hover:to-red-600 text-white hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            ❌ Decline
          </button>
        </div>
        <div className="mt-2 text-xs text-white/50 text-center">
          Typing a message here won't work - this is a hard confirmation
          gate, use the buttons above.
        </div>
      </div>
    </div>
  );
}
