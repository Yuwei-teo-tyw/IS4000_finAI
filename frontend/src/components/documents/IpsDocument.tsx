import { useParams } from "react-router-dom";
import type { IpsVersion } from "../../types/arc";
import { arcApi } from "../../services/arcApi";
import { profileApi } from "../../services/profileApi";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import { useAsync } from "../ui";
import { GenevaMark } from "./GenevaMark";
import { Bullets, DocSection, Dashes, KV, SignatureBlock, WRAP, toBullets } from "./ips/parts";
import { BucketBar, SaaDonut } from "./ips/charts";

const fmt = (s: string) => new Date(s).toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
const STATIC_RULES = [
  "The portfolio is reviewed at least quarterly by the Relationship Manager and Investment Counsellor",
  "Rebalance when an asset class drifts outside its allowed range around the SAA",
  "Review the IPS on any major life event",
  "Reissue the IPS on any change in the client risk profile",
];

interface Props { version: IpsVersion; clientName: string; clientId?: string }

export function IpsDocument({ version: v, clientName, clientId }: Props) {
  const params = useParams();
  const cid = clientId ?? params.clientId ?? "";
  const client = useAsync(() => arcApi.getClient(cid), [cid]);
  const buckets = useAsync(() => arcApi.get3L(cid), [cid]);
  const alloc = useAsync(() => arcApi.getAllocation(cid), [cid]);
  const proj = useAsync(() => arcApi.getGoalProjection(cid), [cid]);
  const profile = useAsync(() => profileApi.getClientProfile(cid), [cid]);

  const part = (n: number) => v.parts.find((p) => p.part === n)?.body ?? "";
  const goals = toBullets(part(1));
  const goalItems = goals.length ? goals : profile?.goals ?? [];
  const riskText = toBullets(part(3));
  const lossItems = [...(profile?.lossTolerance ?? []), ...riskText.filter((t) => /drawdown|tolerate|fall/i.test(t) && !(profile?.lossTolerance ?? []).includes(t))].slice(0, 4);
  const ruleItems = toBullets(part(5));
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

      <DocSection n={1} title="Client Demographics">
        <KV rows={[
          ["Full name", name], ["Client ID", id],
          ["Date of birth / age", profile ? `${profile.dateOfBirth} (${profile.age})` : "—"],
          ["Nationality / residency", profile ? `${profile.nationality} / ${profile.residency}` : "—"],
          ["Occupation", profile?.occupation ?? "—"], ["Marital status", profile?.maritalStatus ?? "—"],
          ["Dependants", profile?.dependants ?? "—"], ["Employment / income source", profile?.incomeSource ?? "—"],
          ["Tax residency", profile?.taxResidency ?? "—"], ["Contact RM", `${rm.person}, ${rm.name}`],
        ]} />
      </DocSection>

      <DocSection n={2} title="Client Goals & Objectives">
        {goalItems.length ? <Bullets items={goalItems} /> : <p className="text-ink-muted">Not yet completed.</p>}
      </DocSection>

      <DocSection n={3} title="Life Events">
        {proj?.events.length ? (
          <ol className="ml-1.5 border-l border-hairline">
            {proj.events.map((e) => (
              <li key={`${e.year}-${e.label}`} className="avoid-break relative pb-4 pl-6 last:pb-0">
                <i className="absolute -left-[5px] top-[7px] h-[9px] w-[9px] rounded-full bg-brand" />
                <p className="font-semibold">{e.year}</p>
                <p className={WRAP}>{e.label}</p>
              </li>
            ))}
          </ol>
        ) : <p className="text-ink-muted">{proj ? "No life events recorded." : "Loading…"}</p>}
      </DocSection>

      <DocSection n={4} title="3L Bucket Allocation">
        {buckets ? <BucketBar buckets={buckets} /> : <p className="text-ink-muted">Loading…</p>}
      </DocSection>

      <DocSection n={5} title="Risk Profile">
        <KV rows={[
          ["Risk category", client?.riskCategory ?? "—"],
          ["Time horizon", profile?.timeHorizon ?? "—"],
          ["Liquidity needs", profile?.liquidityNeeds ?? "—"],
        ]} />
        <div className="avoid-break mt-4">
          <p className="text-[12px] uppercase tracking-[0.06em] text-ink-muted">Product risk limit</p>
          <div className="mt-1"><Dashes value={client?.riskCap ?? 0} /></div>
        </div>
        {lossItems.length > 0 && (
          <div className="avoid-break mt-4">
            <p className="mb-1 text-[12px] uppercase tracking-[0.06em] text-ink-muted">Loss tolerance</p>
            <Bullets items={lossItems} />
          </div>
        )}
      </DocSection>

      <DocSection n={6} title="Strategic Asset Allocation">
        {alloc ? <SaaDonut rows={alloc} /> : <p className="text-ink-muted">Loading…</p>}
      </DocSection>

      <DocSection n={7} title="Review Rules">
        <Bullets items={[...(ruleItems.length ? ruleItems : STATIC_RULES), "Investment Counsellor owns the SAA and TAA; Product Specialist owns product selection; Relationship Manager owns the IPS and client contact"]} />
      </DocSection>

      <DocSection n={8} title="Acknowledgement & Signature">
        <p className="mb-6">The client confirms that this Investment Policy Statement reflects their objectives, risk profile and constraints.</p>
        <div className="grid grid-cols-1 gap-12 sm:grid-cols-2">
          <SignatureBlock label="Client" />
          <SignatureBlock label={`Relationship Manager (${rm.person})`} />
        </div>
      </DocSection>

      <footer className="avoid-break mt-12 flex flex-wrap justify-between gap-2 border-t border-hairline pt-4 text-[12px] text-ink-muted">
        <span>Generated by Geneva · Synthetic data</span>
        <span>Confidential · {`IPS-${id}-v${v.version}`}</span>
      </footer>
    </article>
  );
}
