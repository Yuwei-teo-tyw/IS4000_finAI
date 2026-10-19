export function CitationTag({ tag }: { tag: string }) {
  return <span className="mr-1 inline-block rounded-sm bg-surface-300 px-2 py-0.5 text-xs font-medium text-ink-muted">[{tag}]</span>;
}
