import { usePackReturnedUnseen } from "../../services/packHandover";

/** Small popup bubble shown when the Portfolio Manager has handed a review pack back and the RM has not opened it yet. */
export function PackBackBubble({ clientId, text = "Pack returned by PM", className = "", force = false }: { clientId: string; text?: string; className?: string; /** Show regardless of the unseen state (the Review Pack tab keeps it up for the current visit). */ force?: boolean }) {
  const unseen = usePackReturnedUnseen(clientId);
  if (!unseen && !force) return null;
  return (
    <span role="status" className={`inline-flex items-center gap-2 rounded-sm border border-brand bg-surface-100 px-2.5 py-1 text-[12px] font-semibold leading-4 text-brand shadow-overlay ${className}`}>
      <span aria-hidden className="size-2 rounded-full bg-brand" />{text}
    </span>
  );
}
