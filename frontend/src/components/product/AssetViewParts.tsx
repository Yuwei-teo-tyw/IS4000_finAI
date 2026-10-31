import { Badge, CitationTag } from "../ui";
import type { PrAgreement, PrAssetView, PrRef, PrSegmentView, PrView } from "../../types/productRecommender";

const viewTone = { Buy: "green", Hold: "amber", Sell: "red" } as const;
const segmentTone = { "Most preferred": "green", Neutral: "grey", "Least preferred": "red" } as const;
const agreementTone = { aligned: "green", differs: "amber", opposed: "red" } as const;
const agreementText = { aligned: "Agrees with the CIO", differs: "Differs from the CIO", opposed: "Opposes the CIO" } as const;

export const ViewBadge = ({ view }: { view: PrView }) => <Badge tone={viewTone[view]}>{view}</Badge>;
export const SegmentBadge = ({ view }: { view: PrSegmentView }) => <Badge tone={segmentTone[view]}>{view}</Badge>;
export const AgreementBadge = ({ status }: { status: PrAgreement }) => <Badge tone={agreementTone[status]}>{agreementText[status]}</Badge>;

/** Plain text with inline "[TAG]" markers shown as citation tags. */
export function Tagged({ text }: { text: string }) {
  return <>{text.split(/(\[[A-Za-z0-9-]+\])/).map((p, i) => /^\[[A-Za-z0-9-]+\]$/.test(p) ? <CitationTag key={i} tag={p.slice(1, -1)} /> : <span key={i}>{p}</span>)}</>;
}

/** A cited point: text, then its refs as citation tags. */
export function RefLine({ r }: { r: PrRef }) {
  return <>{r.text} {r.refs.map((t) => <CitationTag key={t} tag={t} />)}</>;
}

/** CIO house view and the agent's own view side by side. The agent view is always labelled and never shown alone. */
export function ViewHeadline({ v, compact = false }: { v: PrAssetView; compact?: boolean }) {
  const cio = v.cio_view;
  const a = v.agent_view;
  const label = "text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted";
  return (
    <div className={`grid gap-6 ${compact ? "" : "md:grid-cols-2"}`}>
      <div className="rounded-sm border border-hairline-strong p-5">
        <p className={label}>CIO house view</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <ViewBadge view={cio.view} />
          <span className="text-[15px] text-ink-700">{cio.cio_term} · {cio.confidence} confidence</span>
          <CitationTag tag={cio.citation_id} />
        </div>
        {cio.basis !== "rated" && (
          <p className="mt-2 text-[13px] text-ink-muted">{cio.basis === "interpreted" ? "Read from the report's prose, not a stated rating." : "Not covered by the report."}</p>
        )}
        {!compact && <p className="mt-3 text-[15px] leading-6 text-ink-700">{cio.rationale}</p>}
      </div>
      <div className="rounded-sm border border-hairline-strong p-5">
        <p className={label}>{a?.label ?? "Agent view (analysis, not the CIO house view)"}</p>
        {a ? (
          <>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <ViewBadge view={a.view} />
              <span className="text-[15px] text-ink-700">{a.confidence} confidence · score {a.score >= 0 ? "+" : ""}{a.score.toFixed(2)}</span>
              {v.agreement && <AgreementBadge status={v.agreement.status} />}
            </div>
            {!compact && <p className="mt-3 text-[15px] leading-6 text-ink-700">{a.thesis}</p>}
          </>
        ) : <p className="mt-3 text-[15px] text-ink-700">Not available: {v.agent_view_unavailable_reason}</p>}
      </div>
      {v.agreement?.explanation && <p className={`text-[15px] leading-6 text-ink-700 ${compact ? "" : "md:col-span-2"}`}><Tagged text={v.agreement.explanation} /></p>}
    </div>
  );
}
