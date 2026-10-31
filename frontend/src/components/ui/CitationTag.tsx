import { lookupCitation } from "../../services/citationRegistry";

const esc = (t: string) => t.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);

/** Opens what the citation points to in a new window: the source document or page when it has a URL, else a page with the id, date, title and verbatim passage. */
function openCitation(tag: string) {
  const info = lookupCitation(tag);
  if (info?.url) { window.open(info.url, "_blank", "noopener"); return; }
  const rows = info
    ? [info.title && `<h1>${esc(info.title)}</h1>`, `<p class="meta">${esc(tag)}${info.date ? ` &middot; ${esc(info.date)}` : ""}</p>`,
       info.passage && `<blockquote>${esc(info.passage)}</blockquote>`, info.note && `<p>${esc(info.note)}</p>`]
    : [`<h1>${esc(tag)}</h1>`, "<p>Source details are not available for this reference.</p>"];
  const html = `<!doctype html><meta charset="utf-8"><title>${esc(tag)}</title><style>body{font:16px/1.6 "Source Sans 3",system-ui,sans-serif;max-width:720px;margin:48px auto;padding:0 24px;color:#1c1c1c}h1{font-weight:300;font-size:28px;margin:0 0 4px}.meta{color:#666;margin:0 0 24px}blockquote{margin:0;padding-left:16px;border-left:3px solid #ccc}</style>${rows.filter(Boolean).join("")}`;
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Citation chip. Hand cursor on hover; click opens the cited source in a new window. */
export function CitationTag({ tag }: { tag: string }) {
  return (
    <button type="button" onClick={() => openCitation(tag)} title="Open source in a new window"
      className="mr-1 inline-block cursor-pointer rounded-sm bg-surface-300 px-2 py-0.5 text-xs font-medium text-ink-muted outline-none hover:bg-surface-400 hover:text-ink focus-visible:ring-1 focus-visible:ring-ink-muted">[{tag}]</button>
  );
}

/** Row of chips for every [TAG] in a text (shown beside editable text, where clicking inner text is not possible). */
export function CitationChips({ text }: { text: string }) {
  const tags = [...new Set([...text.matchAll(/\[([A-Za-z0-9-]+)\]/g)].map((m) => m[1]))];
  if (!tags.length) return null;
  return <div className="mt-1 flex flex-wrap items-center gap-y-1"><span className="mr-2 text-xs text-ink-muted">Sources</span>{tags.map((t) => <CitationTag key={t} tag={t} />)}</div>;
}
