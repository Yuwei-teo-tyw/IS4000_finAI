import type { ReactNode } from "react";

export function ChartCard({ title, caption, children }: { title: string; caption: string; children: ReactNode }) {
  return (
    <div className="flex flex-col">
      <h3 className="text-xl">{title}</h3>
      <p className="mb-4 mt-1 text-sm text-ink-muted">{caption}</p>
      <div className="flex-1 rounded-sm bg-surface-300 p-5">{children}</div>
    </div>
  );
}
