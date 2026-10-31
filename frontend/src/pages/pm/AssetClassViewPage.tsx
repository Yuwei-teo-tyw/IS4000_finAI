import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { BulletList, BulletTextarea, Button, Card, CitationTag, Loading, NextAction, PageHeader, Section, Table, useAsync, useAsyncResult } from "../../components/ui";
import { RefLine, SegmentBadge, ViewHeadline } from "../../components/product/AssetViewParts";
import { arcApi, ProductRecommenderError } from "../../services/arcApi";
import { setActiveClientId, useActiveClientId } from "../../layouts/navConfig";
import { acceptAssetView, useAcceptedAssetView } from "../../services/workflowStore";
import type { PrAssetView } from "../../types/productRecommender";
import { ClientStrip } from "../../components/product/ClientStrip";

/** The text the reviewer accepts: headline and thesis as "• ... [TAG]" bullets. */
function draftViewText(v: PrAssetView): string {
  const cio = v.cio_view;
  const lines = [
    `CIO house view on ${v.asset_class.toLowerCase()}: ${cio.view} (${cio.cio_term}) [${cio.citation_id}]`,
    ...(v.agent_view
      ? [`Agent view: ${v.agent_view.view} with ${v.agent_view.confidence.toLowerCase()} confidence; ${v.agreement?.status === "aligned" ? "agrees with" : "differs from"} the CIO`,
         ...v.agent_view.thesis_points.map((p) => `${p.text} ${p.refs.map((r) => `[${r}]`).join(" ")}`.trim())]
      : []),
  ];
  return lines.map((l) => `• ${l}`).join("\n");
}

type Tab = "overview" | "market" | "risks" | "products" | "sources";
const TABS: [Tab, string][] = [["overview", "Overview"], ["market", "Market"], ["risks", "Risks"], ["products", "Products"], ["sources", "Sources"]];
const fmt = (x: number | null, unit = "") => (x === null ? "–" : `${x >= 0 ? "+" : ""}${x}${unit}`);

function Overview({ v }: { v: PrAssetView }) {
  const groups = [...new Set(v.segments.map((s) => s.group))];
  return (
    <>
      {v.agent_view && (
        <Section title="Thesis" hint="Why the agent reads the class this way. Every point cites its data.">
          <ul className="list-disc space-y-2 pl-5 text-[16px] leading-7 text-ink-700">{v.agent_view.thesis_points.map((p) => <li key={p.text}><RefLine r={p} /></li>)}</ul>
        </Section>
      )}
      <Section title="Segment views" hint="Preference within the asset class, relative to the class as a whole.">
        <Table head={["Group", "Segment", "View", "Why"]} rows={groups.flatMap((g) => v.segments.filter((s) => s.group === g).map((s) => [
          <span className="text-ink-muted">{s.group}</span>,
          <span className="font-semibold">{s.segment}</span>,
          <SegmentBadge view={s.view} />,
          <span className="block max-w-md text-ink-700">{s.reason} {s.refs.map((t) => <CitationTag key={t} tag={t} />)}</span>,
        ]))} />
      </Section>
    </>
  );
}

function Market({ v }: { v: PrAssetView }) {
  return (
    <>
      <Section title="Market snapshot" hint="The series behind the agent view. 3-month changes are in percentage points for rates and percent for prices.">
        <Table head={["Indicator", "Value", "1 month", "3 months", "10-year percentile", "Effect"]} rows={v.snapshot.map((s) => [
          <span className="block max-w-56"><span className="font-semibold">{s.name}</span> <CitationTag tag={s.id} /><span className="block text-[13px] text-ink-muted">{s.why}</span></span>,
          `${s.value}${s.unit === "%" ? "%" : s.unit === "index" ? "" : ` ${s.unit}`}`,
          fmt(s.change_1m), fmt(s.change_3m),
          s.percentile_10y === null ? "–" : `${s.percentile_10y}`,
          s.effect === "supports" ? "Supports" : s.effect === "weighs" ? "Weighs on" : "Neutral",
        ])} />
      </Section>
      <Section title="Drivers and catalysts">
        <ul className="list-disc space-y-2 pl-5 text-[16px] leading-7 text-ink-700">{v.drivers.map((d) => <li key={d.text}><RefLine r={d} /></li>)}</ul>
      </Section>
      <Section title="Scenarios" hint="What would move the agent view. No price targets or forecasts.">
        <div className="grid gap-6 md:grid-cols-3">{v.scenarios.map((s) => (
          <Card key={s.case} className="!p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">{s.case}</p>
            <p className="mt-3 text-[15px] leading-6 text-ink-700">{s.description}</p>
            {s.trigger && <p className="mt-3 text-[14px] text-ink-muted">Trigger: {s.trigger.condition} <CitationTag tag={s.trigger.indicator} /></p>}
            <p className="mt-3 text-[15px] font-semibold">{s.stance_implication}</p>
          </Card>
        ))}</div>
      </Section>
      <Section title="What would change the view">
        <ul className="list-disc space-y-2 pl-5 text-[16px] leading-7 text-ink-700">{v.watch_items.map((w) => <li key={w.text}><RefLine r={w} /></li>)}</ul>
      </Section>
    </>
  );
}

function Products({ v }: { v: PrAssetView }) {
  const f = v.implementation.fees;
  const lens = v.client_lens;
  return (
    <>
      <Section title="Implementation from the shelf" hint={`Fees for this class range ${f.min_pct ?? "–"}% to ${f.max_pct ?? "–"}% (median ${f.median_pct ?? "–"}%), for information only and never used to rank.`}>
        <Table head={["Product", "Segment", "Risk", "Dealing", "Currency"]} rows={v.implementation.products.map((p) => [
          <span className="block max-w-64 font-semibold">{p.product_name}</span>, p.segment, p.risk_rating === null ? "–" : `${p.risk_rating} of 5`,
          (p.liquidity ?? "–").replace("_", " ").toLowerCase(), `${p.currency}${p.currency_hedged ? ", hedged" : ""}`,
        ])} />
      </Section>
      {lens && (
        <Section title="For this client" hint="From the same suitability gate the Product Recommender uses.">
          <BulletList className="!text-base" text={[
            `• Risk level ${lens.risk_level ?? "not established"}; ${lens.eligible} of ${v.implementation.products.length} products in this class pass the suitability gate.`,
            ...Object.entries(lens.excluded).map(([code, n]) => `• ${n} excluded: ${code.replace(/_/g, " ").toLowerCase()}.`),
            `• Segments this client can access: ${lens.accessible_segments.join(", ") || "none"}.`,
            ...(lens.current_weight_pct !== null ? [`• Current weight in ${v.asset_class.toLowerCase()}: ${lens.current_weight_pct}%.`] : []),
          ].join("\n")} />
        </Section>
      )}
    </>
  );
}

function Sources({ v }: { v: PrAssetView }) {
  const d = v.data_quality;
  return (
    <Section title="Sources and data quality">
      <BulletList className="!text-base" text={[
        `• CIO house view as of ${d.house_view_as_of} [${v.cio_view.citation_id}].`,
        `• Market data: ${d.market_source.toLowerCase()} Market Researcher run ${d.market_researcher_run_id ?? "n/a"}, as of ${d.market_as_of ?? "n/a"}, quality ${d.market_quality ?? "n/a"}.`,
        ...(v.agent_view ? [`• ${v.agent_view.coverage.available} of ${v.agent_view.coverage.mapped} mapped series available.`] : []),
        ...(d.stale_indicators.length ? [`• Stale: ${d.stale_indicators.join(", ")}.`] : []),
        ...(d.missing_indicators.length ? [`• Missing: ${d.missing_indicators.join(", ")}.`] : []),
        ...v.caveats.map((c) => `• ${c}`),
        `• Generated ${new Date(v.generated_at).toLocaleString()}. ${v.narrative_source === "llm"
          ? "Text written by AI from the engine's analysis and checked against it; every stance and number is the engine's."
          : "Text is rule-based."}`,
      ].join("\n")} />
    </Section>
  );
}

export default function AssetClassViewPage() {
  const { assetClass = "fixed-income" } = useParams();
  const [params] = useSearchParams();
  const clientId = useActiveClientId();
  const urlClient = params.get("client");
  useEffect(() => { if (urlClient) setActiveClientId(urlClient); }, [urlClient]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const { data: v, error } = useAsyncResult(() => arcApi.getAssetClassView(assetClass, clientId), [assetClass, clientId]);
  const [tab, setTab] = useState<Tab>("overview");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const accepted = useAcceptedAssetView(clientId, v?.asset_class ?? assetClass);

  if (error) {
    return (
      <div>
        <PageHeader eyebrow="Asset class view" title="Unavailable" />
        <Card className="!p-8"><p className="text-base text-ink-700">{error.message}</p>
          {error instanceof ProductRecommenderError && error.details.map((d) => <p key={d} className="mt-2 text-sm text-ink-muted">{d}</p>)}</Card>
      </div>
    );
  }
  if (!v) return <Loading />;
  const accept = (text: string, edited: boolean) => {
    acceptAssetView(clientId, v.asset_class, { text, edited, agentView: v.agent_view?.view ?? "n/a", cioView: v.cio_view.view });
    setEditing(false);
  };

  return (
    <div>
      <PageHeader eyebrow="Asset class view" title={v.asset_class} subtitle="The agent's own analysis beside the CIO house view. The CIO view stays the official one." />
      <ClientStrip client={client} />
      <div className="mb-12"><ViewHeadline v={v} /></div>
      <div role="tablist" className="mb-10 flex flex-wrap gap-8 border-b border-hairline">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`-mb-px cursor-pointer border-b-2 pb-3 text-base ${tab === k ? "border-brand font-semibold text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}>{label}</button>
        ))}
      </div>
      {tab === "overview" && <Overview v={v} />}
      {tab === "market" && <Market v={v} />}
      {tab === "risks" && (
        <Section title="Risks to the view">
          <ul className="list-disc space-y-2 pl-5 text-[16px] leading-7 text-ink-700">{v.risks.map((r) => <li key={r.text}><RefLine r={r} /></li>)}</ul>
        </Section>
      )}
      {tab === "products" && <Products v={v} />}
      {tab === "sources" && <Sources v={v} />}

      {editing && (
        <Section title="Edit before accepting" hint="Keep the citation tags. Your text is stored for this client; nothing is sent.">
          <BulletTextarea className="!border-brand" rows={8} aria-label="Asset class view text" value={draft} onChange={setDraft} />
          <div className="mt-4 flex gap-4">
            <Button onClick={() => accept(draft, true)} disabled={!draft.trim()}>Accept edited view</Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </Section>
      )}
      {!editing && (
        <NextAction
          title={accepted ? `Accepted ${new Date(accepted.acceptedAt).toLocaleString()}${accepted.edited ? " (edited)" : ""}` : "Accept or edit this view"}
          body={accepted ? "Stored for this client for the pack and product reasons. Accept again to replace it." : "The agent drafts; you decide. Accepting stores the text for this client and sends nothing."}
          action={<span className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => { setDraft(accepted?.text ?? draftViewText(v)); setEditing(true); }}>Edit</Button>
            <Button onClick={() => accept(draftViewText(v), false)} disabled={!v.agent_view}>Accept view</Button>
          </span>} />
      )}
    </div>
  );
}
