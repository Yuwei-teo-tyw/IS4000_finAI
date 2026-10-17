import type { GoalProjection as GP } from "../../../types/arc";

export type Pt = GP["points"][number];

export function at(points: Pt[], year: number, k: "projected" | "required"): number {
  if (year <= points[0].year) return points[0][k];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    if (year <= b.year) {
      const t = (year - a.year) / (b.year - a.year || 1);
      return a[k] + (b[k] - a[k]) * t;
    }
  }
  return points[points.length - 1][k];
}
