import { useEffect, useState } from "react";
import { ExternalLink, X } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import type { GenevaArticle } from "../../types/arc";
import type { SourceRef } from "./GenevaMarkdown";

const label = "text-xs uppercase tracking-[0.12em] text-ink-muted";
const hostOf = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } };
const day = (iso: string | null) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
};

/**
 * Reader view of a source a Geneva answer cited (Market Researcher runs only). Most news sites refuse to be
 * embedded, so this shows the extracted text when the site allows it, otherwise the summary and the reason.
 */
export function GenevaArticlePanel({ source, onClose }: { source: SourceRef | null; onClose: () => void }) {
  const [state, setState] = useState<{ url: string; data?: GenevaArticle; error?: string } | null>(null);

  useEffect(() => {
    if (!source) return;
    const ctrl = new AbortController();
    setState({ url: source.url });
    arcApi.getArticle(source.runId, source.url, ctrl.signal)
      .then((data) => setState({ url: source.url, data }))
      .catch((e: unknown) => { if (!ctrl.signal.aborted) setState({ url: source.url, error: e instanceof Error ? e.message : String(e) }); });
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    return () => { ctrl.abort(); document.removeEventListener("keydown", esc); };
  }, [source, onClose]);

  if (!source) return null;
  const data = state?.url === source.url ? state.data : undefined;
  const error = state?.url === source.url ? state.error : undefined;
  const meta = [data?.source ?? hostOf(source.url), data?.author, day(data?.published ?? null)].filter(Boolean).join(" · ");

  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink/20" onClick={onClose} aria-hidden="true" />
      <aside role="dialog" aria-label="Source article" className="geneva-light fixed inset-y-0 right-0 z-50 flex w-full max-w-[34rem] flex-col border-l border-hairline bg-surface-100 shadow-card">
        <header className="flex items-start justify-between gap-4 border-b border-hairline px-8 py-6">
          <div className="min-w-0">
            <p className={label}>Source</p>
            <h2 className="mt-2 text-[22px] leading-8 tracking-tight text-ink">{data?.title || source.title || hostOf(source.url)}</h2>
            <p className="mt-2 text-[13px] text-ink-muted">{meta}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" title="Close" className="inline-flex size-9 shrink-0 items-center justify-center rounded-sm text-ink-muted hover:bg-surface-300 hover:text-ink"><X size={18} /></button>
        </header>

        <div className="flex-1 space-y-8 overflow-y-auto px-8 py-8">
          {!data && !error && <p className="text-[15px] text-ink-muted">Loading the article…</p>}
          {error && <p className="text-[15px] text-ink-700">{error}</p>}
          {data?.summary && (
            <section className="rounded-sm border border-hairline px-5 py-4">
              <p className={label}>Summary</p>
              <p className="mt-3 text-[16px] leading-7 text-ink-700">{data.summary}</p>
            </section>
          )}
          {data?.status === "ok" && (
            <div className="space-y-4 text-[16px] leading-7 text-ink-700">{data.paragraphs.map((p, i) => <p key={i}>{p}</p>)}</div>
          )}
          {data?.status === "unavailable" && (
            <p className="text-[15px] leading-7 text-ink-muted">The full article can't be shown here. {data.reason}</p>
          )}
        </div>

        <footer className="border-t border-hairline px-8 py-5">
          <a href={source.url} target="_blank" rel="noopener noreferrer"
            className="inline-flex min-h-9 items-center gap-2 rounded-sm border border-ink px-4 text-[15px] text-ink hover:bg-surface-300">
            Open original <ExternalLink size={15} />
          </a>
        </footer>
      </aside>
    </>
  );
}
