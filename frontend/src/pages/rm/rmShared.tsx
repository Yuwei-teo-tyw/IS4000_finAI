import { Fragment } from "react";
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

export const packToSections = (pack: PackSection[], override: Record<number, string> = {}): DocSection[] =>
  pack.map((x) => {
    const body = override[x.n] ?? x.body;
    return { n: x.n, title: x.title, owner: x.owner, complete: x.status !== "draft" && body.trim().length > 0, body: <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]"><Tagged text={body} /></span> };
  });
