import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { Sparkles } from "lucide-react";
import type { IpsVersion, Philosophy } from "../../types/arc";
import { philosophySentence } from "../../services/ipsText";
import { arcApi } from "../../services/arcApi";
import { useIpsDraftExtras, saveIpsDraftExtras } from "../../services/workflowStore";
import { profileApi, DEFAULT_REVIEW_RULES } from "../../services/profileApi";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { useAsync } from "../ui";
import { GenevaMark } from "./GenevaMark";
import { Bullets, DocSection, FreeText, Dashes, KV, SignatureBlock, WRAP, toBullets } from "./ips/parts";
import type { Bucket3L } from "../../types/arc";
import { BucketBar } from "./ips/charts";
import { AllocationBuckets, type AllocBucketId } from "./ips/Allocation";
import { BucketEditor, BulletEditor } from "./ips/edit";
import { GoalsSection } from "./ips/GoalsSection";
import { groupsFromBackend } from "./ips/goals";
import { rulesToBullets, seedFromData } from "./ips/ipsData";
import { LifeEventsTimeline } from "./ips/LifeEventsTimeline";
import { normaliseLifeEvents, type IpsLifeEvent, type IpsTarget } from "./ips/ipsTypes";
import type { ThreeLMeta } from "./ips/Allocation";

const fmt = (s: string) => new Date(s).toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
const RM_SIGNATURE = "/signature-isabel.png";

export { philosophySentence };
export type { Philosophy };

export interface IpsEditApi {
  /** IPS part bodies keyed by part number (1 goals, 3 risk text, 5 review rules); newline-separated bullet lines, no "• " stored. */
  text: Record<number, string>;
  setText: (part: number, v: string) => void;
  buckets: Bucket3L[]; setBuckets: (b: Bucket3L[]) => void;
  /** Label -> text override for editable §1 demographic values. */
  demo: Record<string, string>; setDemo: (label: string, v: string) => void;
  /** Label -> text override for editable §5 risk values. */
  risk: Record<string, string>; setRisk: (label: string, v: string) => void;
  /** Investment philosophy statement blanks. */
  philosophy: Philosophy; setPhilosophy: (key: keyof Philosophy, v: string) => void;
  /** Uploaded signature images (data URLs). */
  signatures: { client?: string; rm?: string }; setSignature: (who: "client" | "rm", dataUrl?: string) => void;
  /** Strategy code (A-F) per 3L bucket; liquidity is limited to A-B. */
  allocation?: { liquidity?: string; longevity?: string; legacy?: string }; setAllocation?: (bucket: AllocBucketId, code: string) => void;
  /** Optional justification per bucket. */
  allocationNotes?: Record<string, string>; setAllocationNote?: (bucket: AllocBucketId, text: string) => void;
  /** Geneva's original (un-clamped) strategy per bucket, and backend threeL metadata, for override detection. */
  proposedAllocation?: Partial<Record<AllocBucketId, string>>; allocationMeta?: Partial<Record<AllocBucketId, ThreeLMeta>>;
  /** Lines Geneva could not safely write in the third person (review list in the editor). */
  notIncluded?: string[]; setNotIncluded?: (n: string[]) => void;
}
/** `blank`: a brand-new IPS. Same template, but nothing is prefilled from mock/client data (empty fields for the RM to fill). */
interface Props { version: IpsVersion; clientName: string; clientId?: string; mode?: "view" | "edit"; edit?: IpsEditApi; blank?: boolean; aiGenerated?: boolean; wide?: boolean }

export function IpsDocument({ version: v, clientName, clientId, mode = "view", edit, blank = false, aiGenerated = false, wide = false }: Props) {
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
  const sigs = edit?.signatures ?? saved?.signatures ?? {};
  const withOverrides = (rows: [string, string][], o: Record<string, string>): [string, string][] => rows.map(([k, v]) => [k, o[k] ?? v]);
  const proj = useAsync(() => arcApi.getGoalProjection(cid), [cid]);
  const profileLoaded = useAsync(() => profileApi.getClientProfile(cid), [cid]);
  const profile = blank ? undefined : profileLoaded;
  const dash = blank ? "" : "—";
  const ex = useDraft || edit ? extras : undefined;
  const targets: IpsTarget[] = seed?.targets ?? ex?.targets ?? profile?.targets ?? [];
  const aiEvents: IpsLifeEvent[] = (proj?.events ?? []).map((e) => ({ id: `ai-${e.year}-${e.label}`, year: e.year, label: e.label }));
  const lifeEvents: IpsLifeEvent[] = seed ? seed.lifeEvents : ex?.lifeEvents ? normaliseLifeEvents(ex.lifeEvents) : blank ? [] : aiEvents;
  const defaultRules = rulesToBullets(seed?.reviewRules.length ? seed.reviewRules : ex?.reviewRules?.length ? ex.reviewRules : DEFAULT_REVIEW_RULES);
  const rmSigned = fmt((seed?.rmSignedDate ?? ex?.rmSignedDate ?? v.issuedOn ?? new Date().toISOString()));
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
    <article className={`mx-auto w-full min-w-0 ${wide ? "max-w-[1080px] px-10" : "max-w-[780px] px-14"} break-words [overflow-wrap:anywhere] border border-hairline bg-surface-100 py-16 text-[14px] leading-[22px] text-ink`}>
      {aiGenerated && (
        <div role="note" className="no-print print:hidden mb-8 flex items-start gap-3 rounded-sm border border-hairline bg-surface-200 px-4 py-3 text-[13px] leading-[20px] text-ink">
          <Sparkles size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-muted" />
          <p><span className="font-semibold">AI-generated IPS.</span> Drafted by Geneva from the client's meeting notes. Please ascertain the facts and edit before sending.</p>
        </div>
      )}
      <GenevaMark />

      <header className="avoid-break mt-10">
        <h1 className="text-[34px] font-light leading-[40px]">Investment Policy Statement</h1>
        <div className="mt-4 h-px w-full bg-brand" />
        <p className="mt-3 text-[12px] uppercase tracking-[0.08em] text-ink-muted">
          {(v.clientName ?? name) ? `${v.clientName ?? name} · ` : ""}Version {v.version} · Issued {fmt(v.issuedOn)} · {v.status} · Author {v.author}
        </p>
      </header>

      <DocSection n={1} title="Client Demographics">
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

      <DocSection n={2} title="Investment Philosophy">
        {editing ? (
          <FreeText label="Investment philosophy statement" placeholder="The client prefers a … investing approach, and believes in … kinds of companies and industries, but steers away from …"
            value={phil.statement ?? philosophySentence(phil)} onChange={(t) => edit.setPhilosophy("statement", t)} />
        ) : (phil.statement?.trim() || philosophySentence(phil))
          ? <p className={`${WRAP} whitespace-pre-line`}>{phil.statement?.trim() || philosophySentence(phil)}</p>
          : <p className="text-ink-muted">Not yet completed.</p>}
      </DocSection>

      <DocSection n={3} title="Client Goals & Objectives">
        <GoalsSection editing={editing} body={textOf(1, goalItems)} groups={editing ? undefined : viewGroups} onBody={(t) => edit?.setText(1, t)}
          notIncluded={edit?.notIncluded} onNotIncluded={edit?.setNotIncluded} targets={targets} onTargets={(t) => saveIpsDraftExtras(cid, { targets: t })} />
      </DocSection>

      <DocSection n={4} title="Life Events">
        {!blank && !editing && !seed && !proj && !ex?.lifeEvents ? <p className="text-ink-muted">Loading…</p>
          : <LifeEventsTimeline events={lifeEvents} editing={editing} onChange={(e) => saveIpsDraftExtras(cid, { lifeEvents: e })} />}
      </DocSection>

      <DocSection n={5} title="3L Bucket Allocation">
        {editing && bucketList ? <BucketEditor buckets={bucketList} onChange={edit.setBuckets} />
          : buckets ? <BucketBar buckets={buckets} /> : <p className="text-ink-muted">Loading…</p>}
        <AllocationBuckets editing={editing} blank={blank} allocation={edit?.allocation ?? seed?.allocation ?? saved?.allocation ?? {}}
          notes={edit?.allocationNotes ?? seed?.allocationNotes ?? saved?.allocationNotes} onPick={edit?.setAllocation} clientId={cid}
          onNote={edit?.setAllocationNote} proposed={edit?.proposedAllocation ?? seed?.proposed} meta={edit?.allocationMeta ?? seed?.allocationMeta} />
      </DocSection>

      <DocSection n={6} title="Risk Profile">
        <KV
          onEdit={editing ? edit.setRisk : undefined}
          hints={{ "Risk tolerance (willingness)": "Psychological comfort enduring drawdowns", "Risk capacity (ability)": "Financial ability to bear risk" }}
          rows={withOverrides([
            ["Risk category", (blank ? "" : client?.riskCategory) || dash],
            ["Risk tolerance (willingness)", dash],
            ["Risk capacity (ability)", dash],
            ["Time horizon", profile?.timeHorizon ?? dash],
            ["Liquidity needs", profile?.liquidityNeeds ?? dash],
          ], riskVals)} />
        <div className="avoid-break mt-4">
          <p className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">Product risk limit</p>
          <div className="mt-1"><Dashes value={blank ? 0 : client?.riskCap ?? 0} /></div>
        </div>
        {editing ? (
          <div className="mt-4">
            <p className="mb-1 text-[12px] uppercase tracking-[0.06em] text-ink-muted">Loss tolerance</p>
            <BulletEditor part={3} label="Loss tolerance" value={textOf(3, lossItems)} onChange={(t) => edit.setText(3, t)} />
          </div>
        ) : lossItems.length > 0 && (
          <div className="avoid-break mt-4">
            <p className="mb-1 text-[12px] uppercase tracking-[0.06em] text-ink-muted">Loss tolerance</p>
            <Bullets items={lossItems} />
          </div>
        )}
      </DocSection>

      <DocSection n={7} title="Review Rules">
        {editing
          ? <BulletEditor part={5} label="Review rules" value={textOf(5, ruleItems.length || blank ? ruleItems : defaultRules)} onChange={(t) => edit.setText(5, t)} />
          : <Bullets items={ruleItems.length ? ruleItems : defaultRules} />}
      </DocSection>

      <DocSection n={8} title="Acknowledgement & Signature">
        <p className="mb-6">The client confirms that this Investment Policy Statement reflects their objectives, risk profile and constraints.</p>
        <div className="grid grid-cols-1 gap-12 sm:grid-cols-2">
          <SignatureBlock label="Client" image={sigs.client} editable={editing} onChange={(d) => edit?.setSignature("client", d)} />
          <SignatureBlock label={`Relationship Manager (${rm.person})`} image={rmImage} date={rmSigned} editable={editing} onChange={(d) => edit?.setSignature("rm", d ?? "")} />
        </div>
      </DocSection>

      <footer className="avoid-break mt-12 flex flex-wrap justify-between gap-2 border-t border-hairline pt-4 text-[12px] text-ink-muted">
        <span>Generated by Geneva · Synthetic data</span>
        <span>Confidential · {`IPS-${id}-v${v.version}`}</span>
      </footer>
    </article>
  );
}
