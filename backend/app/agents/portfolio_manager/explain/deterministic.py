"""
Template-based explanations built purely from computed numbers, client
inputs and upstream data. These are always produced, so the response is
fully explained even when no LLM is available; each statement carries its
provenance (`basis`).
"""
from typing import Optional

from app.agents.portfolio_manager.assumptions import CapitalMarketAssumptions
from app.agents.portfolio_manager.engine.construction import BuiltOption, ConstructionContext
from app.agents.portfolio_manager.engine.metrics import ExpectedReturn
from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.schemas.client import ClientProfile
from app.agents.portfolio_manager.schemas.response import (
    GoalAlignment,
    MarketContextSummary,
    MarketEvent,
    MarketIndicator,
    MarketNews,
    PortfolioMetrics,
    RegimeSummary,
    ScenarioDetail,
    ScenarioOutcome,
    Statement,
)
from app.agents.portfolio_manager.schemas.upstream import MarketResearchOutput, ProductCandidate
from app.agents.portfolio_manager.taxonomy import AssetClass

PHASE_LABEL = {
    "early_expansion": "early expansion",
    "late_expansion": "late expansion",
    "recession": "recession",
    "late_recession": "late recession (trough forming)",
}

ASSET_CLASS_RISKS = {
    AssetClass.CASH: [
        "Inflation can erode real purchasing power.",
        "Reinvestment risk: yields may fall when deposits or money-market holdings roll over.",
        "Not risk-free: depends on the issuer/bank and any deposit insurance limits.",
    ],
    AssetClass.FIXED_INCOME: [
        "Interest-rate risk: prices fall when yields rise (longer duration = larger moves).",
        "Credit risk: issuer downgrades or defaults can cause losses; spreads can widen sharply in a downturn.",
        "Inflation and reinvestment risk on coupons and maturities.",
    ],
    AssetClass.EQUITIES: [
        "Equity market risk: significant short-term losses are possible (historical drawdowns above 30%).",
        "Valuation risk: returns may be lower if starting valuations are elevated; dividends can be cut.",
    ],
    AssetClass.HEDGE_FUNDS: [
        "Manager and strategy risk: returns depend on the manager's skill and can disappoint.",
        "Limited liquidity (weekly to quarterly dealing) and higher fees; risk figures may understate true risk.",
    ],
    AssetClass.PRIVATE_MARKETS: [
        "Illiquidity: redemptions are limited or locked for years; selling early may not be possible.",
        "Valuations are appraisal-based and lag public markets, so reported volatility understates risk.",
    ],
    AssetClass.REAL_ESTATE: [
        "Sensitive to interest rates and property-market conditions.",
        "Leverage within REITs can amplify losses; distributions are not guaranteed.",
    ],
    AssetClass.GOLD: [
        "No income; returns rely entirely on price changes.",
        "High price volatility; gold is typically priced in USD.",
    ],
}

ASSET_CLASS_ROLE = {
    AssetClass.CASH: "provides liquidity and stability",
    AssetClass.FIXED_INCOME: "provides income and tends to cushion equity sell-offs",
    AssetClass.EQUITIES: "is the main driver of long-term capital growth",
    AssetClass.HEDGE_FUNDS: "aims for returns less tied to equity and bond markets",
    AssetClass.PRIVATE_MARKETS: "targets an illiquidity premium over public markets",
    AssetClass.REAL_ESTATE: "adds property-linked income and diversification",
    AssetClass.GOLD: "diversifies equity and inflation risk",
}

# Market Researcher `implications` areas -> asset classes they bear on.
IMPLICATION_CLASSES = {
    "duration": {AssetClass.FIXED_INCOME},
    "credit": {AssetClass.FIXED_INCOME, AssetClass.PRIVATE_MARKETS},
    "equities": {AssetClass.EQUITIES, AssetClass.HEDGE_FUNDS, AssetClass.PRIVATE_MARKETS},
    "sectors": {AssetClass.EQUITIES},
    "usd": {AssetClass.CASH, AssetClass.GOLD},
    "commodities": {AssetClass.GOLD},
    "real_estate": {AssetClass.REAL_ESTATE},
}

_CAUTIOUS = [
    "Not risk-free: inflation may exceed the portfolio's return, reducing real wealth.",
    "Reinvestment risk if short-term rates fall; bond prices fall if interest rates rise.",
    "May not generate enough growth to meet long-term goals.",
]
_GROWTH = [
    "Significant short-term losses and high volatility are likely at some point; recovery can take years.",
    "Selling during a drawdown (e.g. to fund withdrawals) would crystallise losses.",
]
OPTION_SPECIFIC_RISKS = {
    "A": _CAUTIOUS,
    "B": _CAUTIOUS[:2] + ["Income can fall if rates drop or issuers cut distributions."],
    "C": ["Can lose value in equity sell-offs; bonds may not fully offset equity losses (e.g. when inflation "
          "drives both down together)."],
    "D": _GROWTH,
    "E": _GROWTH + ["Concentrated in growth assets: a deep bear market could take several years to recover."],
    "F": _GROWTH + ["Larger allocations to hedge funds and private markets reduce liquidity and add manager risk."],
}


def product_risks(prod: ProductCandidate, ac: AssetClass, base_currency: str) -> list[str]:
    risks = list(ASSET_CLASS_RISKS.get(ac, []))
    if prod.currency != base_currency and prod.currency_hedged is not True:
        risks.append(f"Currency risk: denominated in {prod.currency} and unhedged against {base_currency}.")
    if prod.lock_in_period and prod.lock_in_period.lower() not in ("none", "0"):
        risks.append(f"Liquidity risk: lock-in period of {prod.lock_in_period}.")
    if prod.duration and prod.duration >= 6:
        risks.append(f"Duration of {prod.duration} years means meaningful sensitivity to rate changes.")
    return risks


def product_rationale(prod: ProductCandidate, ac: AssetClass, base_currency: str, notes: list[str]) -> str:
    bits = [f"{ac.value} sleeve: {ASSET_CLASS_ROLE.get(ac, 'diversifies the portfolio')}."]
    if prod.currency == base_currency:
        bits.append(f"Denominated in the client's base currency ({base_currency}).")
    elif prod.currency_hedged:
        bits.append(f"Hedged to {base_currency}, limiting currency risk.")
    if prod.management_fee is not None:
        bits.append(f"Illustrative management fee {prod.management_fee}% p.a.")
    if prod.liquidity == "DAILY":
        bits.append("Daily dealing.")
    if prod.credit_rating:
        bits.append(f"Credit rating {prod.credit_rating}.")
    bits.append("Ranked highest among eligible candidates on data completeness, currency fit, cost and liquidity.")
    return " ".join(bits)


def liquidity_assessment(m: PortfolioMetrics, positions) -> str:
    if m.high_liquidity_share_pct is None:
        return "Liquidity data incomplete for at least one product; liquidity cannot be fully assessed."
    locked = [p.sp.product.product_name for p in positions if p.sp.product.liquidity in ("AT_MATURITY", "LOCKED")]
    txt = f"{m.high_liquidity_share_pct:.1f}% of the portfolio is in daily-dealing products."
    if locked:
        txt += f" Funds in {', '.join(locked)} are only accessible at maturity or after a lock-in."
    txt += " Separately, the cash reserve and near-term withdrawals are ring-fenced outside this portfolio."
    return txt


def diversification_assessment(m: PortfolioMetrics) -> str:
    level = (
        "well diversified" if (m.effective_number_of_holdings or 0) >= 6 and m.number_of_asset_classes >= 4
        else "moderately diversified" if (m.effective_number_of_holdings or 0) >= 3
        else "concentrated"
    )
    return (
        f"{m.number_of_products} products across {m.number_of_asset_classes} asset classes; effective number of "
        f"holdings {m.effective_number_of_holdings} (inverse Herfindahl index) - {level}. Underlying look-through "
        "concentration (e.g. common issuers across funds) is not modelled."
    )


def advantages_disadvantages(
    built: BuiltOption, m: PortfolioMetrics, goals: list[GoalAlignment], scenarios: list[ScenarioOutcome]
) -> tuple[list[str], list[str]]:
    adv, dis = [], []
    oid = built.template.option_id
    if m.estimated_stress_drawdown_pct is not None:
        if m.estimated_stress_drawdown_pct <= 8:
            adv.append(f"Low estimated stress drawdown ({m.estimated_stress_drawdown_pct:.1f}%).")
        elif m.estimated_stress_drawdown_pct > 15:
            dis.append(f"Large estimated stress drawdown ({m.estimated_stress_drawdown_pct:.1f}%).")
    if m.growth_asset_share_pct >= 40:
        adv.append(f"Higher long-term growth potential ({m.growth_asset_share_pct:.0f}% growth assets).")
    elif m.growth_asset_share_pct <= 10:
        dis.append("Limited growth potential; real returns depend on inflation staying low.")
    if (m.high_liquidity_share_pct or 0) >= 90:
        adv.append("Highly liquid - almost all holdings deal daily.")
    if m.estimated_annual_fee_pct is not None:
        if m.estimated_annual_fee_pct <= 0.35:
            adv.append(f"Low estimated ongoing cost ({m.estimated_annual_fee_pct:.2f}% p.a.).")
        elif m.estimated_annual_fee_pct >= 0.7:
            dis.append(f"Relatively high estimated ongoing cost ({m.estimated_annual_fee_pct:.2f}% p.a.).")
    if (m.foreign_currency_exposure_pct or 0) > 20:
        dis.append(f"{m.foreign_currency_exposure_pct:.0f}% unhedged foreign-currency exposure adds FX volatility.")
    bear = next((s for s in scenarios if s.scenario.lower().startswith("recession")), None)
    if bear and bear.portfolio_return_pct is not None:
        if bear.portfolio_return_pct >= 0:
            adv.append(f"Positive return in the illustrative recession scenario ({bear.portfolio_return_pct:.1f}%).")
        else:
            dis.append(f"Negative return in the illustrative recession scenario ({bear.portfolio_return_pct:.1f}%).")
    shortfalls = [g.goal for g in goals if g.status == "SHORTFALL"]
    on_track = [g.goal for g in goals if g.status == "ON_TRACK"]
    if on_track:
        adv.append(f"Base-case projection meets: {', '.join(on_track)} (illustrative, not guaranteed).")
    if shortfalls:
        dis.append(f"Base-case projection falls short for: {', '.join(shortfalls)}.")
    dis.extend(OPTION_SPECIFIC_RISKS.get(oid, []))
    return adv, dis


def option_rationale(
    built: BuiltOption,
    ctx: ConstructionContext,
    a: ProfileAssessment,
    p: ClientProfile,
    market: Optional[MarketResearchOutput],
    m: PortfolioMetrics,
) -> list[Statement]:
    out: list[Statement] = []
    out.append(Statement(
        statement=f"Effective risk level {a.effective_level} ({a.effective_label}): {a.effective_basis}",
        basis="CLIENT_INPUT",
    ))
    if p.maximum_acceptable_drawdown is not None:
        dd = m.estimated_stress_drawdown_pct
        out.append(Statement(
            statement=f"Maximum acceptable drawdown of {p.maximum_acceptable_drawdown:g}% applied as a hard limit; "
                      f"this option's estimated stress drawdown is "
                      f"{dd if dd is not None else 'not calculable'}%.",
            basis="CALCULATION",
        ))
    horizon = (f" and {a.shortest_horizon_years:g}-year shortest goal horizon"
               if a.shortest_horizon_years is not None else "")
    market_cut = (f", less {ctx.market_growth_reduction:.0f} points for current market conditions"
                  if ctx.market_growth_reduction else "")
    out.append(Statement(
        statement=f"Growth assets (equities, hedge funds, private markets) are limited to {ctx.growth_ceiling:.0f}% "
                  f"by the client's risk level{horizon}{market_cut}.",
        basis="RULE",
    ))
    if p.maximum_single_asset_allocation is not None:
        out.append(Statement(
            statement=f"No single product exceeds {p.maximum_single_asset_allocation:g}% of the portfolio.",
            basis="CLIENT_INPUT",
        ))
    for mod in built.modifications:
        out.append(Statement(statement=mod, basis="RULE"))

    if market is not None:
        src = "Market Researcher"
        r = market.regime
        if r.phase:
            out.append(Statement(
                statement=f"Economic cycle call: {PHASE_LABEL.get(r.phase, r.phase)} ({r.confidence} confidence).",
                basis="OBSERVED_FACT", source=f"{src} regime model, as of {market.as_of}",
            ))
        if r.recession_prob_12m is not None:
            out.append(Statement(
                statement=f"12-month recession probability of {r.recession_prob_12m * 100:.0f}% (yield-curve model "
                          "estimate).",
                basis="FORECAST", source=f"{src} (NY Fed yield-curve probit)",
            ))
        held = set(built.class_weights())
        for area, text in (market.implications or {}).items():
            if IMPLICATION_CLASSES.get(area.lower(), set()) & held:
                out.append(Statement(statement=f"{area.capitalize()}: {text}", basis="OBSERVED_FACT", source=src))
        for e in market.events:
            if e.severity in ("notable", "major"):
                out.append(Statement(statement=e.description, basis="OBSERVED_FACT",
                                     source=f"{src} event ({', '.join(e.evidence) or 'n/a'})"))
    return out


def option_assumptions(exp: dict[str, ExpectedReturn], cma: CapitalMarketAssumptions) -> list[str]:
    out = [
        f"Expected returns use illustrative product yields (cash, fixed income) and {cma.label} for other asset "
        "classes, net of management fees; they are assumptions, not guarantees.",
        "Stress drawdown assumes all holdings suffer their historical worst drawdown simultaneously.",
    ]
    if any(e.value is None for e in exp.values()):
        out.append("Some products lack a supportable return assumption; portfolio expected return is null.")
    return out


def narrative_template(built: BuiltOption, m: PortfolioMetrics, base_currency: str) -> str:
    weights = sorted(built.class_weights().items(), key=lambda kv: -kv[1])
    mix = ", ".join(f"{ac.value} {w:.1f}%" for ac, w in weights)
    exp = f"{m.expected_annual_return_pct:.2f}% p.a." if m.expected_annual_return_pct is not None else "not calculable"
    dd = f"{m.estimated_stress_drawdown_pct:.1f}%" if m.estimated_stress_drawdown_pct is not None else "not calculable"
    return (
        f"Option {built.template.option_id} ({built.template.name}) allocates {mix}. Its illustrative expected "
        f"return is {exp} and its estimated stress drawdown is {dd}. {built.template.objective} "
        "Figures are calculated from illustrative mock data and are not guaranteed."
    )


def market_context(
    market: Optional[MarketResearchOutput], issues: list[str], source: str, cma: CapitalMarketAssumptions,
) -> MarketContextSummary:
    scenario_details = [
        ScenarioDetail(
            name=sc.name,
            probability=(market.regime.recession_prob_12m if market and sc.uses_recession_probability else None),
            probability_source=("Market Researcher 12-month recession probability (yield-curve model)"
                                if market and sc.uses_recession_probability else None),
            horizon=sc.horizon, narrative=sc.narrative, asset_class_returns=dict(sc.asset_class_returns),
        )
        for sc in cma.scenarios
    ]
    common = dict(
        scenario_details=scenario_details,
        assumptions_label=cma.label,
        long_term_return_assumptions=dict(cma.long_term_expected_return),
    )
    if market is None:
        return MarketContextSummary(
            data_source_label="Unavailable", run_id=None, as_of=None, region=None, quality_status=None, regime=None,
            events=[], indicators=[], market_snapshot=[], news=[], key_themes=[], risks=[], implications={},
            key_observations=[], forecasts=[],
            limitations=["Market research unavailable; no market observations were used."] + issues,
            **common,
        )
    label = "Market Researcher (illustrative mock)" if source == "MOCK" else "Market Researcher"
    r = market.regime
    regime = RegimeSummary(
        phase=r.phase, confidence=r.confidence, probabilities=dict(r.probabilities),
        recession_prob_12m=r.recession_prob_12m, in_recession_prob=r.in_recession_prob,
        drivers=[d.indicator for d in r.drivers], conflicting_signals=list(r.conflicting_signals), changed=r.changed,
    )

    def indicator(i) -> MarketIndicator:
        return MarketIndicator(
            id=i.id, name=i.name, category=i.category, value=i.value, unit=i.unit,
            observation_date=i.observation_date, signal=i.signal, percentile_10y=i.percentile_10y,
            stale=i.stale, source=i.source, source_url=i.source_url,
        )

    def value_text(i) -> str:
        return f"{i.value:g}{i.unit}" if i.unit in ("%", "pp") else f"{i.value:g} {i.unit}"

    observed = [
        Statement(statement=f"{i.name} ({i.id}): {value_text(i)} on {i.observation_date}"
                            + (" - stale" if i.stale else ""),
                  basis="OBSERVED_FACT", source=f"{i.source}; {i.source_url}")
        for i in market.indicators
    ]
    forecasts = []
    if r.recession_prob_12m is not None:
        forecasts.append(Statement(
            statement=f"12-month recession probability {r.recession_prob_12m * 100:.0f}% (yield-curve model).",
            basis="FORECAST", source=label,
        ))
    if r.phase:
        conflicting = f"; conflicting: {'; '.join(r.conflicting_signals)}" if r.conflicting_signals else ""
        forecasts.append(Statement(
            statement=f"Cycle phase: {PHASE_LABEL.get(r.phase, r.phase)}, {r.confidence} confidence{conflicting}.",
            basis="FORECAST", source=label,
        ))
    limitations = list(issues) + list(market.data_quality.notes)
    if source == "MOCK":
        limitations.insert(0, "Market information is illustrative mock data in the Market Researcher's format, "
                              "not a real run.")
    limitations.append(
        f"The Market Researcher publishes no return forecasts; expected and scenario returns are {cma.label}."
    )
    return MarketContextSummary(
        data_source_label=label, run_id=market.run_id, as_of=market.as_of, region=market.region,
        quality_status=market.quality.status if market.quality else None,
        regime=regime,
        events=[MarketEvent(id=e.id, severity=e.severity, description=e.description, evidence=list(e.evidence))
                for e in market.events],
        indicators=[indicator(i) for i in market.indicators],
        market_snapshot=[indicator(i) for i in market.market_snapshot],
        news=[MarketNews(title=n.title, source=n.source, url=n.url, published_at=n.published_at, summary=n.summary,
                         sentiment=n.sentiment, market_impact=n.market_impact) for n in market.news],
        key_themes=list(market.key_themes or []),
        risks=list(market.risks or []),
        implications=dict(market.implications or {}),
        key_observations=observed,
        forecasts=forecasts,
        limitations=limitations,
        **common,
    )
