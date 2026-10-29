import { useState } from "react";
import { Check } from "lucide-react";
import { useParams } from "react-router-dom";
import { SignatureBlock, BulletList, BulletTextarea, toBulletText, Button, Card, GateChip, NextAction, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { ProfessionaliseButton } from "../../components/geneva/ProfessionaliseButton";
import { WordingCompare } from "../rm/rmShared";
import { getChatContext } from "../../services/chatContextStore";
import { ClientStrip, PS_STEPS, loadSelection, saveSelection } from "./psShared";
import { reopenFinalised, savePsReasons, sendFinalised, useFinalised, usePsReasons } from "../../services/workflowStore";
import { FinalisedTable } from "../../components/ps/FinalisedTable";
import { savePackDraft, setSectionDone, useSignatures } from "../../services/packDraftStore";
import { toBulletItems } from "../../utils/bullets";
import { ratingText } from "../../utils/productMatch";

const draftReason = (p: { product: string; assetClass: string; industryFocus: string; rating?: number | null }) => [
  `Suitability: ${p.product} fits the client's IPS objectives and stays within the agreed risk limit.`,
  `Asset class: the ${p.assetClass} exposure supports the target allocation and diversification.`,
  `Rationale: ${p.industryFocus || "aligned with the current house view"}.`,
  ...(p.rating ? [`Product rating: ${p.rating} of 5 on the shelf; a minor tie-breaker, not a measure of confidence.`] : []),
  "Cost: the fee was reviewed for transparency only and was not used to rank this product.",
].map((l) => `• ${l}`).join("\n");

/** Deterministic, offline synthetic reason (bullet format with citation tags) for the demo. */
const syntheticReason = (p: { product: string; assetClass: string; industryFocus: string; rating?: number | null }) => {
  const h = [...p.product].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 9973, 7);
  const cio = ["CIO-2026Q4-02", "CIO-2026Q4-03", "CIO-2026Q4-05"][h % 3];
  return [
    `${p.product} suits the client's IPS objectives and stays inside the agreed risk limit [IPS-v2].`,
    `The ${p.assetClass} exposure supports the target allocation and diversification [${cio}].`,
    `${p.industryFocus || "Aligned with the current house view"} [MKT-0142].`,
    `Suitability was checked first; the fee was shown for transparency only and not used to rank [PRD-FI-007].`,
  ].map((l) => `• ${l}`).join("\n");
};

const PM_RECEIVES = [
  "The approved product list with the Product Specialist's reason for each product.",
  "Fees and risk ratings, shown for information and never used to rank products.",
  "Citation tags linking every statement to its source document.",
  "The market views and house view extracts behind the shortlist.",
  "A clear G3 status so the PM can propose the tactical allocation for the quarterly pack.",
];
const SENT_NOTES = [
  "The PM can now propose the tactical allocation.",
  "The Relationship Manager is notified once the PM completes the pack.",
  "Your reasons stay attached to each product for audit.",
];
const REOPEN_NOTES = [
  "G3 reopens and the list leaves the PM's inbox until you send it again.",
  "G2 and G4 are reset, so the PM and RM approve again.",
  "Your signature is cleared. Your sent reasons are kept as the starting draft.",
];

export default function FinaliseProducts() {
  const { clientId = "jfr" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const [confirm, setConfirm] = useState(false);
  const [phase, setPhase] = useState<"reasons" | "preview">("reasons");
  /** Per-box Geneva state: loading flag and the proposed professional wording awaiting Accept / Keep mine. */
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [proposal, setProposal] = useState<Record<string, string>>({});
  const sentList = useFinalised(clientId);
  const [reopening, setReopening] = useState(false);
  const [editingReason, setEditingReason] = useState<string | null>(null);
  /** Persisted per client so typed reasons survive leaving the page; cleared on send, restored from the sent list on reopen. */
  const reasons = usePsReasons(clientId);
  const setReasons = (next: Record<string, string> | ((r: Record<string, string>) => Record<string, string>)) =>
    savePsReasons(clientId, typeof next === "function" ? next(reasons) : next);

  const [all, setAll] = useState(() => loadSelection(clientId));
  const [ticked, setTicked] = useState<string[]>(() => all.map((r) => r.product));
  const list = all.filter((r) => ticked.includes(r.product));
  /** Baseline: the Product Recommender's cited reason when the product was ticked from a recommendation, else a generic suitability draft. */
  const baseline = (r: (typeof all)[number]) => r.agentReason?.trim() || draftReason(r);
  const [activeProduct, setActiveProduct] = useState<string | null>(null);
  const current = list.find((r) => r.product === activeProduct) ?? list[0];
  const typed = (name: string) => (reasons[name] ?? "").trim().length > 0;
  /** What the PM receives: the PS's reason (professionalised if accepted), else the baseline when nothing was typed. */
  const finalReason = (r: (typeof all)[number]) => (typed(r.product) && toBulletText(reasons[r.product]) ? toBulletText(reasons[r.product]) : toBulletText(baseline(r)) || draftReason(r));
  const professionalise = async (name: string) => {
    setBusy((b) => ({ ...b, [name]: true }));
    const out = await arcApi.professionalise({ clientId, role: "ps", context: "products", items: [{ id: name, label: name, text: finalReason(all.find((r) => r.product === name)!) }], chat: getChatContext(clientId, "ps") });
    setProposal((p) => ({ ...p, [name]: out[0]?.text ?? "" }));
    setBusy((b) => ({ ...b, [name]: false }));
  };
  const hasReason = (r: (typeof all)[number]) => toBulletItems(finalReason(r)).length > 0;
  const closeProposal = (name: string) => setProposal((p) => { const rest = { ...p }; delete rest[name]; return rest; });
  const signed = !!useSignatures(clientId).ps;
  const send = () => {
    const items = list.map((r) => ({ ...r, reason: finalReason(r) }));
    sendFinalised(clientId, items);
    // Pack section 5 (Product recommendations) so PM and RM read the same list.
    const body = items.map((i) => `• ${i.product}: ${toBulletItems(i.reason)[0] ?? i.industryFocus}`).join("\n");
    savePackDraft(clientId, 5, body, "ps");
    setSectionDone(clientId, 5, true, "ps");
    savePsReasons(clientId, {});
    setPhase("reasons");
    setConfirm(false);
  };
  const reopen = () => {
    if (!sentList) return;
    const sentNames = sentList.items.map((i) => i.product);
    // Bring back any sent product that was dropped from the chat selection since, so it can still be edited.
    const merged = [...loadSelection(clientId).filter((r) => !sentNames.includes(r.product)), ...sentList.items.map((i) => ({ assetClass: i.assetClass, product: i.product, industryFocus: i.industryFocus, top5: i.top5, rating: i.rating ?? null, ranking: i.ranking }))];
    saveSelection(clientId, merged);
    setAll(merged);
    setTicked(sentNames);
    reopenFinalised(clientId);
    setReopening(false);
  };
  const toggle = (name: string) => setTicked((cur) => {
    const next = cur.includes(name) ? cur.filter((x) => x !== name) : [...cur, name];
    saveSelection(clientId, all.filter((r) => next.includes(r.product)));
    return next;
  });

  if (sentList) {
    return (
      <div>
        <PageHeader eyebrow="Product review · Done" title="Sent to the Portfolio Manager" actions={<GateChip id="G3" state="approved" />} />
        <Stepper steps={PS_STEPS} current={2} />
        <Card accent className="mb-12 !p-10">
          <h2 className="text-2xl">{sentList.items.length} products approved for {client?.name ?? "the client"}</h2>
          <BulletList className="mt-3 max-w-2xl !text-base" text={SENT_NOTES.map((n) => `• ${n}`).join("\n")} />
          <div className="mt-8"><Button to="/ps/inbox">Back to inbox</Button></div>
        </Card>
        <Section title="Sent list" hint="Click a product to read your reason.">
          <FinalisedTable clientId={clientId} expandable />
        </Section>
        {reopening ? (
          <Card className="mb-12 !p-8">
            <h2 className="text-xl">Edit the sent list?</h2>
            <BulletList className="mt-3 !text-base" text={REOPEN_NOTES.map((n) => `• ${n}`).join("\n")} />
            <div className="mt-6 flex flex-wrap gap-4">
              <Button variant="secondary" onClick={reopen}>Reopen G3 and edit</Button>
              <Button variant="ghost" onClick={() => setReopening(false)}>Cancel</Button>
            </div>
          </Card>
        ) : (
          <NextAction title="Need to change the list?" body="Editing reopens G3 and resets G2 and G4."
            action={<Button variant="secondary" onClick={() => setReopening(true)}>Edit list</Button>} />
        )}
      </div>
    );
  }

  return (
    <div>
      <PageHeader eyebrow="Product review" title="Finalise & send" actions={<GateChip id="G3" state="pending" />} />
      <Stepper steps={PS_STEPS} current={1} />
      <ClientStrip client={client} />

      {phase === "preview" && (
        <Section title="Preview what the PM will see">
          <div className="grid gap-8 md:grid-cols-[300px_1fr] md:items-start">
            <Card className="!p-5">
              <h2 className="text-base">Products</h2>
              <p className="mt-1 text-xs text-ink-muted">{list.length} to send to the PM</p>
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
                    <p className="mt-2 text-sm text-ink-muted">{current.assetClass} · {ratingText(current.rating)}</p>
                  </div>
                  <div className="text-[17px] leading-8 text-ink-700">{editingReason === current.product ? (
                    <BulletTextarea className="!border-brand" aria-label={`Reason for ${current.product}`} value={reasons[current.product] ?? ""}
                      onChange={(v) => { setReasons((r) => ({ ...r, [current.product]: v })); closeProposal(current.product); }}
                      placeholder="• Say in simple words why this suits the client" />
                  ) : <BulletList className="!text-base" text={finalReason(current)} />}</div>
                  {proposal[current.product] !== undefined && (
                    <div className="border-t border-hairline pt-6">
                      <WordingCompare oldText={finalReason(current)} newText={proposal[current.product]}
                        onChangeNew={(t) => setProposal((x) => ({ ...x, [current.product]: t }))}
                        onAccept={() => { setReasons((r) => ({ ...r, [current.product]: proposal[current.product] })); closeProposal(current.product); }}
                        onKeep={() => closeProposal(current.product)} />
                    </div>
                  )}
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div>
                      {proposal[current.product] === undefined && (
                        <Button variant="secondary" size="sm" onClick={() => {
                          if (editingReason === current.product) { setEditingReason(null); return; }
                          if (!typed(current.product)) setReasons((r) => ({ ...r, [current.product]: finalReason(current) }));
                          setEditingReason(current.product);
                        }}>{editingReason === current.product ? "Done" : "Edit reason"}</Button>
                      )}
                    </div>
                    <ProfessionaliseButton size="sm" label="Professionalise with Geneva" loading={!!busy[current.product]} disabled={!hasReason(current) || proposal[current.product] !== undefined || editingReason === current.product} onClick={() => professionalise(current.product)} />
                  </div>
                </div>
              </Card>
            )}
          </div>
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
                  <p className="text-sm text-ink-muted">{p.role ? `${p.role} · ` : ""}{p.assetClass} · {ratingText(p.rating)}</p>
                </div>
                <p className="mt-3 text-sm text-ink-700">{p.industryFocus}</p>
                <label className="mt-6 block text-sm text-ink-muted">Your reason, in plain words
                  <BulletTextarea className="mt-2 !border-brand" aria-label={`Reason for ${p.product}`} value={reasons[p.product] ?? ""} onChange={(v) => { setReasons({ ...reasons, [p.product]: v }); closeProposal(p.product); }}
                    placeholder="• Say in simple words why this suits the client" />
                </label>
                <div className="mt-3 flex flex-wrap justify-end gap-3">
                  <Button variant="secondary" size="sm" onClick={() => { setReasons({ ...reasons, [p.product]: syntheticReason(p) }); closeProposal(p.product); }}>Fill synthetic reason</Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Section>

      </>)}

      <Card className="mb-12 !p-8">
        <h2 className="text-xl">What the PM will receive</h2>
        <BulletList className="mt-3 !text-base" text={PM_RECEIVES.map((n) => `• ${n}`).join("\n")} />
        <label className="mt-6 flex items-start gap-3 text-sm text-ink-700">
          <input type="checkbox" className="mt-0.5 h-5 w-5" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
          I have reviewed this list and confirm every product suits the client's IPS and risk limit.
        </label>
      </Card>

      {phase === "reasons" && (
        <NextAction title="Preview the list"
          action={<Button disabled={list.length === 0 || !confirm} onClick={() => setPhase("preview")}>Preview</Button>} />
      )}
      {phase === "preview" && (
        <NextAction title="Approve and send" body={signed ? "" : "Sign above to enable sending."} action={<Button disabled={!confirm || list.length === 0 || !signed} onClick={send}>Approve list & send to PM (G3)</Button>} />
      )}
    </div>
  );
}
