import type { GoalProjection as GP } from "../../types/arc";
import { ChartCard } from "./goal/ChartCard";
import { WealthTrajectory } from "./goal/WealthTrajectory";
import { FundingByEvent } from "./goal/FundingByEvent";
import { YearsGauge } from "./goal/YearsGauge";
import { SurplusBars } from "./goal/SurplusBars";

export function GoalProjection({ data }: { data: GP }) {
  return (
    <div>
      <div className="mb-10 max-w-[560px]">
        <p className="text-xs text-ink-muted">Goal projection</p>
        <p className="mt-1 text-[44px] font-light leading-[48px] text-ink">On track for {data.yearsOnTrack} more years</p>
        <p className="mt-2 text-sm text-ink-muted">{data.summary}</p>
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <ChartCard title="Wealth Trajectory" caption="Projected portfolio against the value required, with life events."><WealthTrajectory data={data} /></ChartCard>
        <ChartCard title="Funding By Life Event" caption="Share of each event funded by the projected portfolio."><FundingByEvent data={data} /></ChartCard>
        <ChartCard title="Years On Track" caption="Years the plan holds, against a 15-year comfort scale."><YearsGauge years={data.yearsOnTrack} /></ChartCard>
        <ChartCard title="Surplus Or Shortfall Over Time" caption="Projected minus required, every five years (S$m)."><SurplusBars data={data} /></ChartCard>
      </div>
    </div>
  );
}

export default GoalProjection;
