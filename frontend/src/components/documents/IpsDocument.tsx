import { useParams } from "react-router-dom";
import type { IpsVersion } from "../../types/arc";
import { arcApi } from "../../services/arcApi";
import { useIpsDraftExtras } from "../../services/workflowStore";
import { profileApi } from "../../services/profileApi";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { useAsync } from "../ui";
import { GenevaMark } from "./GenevaMark";
import { Bullets, DocSection, Dashes, KV, SignatureBlock, WRAP, EditLegend, LockedTag, toBullets } from "./ips/parts";
import { SaaPortfolios, type BucketId, type SaaPortfolio } from "./ips/SaaPortfolios";
import type { Bucket3L } from "../../types/arc";
import { BucketBar, SaaDonut, SaaRows } from "./ips/charts";
import { BucketEditor, BulletEditor } from "./ips/edit";

const fmt = (s: string) => new Date(s).toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
const OWNERSHIP = "Portfolio Manager owns the SAA and TAA; Product Specialist owns product selection; Relationship Manager owns the IPS and client contact";
const STATIC_RULES = [
  "The portfolio is reviewed at least quarterly by the Relationship Manager and Portfolio Manager",
  "Rebalance when an asset class drifts outside its allowed range around the SAA",
  "Review the IPS on any major life event",
  "Reissue the IPS on any change in the client risk profile",
];

export interface IpsEditApi {
  /** IPS part bodies keyed by part number (1 goals, 3 risk text, 5 review rules); newline-separated bullet lines, no "• " stored. */
  text: Record<number, string>;
  setText: (part: number, v: string) => void;
  buckets: Bucket3L[]; setBuckets: (b: Bucket3L[]) => void;
  /** Per-bucket RM explanation shown inside each SAA portfolio row. */
  saaNotes: Partial<Record<BucketId, string>>; setSaaNotes: (id: BucketId, v: string) => void;
  /** Label -> text override for editable §1 demographic values. */
  demo: Record<string, string>; setDemo: (label: string, v: string) => void;
  /** Label -> text override for editable §5 risk values. */
  risk: Record<string, string>; setRisk: (label: string, v: string) => void;
  /** Uploaded signature images (data URLs). */
  signatures: { client?: string; rm?: string }; setSignature: (who: "client" | "rm", dataUrl?: string) => void;
  saaPortfolios: Partial<Record<BucketId, SaaPortfolio>>; setSaaPortfolio: (id: BucketId, p: SaaPortfolio) => void;
}
interface Props { version: IpsVersion; clientName: string; clientId?: string; mode?: "view" | "edit"; edit?: IpsEditApi }

export function IpsDocument({ version: v, clientName, clientId, mode = "view", edit }: Props) {
  const editing = mode === "edit" && !!edit;
  const params = useParams();
  const cid = clientId ?? params.clientId ?? "";
  const client = useAsync(() => arcApi.getClient(cid), [cid]);
  const fetched = useAsync(() => arcApi.get3L(cid), [cid]);
  const extras = useIpsDraftExtras(cid);
  const useDraft = v.status === "Draft" && !edit;
  const buckets = useDraft && extras?.buckets?.length ? extras.buckets : fetched;
  const saved = useDraft ? extras : undefined;
  const demoVals = edit?.demo ?? saved?.demo ?? {};
  const riskVals = edit?.risk ?? saved?.risk ?? {};
  const sigs = edit?.signatures ?? saved?.signatures ?? {};
  const savedSaa = saved?.saaPortfolios ?? {};
  const hasSavedSaa = Object.keys(savedSaa).length > 0;
  const withOverrides = (rows: [string, string][], o: Record<string, string>): [string, string][] => rows.map(([k, v]) => [k, o[k] ?? v]);
  const savedNotes = useDraft ? extras?.saaNotes : undefined;
  const alloc = useAsync(() => arcApi.getAllocation(cid), [cid]);
  const proj = useAsync(() => arcApi.getGoalProjection(cid), [cid]);
  const profile = useAsync(() => profileApi.getClientProfile(cid), [cid]);

  const part = (n: number) => v.parts.find((p) => p.part === n)?.body ?? "";
  const goals = toBullets(part(1));
  const goalItems = goals.length ? goals : profile?.goals ?? [];
  const riskText = toBullets(part(3));
  const lossItems = [...(profile?.lossTolerance ?? []), ...riskText.filter((t) => /drawdown|tolerate|fall/i.test(t) && !(profile?.lossTolerance ?? []).includes(t))].slice(0, 4);
  const ruleItems = toBullets(part(5));
  const bucketList = editing && edit.buckets.length ? edit.buckets : buckets;
  const textOf = (n: number, fallback: string[]) => edit?.text[n] ?? fallback.join("\n");
  const rm = ROLE_PEOPLE.rm;
  const name = client?.name ?? clientName;
  const id = (client?.id ?? cid).toUpperCase() || "—";

  return (
    <article className="mx-auto w-full min-w-0 max-w-[780px] break-words [overflow-wrap:anywhere] border border-hairline bg-surface-100 px-14 py-16 text-[14px] leading-[22px] text-ink">
      <GenevaMark />

      <header className="avoid-break mt-10">
        <h1 className="text-[34px] font-light leading-[40px]">Investment Policy Statement</h1>
        <div className="mt-4 h-px w-full bg-brand" />
        <p className="mt-3 text-[12px] uppercase tracking-[0.08em] text-ink-muted">
          Version {v.version} · Issued {fmt(v.issuedOn)} · {v.status} · Author {v.author}
        </p>
      </header>

      {editing && <EditLegend />}

      <DocSection n={1} title="Client Demographics">
        <KV
          onEdit={editing ? edit.setDemo : undefined}
          locked={["Full name", "Client ID", "Contact RM"]}
          rows={withOverrides([
            ["Full name", name], ["Client ID", id],
            ["Date of birth / age", profile ? `${profile.dateOfBirth} (${profile.age})` : "—"],
            ["Nationality / residency", profile ? `${profile.nationality} / ${profile.residency}` : "—"],
            ["Occupation", profile?.occupation ?? "—"], ["Marital status", profile?.maritalStatus ?? "—"],
            ["Dependants", profile?.dependants ?? "—"], ["Employment / income source", profile?.incomeSource ?? "—"],
            ["Tax residency", profile?.taxResidency ?? "—"], ["Contact RM", `${rm.person}, ${rm.name}`],
          ], demoVals)} />
      </DocSection>

      <DocSection n={2} title="Client Goals & Objectives">
        {editing ? <BulletEditor part={1} label="Client goals" value={textOf(1, goalItems)} onChange={(t) => edit.setText(1, t)} />
          : goalItems.length ? <Bullets items={goalItems} /> : <p className="text-ink-muted">Not yet completed.</p>}
      </DocSection>

      <DocSection n={3} title="Life Events">
        {proj?.events.length ? (
          <ol className="flex gap-0 overflow-x-auto pb-2 print:flex-wrap print:overflow-visible">
            {proj.events.map((e) => (
              <li key={`${e.year}-${e.label}`} className="avoid-break relative w-40 shrink-0 pr-4 pt-6">
                <span className="absolute left-0 right-0 top-[4px] h-px bg-hairline" aria-hidden="true" />
                <i className="absolute left-0 top-0 h-[9px] w-[9px] rounded-full bg-brand" />
                <p className="font-semibold">{e.year}</p>
                <p className={WRAP}>{e.label}</p>
              </li>
            ))}
          </ol>
        ) : <p className="text-ink-muted">{proj ? "No life events recorded." : "Loading…"}</p>}
      </DocSection>

      <DocSection n={4} title="3L Bucket Allocation">
        {editing && bucketList ? <BucketEditor buckets={bucketList} onChange={edit.setBuckets} />
          : buckets ? <BucketBar buckets={buckets} /> : <p className="text-ink-muted">Loading…</p>}
      </DocSection>

      <DocSection n={5} title="Risk Profile">
        <KV
          onEdit={editing ? edit.setRisk : undefined}
          rows={withOverrides([
            ["Risk category", client?.riskCategory ?? "—"],
            ["Time horizon", profile?.timeHorizon ?? "—"],
            ["Liquidity needs", profile?.liquidityNeeds ?? "—"],
          ], riskVals)} />
        <div className="avoid-break mt-4">
          <p className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">Product risk limit</p>
          <div className="mt-1"><Dashes value={client?.riskCap ?? 0} /></div>
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

      <DocSection n={6} title="Strategic Asset Allocation">
        {editing ? (
          <>
            {bucketList
              ? <SaaPortfolios clientId={cid} buckets={bucketList} value={edit.saaPortfolios} onChange={edit.setSaaPortfolio} editable notes={edit.saaNotes} onNote={edit.setSaaNotes} />
              : <p className="text-ink-muted">Loading…</p>}
            <div className="mt-8">
              <p className="mb-1 flex items-center gap-2 text-[12px] uppercase tracking-[0.06em] text-ink-muted">IC read-only allocation reference <LockedTag>Locked, filled by IC</LockedTag></p>
              {alloc ? <SaaRows rows={alloc} /> : <p className="text-ink-muted">Loading…</p>}
            </div>
          </>
        ) : (
          <>
            {hasSavedSaa && buckets
              ? <SaaPortfolios clientId={cid} buckets={buckets} value={savedSaa} editable={false} notes={savedNotes} />
              : alloc ? <SaaDonut rows={alloc} /> : <p className="text-ink-muted">Loading…</p>}
          </>
        )}
      </DocSection>

      <DocSection n={7} title="Review Rules">
        {editing
          ? <BulletEditor part={5} label="Review rules" value={textOf(5, ruleItems.length ? ruleItems : [...STATIC_RULES, OWNERSHIP])} onChange={(t) => edit.setText(5, t)} />
          : <Bullets items={ruleItems.length ? ruleItems : [...STATIC_RULES, OWNERSHIP]} />}
      </DocSection>

      <DocSection n={8} title="Acknowledgement & Signature">
        <p className="mb-6">The client confirms that this Investment Policy Statement reflects their objectives, risk profile and constraints.</p>
        <div className="grid grid-cols-1 gap-12 sm:grid-cols-2">
          <SignatureBlock label="Client" image={sigs.client} editable={editing} onChange={(d) => edit?.setSignature("client", d)} />
          <SignatureBlock label={`Relationship Manager (${rm.person})`} image={sigs.rm} editable={editing} onChange={(d) => edit?.setSignature("rm", d)} />
        </div>
      </DocSection>

      <footer className="avoid-break mt-12 flex flex-wrap justify-between gap-2 border-t border-hairline pt-4 text-[12px] text-ink-muted">
        <span>Generated by Geneva · Synthetic data</span>
        <span>Confidential · {`IPS-${id}-v${v.version}`}</span>
      </footer>
    </article>
  );
}
