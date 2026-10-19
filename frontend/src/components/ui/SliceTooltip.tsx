import { useCallback, useRef, useState, type MouseEvent } from "react";

export interface SliceTip { label: string; pct: number; x: number; y: number }

/**
 * Hover tooltip for pie/donut slices. Wrap the chart in an element with
 * `ref={containerRef}` and `className="relative"`, spread `bind(label, pct)` on each slice,
 * use `sliceStyle(label)` for highlight/dim, and render `<SliceTooltip tip={tip} />` inside the container.
 */
export function useSliceTooltip() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<SliceTip | null>(null);

  const place = useCallback((e: MouseEvent, label: string, pct: number) => {
    const box = containerRef.current?.getBoundingClientRect();
    if (!box) return;
    setTip({ label, pct, x: e.clientX - box.left, y: e.clientY - box.top });
  }, []);

  const bind = useCallback((label: string, pct: number) => ({
    onMouseEnter: (e: MouseEvent) => place(e, label, pct),
    onMouseMove: (e: MouseEvent) => place(e, label, pct),
    onMouseLeave: () => setTip(null),
  }), [place]);

  /** Spread as `style` on a slice: hovered stays full, others dim. */
  const sliceStyle = useCallback((label: string) => ({
    opacity: tip && tip.label !== label ? 0.35 : 1,
    transition: "opacity 120ms",
    cursor: "pointer",
  }), [tip]);

  return { containerRef, tip, bind, sliceStyle };
}

export function SliceTooltip({ tip }: { tip: SliceTip | null }) {
  if (!tip) return null;
  const pct = Number.isInteger(tip.pct) ? tip.pct : Math.round(tip.pct * 10) / 10;
  return (
    <div role="tooltip" className="pointer-events-none absolute z-20 whitespace-nowrap border border-hairline bg-surface-100 px-3 py-2 text-[13px] leading-5 text-ink"
      style={{ left: tip.x + 12, top: tip.y + 12 }}>
      {tip.label}<span className="ml-3 text-ink-muted">{pct}%</span>
    </div>
  );
}
