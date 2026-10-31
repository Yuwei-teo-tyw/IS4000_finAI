import { useMemo, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { Sparkles } from "lucide-react";
import type { IpsVersion, Philosophy, ThreeLBucketKey, ThreeLProportion } from "../../types/arc";
import { philosophySentence } from "../../services/ipsText";
import { arcApi } from "../../services/arcApi";
import { useIpsDraftExtras, saveIpsDraftExtras } from "../../services/workflowStore";
import { profileApi, DEFAULT_REVIEW_RULES } from "../../services/profileApi";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { useAsync } from "../ui";
import { GenevaMark } from "./GenevaMark";
import { Bullets, Cell, DocSection, FreeText, Dashes, InlineText, IpsGrid, KV, LABEL, SignatureBlock, WRAP, toBullets } from "./ips/parts";
import type { Bucket3L } from "../../types/arc";
import { BucketAllocation } from "./ips/ProportionTable";
import { AllocationBuckets, type AllocBucketId, type AllocWeights } from "./ips/Allocation";
import { BulletEditor } from "./ips/edit";
import { GoalsSection } from "./ips/GoalsSection";
import { groupsFromBackend } from "./ips/goals";
import { rulesToBullets, seedFromData } from "./ips/ipsData";
import { type IpsTarget } from "./ips/ipsTypes";
import type { ThreeLMeta } from "./ips/Allocation";

const fmt = (s: string) => new Date(s).toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
const RM_SIGNATURE = "/signature-isabel.png";

export { philosophySentence };
export type { Philosophy };

export interface IpsEditApi {
  /** IPS part bodies keyed by part number (backend part numbers: 1 goals, 3 risk text, 5 review rules; not the section numbers); newline-separated bullet lines, no "• " stored. */
  text: Record<number, string>;
  setText: (part: number, v: string) => void;
  buckets: Bucket3L[]; setBuckets: (b: Bucket3L[]) => void;
  /** Label -> text override for editable §1 demographic values. */
  demo: Record<string, string>; setDemo: (label: string, v: string) => void;
  /** Label -> text override for editable §4 risk values. */
  risk: Record<string, string>; setRisk: (label: string, v: string) => void;
  /** Investment philosophy statement blanks. */
  philosophy: Philosophy; setPhilosophy: (key: keyof Philosophy, v: string) => void;
  /** Uploaded signature images (data URLs). */
  signatures: { client?: string; rm?: string }; setSignature: (who: "client" | "rm", dataUrl?: string) => void;
  /** Strategy code (A-F) per 3L bucket; Liquidity carries no SAA and shows "NA". */
  allocation?: { liquidity?: string; longevity?: string; legacy?: string }; setAllocation?: (bucket: AllocBucketId, code: string) => void;
  /** Optional justification per bucket. */
  allocationWeights?: AllocWeights; setAllocationWeights?: (bucket: AllocBucketId, w: Record<string, number> | undefined) => void;
  allocationNotes?: Record<string, string>; setAllocationNote?: (bucket: AllocBucketId, text: string) => void;
  /** Geneva's original (un-clamped) strategy per bucket, and backend threeL metadata, for override detection. */
  proposedAllocation?: Partial<Record<AllocBucketId, string>>; allocationMeta?: Partial<Record<AllocBucketId, ThreeLMeta>>;
  /** Lines Geneva could not safely write in the third person (review list in the editor). */
  notIncluded?: string[]; setNotIncluded?: (n: string[]) => void;
  /** IS-75: base 3L percentage proportion from generation (null: not generated, see message/missing). */
  proportion?: ThreeLProportion | null; proportionMessage?: string; proportionMissing?: string[]; setProportionPct?: (k: ThreeLBucketKey, pct: number) => void; setProportionReason?: (k: ThreeLBucketKey, text: string) => void;
  /** Message when the stored 3L recommendation is out of date. */
  outOfDate?: string;
}
/** `blank`: a brand-new IPS. Same template, but nothing is prefilled from mock/client data (empty fields for the RM to fill). */
interface Props { version: IpsVersion; clientName: string; clientId?: string; mode?: "view" | "edit"; edit?: IpsEditApi; blank?: boolean; aiGenerated?: boolean; wide?: boolean; /** PM vetting view: sections other than 3L/SAA are read-only, 3L/SAA highlighted. */ pmReview?: boolean; /** Extra content under the SAA boxes (PM: Run Geneva 3L recommendation). */ saaSlot?: ReactNode; /** PM signature slot (PM review page); read-only elsewhere from the saved draft. */ pmSign?: PmSign }
export interface PmSign { image?: string; signedAt?: string; onChange?: (dataUrl?: string) => void }

export function IpsDocument({ version: v, clientName, clientId, mode = "view", edit, blank = false, aiGenerated = false, wide = false, pmReview = false, saaSlot, pmSign }: Props) {
  const editing = mode === "edit" && !!edit;
  const params = useParams();
  const cid = clientId ?? params.clientId ?? "";
  const client = useAsync(() => arcApi.getClient(cid), [cid]);
  const fetched = useAsync(() => arcApi.get3L(cid), [cid]);
  const extras = useIpsDraftExtras(cid);
  /** A saved backend version carries structured `data`; the read-only view renders from it instead of the lossy text parts. */
  const bd = !edit && v.data ? v.data : undefined;
  const seed = useMemo(() => (bd ? seedFromData(bd) : null), [bd]);
  const viewGroups = useMemo(() => (bd ? groupsFromBackend(bd.goals) : undefined), [bd]);
  const useDraft = v.status === "Draft" && !edit && !bd;
  const buckets = useDraft && extras?.buckets?.length ? extras.buckets : fetched;
  const saved = useDraft ? extras : undefined;
  const demoVals = edit?.demo ?? seed?.demo ?? saved?.demo ?? {};
  const riskVals = edit?.risk ?? seed?.risk ?? saved?.risk ?? {};
  const phil: Philosophy = edit?.philosophy ?? seed?.philosophy ?? saved?.philosophy ?? {};
  /** Signatures always come from the live editor state; a plain Draft view reads the live draft store, never a stale snapshot. */
  const liveDraft = v.status === "Draft" && !edit ? extras : undefined;
  const sigs = edit?.signatures ?? liveDraft?.signatures ?? {};
  const withOverrides = (rows: [string, string][], o: Record<string, string>): [string, string][] => rows.map(([k, v]) => [k, o[k] ?? v]);
  const profileLoaded = useAsync(() => profileApi.getClientProfile(cid), [cid]);
  const profile = blank ? undefined : profileLoaded;
  const dash = blank ? "" : "—";
  const ex = useDraft || edit ? extras : undefined;
  const targets: IpsTarget[] = seed?.targets ?? ex?.targets ?? profile?.targets ?? [];
  const defaultRules = rulesToBullets(seed?.reviewRules.length ? seed.reviewRules : ex?.reviewRules?.length ? ex.reviewRules : DEFAULT_REVIEW_RULES);
  const rmSigned = fmt((seed?.rmSignedDate ?? ex?.rmSignedDate ?? v.issuedOn ?? new Date().toISOString()));
  const pmSaved = (extras?.pmOpened ? (liveDraft?.signatures ?? extras?.signatures) : undefined) as { pm?: string; pmSignedAt?: string } | undefined;
  const pmShown = pmSign ?? { image: pmSaved?.pm, signedAt: pmSaved?.pmSignedAt };
  const rmImage = sigs.rm === undefined ? (seed?.rmSignatureImage || RM_SIGNATURE) : sigs.rm || undefined;

  const part = (n: number) => v.parts.find((p) => p.part === n)?.body ?? "";
  const goals = seed?.text[1] !== undefined ? toBullets(seed.text[1].replace(/^[^:\n]{1,48}:\s+/gm, "")) : toBullets(part(1));
  const goalItems = goals.length ? goals : profile?.goals ?? [];  // blank: profile is undefined, so empty
  const riskText = seed?.text[3] !== undefined ? seed.text[3].split("\n").filter(Boolean) : toBullets(part(3));
  const lossItems = [...(profile?.lossTolerance ?? []), ...riskText.filter((t) => /drawdown|tolerate|fall/i.test(t) && !(profile?.lossTolerance ?? []).includes(t))].slice(0, 4);
  const ruleItems = seed ? [] : toBullets(part(5));
  const bucketList = editing && edit.buckets.length ? edit.buckets : buckets;
  const textOf = (n: number, fallback: string[]) => edit?.text[n] ?? fallback.join("\n");
  const rm = ROLE_PEOPLE.rm;
  const name = client?.name ?? clientName;
  const id = (client?.id ?? cid).toUpperCase() || "—";

  return (
    <article className={`mx-auto w-full min-w-0 ${wide ? "max-w-[1480px]" : "max-w-[1180px]"} px-6 py-10 sm:px-14 sm:py-16 print:max-w-none print:border-0 print:bg-transparent print:p-0 break-words [overflow-wrap:anywhere] border border-hairline bg-surface-100 font-light text-[15px] leading-6 text-ink`}>
      {aiGenerated && (
        <div role="note" className="no-print print:hidden mb-8 flex items-start gap-3 rounded-sm border border-hairline bg-surface-200 px-4 py-3 text-[13px] leading-[20px] text-ink">
          <Sparkles size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-muted" />
          <p><span className="font-normal">AI-generated IPS.</span> Drafted by Geneva from the client's meeting notes. Please ascertain the facts and edit before sending.</p>
        </div>
      )}
      <GenevaMark />

      <header className="avoid-break mt-10">
        <h1 className="text-[34px] font-light leading-[40px]">Investment Policy Statement</h1>
        <div className="mt-4 h-px w-full bg-ink" />
        <p className={`mt-3 ${LABEL}`}>
          {(v.clientName ?? name) ? `${v.clientName ?? name} · ` : ""}Version {v.version} · Issued {fmt(v.issuedOn)} · {v.status} · Author {v.author}
        </p>
      </header>

      <DocSection n={1} locked={pmReview} title="Client Demographics">
        <KV
          onEdit={editing ? edit.setDemo : undefined}
          locked={["Full name", "Client ID", "Contact RM"]}
          rows={withOverrides([
            ["Full name", name], ["Client ID", id],
            ["Date of birth / age", profile ? `${profile.dateOfBirth} (${profile.age})` : dash],
            ["Occupation", profile?.occupation ?? dash], ["Employment / income source", profile?.incomeSource ?? dash],
            ["Annual income", profile?.annualIncome ?? dash],
            ["AUM", !blank && client?.aumSgd ? `S$${client.aumSgd.toLocaleString("en-SG")}` : dash],
            ["Contact RM", `${rm.person}, ${rm.name}`],
          ], demoVals)} />
      </DocSection>

      <DocSection n={2} locked={pmReview} title="Investment Philosophy">
        <IpsGrid>
          <Cell wide>
            {editing ? (
              <FreeText label="Investment philosophy statement" placeholder="The client prefers a … investing approach, and believes in … kinds of companies and industries, but steers away from …"
                value={phil.statement ?? philosophySentence(phil)} onChange={(t) => edit.setPhilosophy("statement", t)} />
            ) : (phil.statement?.trim() || philosophySentence(phil))
              ? <p className={`${WRAP} whitespace-pre-line`}>{phil.statement?.trim() || philosophySentence(phil)}</p>
              : <p className="text-ink-muted">Not yet completed.</p>}
          </Cell>
          <Cell wide data-testid="investment-period">
            <p className={LABEL}>Investment Period</p>
            {editing
              ? <div className="mt-1"><InlineText label="Investment period" placeholder="e.g. 10 years" value={phil.investmentPeriod ?? ""} onChange={(t) => edit.setPhilosophy("investmentPeriod", t)} /></div>
              : phil.investmentPeriod?.trim() ? <p className={`mt-1 ${WRAP}`}>{phil.investmentPeriod}</p> : <p className="mt-1 text-ink-muted">Not yet completed.</p>}
          </Cell>
        </IpsGrid>
      </DocSection>

      <DocSection n={3} locked={pmReview} title="Client Goals & Objectives">
        <GoalsSection editing={editing} body={textOf(1, goalItems)} groups={editing ? undefined : viewGroups} onBody={(t) => edit?.setText(1, t)}
          notIncluded={edit?.notIncluded} onNotIncluded={edit?.setNotIncluded} clientId={cid} targets={targets} onTargets={(t) => saveIpsDraftExtras(cid, { targets: t })} />
      </DocSection>

      <DocSection n={4} locked={pmReview} title="Risk Profile">
        <KV
          onEdit={editing ? edit.setRisk : undefined}
          hints={{ "Risk tolerance (willingness)": "Psychological comfort enduring drawdowns", "Risk capacity (ability)": "Financial ability to bear risk" }}
          rows={withOverrides([
            ["Risk category", (blank ? "" : client?.riskCategory) || dash],
            ["Risk tolerance (willingness)", dash],
            ["Risk capacity (ability)", dash],
            ["Time horizon", profile?.timeHorizon ?? dash],
            ["Liquidity needs", profile?.liquidityNeeds ?? dash],
          ], riskVals)}>
          <Cell>
            <dt className={LABEL}>Product risk limit</dt>
            <dd className="mt-1"><Dashes value={blank ? 0 : client?.riskCap ?? 0} /></dd>
          </Cell>
          {(editing || lossItems.length > 0) && (
            <Cell wide>
              <dt className={LABEL}>Loss tolerance</dt>
              <dd className={`mt-1 ${WRAP}`}>
                {editing
                  ? <BulletEditor part={3} label="Loss tolerance" value={textOf(3, lossItems)} onChange={(t) => edit.setText(3, t)} />
                  : <Bullets items={lossItems} />}
              </dd>
            </Cell>
          )}
        </KV>
      </DocSection>

      <DocSection n={5} highlight={pmReview} title="3L Bucket Allocation">
        <BucketAllocation buckets={editing ? bucketList : buckets} onBuckets={editing ? edit.setBuckets : undefined}
          proportion={edit ? edit.proportion : seed?.proportion ?? saved?.proportion} message={edit ? edit.proportionMessage : seed?.proportionMessage}
          missing={edit?.proportionMissing} onPct={edit?.setProportionPct} onReason={edit?.setProportionReason} />
        <AllocationBuckets editing={editing} blank={blank} allocation={edit?.allocation ?? seed?.allocation ?? saved?.allocation ?? {}}
          notes={edit?.allocationNotes ?? seed?.allocationNotes ?? saved?.allocationNotes} onPick={edit?.setAllocation} clientId={cid}
          weights={edit?.allocationWeights ?? saved?.allocationWeights} onWeights={edit?.setAllocationWeights}
          outOfDate={edit?.outOfDate ?? seed?.outOfDate} onNote={edit?.setAllocationNote} proposed={edit?.proposedAllocation ?? seed?.proposed} meta={edit?.allocationMeta ?? seed?.allocationMeta} />
        {saaSlot}
      </DocSection>

      <DocSection n={6} locked={pmReview} title="Review Rules">
        {editing
          ? <BulletEditor part={5} label="Review rules" value={textOf(5, ruleItems.length || blank ? ruleItems : defaultRules)} onChange={(t) => edit.setText(5, t)} />
          : <Bullets items={ruleItems.length ? ruleItems : defaultRules} />}
      </DocSection>

      <DocSection n={7} title="Acknowledgement & Signatures">
        <p>The client confirms that this Investment Policy Statement reflects their objectives, risk profile and constraints.{(pmSign || pmSaved?.pm) && " The Portfolio Manager confirms the 3L allocation and SAA portfolios have been reviewed."}</p>
        <div className="@container"><div className={`grid grid-cols-1 gap-8 ${pmSign || pmSaved?.pm ? "@xl:grid-cols-3" : "@xl:grid-cols-2"}`}>
          <div className={pmReview ? "pointer-events-none" : ""}><SignatureBlock label="Client" image={sigs.client} editable={editing && !pmReview} onChange={(d) => edit?.setSignature("client", d)} /></div>
          <div className={pmReview ? "pointer-events-none" : ""}><SignatureBlock label={`Relationship Manager (${rm.person})`} image={rmImage} date={rmSigned} editable={editing && !pmReview} onChange={(d) => edit?.setSignature("rm", d ?? "")} /></div>
          {(pmSign || pmSaved?.pm) && (
            <SignatureBlock label={`Portfolio Manager (${ROLE_PEOPLE.pm.person})`} image={pmShown.image} date={pmShown.image && pmShown.signedAt ? fmt(pmShown.signedAt) : undefined}
              editable={!!pmSign?.onChange} onChange={pmSign?.onChange} />
          )}
        </div></div>
      </DocSection>

      <footer className="avoid-break mt-12 flex flex-wrap justify-between gap-2 border-t border-hairline pt-4 text-[12px] text-ink-muted">
        <span>Generated by Geneva · Synthetic data</span>
        <span>Confidential · {`IPS-${id}-v${v.version}`}</span>
      </footer>
    </article>
  );
}
