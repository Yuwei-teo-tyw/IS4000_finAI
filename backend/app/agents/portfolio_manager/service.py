"""
Orchestrates one POST /portfolio/generate request:

  validate profile -> liquidity plan -> fetch upstream data (in parallel)
  -> screen products -> construct options -> metrics -> numeric validation
  -> comparison + preferred option -> optional LLM narrative -> response

Dependencies (upstream fetchers, LLM factory, clock, store) are injected so
tests can replace each one without touching the network.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.agents.portfolio_manager.assumptions import CapitalMarketAssumptions, load_assumptions
from app.agents.portfolio_manager.config import Settings, get_settings
from app.agents.portfolio_manager.engine.comparison import OFFERED, build_comparison, choose_preferred
from app.agents.portfolio_manager.engine.construction import TEMPLATES, BuiltOption, ConstructionContext, build_option, differentiate
from app.agents.portfolio_manager.engine.liquidity import build_liquidity_plan
from app.agents.portfolio_manager.engine.metrics import (
    compute_metrics,
    constraint_checks,
    goal_alignment,
    risk_level,
    scenario_outcomes,
)
from app.agents.portfolio_manager.engine.product_screening import screen_products
from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment, assess_profile
from app.agents.portfolio_manager.engine.validation import validate_option
from app.agents.portfolio_manager.explain import deterministic as det
from app.agents.portfolio_manager.explain.explainer import generate_explanations
from app.agents.portfolio_manager.explain.guardrails import AllowedNumbers
from app.agents.portfolio_manager.explain.llm_client import get_llm
from app.agents.portfolio_manager.schemas.client import PortfolioGenerateRequest
from app.agents.portfolio_manager.schemas.response import (
    AssetAllocationItem,
    CandidateProduct,
    ClientProfileSummary,
    DataStatus,
    ExcludedProduct,
    MissingInformation,
    PortfolioOption,
    PortfolioResponse,
    ProductDetails,
    ProductSelection,
    SubAssetAllocationItem,
)
from app.agents.portfolio_manager.schemas.upstream import MarketResearchOutput, ProductCandidate, UpstreamResult
from app.agents.portfolio_manager.storage import ProposalStore
from app.agents.portfolio_manager.engine.construction import MEDIUM_HORIZON_CAP
from app.agents.portfolio_manager.taxonomy import GROWTH_CEILING_BY_RISK_LEVEL, AssetClass, parse_asset_class
from app.agents.portfolio_manager.upstream import fetch_market_analysis, fetch_product_candidates

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Prototype output for Relationship Manager review only. Not investment advice and not a final recommendation. "
    "No transactions have been or will be executed by this service. Market and product data are illustrative mock "
    "data; projections are assumptions, not guarantees."
)


# Market-conditions rule: a recession call, or a high 12-month recession
# probability, from the Market Researcher trims the growth ceiling.
RECESSION_PROB_THRESHOLD = 0.5
MARKET_GROWTH_CUT_PP = 10.0


class DuplicateRequestError(Exception):
    pass


def market_growth_adjustment(market: Optional[MarketResearchOutput]) -> tuple[float, Optional[str]]:
    """Points to remove from the growth ceiling, and why (None if no cut)."""
    if market is None:
        return 0.0, None
    r = market.regime
    reasons = []
    if r.phase == "recession":
        reasons.append(f"the Market Researcher's cycle call is recession ({r.confidence} confidence)")
    if r.recession_prob_12m is not None and r.recession_prob_12m >= RECESSION_PROB_THRESHOLD:
        reasons.append(f"its 12-month recession probability is {r.recession_prob_12m * 100:.0f}%")
    if not reasons:
        return 0.0, None
    return MARKET_GROWTH_CUT_PP, (
        f"Growth ceiling reduced by {MARKET_GROWTH_CUT_PP:.0f} points because " + " and ".join(reasons) + "."
    )


def _details(prod: ProductCandidate) -> ProductDetails:
    return ProductDetails(**{f: getattr(prod, f) for f in ProductDetails.model_fields})


def _data_status(res: UpstreamResult) -> str:
    if res.status == "UNAVAILABLE":
        return "UNAVAILABLE"
    return res.source + ("_INCOMPLETE" if res.status == "INCOMPLETE" else "")


class PortfolioService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        store: Optional[ProposalStore] = None,
        market_fetcher: Callable = fetch_market_analysis,
        product_fetcher: Callable = fetch_product_candidates,
        llm_factory: Callable[[Settings], Any] = get_llm,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        assumptions: Optional[CapitalMarketAssumptions] = None,
    ):
        self.settings = settings or get_settings()
        self.store = store or ProposalStore(self.settings.store_max_items)
        self.market_fetcher = market_fetcher
        self.product_fetcher = product_fetcher
        self.llm_factory = llm_factory
        self.clock = clock
        self.cma = assumptions or load_assumptions()

    def get(self, request_id: str) -> Optional[PortfolioResponse]:
        return self.store.get(request_id)

    async def generate(self, req: PortfolioGenerateRequest) -> PortfolioResponse:
        request_id = req.request_id or f"PM-{uuid.uuid4().hex[:12].upper()}"
        if self.store.exists(request_id):
            raise DuplicateRequestError(request_id)

        now = self.clock()
        profile = req.client_profile
        a = assess_profile(profile, req.trigger, now.date())
        liq = build_liquidity_plan(profile, a)
        a.conflicts.extend(liq.conflicts)
        a.assumptions.extend(liq.assumptions)

        market_res, product_res = await asyncio.gather(
            self.market_fetcher(profile.base_currency), self.product_fetcher(profile.base_currency)
        )
        market: Optional[MarketResearchOutput] = market_res.data if market_res.status != "UNAVAILABLE" else None
        warnings = list(a.warnings)
        warnings += self._upstream_warnings(market_res, product_res, market, now)

        options: list[PortfolioOption] = []
        built: list[BuiltOption] = []
        excluded: list[ExcludedProduct] = []
        candidates: list[CandidateProduct] = []
        ctx: Optional[ConstructionContext] = None
        missing = list(a.missing)

        if product_res.status == "UNAVAILABLE":
            missing.append(MissingInformation(
                field="product_candidates", severity="BLOCKING",
                impact="No usable product data from the Product Specialist Agent; no portfolio can be constructed.",
            ))

        market_cut, market_cut_reason = market_growth_adjustment(market)
        can_build = not a.is_blocked and liq.eligible_value is not None and product_res.status != "UNAVAILABLE"
        if can_build:
            products = product_res.data.products
            screening = screen_products(
                products, profile, a, a.reference_date, self.settings.product_stale_after_days
            )
            excluded = [ExcludedProduct(product_id=pid, reason=r) for pid, r in screening.excluded]
            ctx = ConstructionContext(
                eligible_value=liq.eligible_value,
                base_currency=profile.base_currency,
                effective_level=a.effective_level,
                horizon_years=a.shortest_horizon_years,
                max_single_pct=profile.maximum_single_asset_allocation,
                max_drawdown_pct=profile.maximum_acceptable_drawdown,
                max_fx_pct=profile.maximum_currency_exposure,
                screening=screening,
                esg_preferred=bool(profile.esg_preferences and profile.esg_preferences.level == "Preferred"),
                exclusion_reasons=self._class_exclusion_reasons(products, screening, a),
                market_growth_reduction=market_cut,
            )
            if a.shortest_horizon_years is None:
                a.assumptions.append(
                    f"Investment horizon unknown: growth assets capped at {MEDIUM_HORIZON_CAP:.0f}% in every option."
                )
            if market_cut_reason:
                a.assumptions.append(market_cut_reason)
            built = [build_option(t, ctx) for t in TEMPLATES]
            differentiate(built)
            source = "UPSTREAM_API" if product_res.source == "LIVE" else "ILLUSTRATIVE_MOCK"
            options = [self._assemble(b, ctx, a, profile, market, source) for b in built]
            options = [self._enforce_validation(o) for o in options]
            self._add_key_differences(options)
            candidates = self._candidates(products, screening, options, source)

        offered = [o for o in options if o.suitability_status in OFFERED]
        comparison = build_comparison(options, a) if offered else []
        preferred, pref_rationale = choose_preferred(options, a, market is not None)
        if not can_build:
            preferred, pref_rationale = None, "No portfolio options were constructed, so none is preferred."

        status = self._overall_status(a, missing, can_build, offered, warnings)

        # --- Explanations ---------------------------------------------------
        allowed = self._allowed_numbers(options, liq, profile, market, ctx, self.cma)
        facts = self._llm_facts(options, a, profile, market, preferred, pref_rationale)
        allowed.add_from_text(json.dumps(facts, default=str))
        expl = await generate_explanations(
            facts, {o.option_id for o in offered}, allowed, self.settings, self.llm_factory
        )
        for o in offered:
            if o.option_id in expl.option_narratives:
                o.narrative = expl.option_narratives[o.option_id]
                o.narrative_source = "LLM_INTERPRETATION"
        comparison_summary = expl.comparison_summary or self._comparison_summary(options)
        if expl.preferred_commentary and preferred:
            pref_rationale += f" [LLM interpretation] {expl.preferred_commentary}"

        response = PortfolioResponse(
            request_id=request_id,
            client_id=req.client_id,
            analysis_timestamp=now,
            status=status,
            data_status=DataStatus(
                client_profile=self._profile_status(a, missing),
                market_analysis=_data_status(market_res),
                product_candidates=_data_status(product_res),
            ),
            client_profile_summary=ClientProfileSummary(
                base_currency=profile.base_currency,
                risk_appetite=profile.risk_appetite,
                risk_capacity=profile.risk_capacity,
                risk_tolerance_score=profile.risk_tolerance_score,
                effective_risk_level=a.effective_level,
                effective_risk_label=a.effective_label,
                effective_risk_basis=a.effective_basis,
                maximum_acceptable_drawdown=profile.maximum_acceptable_drawdown,
                primary_goals=[g.goal for g in sorted(a.goals, key=lambda g: {"High": 0, "Medium": 1}.get(g.priority, 2))],
                shortest_goal_horizon_years=a.shortest_horizon_years,
                review_trigger=self._trigger_text(req),
            ),
            liquidity_plan=liq.plan,
            market_context_summary=det.market_context(market, market_res.issues, market_res.source, self.cma),
            portfolio_options=options,
            comparison_matrix=comparison,
            comparison_summary=comparison_summary if offered else None,
            preferred_option=preferred,
            preferred_option_rationale=pref_rationale,
            key_risks=self._key_risks(market, offered),
            assumptions=self._assumptions(a),
            missing_information=missing,
            conflicts=a.conflicts,
            excluded_products=excluded,
            candidate_products=candidates,
            warnings=warnings,
            explanation_status=expl.status,
            disclaimer=DISCLAIMER,
        )
        self.store.save(response)
        # Log identifiers and outcome only - never profile contents.
        logger.info("Portfolio proposal %s generated: status=%s options_offered=%d",
                    request_id, status, len(offered))
        return response

    # --- Assembly ------------------------------------------------------------

    def _assemble(self, b: BuiltOption, ctx, a: ProfileAssessment, profile, market, provenance) -> PortfolioOption:
        t = b.template
        common = dict(
            option_id=t.option_id, option_name=t.name, objective=t.objective,
            suitability_status=b.status, suitability_explanation=b.explanation,
            eligible_portfolio_value=ctx.eligible_value, base_currency=ctx.base_currency,
        )
        if not b.is_offered:
            return PortfolioOption(
                **common, asset_allocation=[], product_selections=[], expected_portfolio_return=None,
                estimated_risk_level=None, metrics=None, scenario_analysis=[], goal_alignment=[],
                constraint_checks=[], liquidity_assessment="Not applicable - option not offered.",
                diversification_assessment="Not applicable - option not offered.",
                advantages=[], disadvantages=[], rationale=[], assumptions=[],
                warnings=[f"Option {t.option_id} not offered: {b.explanation}"],
                narrative=None, narrative_source="NONE",
            )

        metrics, exp = compute_metrics(b, ctx, self.cma)
        scenarios = scenario_outcomes(
            b, ctx.eligible_value, self.cma, market.regime.recession_prob_12m if market else None
        )
        goals = goal_alignment(ctx.eligible_value, metrics.expected_annual_return_pct, a, ctx.base_currency)
        checks = constraint_checks(b, metrics, ctx)
        adv, dis = det.advantages_disadvantages(b, metrics, goals, scenarios)

        current = self._current_allocation(profile)
        weights = b.class_weights()
        amounts: dict = {}
        for p in b.positions:
            amounts[p.sp.asset_class] = amounts.get(p.sp.asset_class, 0.0) + p.amount
        allocation = [
            AssetAllocationItem(
                asset_class=ac.value,
                allocation_percentage=round(w, 2),
                investment_amount=round(amounts[ac], 2),
                change_from_current_pp=(round(w - current.get(ac, 0.0), 2) if current is not None else None),
            )
            for ac, w in sorted(weights.items(), key=lambda kv: -kv[1])
        ]

        selections = []
        option_warnings = []
        for p in b.positions:
            prod = p.sp.product
            er = exp[p.sp.product_id]
            selections.append(ProductSelection(
                product_id=prod.product_id, product_name=prod.product_name, asset_class=p.sp.asset_class.value,
                product_type=prod.product_type, currency=prod.currency, currency_hedged=prod.currency_hedged,
                allocation_percentage=p.pct, investment_amount=p.amount,
                expected_return_assumption=er.value, expected_return_basis=er.basis,
                management_fee=prod.management_fee,
                estimated_transaction_cost=(round(p.amount * prod.transaction_fee / 100, 2)
                                            if prod.transaction_fee is not None else None),
                liquidity=prod.liquidity,
                key_rationale=det.product_rationale(prod, p.sp.asset_class, ctx.base_currency, p.sp.notes),
                key_risks=det.product_risks(prod, p.sp.asset_class, ctx.base_currency),
                data_provenance="ILLUSTRATIVE_MOCK" if (provenance == "ILLUSTRATIVE_MOCK" or prod.is_illustrative)
                else "UPSTREAM_API",
                as_of_date=prod.as_of_date,
                data_warnings=list(p.sp.notes),
                details=_details(prod),
            ))
            option_warnings += [f"{prod.product_id}: {n}" for n in p.sp.notes]

        if a.shortest_horizon_years is not None:
            long_dated = sum(p.pct for p in b.positions
                             if (p.sp.product.recommended_horizon or 0) > a.shortest_horizon_years)
            if long_dated > 0:
                option_warnings.append(
                    f"{long_dated:.1f}% of this option is in products whose recommended holding period exceeds the "
                    f"shortest goal horizon ({a.shortest_horizon_years:g} years)."
                )
        for c in checks:
            if c.status == "UNVERIFIED":
                option_warnings.append(f"{c.constraint}: {c.detail}")

        return PortfolioOption(
            **common,
            asset_allocation=allocation,
            sub_asset_allocation=self._sub_allocation(selections),
            product_selections=selections,
            expected_portfolio_return=metrics.expected_annual_return_pct,
            estimated_risk_level=risk_level(metrics),
            metrics=metrics,
            scenario_analysis=scenarios,
            goal_alignment=goals,
            constraint_checks=checks,
            liquidity_assessment=det.liquidity_assessment(metrics, b.positions),
            diversification_assessment=det.diversification_assessment(metrics),
            advantages=adv,
            disadvantages=dis,
            rationale=det.option_rationale(b, ctx, a, profile, market, metrics),
            assumptions=det.option_assumptions(exp, self.cma),
            warnings=option_warnings,
            narrative=det.narrative_template(b, metrics, ctx.base_currency),
            narrative_source="DETERMINISTIC_TEMPLATE",
        )

    @staticmethod
    def _sub_allocation(selections) -> list:
        agg: dict = {}
        for s in selections:
            key = (s.asset_class, s.details.sub_asset_class or s.asset_class)
            pct, amt = agg.get(key, (0.0, 0.0))
            agg[key] = (pct + s.allocation_percentage, amt + s.investment_amount)
        return [SubAssetAllocationItem(asset_class=ac, sub_asset_class=sub, allocation_percentage=round(p, 2),
                                       investment_amount=round(a, 2))
                for (ac, sub), (p, a) in sorted(agg.items(), key=lambda kv: -kv[1][0])]

    @staticmethod
    def _add_key_differences(options: list[PortfolioOption]) -> None:
        """Plain statements of how each offered option differs from the previous (more cautious) one."""
        offered = [o for o in options if o.suitability_status in OFFERED and o.metrics]
        for i, o in enumerate(offered):
            m = o.metrics
            if i == 0:
                defensive = sum(a.allocation_percentage for a in o.asset_allocation if a.asset_class in ("Cash", "Fixed income"))
                o.key_differences = [
                    f"Most cautious portfolio proposed: {defensive:.1f}% in cash and fixed income, "
                    f"{m.growth_asset_share_pct:.1f}% growth assets."
                ]
                continue
            prev = offered[i - 1]
            pm = prev.metrics
            mine = {a.asset_class: a.allocation_percentage for a in o.asset_allocation}
            theirs = {a.asset_class: a.allocation_percentage for a in prev.asset_allocation}
            moves = sorted(((ac, mine.get(ac, 0.0) - theirs.get(ac, 0.0)) for ac in set(mine) | set(theirs)),
                           key=lambda kv: -abs(kv[1]))
            moves = [f"{ac} {d:+.1f} pts" for ac, d in moves if abs(d) >= 1.0][:4]
            diffs = [f"Compared with {prev.option_id} ({prev.option_name}): " + (", ".join(moves) if moves else
                                                                                 "a similar asset mix") + "."]
            if m.estimated_stress_drawdown_pct is not None and pm.estimated_stress_drawdown_pct is not None:
                diffs.append(f"Estimated stress drawdown {m.estimated_stress_drawdown_pct:.1f}% vs "
                             f"{pm.estimated_stress_drawdown_pct:.1f}%.")
            if o.expected_portfolio_return is not None and prev.expected_portfolio_return is not None:
                diffs.append(f"Expected return assumption {o.expected_portfolio_return:.2f}% vs "
                             f"{prev.expected_portfolio_return:.2f}% a year.")
            if m.high_liquidity_share_pct is not None and pm.high_liquidity_share_pct is not None                     and abs(m.high_liquidity_share_pct - pm.high_liquidity_share_pct) >= 1:
                diffs.append(f"Daily-dealing share {m.high_liquidity_share_pct:.0f}% vs {pm.high_liquidity_share_pct:.0f}%.")
            o.key_differences = diffs

    @staticmethod
    def _enforce_validation(o: PortfolioOption) -> PortfolioOption:
        errors = validate_option(o)
        if not errors:
            return o
        logger.error("Option %s withheld: failed numerical validation (%d errors)", o.option_id, len(errors))
        return o.model_copy(update=dict(
            suitability_status="INFEASIBLE",
            suitability_explanation="Withheld: the option failed programmatic numerical validation.",
            asset_allocation=[], sub_asset_allocation=[], product_selections=[], expected_portfolio_return=None,
            estimated_risk_level=None, metrics=None, scenario_analysis=[], goal_alignment=[],
            advantages=[], disadvantages=[], narrative=None, narrative_source="NONE",
            warnings=o.warnings + [f"Validation error: {e}" for e in errors],
        ))

    @staticmethod
    def _candidates(products, screening, options, source) -> list[CandidateProduct]:
        reasons = dict(screening.excluded)
        notes = {sp.product_id: sp.notes for lst in screening.by_class.values() for sp in lst}
        used: dict[str, list[str]] = {}
        for o in options:
            for s in o.product_selections:
                used.setdefault(s.product_id, []).append(o.option_id)
        out = []
        for prod in products:
            pid = prod.product_id
            status = "EXCLUDED" if pid in reasons else ("SELECTED" if pid in used else "ELIGIBLE_NOT_SELECTED")
            out.append(CandidateProduct(
                product_id=pid, product_name=prod.product_name, asset_class=prod.asset_class,
                product_type=prod.product_type, currency=prod.currency, currency_hedged=prod.currency_hedged,
                management_fee=prod.management_fee, liquidity=prod.liquidity, screening_status=status,
                selected_in_options=used.get(pid, []), exclusion_reason=reasons.get(pid),
                notes=list(notes.get(pid, [])),
                data_provenance="ILLUSTRATIVE_MOCK" if (source == "ILLUSTRATIVE_MOCK" or prod.is_illustrative)
                else "UPSTREAM_API",
                as_of_date=prod.as_of_date, details=_details(prod),
            ))
        return out

    @staticmethod
    def _current_allocation(profile) -> Optional[dict]:
        cur = profile.current_asset_allocation
        if not cur or abs(sum(cur.values()) - 100) > 1:
            return None
        out: dict = {}
        for label, pct in cur.items():
            ac = parse_asset_class(label)
            if ac is None:
                return None
            out[ac] = out.get(ac, 0.0) + pct
        return out

    @staticmethod
    def _class_exclusion_reasons(products, screening, a: ProfileAssessment) -> dict:
        reasons = {}
        excluded_ids = dict(screening.excluded)
        for ac in AssetClass:
            if a.preferred_classes is not None and ac not in a.preferred_classes:
                reasons[ac] = "outside the client's preferred asset classes"
                continue
            in_class = [p for p in products if parse_asset_class(p.asset_class) == ac]
            if not in_class:
                reasons[ac] = "no candidate products supplied by the Product Specialist Agent"
            elif all(p.product_id in excluded_ids for p in in_class):
                reasons[ac] = "all candidate products excluded by client constraints"
        return reasons

    # --- Status / summaries --------------------------------------------------

    @staticmethod
    def _profile_status(a: ProfileAssessment, missing) -> str:
        if any(c.severity == "BLOCKING" for c in a.conflicts):
            return "INVALID"
        if any(m.severity in ("BLOCKING", "MATERIAL") for m in missing):
            return "INCOMPLETE"
        return "VALIDATED"

    @staticmethod
    def _overall_status(a, missing, can_build, offered, warnings) -> str:
        if any(m.severity == "BLOCKING" for m in missing):
            return "INSUFFICIENT_INFORMATION"
        if not can_build or not offered:
            return "CONSTRAINT_CONFLICT"
        if warnings or a.has_material_issues:
            return "COMPLETED_WITH_WARNINGS"
        return "COMPLETED"

    def _upstream_warnings(self, market_res, product_res, market, now) -> list[str]:
        out = []
        for name, res in (("Market research", market_res), ("Product data", product_res)):
            if res.source == "MOCK":
                out.append(f"{name} is illustrative MOCK data, not verified real-world information.")
            if res.status == "UNAVAILABLE":
                out.append(f"{name} unavailable from the upstream agent.")
            out.extend(res.issues)
        if market:
            age = (now.date() - market.as_of).days
            if age > self.settings.market_stale_after_days:
                out.append(f"Market research is stale ({age} days old, as of {market.as_of}).")
        return out

    @staticmethod
    def _key_risks(market, offered) -> list[str]:
        risks = []
        if market:
            risks += list(market.risks or [])
            risks += [e.description for e in market.events if e.severity == "major"]
        risks.append("All options can lose value; none is risk-free, and projected returns are not guaranteed.")
        if any(o.metrics and (o.metrics.foreign_currency_exposure_pct or 0) > 0 for o in offered):
            risks.append("Some options carry unhedged foreign-currency exposure.")
        risks.append("Analysis relies on illustrative mock data; real product terms and market conditions will differ.")
        return risks

    @staticmethod
    def _assumptions(a: ProfileAssessment) -> list[str]:
        ceilings = ", ".join(f"level {k}: {v:.0f}%" for k, v in GROWTH_CEILING_BY_RISK_LEVEL.items())
        return a.assumptions + [
            f"Growth-asset ceilings by effective risk level ({ceilings}), further capped at 40% for horizons under "
            "5 years and 20% under 3 years. These are prototype house rules.",
            "Options are built from rules-based templates adapted to constraints; no mathematical optimisation is "
            "performed, so no option is claimed to be optimal.",
            "Effective risk level is the lower of risk willingness (appetite / tolerance score) and risk capacity.",
        ]

    @staticmethod
    def _trigger_text(req) -> Optional[str]:
        t = req.trigger
        if not t:
            return None
        parts = [x for x in (t.life_event, t.requirement_change, t.reason_for_review) if x]
        if t.effective_date:
            parts.append(f"effective {t.effective_date}")
        return "; ".join(parts) or None

    @staticmethod
    def _comparison_summary(options: list[PortfolioOption]) -> str:
        offered = [o for o in options if o.suitability_status in OFFERED]
        parts = []
        for o in offered:
            m = o.metrics
            exp = f"{m.expected_annual_return_pct:.2f}%" if m.expected_annual_return_pct is not None else "n/a"
            dd = f"{m.estimated_stress_drawdown_pct:.1f}%" if m.estimated_stress_drawdown_pct is not None else "n/a"
            parts.append(f"Option {o.option_id} ({o.option_name}): growth assets {m.growth_asset_share_pct:.1f}%, "
                         f"expected return {exp} p.a., stress drawdown {dd}.")
        not_offered = [o for o in options if o.suitability_status not in OFFERED]
        for o in not_offered:
            parts.append(f"Option {o.option_id} not offered: {o.suitability_explanation}")
        parts.append("Higher growth share brings higher expected return and larger potential losses; "
                     "all figures are illustrative.")
        return " ".join(parts)

    # --- LLM inputs ----------------------------------------------------------

    @staticmethod
    def _allowed_numbers(options, liq, profile, market, ctx, cma) -> AllowedNumbers:
        al = AllowedNumbers()
        al.add_pct(0, 100)
        al.add_amount(liq.plan.investable_assets, liq.plan.minimum_cash_reserve_required, liq.plan.reserve_carved_out,
                      liq.plan.near_term_withdrawals_carved_out, liq.plan.eligible_portfolio_value)
        al.add_pct(profile.maximum_acceptable_drawdown, profile.maximum_single_asset_allocation,
                   profile.maximum_currency_exposure)
        if ctx:
            al.add_pct(ctx.growth_ceiling)
        for o in options:
            for x in o.asset_allocation:
                al.add_pct(x.allocation_percentage, x.change_from_current_pp)
                al.add_amount(x.investment_amount)
            for s in o.product_selections:
                al.add_pct(s.allocation_percentage, s.expected_return_assumption, s.management_fee)
                al.add_amount(s.investment_amount, s.estimated_transaction_cost)
            if o.metrics:
                m = o.metrics
                al.add_pct(m.expected_annual_return_pct, m.estimated_volatility_pct, m.estimated_stress_drawdown_pct,
                           m.growth_asset_share_pct, m.estimated_annual_fee_pct, m.high_liquidity_share_pct,
                           m.foreign_currency_exposure_pct)
                al.add_amount(m.estimated_annual_fee_amount, m.estimated_one_off_transaction_cost)
                if m.estimated_stress_drawdown_pct is not None and o.eligible_portfolio_value:
                    al.add_amount(o.eligible_portfolio_value * m.estimated_stress_drawdown_pct / 100)
            for sc in o.scenario_analysis:
                al.add_pct(sc.portfolio_return_pct, (sc.probability or 0) * 100)
                al.add_amount(sc.portfolio_value_change)
            for g in o.goal_alignment:
                al.add_amount(g.target_amount, g.projected_value_base_case)
                if g.target_amount is not None and g.projected_value_base_case is not None:
                    al.add_amount(g.projected_value_base_case - g.target_amount)
        if market:
            for i in market.indicators + market.market_snapshot:
                al.add_pct(i.value, *i.changes.values())
                al.add_amount(i.value)
                if i.percentile_10y is not None:
                    al.add_pct(i.percentile_10y)
            r = market.regime
            al.add_pct(*(v * 100 for v in r.probabilities.values()))
            if r.recession_prob_12m is not None:
                al.add_pct(r.recession_prob_12m * 100, round(r.recession_prob_12m * 100))
        al.add_pct(*cma.long_term_expected_return.values())
        for sc in cma.scenarios:
            al.add_pct(*sc.asset_class_returns.values())
        return al

    @staticmethod
    def _llm_facts(options, a: ProfileAssessment, profile, market, preferred, pref_rationale) -> dict:
        """Anonymised facts for the LLM: no client_id, residency or account details."""
        return {
            "data_provenance": "All market and product data are ILLUSTRATIVE MOCK data; expected and scenario "
                               "returns are illustrative house assumptions.",
            "client": {
                "risk_appetite": profile.risk_appetite,
                "risk_capacity": profile.risk_capacity,
                "effective_risk_level": a.effective_level,
                "effective_risk_label": a.effective_label,
                "effective_risk_basis": a.effective_basis,
                "maximum_acceptable_drawdown_pct": profile.maximum_acceptable_drawdown,
                "base_currency": profile.base_currency,
                "goals": [g.__dict__ for g in a.goals],
            },
            "market": None if market is None else {
                "source": "Market Researcher",
                "as_of": str(market.as_of),
                "region": market.region,
                "cycle_phase": market.regime.phase,
                "cycle_confidence": market.regime.confidence,
                "recession_prob_12m_pct": (round(market.regime.recession_prob_12m * 100)
                                           if market.regime.recession_prob_12m is not None else None),
                "notable_events": [e.description for e in market.events if e.severity in ("notable", "major")],
                "key_themes": market.key_themes or [],
                "risks": market.risks or [],
                "implications": market.implications or {},
            },
            "return_assumptions_source": "Portfolio Manager house assumptions (illustrative), not the Market Researcher",
            "options_to_narrate": [o.option_id for o in options if o.suitability_status in OFFERED],
            "options_not_offered": {
                o.option_id: o.suitability_explanation for o in options if o.suitability_status not in OFFERED
            },
            "options": [
                {
                    "option_id": o.option_id,
                    "name": o.option_name,
                    "status": o.suitability_status,
                    "status_explanation": o.suitability_explanation,
                    "asset_allocation_pct": {x.asset_class: x.allocation_percentage for x in o.asset_allocation},
                    "metrics": o.metrics.model_dump() if o.metrics else None,
                    "scenarios": [s.model_dump() for s in o.scenario_analysis],
                    "goal_alignment": [g.model_dump() for g in o.goal_alignment],
                    "advantages": o.advantages,
                    "disadvantages": o.disadvantages,
                }
                for o in options if o.suitability_status in OFFERED
            ],
            "preferred_option": preferred,
            "preferred_option_rule_based_rationale": pref_rationale,
        }
