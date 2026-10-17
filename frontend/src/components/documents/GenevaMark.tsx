/** UBS keys + "Geneva" wordmark for the top of every paper. .ubs-logo inverts in dark mode (paper is dark there) and not in print. */
export function GenevaMark({ className = "" }: { className?: string }) {
  return (
    <div className={`avoid-break flex items-center gap-3 border-b border-hairline pb-4 ${className}`}>
      <img src="/ubs-logo.png" alt="UBS" className="ubs-logo h-7 w-auto" />
      <span className="text-xl font-light text-ink">Geneva</span>
    </div>
  );
}
