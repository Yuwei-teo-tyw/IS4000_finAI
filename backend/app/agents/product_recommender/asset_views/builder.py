"""
Assembles an AssetClassView from the latest Market Researcher run, the CIO
house view and the shelf. All text here is deterministic and built from the
scores, with an indicator, event or citation ref on every point.
"""
from datetime import datetime
from typing import Optional

from app.agents.market_researcher.schemas import MarketResearchOutput
from app.agents.portfolio_agent.schemas.client import ClientProfile
from app.agents.portfolio_agent.schemas.upstream import UpstreamResult
from app.agents.portfolio_agent.taxonomy import AssetClass
from app.agents.product_recommender.asset_views import config as cfg
from app.agents.product_recommender.asset_views import scoring, shelf_lens
from app.agents.product_recommender.asset_views.schemas import (
    AgentView,
    AgreementResult,
    AssetClassHeadline,
    AssetClassView,
    Coverage,
    DataQuality,
    Ref,
    RegimeRef,
    Scenario,
    SegmentResult,
    SnapshotItem,
    Trigger,
)
from app.agents.product_recommender.config import Settings
from app.agents.product_recommender.schemas import (
    AssetClassHouseView,
    HouseView,
    ShelfProduct,
)

US_ONLY = "Market data is US-only; SGD rates and Singapore and Asian markets are not yet covered by the Market Researcher."
PHASE_TEXT = {"early_expansion": "early expansion", "late_expansion": "late expansion",
              "recession": "recession", "late_recession": "late recession"}
_ORDER = {"Sell": 0, "Hold": 1, "Buy": 2}


# --- Text helpers ------------------------------------------------------------

def _value(c: scoring.Contribution) -> str:
    ind = c.series.ind
    if ind.unit == "%":
        return f"{ind.value:g}%"
    return f"{ind.value:g}" if ind.unit == "index" else f"{ind.value:g} {ind.unit}"


def _change(c: scoring.Contribution, x: float) -> str:
    if c.series.is_price:
        return f"{x:+.1f}%"
    return f"{x:+.2f}pp" if c.series.ind.unit in ("%", "pp") else f"{x:+.2f}"


def ordinal(p: float) -> str:
    whole = int(p)
    if p != whole:
        return f"{p:g}th"
    return f"{whole}{'th' if 10 <= whole % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(whole % 10, 'th')}"


def describe(c: scoring.Contribution) -> str:
    ind = c.series.ind
    if c.sig.basis == "level":
        return f"{ind.name} at {_value(c)}, in the {ordinal(ind.percentile_10y)} percentile of the last 10 years"
    ch = ind.changes.get("3m", 0.0)
    if c.sig.basis == "relative":
        lead = "ahead of" if c.reading >= 0 else "behind"
        return f"{ind.name} {lead} the S&P 500 over 3 months ({_change(c, ch)})"
    return f"{ind.name} {_change(c, ch)} over 3 months"


def short_label(c: scoring.Contribution) -> str:
    """Names which reading of a series is meant, so a level and a move of the same series read differently."""
    name = c.series.ind.name
    if c.sig.basis == "level":
        return f"the level of the {name}"
    if c.sig.basis == "relative":
        return f"how the {name} has done against the S&P 500"
    return f"the 3-month {'rise' if c.series.ind.changes.get('3m', 0) >= 0 else 'fall'} in the {name}"


def _effect(c: scoring.Contribution) -> str:
    return "supports" if c.value > 0.05 else "weighs" if c.value < -0.05 else "neutral"


def _ref(c: scoring.Contribution, ac: AssetClass) -> Ref:
    verb = {"supports": "supports", "weighs": "weighs on", "neutral": "is neutral for"}[_effect(c)]
    why = f" ({c.sig.why})" if c.sig.why else ""
    return Ref(text=f"{describe(c)}: {verb} {ac.value.lower()}{why}", refs=[c.sig.id])


def _trigger_text(c: scoring.Contribution, towards: int) -> str:
    """A move that would push this signal fully to +1 (towards=1) or -1 (towards=-1) for the class."""
    need = towards * c.sig.direction  # reading sign needed
    name = c.series.ind.name
    if c.sig.basis == "level":
        return f"{name} {'above' if need > 0 else 'below'} its 10-year {'high' if need > 0 else 'low'} range ({'90th' if need > 0 else '10th'} percentile or {'more' if need > 0 else 'less'})"
    move = _change(c, c.sig.scale).lstrip("+")
    if c.sig.basis == "relative":
        return f"{name} {'outperforms' if need > 0 else 'underperforms'} the S&P 500 by {move} or more over 3 months"
    return f"{name} {'rises' if need > 0 else 'falls'} by {move} or more over 3 months"


# --- Pieces ------------------------------------------------------------------

def _agreement(cio: str, agent: str, h: scoring.Headline, ac: AssetClass, cv: AssetClassHouseView) -> AgreementResult:
    gap = abs(_ORDER[cio] - _ORDER[agent])
    if gap == 0:
        return AgreementResult(status="aligned")
    sign = 1 if _ORDER[agent] > _ORDER[cio] else -1  # agent more positive (1) or more negative (-1)
    drivers = sorted((c for c in h.scored.contributions if c.value * sign > 0.05), key=lambda c: -abs(c.weighted))[:2]
    because = "; ".join(describe(c) for c in drivers) or "the regime reading"
    return AgreementResult(
        status="differs" if gap == 1 else "opposed",
        explanation=(f"The CIO rates {ac.value.lower()} {cv.cio_term} ({cv.view}) [{cv.citation_id}]; the agent's data reads "
                     f"{agent}, driven by {because}. Raise with the CIO desk if it matters for this client."),
    )


def _segments(ac: AssetClass, spec, idx, class_score: float) -> list[SegmentResult]:
    out = []
    for s in scoring.segments(spec, idx, class_score):
        if s.scored is None:
            out.append(SegmentResult(group=s.segment.group, segment=s.segment.name, view="Neutral", reason=s.segment.no_data_reason))
            continue
        top = max(s.scored.contributions, key=lambda c: abs(c.weighted))
        out.append(SegmentResult(
            group=s.segment.group, segment=s.segment.name, view=s.view, score=s.scored.score,
            reason=f"{describe(top)} (segment score {s.scored.score:+.2f} vs {class_score:+.2f} for the class)",
            refs=sorted({c.sig.id for c in s.scored.contributions}),
        ))
    return out


def _scenarios(ac: AssetClass, h: scoring.Headline) -> tuple[list[Scenario], list[Ref]]:
    key = [c for c in scoring.key_signals(h, len(h.scored.contributions)) if c.sig.basis != "level"][:3]
    scenarios = [Scenario(case="base", description=f"Current readings persist: the agent view stays {h.view}.",
                          stance_implication=f"Stays {h.view} (score {h.scored.score:+.2f}).")]
    for case, towards in (("upside", 1), ("downside", -1)):
        lead = scoring.biggest_swing(h, towards)
        if lead is None:
            continue
        score, new = scoring.what_if(h, lead, towards * lead.sig.direction)
        scenarios.append(Scenario(
            case=case,
            description=(f"{'Better' if towards > 0 else 'Worse'} conditions for {ac.value.lower()}, led by the series "
                         f"with the most room to move: {lead.series.ind.name}."),
            trigger=Trigger(indicator=lead.sig.id, condition=_trigger_text(lead, towards)),
            stance_implication=f"Would move to {new} (score {score:+.2f})." if new != h.view else f"Stays {h.view} (score {score:+.2f}).",
        ))
    watch = []
    for c in key:
        for towards in (1, -1):
            score, new = scoring.what_if(h, c, towards * c.sig.direction)
            if new != h.view:
                watch.append(Ref(text=f"If {_trigger_text(c, towards)}, the agent view would move to {new} (score {score:+.2f}).", refs=[c.sig.id]))
    if not watch and key:
        watch.append(Ref(text=f"No single 3-month move in {', '.join(c.series.ind.name for c in key)} would change the {h.view} view on its own.",
                         refs=[c.sig.id for c in key]))
    elif not watch:
        levels = scoring.key_signals(h, 3)
        watch.append(Ref(text=(f"No 3-month moves are tracked for {ac.value.lower()}; the view rests on where "
                               f"{', '.join(c.series.ind.name for c in levels)} sit in their 10-year ranges, which change slowly."),
                         refs=[c.sig.id for c in levels]))
    return scenarios, watch[:3]


# --- Assembly ----------------------------------------------------------------

def build_view(ac: AssetClass, market_res: UpstreamResult, hv: HouseView, shelf: list[ShelfProduct], now: datetime,
               settings: Settings, shelf_illustrative: bool, client_id: Optional[str] = None,
               profile: Optional[ClientProfile] = None) -> AssetClassView:
    spec = cfg.SPECS[ac]
    cv = hv.for_class(ac.value)
    products = shelf_lens.in_class(ac, shelf)
    market: Optional[MarketResearchOutput] = market_res.data if market_res.status != "UNAVAILABLE" else None
    caveats = [US_ONLY]
    if market_res.source == "MOCK":
        caveats.append("Market data is an illustrative mock run, not a live Market Researcher run.")
    if spec.low_coverage:
        caveats.append(f"Few series describe {ac.value.lower()} directly; the agent view reads the market environment, so its confidence is capped at Low.")
    lens = shelf_lens.client_lens(ac, products, client_id, profile, now.date(), settings) if profile is not None and client_id else None
    mapped_ids = sorted({s.id for s in spec.signals})

    if market is None:
        return AssetClassView(
            asset_class=ac.value, generated_at=now, is_illustrative=True, cio_view=cv, agent_view=None,
            agent_view_unavailable_reason="; ".join(market_res.issues) or "No usable Market Researcher run.",
            snapshot=[], segments=[SegmentResult(group=s.group, segment=s.name, view="Neutral", reason="No market data") for s in spec.segments],
            drivers=[], scenarios=[], watch_items=[], risks=[], implementation=shelf_lens.implementation(ac, products),
            client_lens=lens, caveats=caveats,
            data_quality=DataQuality(market_source=market_res.source, market_status=market_res.status,
                                     missing_indicators=mapped_ids, house_view_as_of=hv.as_of),
        )

    idx = scoring.index_series(market)
    h = scoring.headline(ac, spec, idx, market)
    sc = h.scored
    ranked = sorted(sc.contributions, key=lambda c: (-abs(c.weighted), c.sig.id))
    supports = [c for c in ranked if c.value > 0.05]
    weighs = [c for c in ranked if c.value < -0.05]

    snapshot = [
        SnapshotItem(id=c.sig.id, name=c.series.ind.name, value=c.series.ind.value, unit=c.series.ind.unit,
                     change_1m=c.series.ind.changes.get("1m"), change_3m=c.series.ind.changes.get("3m"),
                     percentile_10y=c.series.ind.percentile_10y, observation_date=c.series.ind.observation_date,
                     stale=c.series.ind.stale, basis=c.sig.basis, reading=round(c.reading, 3), contribution=round(c.value, 3),
                     weight=c.sig.weight, effect=_effect(c), why=c.sig.why)
        for c in sorted(sc.contributions, key=lambda c: (-c.sig.weight, c.sig.id))
    ]
    phase = market.regime.phase
    regime_ref = RegimeRef(phase=phase, confidence=market.regime.confidence, tilt=sc.regime_tilt, run_id=market.run_id)
    if h.insufficient:
        thesis = (f"Not enough current data to form a view ({sc.available} of {sc.mapped} series available); "
                  f"shown as Hold with Low confidence.")
    else:
        parts = [f"{h.view} with {h.confidence.lower()} confidence: {len(supports)} of {sc.available} indicators support "
                 f"{ac.value.lower()} and {len(weighs)} {'weighs' if len(weighs) == 1 else 'weigh'} on it"]
        if supports:
            parts.append(f"the strongest support is {short_label(supports[0])}")
        if weighs:
            parts.append(f"the strongest headwind is {short_label(weighs[0])}")
        thesis = "; ".join(parts) + f", in a {PHASE_TEXT.get(phase, 'unclassified')} regime."
    points = [_ref(c, ac) for c in ranked[:3]]
    if phase and sc.regime_tilt is not None:
        lean = "favours" if sc.regime_tilt > 0 else "weighs on" if sc.regime_tilt < 0 else "is neutral for"
        points.append(Ref(text=f"The cycle phase is {PHASE_TEXT.get(phase, phase)} ({market.regime.confidence} confidence), which {lean} {ac.value.lower()}.",
                          refs=[market.run_id]))

    ids = set(mapped_ids) | {s.id for seg in spec.segments for s in seg.signals}
    events = [Ref(text=e.description, refs=[f"event:{e.id}", *e.evidence]) for e in market.events if ids & set(e.evidence)]
    # Risks to the view are what pulls against it. A Hold can break either way, so it lists the strongest of each side.
    if h.view == "Buy":
        risks = [_ref(c, ac) for c in weighs[:2]]
    elif h.view == "Sell":
        risks = [_ref(c, ac) for c in supports[:2]]
    else:
        risks = [_ref(c, ac) for c in supports[:1] + weighs[:1]]
    agreement = _agreement(cv.view, h.view, h, ac, cv)
    if agreement.explanation:
        risks.append(Ref(text=agreement.explanation, refs=[cv.citation_id]))
    scenarios, watch = _scenarios(ac, h)
    stale = sorted({c.sig.id for c in sc.contributions if c.series.ind.stale})
    missing = sorted({s.id for s in spec.signals} - {c.sig.id for c in sc.contributions})
    if h.insufficient:
        caveats.append(f"Insufficient evidence: {sc.available} of {sc.mapped} mapped series are available.")

    return AssetClassView(
        asset_class=ac.value, generated_at=now,
        is_illustrative=shelf_illustrative or hv.is_illustrative or market_res.source == "MOCK",
        cio_view=cv,
        agent_view=AgentView(view=h.view, confidence=h.confidence, score=sc.score, thesis=thesis, thesis_points=points,
                             regime=regime_ref, coverage=Coverage(mapped=sc.mapped, available=sc.available),
                             insufficient_evidence=h.insufficient),
        agreement=agreement,
        snapshot=snapshot,
        segments=_segments(ac, spec, idx, sc.score),
        drivers=[_ref(c, ac) for c in ranked[:3]] + events,
        scenarios=scenarios, watch_items=watch, risks=risks,
        implementation=shelf_lens.implementation(ac, products),
        client_lens=lens, caveats=caveats,
        data_quality=DataQuality(market_source=market_res.source, market_status=market_res.status, market_researcher_run_id=market.run_id,
                                 market_as_of=market.as_of, market_quality=market.quality.status if market.quality else None,
                                 stale_indicators=stale, missing_indicators=missing, house_view_as_of=hv.as_of),
    )


def headline_only(ac: AssetClass, market_res: UpstreamResult, hv: HouseView) -> AssetClassHeadline:
    cv = hv.for_class(ac.value)
    out = AssetClassHeadline(asset_class=ac.value, cio_view=cv.view, cio_term=cv.cio_term, cio_confidence=cv.confidence)
    if market_res.status == "UNAVAILABLE" or market_res.data is None:
        return out
    h = scoring.headline(ac, cfg.SPECS[ac], scoring.index_series(market_res.data), market_res.data)
    out.agent_view, out.agent_confidence = h.view, h.confidence
    out.agreement = _agreement(cv.view, h.view, h, ac, cv).status
    return out
