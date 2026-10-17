import { Fragment, type ReactNode } from "react";
import { CitationTag } from "../../components/ui";
import type { DocSection } from "../../components/export/CompiledDocument";
import type { IpsPart, PackSection } from "../../types/arc";

/** Render text, turning [TAG-123] markers into citation chips. */
export function Tagged({ text }: { text: string }) {
  const parts = text.split(/(\[[A-Z]+[A-Za-z0-9-]*\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[[A-Z]+[A-Za-z0-9-]*\]$/.test(p) ? <CitationTag key={i} tag={p.slice(1, -1)} /> : <Fragment key={i}>{p}</Fragment>,
      )}
    </>
  );
}

const isBullet = (l: string) => /^\s*(•|-|\*)\s+/.test(l);
/** Section text always renders as bullets: bullet lines stay, prose is split into sentences. */
export function toBulletLines(text: string): string[] {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.some(isBullet)) return lines.map((l) => l.replace(/^\s*(•|-|\*)\s+/, ""));
  return lines.flatMap((l) => l.split(/(?<=\.)\s+(?=[A-Z[])/)).map((x) => x.replace(/\.$/, "").trim()).filter(Boolean);
}
export function BodyView({ text }: { text: string }) {
  const items = toBulletLines(text);
  if (items.length === 0) return <span className="text-ink-muted">Not yet completed.</span>;
  return (
    <ul className="list-disc space-y-2 pl-5">
      {items.map((l, i) => <li key={i} className="break-words [overflow-wrap:anywhere]"><Tagged text={l} /></li>)}
    </ul>
  );
}

export const onboardingSteps = [
  { label: "Upload notes" }, { label: "Summary" }, { label: "IPS draft" }, { label: "Send to IC" }, { label: "Approve G1" },
];

export const fmtDate = (s: string) =>
  new Date(s).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });

export const ipsToSections = (parts: IpsPart[], override: Record<number, string> = {}): DocSection[] =>
  parts.map((p) => {
    const body = (override[p.part] ?? p.body).trim();
    return { n: p.part, title: p.title, owner: p.owner, complete: p.status !== "blank" && body.length > 0, body: <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{body}</span> };
  });

/** Section text with an optional visual: profile (1) puts bullets and chart side by side. */
export function SectionBody({ n, text, extra }: { n: number; text: string; extra?: ReactNode }) {
  if (n === 1 && extra) {
    return (
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <BodyView text={text} />
        <div className="min-w-0">{extra}</div>
      </div>
    );
  }
  return <><BodyView text={text} />{extra && <div className="mt-8">{extra}</div>}</>;
}

/** `touched` = sections the RM wrote or applied from Geneva: they count as complete. `extras` = visuals shown under a section's text. */
export const packToSections = (pack: PackSection[], override: Record<number, string> = {}, touched: number[] = [], extras: Record<number, ReactNode> = {}): DocSection[] =>
  pack.map((x) => {
    const body = override[x.n] ?? x.body;
    return { n: x.n, title: x.title, owner: x.owner, complete: touched.includes(x.n) ? body.trim().length > 0 : x.status !== "draft" && body.trim().length > 0, body: <SectionBody n={x.n} text={body} extra={extras[x.n]} />, wide: x.n === 1 || x.n === 7 };
  });
