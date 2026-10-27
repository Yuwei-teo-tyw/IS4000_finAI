import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Link, useOutletContext } from "react-router-dom";
import { Button, Section, Loading, MockTag } from "../../components/ui";
import type { PortfolioCtx } from "./ClientLayout";
import type { ClientPortfolio as Portfolio, PortfolioHolding, PortfolioThreeLRow } from "../../types/arc";

const n2 = (v: number | null | undefined) => (v == null ? "" : v.toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const whole = (v: number) => v.toLocaleString("en-SG", { maximumFractionDigits: 0 });
const signedWhole = (v: number) => { const r = Math.round(v); return `${r > 0 ? "+" : ""}${whole(r)}`; };
const signedPct = (v: number) => { const r = Math.round(v); return `${r > 0 ? "+" : ""}${r}%`; };
const TAA_FLAG_PTS = 10;
const p1 = (v: number | null | undefined) => (v == null ? "Not set" : `${v.toFixed(1)}%`);
const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/* ---- shared asset-class palette (same colour for SAA and TAA) ---- */
type ClassKey = "Equities" | "Fixed income" | "Alternatives" | "Liquidity" | "Other";
const CLASSES: { key: ClassKey; color: string }[] = [
  { key: "Equities", color: "var(--chart-equities)" },
  { key: "Fixed income", color: "var(--chart-bonds)" },
  { key: "Alternatives", color: "var(--chart-alternatives)" },
  { key: "Liquidity", color: "var(--chart-liquidity)" },
  { key: "Other", color: "var(--hairline-strong)" },
];
function toClass(raw: string): ClassKey {
  const s = raw.toLowerCase();
  if (s.includes("equit")) return "Equities";
  if (s.includes("fixed") || s.includes("bond")) return "Fixed income";
  if (s.includes("altern")) return "Alternatives";
  if (s.includes("cash") || s.includes("liquid")) return "Liquidity";
  return "Other";
}
type Slice = { key: ClassKey; pct: number };

function bucketSaa(saa: Record<string, number> | null | undefined): Slice[] | null {
  if (!saa) return null;
  const m = new Map<ClassKey, number>();
  Object.entries(saa).forEach(([k, v]) => m.set(toClass(k), (m.get(toClass(k)) ?? 0) + Number(v)));
  const out = CLASSES.map((c) => ({ key: c.key, pct: m.get(c.key) ?? 0 }));
  return out.some((s) => s.pct > 0) ? out : null;
}
function bucketHoldings(hs: PortfolioHolding[]): Slice[] | null {
  const priced = hs.filter((h) => (h.market_value ?? 0) > 0);
  const total = priced.reduce((a, h) => a + (h.market_value ?? 0), 0);
  if (total <= 0) return null;
  return CLASSES.map((c) => ({
    key: c.key,
    pct: (priced.filter((h) => toClass(h.asset_class) === c.key).reduce((a, h) => a + (h.market_value ?? 0), 0) / total) * 100,
  }));
}

/* ---- MOCKED scores (deterministic, computed in the browser) ---- */
function diversificationScore(hs: PortfolioHolding[]): number | null {
  const slices = bucketHoldings(hs);
  if (!slices) return null;
  const n = hs.filter((h) => (h.market_value ?? 0) > 0).length;
  const w = slices.map((s) => s.pct / 100).filter((x) => x > 0);
  const entropy = w.length > 1 ? -w.reduce((a, x) => a + x * Math.log(x), 0) / Math.log(CLASSES.length) : 0;
  const maxHolding = Math.max(...hs.map((h) => (h.weight_pct ?? 0) / 100), 0);
  return Math.round(Math.min(n, 20) / 20 * 35 + entropy * 40 + (1 - maxHolding) * 25);
}
const RISK_FACTOR: Record<ClassKey, number> = { Equities: 80, "Fixed income": 30, Alternatives: 70, Liquidity: 5, Other: 50 };
function riskScore(hs: PortfolioHolding[]): number | null {
  const slices = bucketHoldings(hs);
  return slices ? Math.round(slices.reduce((a, s) => a + (s.pct / 100) * RISK_FACTOR[s.key], 0)) : null;
}

const PANEL_H = "h-[400px]";
const panel = `${PANEL_H} flex flex-col border border-hairline bg-surface-100 p-6`;

/* ---- KPI ---- */
function Kpi({ label, value, note, mock }: { label: string; value: string; note: string; mock?: boolean }) {
  return (
    <div className="flex h-[168px] min-w-0 flex-col justify-between overflow-hidden border border-hairline bg-surface-100 p-6">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-normal uppercase tracking-[0.12em] text-ink-muted">{label}</p>
        {mock && <MockTag note="Computed in the browser from holdings; not a backend value." />}
      </div>
      <p className="break-words text-3xl font-light leading-tight md:text-[36px]">{value}</p>
      <p className="text-sm font-light text-ink-muted">{note}</p>
    </div>
  );
}

/* ---- 3L target vs actual ---- */
function ThreeLBars({ rows }: { rows: PortfolioThreeLRow[] }) {
  return (
    <div className="space-y-6">
      {rows.map((r) => {
        const t = r.target_pct, a = r.actual_pct;
        const gap = t != null && r.difference_pct != null ? ` · Gap ${r.difference_pct > 0 ? "+" : ""}${r.difference_pct.toFixed(1)}%` : "";
        return (
          <div key={r.portfolio}>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-base font-light">{cap(r.portfolio)}</p>
              <p className="text-sm font-light tabular-nums text-ink-muted">{t == null ? "Target not set" : `Target ${p1(t)}`} · Actual {p1(a)}{gap}</p>
            </div>
            <div className="relative h-2 bg-surface-300" role="img" aria-label={`${cap(r.portfolio)} actual ${p1(a)}, ${t == null ? "target not set" : `target ${p1(t)}`}`}>
              <div className="h-2 bg-ink" style={{ width: `${Math.min(a ?? 0, 100)}%` }} />
              {t != null && <div className="absolute -top-1 h-4 w-0.5 bg-ink" style={{ left: `${Math.min(t, 100)}%` }} title={`Target ${p1(t)}`} />}
            </div>
          </div>
        );
      })}
      <p className="text-xs font-light text-ink-muted">{rows.some((r) => r.target_pct != null) ? "Bar is the actual share of AUM; the marker is the IPS target. Portfolios with no target set show no marker." : "Bar is the actual share of AUM. No IPS target is set, so there is no marker."}</p>
    </div>
  );
}

/* ---- Donut (plain SVG) ---- */
function Donut({ title, slices, empty, active, onActive, compareTo }: { title: string; slices: Slice[] | null; empty: string; active?: ClassKey | null; onActive?: (k: ClassKey | null) => void; compareTo?: Slice[] | null }) {
  return (
    <div className={panel}>
      <h4 className="text-lg font-light">{title}</h4>
      {!slices ? (
        <p className="mt-6 text-sm font-light text-ink-muted">{empty}</p>
      ) : (
        <>
          <DonutSvg title={title} slices={slices} active={active ?? null} onActive={onActive} />
          <ul className="mt-auto space-y-1 text-sm font-light">
            {slices.map((s) => {
              const saaPct = compareTo ? compareTo.find((x) => x.key === s.key)?.pct : undefined;
              const diff = saaPct != null ? s.pct - saaPct : null;
              const flagged = diff != null && Math.abs(diff) >= TAA_FLAG_PTS - 1e-9;
              const dText = diff == null ? "" : `${diff > 0 ? "+" : ""}${diff.toFixed(1)} pts`;
              const flagLabel = `${s.key} is ${dText} vs SAA`;
              const on = active === s.key;
              return (
                <li key={s.key} tabIndex={onActive ? 0 : undefined}
                  aria-label={`${s.key} ${s.pct.toFixed(1)} percent${flagged ? `. Warning: ${flagLabel}` : ""}`}
                  onMouseEnter={() => onActive?.(s.key)} onMouseLeave={() => onActive?.(null)}
                  onFocus={() => onActive?.(s.key)} onBlur={() => onActive?.(null)}
                  className={`flex items-center justify-between gap-3 border-l-2 pl-2 ${on ? "border-ink" : "border-transparent"} ${active && !on ? "opacity-50" : ""}`}>
                  <span className="flex items-center gap-2"><i className="inline-block h-2.5 w-2.5" style={{ background: CLASSES.find((c) => c.key === s.key)!.color, outline: "1px solid var(--hairline-strong)" }} />{s.key}
                    {flagged && <AlertTriangle className="h-3.5 w-3.5 text-ink" role="img" aria-label={flagLabel}><title>{flagLabel}</title></AlertTriangle>}
                  </span>
                  <span className="tabular-nums">{flagged && <span className="mr-2 text-ink-muted">{dText}</span>}{s.pct.toFixed(1)}%</span>
                </li>
              );
            })}
          </ul>
          {compareTo && <p className="mt-2 text-xs font-light text-ink-muted">A warning icon marks an asset class whose TAA weight differs from its SAA weight by {TAA_FLAG_PTS} percentage points or more.</p>}
        </>
      )}
    </div>
  );
}
function DonutSvg({ title, slices, active, onActive }: { title: string; slices: Slice[]; active: ClassKey | null; onActive?: (k: ClassKey | null) => void }) {
  const r = 52, c = 2 * Math.PI * r;
  let off = 0;
  const total = slices.reduce((a, s) => a + s.pct, 0) || 1;
  return (
    <svg viewBox="0 0 140 140" className="mx-auto my-3 h-[150px] w-[150px] shrink-0" role="group"
      aria-label={`${title}: ${slices.filter((s) => s.pct > 0).map((s) => `${s.key} ${s.pct.toFixed(1)} percent`).join(", ")}`}>
      <title>{title}</title>
      <circle cx="70" cy="70" r={r} fill="none" stroke="var(--surface-300)" strokeWidth="22" />
      {slices.filter((s) => s.pct > 0).map((s) => {
        const len = (s.pct / total) * c;
        const ang = (off / c) * 2 * Math.PI - Math.PI / 2;
        const sep = <line key={s.key + "-sep"} x1={70 + (r - 12) * Math.cos(ang)} y1={70 + (r - 12) * Math.sin(ang)} x2={70 + (r + 12) * Math.cos(ang)} y2={70 + (r + 12) * Math.sin(ang)} stroke="var(--surface-100)" strokeWidth="1.5" />;
        const el = (
          <circle cx="70" cy="70" r={r} fill="none" stroke={CLASSES.find((x) => x.key === s.key)!.color} strokeWidth="22"
            strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-off} transform="rotate(-90 70 70)"
            tabIndex={onActive ? 0 : undefined} role="img" aria-label={`${title}: ${s.key} ${s.pct.toFixed(1)} percent`}
            opacity={active && active !== s.key ? 0.3 : 1}
            onMouseEnter={() => onActive?.(s.key)} onMouseLeave={() => onActive?.(null)}
            onFocus={() => onActive?.(s.key)} onBlur={() => onActive?.(null)}>
            <title>{`${s.key} ${s.pct.toFixed(1)}%`}</title>
          </circle>
        );
        off += len;
        return <g key={s.key}>{el}{sep}</g>;
      })}
    </svg>
  );
}

/* ---- Holdings per L ---- */
function HoldingsPanel({ name, hs, currency, active }: { name: string; hs: PortfolioHolding[]; currency: string; active?: ClassKey | null }) {
  const total = hs.reduce((a, h) => a + (h.market_value ?? 0), 0);
  return (
    <div className={panel}>
      <h4 className="text-lg font-light">Holdings</h4>
      {hs.length === 0 ? (
        <p className="mt-6 text-sm font-light text-ink-muted">No holdings in the {name} portfolio.</p>
      ) : (
        <div className="mt-3 min-h-0 flex-1 overflow-auto border-y border-hairline">
          <table className="w-full text-left text-[13px] font-light">
            <caption className="sr-only">{name} holdings, values in {currency}</caption>
            <thead className="sticky top-0 bg-surface-100 text-ink-muted">
              <tr>
                <th className="py-2 pr-2 text-xs font-normal uppercase tracking-[0.12em]">Holding</th>
                <th className="py-2 pr-2 text-xs font-normal uppercase tracking-[0.12em]">Class</th>
                <th className="py-2 pr-2 text-right text-xs font-normal uppercase tracking-[0.12em]">Value</th>
                <th className="py-2 pr-2 text-right text-xs font-normal uppercase tracking-[0.12em]">P&amp;L</th>
                <th className="py-2 pr-2 text-right text-xs font-normal uppercase tracking-[0.12em]">P&amp;L %</th>
                <th className="py-2 text-right text-xs font-normal uppercase tracking-[0.12em]">% of L</th>
              </tr>
            </thead>
            <tbody>
              {hs.map((h, i) => (
                <tr key={h.ticker + i} aria-current={active && toClass(h.asset_class) === active ? "true" : undefined}
                  className={`border-t border-hairline ${h.price_available ? "" : "text-ink-muted"} ${active ? (toClass(h.asset_class) === active ? "bg-surface-200" : "opacity-40") : ""}`}>
                  <td className={`border-l-2 py-2 pl-2 pr-2 align-top ${active && toClass(h.asset_class) === active ? "border-ink" : "border-transparent"}`}><span className="block">{h.ticker}</span><span className="block text-xs text-ink-muted">{h.name}</span></td>
                  <td className="py-2 pr-2 align-top">{toClass(h.asset_class)}</td>
                  <td className="py-2 pr-2 text-right align-top tabular-nums">{h.price_available ? n2(h.market_value) : "No price"}</td>
                  <td className="py-2 pr-2 text-right align-top tabular-nums">{h.price_available && h.pnl != null ? signedWhole(h.pnl) : ""}</td>
                  <td className="py-2 pr-2 text-right align-top tabular-nums">{h.price_available && h.pnl_pct != null ? signedPct(h.pnl_pct) : ""}</td>
                  <td className="py-2 text-right align-top tabular-nums">{h.price_available && total > 0 ? `${(((h.market_value ?? 0) / total) * 100).toFixed(1)}%` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LRow({ name, hs, row, currency, tlAvailable }: { name: string; hs: PortfolioHolding[]; row?: PortfolioThreeLRow; currency: string; tlAvailable: boolean }) {
  const [active, setActive] = useState<ClassKey | null>(null);
  const saa = tlAvailable ? bucketSaa(row?.saa) : null;
  const taa = bucketHoldings(hs);
  const saaMsg = !tlAvailable
    ? "The saved IPS has no 3L allocation, so the strategic allocation is unavailable."
    : row?.strategy ? "No SAA weights are available for this strategy." : "No SAA strategy is set for this portfolio in the IPS.";
  const bothMissing = !saa && !taa;
  return (
    <Section title={cap(name)} hint={row?.strategy ? `Strategy ${row.strategy}${row.strategy_name ? ` · ${row.strategy_name}` : ""}` : "No strategy set"}>
      {!bothMissing && (
        <ul className="mb-4 flex flex-wrap gap-x-6 gap-y-1 text-xs font-light text-ink-muted" aria-label="Asset class legend (shared by both charts)">
          {CLASSES.map((c) => (
            <li key={c.key} className="flex items-center gap-2"><i className="inline-block h-2.5 w-2.5" style={{ background: c.color, outline: "1px solid var(--hairline-strong)" }} />{c.key}</li>
          ))}
        </ul>
      )}
      {!saa && <p className="mb-4 text-sm font-light text-ink-muted">{bothMissing ? `${saaMsg} There are also no priced holdings in the ${name} portfolio.` : saaMsg}</p>}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {saa && <Donut title="Strategic allocation (SAA)" slices={saa} empty="" active={active} onActive={setActive} />}
        {taa ? <Donut title="Tactical allocation (TAA, current)" slices={taa} empty="" active={active} onActive={setActive} compareTo={saa} /> : saa ? <Donut title="Tactical allocation (TAA, current)" slices={null} empty={`No priced holdings in the ${name} portfolio.`} /> : null}
        <div className={`${saa && taa ? "md:col-span-2 lg:col-span-1" : "md:col-span-2 lg:col-span-3"}`}><HoldingsPanel name={name} hs={hs} currency={currency} active={active} /></div>
      </div>
    </Section>
  );
}

function NoHoldingsView({ p }: { p: Portfolio }) {
  return (
    <div>
      <Section title="Portfolio at a glance">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <Kpi label="AUM" value={p.aum.label || "No holdings yet"} note="No value until holdings are added" />
          <Kpi label="Diversification score" value="Not available" note="Needs holdings" />
          <Kpi label="Risk score" value="Not available" note="Needs holdings" />
        </div>
      </Section>
      <div className="border border-hairline bg-surface-100 p-8" role="status">
        <p className="text-lg font-light text-ink">No holdings yet</p>
        <p className="mt-2 text-sm font-light text-ink-muted">This client has no holdings recorded. Allocation and holdings appear here once holdings are added.</p>
      </div>
    </div>
  );
}

function View({ p }: { p: Portfolio }) {
  const asAt = p.holdings.filter((h) => h.price_as_at).map((h) => h.price_as_at as string).sort().pop() ?? null;
  const tl = p.three_l;
  const div = diversificationScore(p.holdings);
  const risk = riskScore(p.holdings);
  const riskLabel = risk == null ? "" : risk < 35 ? "Low" : risk < 60 ? "Moderate" : "High";
  const rowFor = (name: string) => tl?.portfolios?.find((r) => r.portfolio.toLowerCase() === name);
  return (
    <div>
      <Section title="Portfolio at a glance" hint={asAt ? `Prices as at ${asAt}` : undefined}>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <Kpi label="AUM" value={p.aum.value == null ? p.aum.label : `${p.currency} ${p.aum.label}`} note="Total, priced holdings only" />
          <Kpi label="Diversification score" value={div == null ? "Not available" : `${div} / 100`} note="Holding count, asset-class spread, concentration" mock />
          <Kpi label="Risk score" value={risk == null ? "Not available" : `${risk} / 100 · ${riskLabel}`} note="Weighted by asset-class risk factors" mock />
        </div>
      </Section>

      <Section title="3L portfolio allocation" hint="Saved IPS target compared with what is held.">
        {tl?.available && tl.portfolios ? <ThreeLBars rows={tl.portfolios} /> : <p className="text-sm font-light text-ink-muted">{tl?.message ?? "The 3L comparison is unavailable."}</p>}
      </Section>

      {["liquidity", "longevity", "legacy"].map((name) => (
        <LRow key={name} name={name} hs={p.holdings.filter((h) => h.portfolio.toLowerCase() === name)} row={rowFor(name)} currency={p.currency} tlAvailable={!!tl?.available} />
      ))}

      {p.notes.length > 0 && <ul className="space-y-1 text-sm font-light text-ink-muted">{p.notes.map((t) => <li key={t}>{t}</li>)}</ul>}
    </div>
  );
}

export default function ClientPortfolio() {
  const { portfolio } = useOutletContext<PortfolioCtx>();
  if (portfolio.loading) return <Loading />;
  if (portfolio.error) return (
    <div role="alert">
      <p className="text-lg font-light text-ink">The portfolio could not be loaded.</p>
      <p className="mt-2 text-sm font-light text-ink-muted">{portfolio.error.message || "The portfolio service did not respond."} Your data is unchanged; try again.</p>
      <div className="mt-6 flex items-center gap-6">
        <Button variant="secondary" onClick={portfolio.retry}>Retry</Button>
        <Link to=".." relative="path" className="text-sm text-ink-muted hover:text-ink">Back to overview</Link>
      </div>
    </div>
  );
  if (!portfolio.data) return (
    <div>
      <p className="text-lg font-light text-ink">Portfolio data is unavailable.</p>
      <Link to=".." relative="path" className="mt-4 inline-block text-sm text-ink-muted hover:text-ink">Back to overview</Link>
    </div>
  );
  if (portfolio.data.status === "no_holdings") return <NoHoldingsView p={portfolio.data} />;
  return <View p={portfolio.data} />;
}
