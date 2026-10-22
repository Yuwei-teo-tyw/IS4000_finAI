import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { arcApi, PortfolioAgentError } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, NextAction, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { classColor } from "../../components/portfolio/allocation";
import { DASH, pct, sgdAmt } from "../../components/portfolio/paFormat";
import type { PaBucketChoice, PaCombinedReview } from "../../types/portfolio";
import { returnIpsToRm, savePmProgress, usePmProgress, useIpsReturned } from "../../services/workflowStore";
import { ASSETS, BackLink, Msg } from "./pmHelpers";
import { PM_STEPS } from "./pmSteps";
import { BucketTabs } from "./BucketTabs";
import { bucketStatus, currentStep, isDone } from "./saaState";

const CHECK_TONE = { PASS: "green", FAIL: "red", UNVERIFIED: "amber", NOT_APPLICABLE: "grey" } as const;

type Review = { phase: "idle" } | { phase: "loading" } | { phase: "ready"; review: PaCombinedReview } | { phase: "error"; error: PortfolioAgentError };

/** Step 3 of the IPS SAA request: the three bucket portfolios as one client portfolio, then send back to the RM. */
export default function SaaReview() {
  const { clientId = "ser" } = useParams();
  const navigate = useNavigate();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const inputs = useAsync(() => arcApi.getBucketInputs(clientId), [clientId]);
  const progress = usePmProgress(clientId);
  const sent = useIpsReturned(clientId);
  const drafts = progress.saaBuckets ?? {};
  const [state, setState] = useState<Review>({ phase: "idle" });

  const ready = !!inputs && inputs.every((i) => isDone(bucketStatus(i, drafts[i.id])));
  const choices: PaBucketChoice[] = (inputs ?? []).filter((i) => i.amount > 0 && drafts[i.id]?.requestId && drafts[i.id]?.optionId)
    .map((i) => ({ bucket: i.id, request_id: drafts[i.id]!.requestId!, option_id: drafts[i.id]!.optionId!, weights: drafts[i.id]!.weights ?? null }));
  const key = JSON.stringify(choices);

  useEffect(() => {
    if (!ready || !client || !choices.length) return;
    let live = true;
    setState({ phase: "loading" });
    arcApi.reviewCombined(choices, client.aumSgd)
      .then((review) => { if (live) setState({ phase: "ready", review }); })
      .catch((e) => { if (live) setState({ phase: "error", error: e instanceof PortfolioAgentError ? e : new PortfolioAgentError("SERVER", String(e)) }); });
    return () => { live = false; };
  }, [ready, key, client?.aumSgd]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!client || !inputs) return <Loading />;
  // The review opens only after every bucket is confirmed; until then, go to the bucket the PM is on.
  if (!ready) return <Navigate to={`/pm/requests/${clientId}/saa/${currentStep(inputs, drafts)}`} replace />;
  const review = state.phase === "ready" ? state.review : null;

  const send = () => {
    if (!review) return;
    const whole = Object.fromEntries(review.classes.map((c) => [c.asset_class, c.pct]));
    savePmProgress(clientId, {
      saaWeights: whole, saaOriginal: whole, saa: ASSETS.map((a) => whole[a] ?? 0),
      saaTemplate: review.buckets.map((b) => `${b.label} ${b.option_id}`).join(" · "),
    });
    returnIpsToRm(clientId);
    navigate("/pm/inbox");
  };

  return (
    <div>
      <PageHeader eyebrow={`${client.name} · Request`} title="Combined review"
        subtitle="The portfolio chosen for each bucket, checked together as the client's whole portfolio."
        actions={<GateChip id="G2" state={sent ? "pending" : "not_started"} />} />
      <Stepper steps={PM_STEPS} current={sent ? 3 : 2} />
      <BucketTabs clientId={clientId} inputs={inputs} drafts={drafts} current="review" />

      {state.phase === "loading" && <p className="animate-geneva-flow py-6 text-lg font-light">Checking the three buckets together…</p>}
      {state.phase === "error" && <Msg ok={false}>{state.error.message} {state.error.details.join(" ")}</Msg>}
      {review && <ReviewBody review={review} />}

      {sent ? <Msg ok>SAA sent back to the RM for the IPS. Awaiting RM review.</Msg>
        : review && review.valid ? (
          <NextAction title="All buckets and combined checks pass"
            body="Send the 3L allocation and the SAA for each bucket back to the RM for the IPS. Nothing is traded; the RM and client still approve it."
            action={<Button variant="gold" onClick={send}>Send back to RM</Button>} />
        ) : (
          <NextAction title={state.phase === "loading" ? "Checking…" : "Blocked: fix the failing checks"}
            body={"Open the bucket named in the failing check, adjust it, and come back."}
            action={<Button disabled>Send back to RM</Button>} />
        )}
      <BackLink to={`/pm/requests/${clientId}/saa/legacy`}>Back to the buckets</BackLink>
    </div>
  );
}

function ReviewBody({ review }: { review: PaCombinedReview }) {
  const c = review.combined;
  const metrics: [string, string, string][] = [
    ["Expected return (products, after fees)", pct(c.product_expected_return_pct, 2), "Amount-weighted, house assumptions"],
    ["Volatility (model)", pct(c.model_volatility_pct), "House assumptions on the combined mix"],
    ["Stress drawdown", pct(c.stress_drawdown_pct), "All buckets falling together"],
    ["Growth assets", pct(c.growth_asset_share_pct), "Equities, hedge funds, private markets"],
    ["Ongoing fees", pct(c.estimated_annual_fee_pct, 2), "Product management fees"],
    ["Unhedged foreign currency", pct(c.foreign_currency_exposure_pct), "Products"],
    ["Deals daily or weekly", pct(c.fast_dealing_share_pct, 0), "Share of the whole portfolio"],
    ["Largest single product", c.largest_product ? `${pct(c.largest_product_pct)} · ${c.largest_product}` : DASH, "Counted once across buckets"],
  ];
  return (
    <>
      <Section title="Allocation across the three buckets" hint="Amounts per asset class in each bucket, and the whole portfolio. Each bucket was built for its own purpose, so a portfolio that suits one bucket is not interchangeable with another's.">
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-ink-muted">
                <tr className="border-b border-hairline">
                  <th className="py-3 pr-4 font-semibold">Asset class</th>
                  {review.buckets.map((b) => (
                    <th key={b.bucket} className="py-3 pr-4 text-right font-semibold">
                      {b.label}<span className="block font-normal">{b.option_id} · {b.option_name} · {sgdAmt(b.amount)}</span>
                    </th>
                  ))}
                  <th className="py-3 text-right font-semibold">Whole portfolio</th>
                </tr>
              </thead>
              <tbody>
                {review.classes.map((cl) => (
                  <tr key={cl.asset_class} className="border-b border-hairline">
                    <td className="py-3 pr-4"><span className="inline-flex items-center gap-2 text-ink"><i className="inline-block h-2.5 w-2.5" style={{ background: classColor(cl.asset_class) }} aria-hidden />{cl.asset_class}</span></td>
                    {review.buckets.map((b) => <td key={b.bucket} className="py-3 pr-4 text-right text-ink-700">{cl.by_bucket[b.bucket] ? sgdAmt(cl.by_bucket[b.bucket]!) : DASH}</td>)}
                    <td className="py-3 text-right text-ink">{pct(cl.pct)} <span className="text-ink-muted">· {sgdAmt(cl.amount)}</span></td>
                  </tr>
                ))}
                <tr className="font-semibold">
                  <td className="py-3 pr-4 text-ink">Total</td>
                  {review.buckets.map((b) => <td key={b.bucket} className="py-3 pr-4 text-right text-ink">{sgdAmt(b.amount)} <span className="font-normal text-ink-muted">({b.share_pct}%)</span></td>)}
                  <td className="py-3 text-right text-ink">{sgdAmt(review.total_amount)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      <Section title="Whole-portfolio risk and checks" hint="What only shows up across buckets: the 3L total, and the client's overall drawdown, currency and concentration limits.">
        <div className="grid gap-10 xl:grid-cols-2">
          <Card>
            <dl className="grid gap-5 sm:grid-cols-2">
              {metrics.map(([label, value, basis]) => (
                <div key={label}><dt className="text-xs text-ink-muted">{label}</dt><dd className="mt-1 text-lg font-light text-ink">{value}</dd><dd className="text-xs text-ink-muted">{basis}</dd></div>
              ))}
            </dl>
          </Card>
          <Card>
            <ul className="flex flex-col gap-3 text-sm" aria-live="polite">
              {review.checks.map((ch) => (
                <li key={ch.constraint} className="flex flex-wrap items-center gap-3">
                  <Badge tone={CHECK_TONE[ch.status]}>{ch.status.replace("_", " ").toLowerCase()}</Badge>
                  <span className="text-ink">{ch.constraint}</span>
                  <span className="w-full text-ink-muted">{ch.detail}{ch.actual !== null && ch.limit !== null ? ` (${+ch.actual.toFixed(2)} vs limit ${ch.limit})` : ""}</span>
                </li>
              ))}
            </ul>
            <div className="mt-6 space-y-1 text-xs text-ink-muted">{review.notes.map((n) => <p key={n}>{n}</p>)}</div>
          </Card>
        </div>
      </Section>
    </>
  );
}
