import { useState } from "react";
import { Check } from "lucide-react";
import { useParams } from "react-router-dom";
import { SignatureBlock, BulletList, BulletTextarea, toBulletText, Button, Card, GateChip, NextAction, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import ProfessionaliseReview from "../../components/geneva/ProfessionaliseReview";
import { ClientStrip, PS_STEPS, loadSelection, saveSelection } from "./psShared";
import { sendFinalised } from "../../services/workflowStore";
import { savePackDraft, setSectionDone, useSignatures } from "../../services/packDraftStore";
import { toBulletItems } from "../../utils/bullets";

const draftReason = (p: { product: string; assetClass: string; industryFocus: string; confidencePct: number }) => [
  `Suitability: ${p.product} fits the client's IPS objectives and stays within the agreed risk limit.`,
  `Asset class: the ${p.assetClass} exposure supports the target allocation and diversification.`,
  `Rationale: ${p.industryFocus || "aligned with the current house view"}.`,
  `Confidence: the assistant rates this recommendation at ${p.confidencePct}% based on cited sources.`,
  "Cost: the fee was reviewed for transparency only and was not used to rank this product.",
].map((l) => `• ${l}`).join("\n");

/** Deterministic, offline synthetic reason (bullet format with citation tags) for the demo. */
const syntheticReason = (p: { product: string; assetClass: string; industryFocus: string; confidencePct: number }) => {
  const h = [...p.product].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 9973, 7);
  const cio = ["CIO-2026Q4-02", "CIO-2026Q4-03", "CIO-2026Q4-05"][h % 3];
  return [
    `${p.product} suits the client's IPS objectives and stays inside the agreed risk limit [IPS-v2].`,
    `The ${p.assetClass} exposure supports the target allocation and diversification [${cio}].`,
    `${p.industryFocus || "Aligned with the current house view"} [MKT-0142].`,
    `Suitability was checked first; the fee was shown for transparency only and not used to rank [PRD-FI-007].`,
  ].map((l) => `• ${l}`).join("\n");
};

const IC_RECEIVES = [
  "The approved product list with the Product Specialist's reason for each product.",
  "Fees and risk ratings, shown for information and never used to rank products.",
  "Citation tags linking every statement to its source document.",
  "The market views and house view extracts behind the shortlist.",
  "A clear G3 status so the IC can propose the tactical allocation for the quarterly pack.",
];
const SENT_NOTES = [
  "The IC can now propose the tactical allocation.",
  "If you edit this list after sending, G3 reopens.",
  "G2 and G4 are reset, so the IC and RM approve again.",
  "The Relationship Manager is notified once the IC completes the pack.",
  "Your reasons stay attached to each product for audit.",
];

export default function FinaliseProducts() {
  const { clientId = "jfr" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const products = useAsync(() => arcApi.getProducts(clientId), [clientId]);
  const [confirm, setConfirm] = useState(false);
  const [phase, setPhase] = useState<"reasons" | "geneva" | "preview">("reasons");
  const [applied, setApplied] = useState<Record<string, string> | null>(null);
  const [sent, setSent] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const [all] = useState(() => loadSelection(clientId));
  const [ticked, setTicked] = useState<string[]>(() => all.map((r) => r.product));
  const list = all.filter((r) => ticked.includes(r.product));
  /** Professional baseline: seeded Product.psReason when the product is on the shelf, else a generic suitability draft. */
  const baseline = (r: (typeof all)[number]) => (clientId === "jfr" ? products?.find((x) => x.name === r.product)?.psReason : undefined) ?? draftReason(r);
  const [activeProduct, setActiveProduct] = useState<string | null>(null);
  const current = list.find((r) => r.product === activeProduct) ?? list[0];
  const typed = (name: string) => (reasons[name] ?? "").trim().length > 0;
  /** What the IC receives: the professionalised text, else the baseline when nothing was typed, else the PS's own wording. */
  const finalReason = (r: (typeof all)[number]) => applied?.[r.product] ?? (typed(r.product) ? toBulletText(reasons[r.product]) : baseline(r));
  const typedList = list.filter((r) => typed(r.product));
  const signed = !!useSignatures(clientId).ps;
  const send = () => {
    const items = list.map((r) => ({ ...r, reason: finalReason(r) }));
    sendFinalised(clientId, items);
    // Pack section 5 (Product recommendations) so IC and RM read the same list.
    const body = items.map((i) => `• ${i.product}: ${toBulletItems(i.reason)[0] ?? i.industryFocus}`).join("\n");
    savePackDraft(clientId, 5, body, "ps");
    setSectionDone(clientId, 5, true, "ps");
    setSent(true);
  };
  const toggle = (name: string) => setTicked((cur) => {
    const next = cur.includes(name) ? cur.filter((x) => x !== name) : [...cur, name];
    saveSelection(clientId, all.filter((r) => next.includes(r.product)));
    return next;
  });

  if (sent) {
    return (
      <div>
        <PageHeader eyebrow="Product review · Done" title="Sent to the Investment Counsellor" actions={<GateChip id="G3" state="approved" />} />
        <Stepper steps={PS_STEPS} current={2} />
        <Card accent className="mb-12 !p-10">
          <h2 className="text-2xl">{list.length} products approved for {client?.name ?? "the client"}</h2>
          <BulletList className="mt-3 max-w-2xl !text-base" text={SENT_NOTES.map((n) => `• ${n}`).join("\n")} />
          <div className="mt-8"><Button to="/ps/inbox">Back to inbox</Button></div>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader eyebrow="Product review" title="Finalise & send" actions={<GateChip id="G3" state="pending" />} />
      <Stepper steps={PS_STEPS} current={1} />
      <ClientStrip client={client} />

      {phase === "geneva" && (
        <Section title="Professionalise your reasons" hint="Geneva rewrites your plain wording.">
          <ProfessionaliseReview clientId={clientId} role="ps" context="products"
            items={typedList.map((r) => ({ id: r.product, label: r.product, text: toBulletText(reasons[r.product]) }))}
            onApply={(out) => setApplied(Object.fromEntries(out.map((o) => [o.id, o.text])))} />
          <div className="mt-8 flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => setPhase("reasons")}>Back to reasons</Button>
            <Button onClick={() => setPhase("preview")}>{applied ? "Continue to preview" : "Skip and preview"}</Button>
          </div>
        </Section>
      )}

      {phase === "preview" && (
        <Section title="Preview what the IC will see">
          <div className="grid gap-8 md:grid-cols-[300px_1fr] md:items-start">
            <Card className="!p-5">
              <h2 className="text-base">Products</h2>
              <p className="mt-1 text-xs text-ink-muted">{list.length} to send to the IC</p>
              <p className="mt-3 flex items-center gap-2 text-xs text-ink-muted"><span className="inline-block h-3 w-5 border border-brand" />Reasons you wrote</p>
              <nav className="mt-4 flex flex-col gap-2">
                {list.map((p, idx) => (
                  <button key={p.product} onClick={() => setActiveProduct(p.product)}
                    className={`flex cursor-pointer items-center justify-between gap-3 rounded-sm border border-brand px-4 py-3.5 text-left text-sm transition-colors duration-300 ${current?.product === p.product ? "bg-surface-inverse text-ink-inverse" : "bg-surface-100 text-ink-700 hover:bg-surface-300"}`}>
                    <span className="min-w-0">{idx + 1}. {p.product}</span>
                    <Check size={16} className={`shrink-0 ${current?.product === p.product ? "text-ink-inverse" : "text-positive"}`} aria-label="Reason ready" />
                  </button>
                ))}
              </nav>
            </Card>
            {current && (
              <Card className="min-h-96 !border-brand !p-10">
                <div key={current.product} className="animate-geneva-in space-y-8">
                  <div className="min-w-0">
                    <h2 className="text-[28px] font-light tracking-tight">{list.indexOf(current) + 1}. {current.product}</h2>
                    <p className="mt-2 text-xs uppercase tracking-[0.14em] text-brand">You fill in this section</p>
                    <p className="mt-2 text-sm text-ink-muted">{current.assetClass} · {current.confidencePct}% confidence</p>
                  </div>
                  <div className="text-[17px] leading-8 text-ink-700"><BulletList className="!text-base" text={finalReason(current)} /></div>
                </div>
              </Card>
            )}
          </div>
          {typedList.length > 0 && !applied && <p className="mt-6 text-sm text-ink-muted">Some reasons are in your own wording.</p>}
          <div className="mt-8"><Button variant="secondary" onClick={() => setPhase("reasons")}>Back to reasons</Button></div>
        </Section>
      )}
      {phase === "preview" && (
        <Section title="Signature">
          <SignatureBlock clientId={clientId} role="ps" />
        </Section>
      )}

      {phase === "reasons" && (<>

      <Section title="Ticked products" hint={`${list.length} selected.`}>
        {all.length === 0 ? (
          <Card className="!p-8"><p className="text-base text-ink-muted">No products ticked yet.</p><div className="mt-5"><Button variant="ghost" to={`/ps/cases/${clientId}/market`}>Back to AI Assistant</Button></div></Card>
        ) : (
          <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
            {all.map((p) => (
              <Card key={p.product} className="flex flex-col !p-8">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <label className="flex min-w-0 cursor-pointer items-start gap-3">
                    <input type="checkbox" className="mt-1 h-5 w-5 cursor-pointer" checked={ticked.includes(p.product)} onChange={() => toggle(p.product)} aria-label={`Include ${p.product}`} />
                    <span className="min-w-0 text-xl">{p.product}</span>
                  </label>
                  <p className="text-sm text-ink-muted">{p.assetClass} · {p.confidencePct}% confidence</p>
                </div>
                <p className="mt-3 text-sm text-ink-700">{p.industryFocus}</p>
                <label className="mt-6 block text-sm text-ink-muted">Your reason, in plain words
                  <BulletTextarea className="mt-2 !border-brand" aria-label={`Reason for ${p.product}`} value={reasons[p.product] ?? ""} onChange={(v) => { setReasons({ ...reasons, [p.product]: v }); setApplied(null); }}
                    placeholder="• Say in simple words why this suits the client" />
                </label>
                <div className="mt-3 flex justify-end">
                  <Button variant="secondary" size="sm" onClick={() => { setReasons({ ...reasons, [p.product]: syntheticReason(p) }); setApplied(null); }}>Fill synthetic reason</Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Section>

      </>)}

      {phase !== "geneva" && <Card className="mb-12 !p-8">
        <h2 className="text-xl">What the IC will receive</h2>
        <BulletList className="mt-3 !text-base" text={IC_RECEIVES.map((n) => `• ${n}`).join("\n")} />
        <label className="mt-6 flex items-start gap-3 text-sm text-ink-700">
          <input type="checkbox" className="mt-0.5 h-5 w-5" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
          I have reviewed this list and confirm every product suits the client's IPS and risk limit.
        </label>
      </Card>}

      {phase === "reasons" && (
        <NextAction title={typedList.length ? "Professionalise your reasons" : "Preview the list"}
          action={<Button disabled={list.length === 0 || !confirm} onClick={() => setPhase(typedList.length ? "geneva" : "preview")}>{typedList.length ? "Professionalise with Geneva" : "Preview"}</Button>} />
      )}
      {phase === "preview" && (
        <NextAction title="Approve and send" body={signed ? "" : "Sign above to enable sending."} action={<Button disabled={!confirm || list.length === 0 || !signed} onClick={send}>Approve list & send to IC (G3)</Button>} />
      )}
    </div>
  );
}
