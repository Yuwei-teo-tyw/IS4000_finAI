import { Children, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CitationTag } from "../ui";

/** A source link in a backend answer, identified by the Market Researcher run that cited it. */
export interface SourceRef { runId: string; url: string; title: string }

/** Render "[TAG]" markers in plain strings as citation tags. */
export function Tagged({ text }: { text: string }) {
  return <>{text.split(/(\[[A-Za-z0-9-]+\])/).map((p, i) => /^\[[A-Za-z0-9-]+\]$/.test(p) ? <CitationTag key={i} tag={p.slice(1, -1)} /> : <span key={i}>{p}</span>)}</>;
}

const tagged = (children: ReactNode) => Children.map(children, (c) => (typeof c === "string" ? <Tagged text={c} /> : c));
const textOf = (children: ReactNode): string =>
  Children.toArray(children).map((c) => (typeof c === "string" || typeof c === "number" ? String(c) : "")).join("");

/**
 * A LangGraph answer (Markdown) in Geneva's type scale: light weight, headings 26px, body and lists 16-17px,
 * tables styled like the ui `Table`. Source links of a Market Researcher run open the reader panel.
 */
export function GenevaMarkdown({ text, runId, onOpenSource }: { text: string; runId: string | null; onOpenSource?: (s: SourceRef) => void }) {
  const components: Components = {
    h1: ({ children }) => <h4 className="text-[26px] tracking-tight text-ink">{children}</h4>,
    h2: ({ children }) => <h4 className="text-[26px] tracking-tight text-ink">{children}</h4>,
    h3: ({ children }) => <h4 className="text-[22px] tracking-tight text-ink">{children}</h4>,
    p: ({ children }) => <p className="text-[17px] leading-8 text-ink-700">{tagged(children)}</p>,
    ul: ({ children }) => <ul className="list-disc space-y-2 pl-5 text-[17px] leading-7 text-ink-700">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal space-y-2 pl-5 text-[17px] leading-7 text-ink-700">{children}</ol>,
    li: ({ children }) => <li>{tagged(children)}</li>,
    strong: ({ children }) => <strong className="text-ink">{children}</strong>,
    em: ({ children }) => <em className="text-[15px] text-ink-muted">{children}</em>,
    code: ({ children }) => <code className="text-[15px] text-ink">{children}</code>,
    hr: () => <hr className="border-hairline" />,
    table: ({ children }) => (
      <div className="overflow-x-auto rounded-lg border border-hairline bg-surface-100">
        <table className="w-full text-left text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-surface-200 text-ink-muted">{children}</thead>,
    tr: ({ children }) => <tr className="border-t border-hairline first:border-t-0">{children}</tr>,
    th: ({ children }) => <th className="px-6 py-4 text-xs">{children}</th>,
    td: ({ children }) => <td className="px-6 py-4 align-top">{children}</td>,
    a: ({ href, children }) => {
      const external = !!href && /^https?:\/\//.test(href);
      const opensPanel = external && !!runId && !!onOpenSource;
      return (
        <a
          href={href}
          target={external ? "_blank" : undefined}
          rel={external ? "noopener noreferrer" : undefined}
          className="text-ink underline decoration-hairline-strong underline-offset-4 hover:decoration-ink"
          onClick={(e) => {
            // Plain clicks open the reader panel; modified clicks still open the original page.
            if (!opensPanel || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            onOpenSource!({ runId: runId!, url: href!, title: textOf(children) });
          }}
        >
          {children}
        </a>
      );
    },
  };
  return (
    <div className="min-w-0 space-y-6 font-light">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>{text}</Markdown>
    </div>
  );
}
