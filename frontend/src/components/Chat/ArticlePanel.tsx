import { useEffect, useState } from "react";
import type { ArticleRef, ArticleView } from "../../types";
import { fetchArticle } from "../../services/api";

interface ArticlePanelProps {
  article: ArticleRef | null;
  onClose: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; data: ArticleView }
  | { kind: "error"; message: string };

const SENTIMENT_STYLES: Record<string, string> = {
  risk_on: "bg-emerald-400/20 text-emerald-200 border-emerald-300/30",
  risk_off: "bg-rose-400/20 text-rose-200 border-rose-300/30",
  neutral: "bg-white/10 text-white/80 border-white/20",
};

function formatDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// Side panel showing a cited news article in reader view, instead of
// navigating away from the chat. Most news sites can't be embedded in an
// iframe, so the backend extracts the article text; when a site is
// paywalled or blocks automated reading, the panel shows the agent's
// summary and a link to the original.
export function ArticlePanel({ article, onClose }: ArticlePanelProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!article) return;
    const controller = new AbortController();
    setState({ kind: "loading" });
    fetchArticle(article.runId, article.url, controller.signal)
      .then((data) => setState({ kind: "loaded", data }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : "Failed to load article",
        });
      });
    return () => controller.abort();
  }, [article]);

  useEffect(() => {
    if (!article) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [article, onClose]);

  if (!article) return null;

  const data = state.kind === "loaded" ? state.data : null;
  const title = data?.title || article.title;
  const meta = [
    data?.source || hostOf(article.url),
    formatDate(data?.published ?? null),
    data?.author,
  ].filter(Boolean);

  return (
    <aside
      className="fixed inset-0 z-40 flex flex-col bg-slate-900/95 backdrop-blur-xl sm:static sm:z-auto sm:w-[28rem] sm:shrink-0 sm:border-l sm:border-white/20 sm:bg-white/5"
      aria-label="Article reader"
    >
      <div className="flex items-start justify-between gap-3 border-b border-white/20 px-5 py-4">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wide text-cyan-300/90">
            📰 Source article
          </p>
          <h2 className="mt-1 text-base font-semibold leading-snug text-white">
            {title}
          </h2>
          {meta.length > 0 && (
            <p className="mt-1 text-xs text-white/60">{meta.join(" · ")}</p>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-lg px-2 py-1 text-white/70 hover:bg-white/10 hover:text-white"
          aria-label="Close article"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 text-sm text-white/90">
        {state.kind === "loading" && (
          <p className="animate-pulse text-white/60">Loading article…</p>
        )}

        {state.kind === "error" && (
          <p className="rounded-lg border border-rose-300/30 bg-rose-400/10 px-3 py-2 text-rose-100">
            {state.message}
          </p>
        )}

        {data && (
          <>
            {(data.summary || data.topics.length > 0) && (
              <div className="mb-4 rounded-xl border border-white/15 bg-white/5 px-4 py-3">
                <p className="mb-1 text-xs font-medium text-white/60">
                  Market Researcher summary
                </p>
                {data.summary && <p className="leading-relaxed">{data.summary}</p>}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {data.sentiment && (
                    <span
                      className={`rounded-full border px-2 py-0.5 text-xs ${SENTIMENT_STYLES[data.sentiment] ?? SENTIMENT_STYLES.neutral}`}
                    >
                      {data.sentiment.replace("_", "-")}
                    </span>
                  )}
                  {data.market_impact && (
                    <span className="rounded-full border border-white/20 bg-white/10 px-2 py-0.5 text-xs text-white/80">
                      {data.market_impact} impact
                    </span>
                  )}
                  {data.topics.map((topic) => (
                    <span
                      key={topic}
                      className="rounded-full border border-cyan-300/30 bg-cyan-400/10 px-2 py-0.5 text-xs text-cyan-100"
                    >
                      {topic}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {data.status === "ok" ? (
              <div className="space-y-3 leading-relaxed">
                {data.paragraphs.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            ) : (
              <p className="rounded-lg border border-amber-300/30 bg-amber-400/10 px-3 py-2 text-amber-100">
                The full article can't be shown here. {data.reason}
              </p>
            )}
          </>
        )}
      </div>

      <div className="border-t border-white/20 px-5 py-3">
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 px-4 py-2 text-sm font-medium text-white shadow hover:from-cyan-400 hover:to-blue-500"
        >
          Open original ↗
        </a>
      </div>
    </aside>
  );
}
