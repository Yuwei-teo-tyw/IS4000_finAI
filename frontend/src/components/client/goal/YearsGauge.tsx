const SCALE = 15;

export function YearsGauge({ years }: { years: number }) {
  const filled = Math.max(0, Math.min(SCALE, Math.round(years)));
  return (
    <div className="flex h-full flex-col justify-center gap-6">
      <p className="text-[56px] font-light leading-none text-ink">{years}<span className="ml-2 text-base text-ink-muted">years</span></p>
      <svg viewBox="0 0 300 36" className="w-full" role="img" aria-label={`${years} of ${SCALE} comfortable years`}>
        {Array.from({ length: SCALE }, (_, i) => (
          <rect key={i} x={i * 20} y="0" width="16" height="24" className={i < filled ? "fill-scale-fill" : "fill-scale-track"} />
        ))}
        <text x="0" y="36" className="fill-ink-muted" fontSize="12">0</text>
        <text x="300" y="36" textAnchor="end" className="fill-ink-muted" fontSize="12">{SCALE} yrs comfort</text>
      </svg>
    </div>
  );
}
