"""Server-side SVG charts for the review-pack template.

Each chart is a pure function (data -> SVG string). Output only contains numbers
and fixed labels from our own enums, so it is safe to mark as trusted markup.
"""
from html import escape
from math import pi

from markupsafe import Markup

COLORS = {
    "Cash": "#5a5249",
    "Fixed income": "#d5c4b0",
    "Equities": "#a06a50",
    "Alternatives": "#e3cd85",
}
GROUP_ORDER = ["Cash", "Fixed income", "Equities", "Alternatives"]


def _group(asset_class: str) -> str:
    return asset_class if asset_class in COLORS else "Alternatives"


def saa_donut(rows: list[dict]) -> Markup:
    """Strategic asset allocation donut with legend and per-class bands."""
    totals = {g: 0.0 for g in GROUP_ORDER}
    for r in rows:
        totals[_group(r["asset_class"])] += float(r["saa"])
    total = sum(totals.values()) or 1.0
    radius, circ, offset = 70, 2 * pi * 70, 0.0
    arcs = []
    for g in GROUP_ORDER:
        if totals[g] <= 0:
            continue
        length = totals[g] / total * circ
        arcs.append(
            f'<circle cx="100" cy="100" r="{radius}" fill="none" stroke="{COLORS[g]}" stroke-width="28" '
            f'stroke-dasharray="{length:.2f} {circ - length:.2f}" stroke-dashoffset="{-offset:.2f}"/>'
        )
        offset += length
    legend = "".join(
        f'<li><i style="background:{COLORS[g]}"></i>{escape(g)}<b>{totals[g]:g}%</b></li>'
        for g in GROUP_ORDER
        if totals[g] > 0
    )
    bands = "".join(
        f'<li>{escape(str(r["asset_class"]))} {float(r["saa"]):g}% '
        f'<span>(min {max(0, float(r["saa"]) - float(r["band"])):g}% – max {float(r["saa"]) + float(r["band"]):g}%)</span></li>'
        for r in rows
    )
    return Markup(
        '<div class="chart chart-saa"><p class="chart-title">Strategic asset allocation</p>'
        '<div class="saa-grid"><div>'
        '<svg viewBox="0 0 200 200" width="180" height="180" role="img" aria-label="Strategic asset allocation">'
        '<circle cx="100" cy="100" r="70" fill="none" stroke="#d0cec5" stroke-width="28"/>'
        f'<g transform="rotate(-90 100 100)">{"".join(arcs)}</g>'
        '<text x="100" y="105" text-anchor="middle" font-size="14" fill="#1c1c1c">SAA</text></svg>'
        f'<ul class="legend">{legend}</ul></div><ul class="bands">{bands}</ul></div></div>'
    )


def taa_bars(rows: list[dict]) -> Markup:
    """Old vs new tactical allocation, paired horizontal bars per asset class."""
    peak = max([float(r[k]) for r in rows for k in ("old_taa", "new_taa")] + [1.0])
    lines = []
    for r in rows:
        old, new = float(r["old_taa"]), float(r["new_taa"])
        lines.append(
            f'<div class="taa-row"><span class="taa-label">{escape(str(r["asset_class"]))}</span><div class="taa-bars">'
            f'<div class="bar old" style="width:{old / peak * 100:.1f}%"></div>'
            f'<div class="bar new" style="width:{new / peak * 100:.1f}%"></div></div>'
            f'<span class="taa-val">{old:g}% → {new:g}%</span></div>'
        )
    return Markup(
        '<div class="chart chart-taa"><p class="chart-title">Old vs new tactical allocation</p>'
        f'{"".join(lines)}<p class="chart-key"><i class="old"></i>Old TAA <i class="new"></i>New TAA</p></div>'
    )


# Placeholder registry: template names -> (renderer, data key it consumes).
# Unknown names or missing data fail loudly instead of silently dropping a chart.
CHARTS = {"saa": (saa_donut, "allocation"), "taa": (taa_bars, "allocation")}
