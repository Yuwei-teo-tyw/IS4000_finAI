"""
Deterministic scoring behind an asset-class view.

data score = (sum of weight x direction x reading over available signals
              + regime weight x regime tilt) / (sum of the weights used)

so it always lies in [-1, 1] and can be recomputed from the response's own
snapshot. The agent view is anchored on the CIO view:

score = CIO_SHARE x CIO anchor + (1 - CIO_SHARE) x data score

and its stance is kept within one step of the CIO's, so market data can
soften or firm up the CIO view but never flip it. The stance, segment
preferences, scenarios and watch items all come from here; an LLM may only
describe them.
"""
from dataclasses import dataclass
from typing import Optional

from app.agents.market_researcher.schemas import Indicator, MarketResearchOutput
from app.agents.portfolio_agent.taxonomy import AssetClass
from app.agents.product_recommender.asset_views import config as cfg
from app.agents.product_recommender.asset_views.config import (
    AssetClassSpec,
    Segment,
    Signal,
)


@dataclass
class Series:
    ind: Indicator
    is_price: bool  # market_snapshot changes are in %, indicator changes are in the value's own unit


@dataclass
class Contribution:
    sig: Signal
    series: Series
    reading: float  # [-1, 1], before direction

    @property
    def value(self) -> float:
        return self.sig.direction * self.reading

    @property
    def weighted(self) -> float:
        return self.sig.weight * self.value


@dataclass
class Scored:
    score: float
    contributions: list[Contribution]
    mapped: int
    available: int
    regime_tilt: Optional[float] = None
    regime_weight: float = 0.0


def index_series(market: MarketResearchOutput) -> dict[str, Series]:
    idx: dict[str, Series] = {}
    for ind in [*market.indicators, *market.planned_indicators]:
        idx.setdefault(ind.id, Series(ind, is_price=False))
    for ind in [*market.market_snapshot, *market.planned_market]:
        idx.setdefault(ind.id, Series(ind, is_price=True))
    return idx


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def read(sig: Signal, idx: dict[str, Series]) -> Optional[tuple[Series, float]]:
    s = idx.get(sig.id)
    if s is None or s.ind.stale:
        return None
    if sig.basis == "level":
        p = s.ind.percentile_10y
        return None if p is None else (s, _clip((p - 50) / 50))
    ch = s.ind.changes.get("3m")
    if ch is None:
        return None
    if sig.basis == "relative":
        other = idx.get(sig.vs or "")
        base = other.ind.changes.get("3m") if other and not other.ind.stale else None
        if base is None:
            return None
        ch = ch - base
    return s, _clip(ch / sig.scale)


def score_signals(signals: tuple[Signal, ...], idx: dict[str, Series], regime_tilt: Optional[float] = None,
                  regime_weight: float = 0.0) -> Scored:
    contributions = []
    for sig in signals:
        r = read(sig, idx)
        if r is not None:
            contributions.append(Contribution(sig, r[0], r[1]))
    total_w = sum(c.sig.weight for c in contributions)
    total = sum(c.weighted for c in contributions)
    if regime_tilt is not None and regime_weight > 0:
        total_w += regime_weight
        total += regime_weight * regime_tilt
    score = round(total / total_w, 3) if total_w else 0.0
    return Scored(score, contributions, mapped=len(signals), available=len(contributions),
                  regime_tilt=regime_tilt, regime_weight=regime_weight if regime_tilt is not None else 0.0)


def stance(score: float) -> str:
    return "Buy" if score >= cfg.BUY_AT else "Sell" if score <= cfg.SELL_AT else "Hold"


def regime_inputs(ac: AssetClass, market: MarketResearchOutput) -> tuple[Optional[float], float]:
    phase = market.regime.phase
    if phase is None:
        return None, 0.0
    tilt = cfg.REGIME_TILT.get(phase, {}).get(ac)
    weight = cfg.REGIME_WEIGHT * cfg.REGIME_CONFIDENCE.get(market.regime.confidence, 0.5)
    return tilt, weight


_ORDER = ("Sell", "Hold", "Buy")


def step_confidence(confidence: str, steps: int) -> str:
    i = cfg.CONFIDENCE_STEPS.index(confidence) + steps
    return cfg.CONFIDENCE_STEPS[max(0, min(len(cfg.CONFIDENCE_STEPS) - 1, i))]


def combine(data_score: float, cio_view: str) -> tuple[float, str]:
    """The agent score and stance: the CIO anchor blended with the data score, kept within one step of the CIO."""
    score = round(cfg.CIO_SHARE * cfg.CIO_ANCHOR[cio_view] + (1 - cfg.CIO_SHARE) * data_score, 3)
    raw, cio = _ORDER.index(stance(score)), _ORDER.index(cio_view)
    return score, _ORDER[max(cio - 1, min(cio + 1, raw))]


def adjustment(cio_view: str, view: str) -> str:
    if view == cio_view:
        return "unchanged"
    if cio_view != "Hold":
        return "softened"
    return "upgraded" if view == "Buy" else "downgraded"


@dataclass
class Headline:
    scored: Scored  # market data only; scored.score is the data score
    view: str
    confidence: str
    insufficient: bool
    score: float  # the agent score, anchored on the CIO view
    cio_view: str
    adjustment: str


def _data_confidence(spec: AssetClassSpec, scored: Scored, coverage: float) -> str:
    """How firmly the market data alone points one way."""
    sign = 1 if scored.score >= 0 else -1
    moving = [c for c in scored.contributions if abs(c.value) > 0.05]
    agree_w = sum(c.sig.weight for c in moving if (c.value > 0) == (sign > 0))
    agree = agree_w / sum(c.sig.weight for c in moving) if moving else 0.0
    if spec.low_coverage or coverage < 0.6 or agree < 0.55:
        return "Low"
    if coverage >= 0.8 and agree >= 0.7 and abs(scored.score) >= 0.35:
        return "High"
    return "Medium"


def headline(ac: AssetClass, spec: AssetClassSpec, idx: dict[str, Series], market: MarketResearchOutput,
             cio_view: str, cio_confidence: str) -> Headline:
    tilt, weight = regime_inputs(ac, market)
    scored = score_signals(spec.signals, idx, tilt, weight)
    coverage = scored.available / scored.mapped if scored.mapped else 0.0
    if coverage < cfg.MIN_COVERAGE:
        # Too little data to move the CIO view: keep it, one step less sure.
        return Headline(scored, cio_view, step_confidence(cio_confidence, -1), insufficient=True,
                        score=round(cfg.CIO_SHARE * cfg.CIO_ANCHOR[cio_view], 3), cio_view=cio_view, adjustment="unchanged")
    score, view = combine(scored.score, cio_view)
    data_dir = _ORDER.index(stance(scored.score)) - 1
    cio_dir = _ORDER.index(cio_view) - 1
    data_conf = _data_confidence(spec, scored, coverage)
    if view != cio_view:
        confidence = step_confidence(cio_confidence, -1)
    elif data_dir == cio_dir and data_conf != "Low":
        confidence = step_confidence(cio_confidence, 1)
    elif data_dir == -cio_dir and data_dir != 0:
        confidence = step_confidence(cio_confidence, -1)
    else:
        confidence = cio_confidence
    if spec.low_coverage:
        confidence = "Low"
    return Headline(scored, view, confidence, insufficient=False, score=score, cio_view=cio_view,
                    adjustment=adjustment(cio_view, view))


@dataclass
class SegmentScore:
    segment: Segment
    view: str
    scored: Optional[Scored]


def segments(spec: AssetClassSpec, idx: dict[str, Series], class_score: float) -> list[SegmentScore]:
    """Preference within the class: a segment is Most preferred when its own score beats the class score by the margin."""
    out = []
    for seg in spec.segments:
        scored = score_signals(seg.signals, idx) if seg.signals else None
        if scored is None or scored.available == 0:
            out.append(SegmentScore(seg, "Neutral", None))
            continue
        if scored.score >= class_score + cfg.SEGMENT_MARGIN:
            view = "Most preferred"
        elif scored.score <= class_score - cfg.SEGMENT_MARGIN:
            view = "Least preferred"
        else:
            view = "Neutral"
        out.append(SegmentScore(seg, view, scored))
    return out


def what_if(h: Headline, target: Contribution, reading: float) -> tuple[float, str]:
    """Rescore the headline with one signal's reading replaced (direction applied as usual)."""
    sc = h.scored
    total_w = sum(c.sig.weight for c in sc.contributions) + sc.regime_weight
    total = sum(c.weighted for c in sc.contributions if c is not target) + target.sig.weight * target.sig.direction * reading
    total += sc.regime_weight * (sc.regime_tilt or 0.0)
    data_score = round(total / total_w, 3) if total_w else 0.0
    return combine(data_score, h.cio_view)


def biggest_swing(h: Headline, towards: int) -> Optional[Contribution]:
    """The movement signal (3-month change) whose full swing in one direction would move the score most.
    Level signals are left out: where a series sits in its 10-year range changes slowly, so it is not a trigger."""
    moves = [c for c in h.scored.contributions if c.sig.basis != "level"]

    def room(c: Contribution) -> float:
        return c.sig.weight * (1 - towards * c.value)

    if not moves:
        return None
    best = max(moves, key=lambda c: (room(c), c.sig.weight, c.sig.id))
    return best if room(best) > 0.05 else None


def key_signals(h: Headline, n: int = 3) -> list[Contribution]:
    """The available signals with the most weight: the ones whose moves matter most."""
    return sorted(h.scored.contributions, key=lambda c: (-c.sig.weight, c.sig.id, c.sig.basis))[:n]
