import { ArrowDownWideNarrow, ArrowUpNarrowWide } from "lucide-react";

export type SortOrder = "latest" | "earliest";

export function SortByDate({ value, onChange }: { value: SortOrder; onChange: (v: SortOrder) => void }) {
  const latest = value === "latest";
  const label = latest ? "Latest first" : "Earliest first";
  const Icon = latest ? ArrowDownWideNarrow : ArrowUpNarrowWide;
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => onChange(latest ? "earliest" : "latest")}
      className="inline-flex size-10 items-center justify-center rounded-sm border border-hairline-strong bg-surface-100 text-ink hover:bg-surface-300"
    >
      <Icon size={18} />
    </button>
  );
}
