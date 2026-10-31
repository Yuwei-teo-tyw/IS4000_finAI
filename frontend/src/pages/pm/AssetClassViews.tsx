import { Card, Loading, PageHeader, Section, Table, useAsyncResult } from "../../components/ui";
import { AgreementBadge, ViewBadge } from "../../components/product/AssetViewParts";
import { arcApi, assetClassSlug, ProductRecommenderError } from "../../services/arcApi";
import { Link } from "react-router-dom";

/** All seven asset classes: the CIO's stance and the agent's own, side by side. */
export default function AssetClassViews() {
  const { data: rows, error } = useAsyncResult(() => arcApi.getAssetClassViews(), []);
  return (
    <div>
      <PageHeader eyebrow="Market research" title="Asset Class Views" subtitle="The agent's own view on each asset class beside the CIO house view. Open one for the full analysis." />
      {error ? (
        <Card className="!p-8"><p className="text-base text-ink-700">{error.message}</p>
          {error instanceof ProductRecommenderError && error.details.map((d) => <p key={d} className="mt-2 text-sm text-ink-muted">{d}</p>)}</Card>
      ) : !rows ? <Loading /> : (
        <Section title="CIO and agent views" hint="A difference is a prompt to check with the CIO desk, not a change to the house view.">
          <Table head={["Asset class", "CIO house view", "Agent view", "Agreement", ""]} rows={rows.map((r) => [
            <span className="font-semibold">{r.asset_class}</span>,
            <span className="flex flex-wrap items-center gap-2"><ViewBadge view={r.cio_view} /><span className="text-ink-muted">{r.cio_term}</span></span>,
            r.agent_view ? <span className="flex flex-wrap items-center gap-2"><ViewBadge view={r.agent_view} /><span className="text-ink-muted">{r.agent_confidence} confidence</span></span> : "Unavailable",
            r.agreement ? <AgreementBadge status={r.agreement} /> : "–",
            <Link to={`/pm/asset-views/${assetClassSlug(r.asset_class)}`} className="font-semibold text-ink underline underline-offset-4">Open</Link>,
          ])} />
        </Section>
      )}
    </div>
  );
}
