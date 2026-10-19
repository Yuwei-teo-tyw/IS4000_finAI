"""
Side-by-side comparison of the evaluated options and the (deterministic)
choice of a preferred option for RM review.

A preferred option is only nominated when the evidence supports a
defensible choice: no material missing/contradictory client information,
market analysis available, and at least one option that passes every
constraint check. Among those, the option whose growth-asset share is
closest to the client's risk-level target wins (the growth share of the
template matching that level: 1 -> A, 2 -> B, 3 -> C, 4 -> D, 5 -> E), with a penalty for missing
a high-priority goal under base-case assumptions. This is a transparent
rule, not an optimisation.
"""
from typing import Optional

from app.agents.portfolio_manager.engine.construction import TEMPLATES, template_growth
from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.schemas.response import ComparisonRow, PortfolioOption
from app.agents.portfolio_manager.taxonomy import RISK_LEVEL_LABELS, risk_label_for_stress_drawdown

GOAL_SHORTFALL_PENALTY_PP = 15.0
# Risk level 1-5 -> growth share of the matching template (A-E).
GROWTH_TARGET_BY_RISK_LEVEL = {level: template_growth(TEMPLATES[level - 1]) for level in range(1, 6)}
OFFERED = ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS")


def _fmt_pct(v: Optional[float], suffix: str = "%") -> str:
    return f"{v:.2f}{suffix}" if v is not None else "Not calculable"


def _cell(opt: PortfolioOption, fn) -> str:
    if opt.suitability_status not in OFFERED:
        return f"Not offered ({opt.suitability_status.replace('_', ' ').lower()})"
    return fn(opt)


def _scenarios(o: PortfolioOption) -> str:
    if not o.scenario_analysis:
        return "No scenario data"
    return "; ".join(
        f"{s.scenario}: {_fmt_pct(s.portfolio_return_pct)}" for s in o.scenario_analysis
    ) + " (illustrative 12-month house scenarios)"


def _risk_alignment(level: Optional[int], label: str):
    def fn(o: PortfolioOption) -> str:
        dd = o.metrics.estimated_stress_drawdown_pct if o.metrics else None
        if dd is None or level is None:
            return "Cannot assess (drawdown data incomplete)"
        opt_level, opt_label = risk_label_for_stress_drawdown(dd)
        if opt_level > level:
            return f"Above {label} (option risk {opt_label} vs client level {level})"
        if level - opt_level >= 2:
            return f"Well within {label} (option risk {opt_label}); may under-use the client's risk budget"
        return f"Within {label} (option risk {opt_label} vs client level {level})"
    return fn


def _goals(o: PortfolioOption) -> str:
    if not o.goal_alignment:
        return "No goals to assess"
    return "; ".join(f"{g.goal}: {g.status.replace('_', ' ').lower()}" for g in o.goal_alignment)


def _horizon_fn(horizon: Optional[float]):
    def fn(o: PortfolioOption) -> str:
        if horizon is None:
            return "Horizon unknown"
        return f"Growth assets {o.metrics.growth_asset_share_pct:.1f}% for a {horizon:g}-year shortest horizon"
    return fn


def build_comparison(options: list[PortfolioOption], a: ProfileAssessment) -> list[ComparisonRow]:
    def row(criterion: str, fn) -> ComparisonRow:
        return ComparisonRow(criterion=criterion, values={o.option_id: _cell(o, fn) for o in options})

    willingness = (
        min(x for x in (a.appetite_level, a.score_level) if x is not None)
        if (a.appetite_level or a.score_level) else None
    )
    return [
        row("Expected return potential (p.a., illustrative)", lambda o: _fmt_pct(o.expected_portfolio_return)),
        row("Growth-asset share", lambda o: _fmt_pct(o.metrics.growth_asset_share_pct)),
        row("Downside risk (estimated stress drawdown)", lambda o: (
            f"{_fmt_pct(o.metrics.estimated_stress_drawdown_pct)}"
            + (f" (~{o.eligible_portfolio_value * o.metrics.estimated_stress_drawdown_pct / 100:,.0f} {o.base_currency})"
               if o.metrics.estimated_stress_drawdown_pct is not None else "")
        )),
        row("Expansion / slowdown / recession sensitivity", _scenarios),
        row("Liquidity (share in daily-dealing products)", lambda o: _fmt_pct(o.metrics.high_liquidity_share_pct)),
        row("Diversification", lambda o: (
            f"{o.metrics.number_of_products} products across {o.metrics.number_of_asset_classes} asset classes; "
            f"effective holdings {o.metrics.effective_number_of_holdings}"
        )),
        row("Fees and estimated costs", lambda o: (
            f"{_fmt_pct(o.metrics.estimated_annual_fee_pct)} p.a."
            + (f" (~{o.metrics.estimated_annual_fee_amount:,.0f} {o.base_currency}/yr)"
               if o.metrics.estimated_annual_fee_amount is not None else "")
            + (f"; one-off dealing ~{o.metrics.estimated_one_off_transaction_cost:,.0f}"
               if o.metrics.estimated_one_off_transaction_cost is not None else "; dealing costs unknown")
        )),
        row("Currency exposure (unhedged foreign)", lambda o: _fmt_pct(o.metrics.foreign_currency_exposure_pct)),
        row("Alignment with risk appetite", _risk_alignment(willingness, "risk appetite")),
        row("Alignment with risk capacity", _risk_alignment(a.capacity_level, "risk capacity")),
        row("Alignment with investment horizon", _horizon_fn(a.shortest_horizon_years)),
        row("Alignment with financial goals", _goals),
    ]


def choose_preferred(
    options: list[PortfolioOption], a: ProfileAssessment, market_available: bool
) -> tuple[Optional[str], str]:
    offered = [o for o in options if o.suitability_status in OFFERED]
    if not offered:
        return None, "No option could be offered within the client's constraints, so none is preferred."

    if a.has_material_issues:
        fields = sorted({m.field for m in a.missing if m.severity == "MATERIAL"}
                        | {", ".join(c.fields) for c in a.conflicts if c.severity == "MATERIAL"})
        return None, (
            "No preferred option is nominated because material client information is missing or contradictory "
            f"({'; '.join(fields)}). The RM should resolve these before choosing between the options."
        )
    if not market_available:
        return None, "No preferred option is nominated because market analysis was unavailable."

    clean = [o for o in offered if all(c.status in ("PASS", "NOT_APPLICABLE") for c in o.constraint_checks)]
    if not clean:
        return None, "No offered option could be verified against every constraint, so none is preferred."

    level = a.effective_level
    target = GROWTH_TARGET_BY_RISK_LEVEL[level]

    def score(o: PortfolioOption) -> tuple:
        dist = abs(o.metrics.growth_asset_share_pct - target)
        if any(g.status == "SHORTFALL" and g.priority == "High" for g in o.goal_alignment):
            dist += GOAL_SHORTFALL_PENALTY_PP
        # Ties go to the more conservative option.
        return (round(dist, 4), o.metrics.growth_asset_share_pct)

    best = min(clean, key=score)
    others = [o for o in offered if o is not best]
    parts = [
        f"Option {best.option_id} ({best.option_name}) is nominated for review. Its growth-asset share "
        f"({best.metrics.growth_asset_share_pct:.1f}%) is closest to the {target:.0f}% reference level for the "
        f"client's effective risk level ({RISK_LEVEL_LABELS[level]}), and it passes every constraint check.",
    ]
    shortfalls = [g.goal for g in best.goal_alignment if g.status == "SHORTFALL"]
    if shortfalls:
        parts.append(f"However, it shows a projected shortfall for: {', '.join(shortfalls)}.")
    for o in others:
        if o.metrics.growth_asset_share_pct < best.metrics.growth_asset_share_pct:
            parts.append(
                f"Option {o.option_id} trades lower expected return for lower estimated drawdown "
                f"({_fmt_pct(o.metrics.estimated_stress_drawdown_pct)} vs "
                f"{_fmt_pct(best.metrics.estimated_stress_drawdown_pct)})."
            )
        else:
            parts.append(
                f"Option {o.option_id} offers higher expected return ({_fmt_pct(o.expected_portfolio_return)} vs "
                f"{_fmt_pct(best.expected_portfolio_return)}) at the cost of larger estimated drawdown "
                f"({_fmt_pct(o.metrics.estimated_stress_drawdown_pct)})."
            )
    parts.append(
        "This is a rules-based nomination from illustrative data, not a mathematically optimal portfolio; "
        "the adviser decides which option, if any, goes forward."
    )
    return best.option_id, " ".join(parts)
