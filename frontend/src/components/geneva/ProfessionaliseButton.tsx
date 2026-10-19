/** Liquid-glass button for "Professionalise with Geneva". Not a brand button: translucent, frosted, calm. */
export function ProfessionaliseButton({ onClick, loading = false, disabled = false, label = "Professionalise", size = "md" }: {
  onClick?: () => void; loading?: boolean; disabled?: boolean; label?: string; size?: "sm" | "md" | "lg";
}) {
  const pad = size === "sm" ? "h-9 px-4 text-[13px] gap-2" : size === "lg" ? "h-14 px-8 text-[17px] gap-3" : "h-11 px-6 text-[15px] gap-2.5";
  const icon = size === "sm" ? "h-3.5" : size === "lg" ? "h-5" : "h-4";
  return (
    <button type="button" onClick={onClick} disabled={disabled || loading} aria-busy={loading} data-loading={loading}
      className={`geneva-glass inline-flex items-center justify-center font-light ${pad}`}>
      <span className="gg-blob gg-blob-a" aria-hidden="true" />
      <span className="gg-blob gg-blob-b" aria-hidden="true" />
      <img src="/ubs-logo.png" alt="" aria-hidden="true" className={`ubs-logo w-auto ${icon}`} />
      <span className={loading ? "animate-geneva-breathe" : undefined}>{loading ? "Professionalising…" : label}</span>
      <span className="sr-only" role="status">{loading ? "Geneva is working" : ""}</span>
    </button>
  );
}
export default ProfessionaliseButton;
