/**
 * SVG path for one donut or pie slice: a filled ring segment from fraction `f0` to `f1` of the circle
 * (0 = 12 o'clock, clockwise). `rInner` 0 gives a pie slice.
 *
 * Donuts used to be drawn as thick dashed circles (stroke-dasharray). Chrome and Edge flatten a dashed curve
 * into short straight pieces, which shows as faceted, polygon-like ring edges. Real arcs stay smooth on
 * screen, in print and in the PDF export. Use with fillRule="evenodd" so a whole ring keeps its hole.
 */
export function ringPath(cx: number, cy: number, rOuter: number, rInner: number, f0: number, f1: number): string {
  const circle = (r: number, sweep: 0 | 1) =>
    `M ${cx} ${cy - r} A ${r} ${r} 0 1 ${sweep} ${cx} ${cy + r} A ${r} ${r} 0 1 ${sweep} ${cx} ${cy - r} Z`;
  if (f1 - f0 >= 0.9999) {
    // A whole ring cannot be one arc: two half-circles per edge; evenodd cuts the hole.
    return rInner > 0 ? `${circle(rOuter, 1)} ${circle(rInner, 0)}` : circle(rOuter, 1);
  }
  const pt = (r: number, f: number) =>
    `${(cx + r * Math.sin(2 * Math.PI * f)).toFixed(3)} ${(cy - r * Math.cos(2 * Math.PI * f)).toFixed(3)}`;
  const large = f1 - f0 > 0.5 ? 1 : 0;
  const outer = `M ${pt(rOuter, f0)} A ${rOuter} ${rOuter} 0 ${large} 1 ${pt(rOuter, f1)}`;
  return rInner > 0
    ? `${outer} L ${pt(rInner, f1)} A ${rInner} ${rInner} 0 ${large} 0 ${pt(rInner, f0)} Z`
    : `${outer} L ${cx} ${cy} Z`;
}
