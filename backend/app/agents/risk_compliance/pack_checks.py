"""
Final check of the assembled review pack before the RM can approve G4.

Each specialist already enforces its own rules while building its part
(the Product Recommender's suitability gate, the PM's construction
limits). This is the independent second line: it re-checks the finished
pack as a whole, where problems between agents show up - an IC allocation
above the client's growth ceiling, a PS product the client cannot hold,
an unfinished or flagged section, a guarantee in the text.

Every function is pure and returns findings; none of them passes anything
by default. Product suitability is the shared `suitability.gate()`, not a
copy of its rules, and the wording check is the PM's narrative guardrails.
"""
from datetime import date
from typing import Optional

from app.agents.portfolio_manager.engine.profile_assessment import ProfileAssessment
from app.agents.portfolio_manager.explain.guardrails import (
    AllowedNumbers,
    find_claim_violations,
    find_number_violations,
)
from app.agents.portfolio_manager.schemas.client import ClientProfile
from app.agents.portfolio_manager.taxonomy import (
    GROWTH_WEIGHT,
    AssetClass,
    parse_asset_class,
)
from app.agents.product_recommender.schemas import ShelfProduct
from app.agents.product_recommender.suitability import gate
from app.agents.risk_compliance.config import Settings
from app.agents.risk_compliance.policy import LoadedPolicy
from app.agents.risk_compliance.readiness import ReadinessOutcome
from app.agents.risk_compliance.schemas import (
    AllocationRowIn,
    ClientConstraints,
    PackProduct,
    PackSectionIn,
    ReviewPackCheckRequest,
    RiskFinding,
)

EPS = 1e-9


# --- Data freshness ------------------------------------------------------------

def check_market_freshness(market_as_of: Optional[date], ref: date, policy: LoadedPolicy) -> list[RiskFinding]:
    limit = policy.t.market_stale_after_days
    if market_as_of is None:
        return [policy.finding(
            "DATA.MARKET_STALE", "MARKET_AS_OF_UNKNOWN",
            "The as-of date of the market data in the pack is unknown, so its currency cannot be checked.",
            fields=["data_as_of.market"], observed="unknown", threshold=limit,
        )]
    age = (ref - market_as_of).days
    if age > limit:
        return [policy.finding(
            "DATA.MARKET_STALE", "MARKET_STALE",
            f"The market data in the pack is {age} days old; the policy allows {limit}.",
            fields=["data_as_of.market"], observed=age, threshold=limit,
        )]
    return []


# --- Allocation ------------------------------------------------------------------

def check_allocation(
    rows: list[AllocationRowIn], a: ProfileAssessment, c: ClientConstraints, policy: LoadedPolicy,
) -> list[RiskFinding]:
    t = policy.t
    if not rows:
        return [policy.finding(
            "ALLOC.MISSING", "ALLOCATION_MISSING", "The pack has no allocation, so the TAA cannot be checked.",
            fields=["allocation"],
        )]

    findings: list[RiskFinding] = []
    total = sum(r.new_taa for r in rows)
    if abs(total - 100) > t.allocation_sum_tolerance_pct + EPS:
        findings.append(policy.finding(
            "ALLOC.SUM", "TAA_SUM", f"The new TAA sums to {total:.2f}%, not 100%.",
            fields=["allocation[*].new_taa"], observed=round(total, 4), threshold=100.0,
        ))

    growth = 0.0
    for r in rows:
        ac = parse_asset_class(r.asset_class)
        field = f"allocation[{r.asset_class}].new_taa"
        if ac is None:
            findings.append(policy.finding(
                "ALLOC.UNKNOWN_CLASS", "UNKNOWN_ASSET_CLASS",
                f"'{r.asset_class}' is not a recognised asset class, so its weight cannot be checked.",
                fields=[f"allocation[{r.asset_class}]"], observed=r.asset_class,
            ))
            continue
        growth += r.new_taa * GROWTH_WEIGHT[ac]

        limit = r.band + t.band_tolerance_pct
        drift = abs(r.new_taa - r.saa)
        if drift > limit + EPS:
            findings.append(policy.finding(
                "ALLOC.BAND", "OUTSIDE_SAA_BAND",
                f"{ac.value}: new TAA {r.new_taa:g}% is {drift:g}pp from the SAA of {r.saa:g}%; the band is ±{r.band:g}pp.",
                fields=[field], observed=round(drift, 4), threshold=limit,
            ))
        if a.preferred_classes is not None and r.new_taa > EPS and ac not in a.preferred_classes:
            findings.append(policy.finding(
                "ALLOC.NOT_PREFERRED", "CLASS_NOT_PREFERRED",
                f"The new TAA puts {r.new_taa:g}% in {ac.value}, outside the client's preferred asset classes.",
                fields=[field, "preferred_asset_classes"], observed=r.new_taa, threshold=0.0,
            ))

    if c.max_growth_pct is not None:
        limit = c.max_growth_pct + t.growth_ceiling_tolerance_pct
        if growth > limit + EPS:
            findings.append(policy.finding(
                "ALLOC.GROWTH_CEILING", "GROWTH_ABOVE_CEILING",
                f"Growth assets are {growth:g}% of the new TAA; the ceiling for risk level "
                f"{c.effective_risk_level} and the client's horizon is {c.max_growth_pct:g}%.",
                fields=["allocation[*].new_taa"], observed=round(growth, 4), threshold=c.max_growth_pct,
            ))
    return findings


# --- Products --------------------------------------------------------------------

def _resolve(item: PackProduct, by_id: dict, by_name: dict) -> Optional[ShelfProduct]:
    if item.product_id and item.product_id in by_id:
        return by_id[item.product_id]
    return by_name.get(item.product_name.strip().lower())


def check_products(
    items: list[PackProduct],
    shelf: Optional[list[ShelfProduct]],
    p: ClientProfile,
    a: ProfileAssessment,
    c: ClientConstraints,
    rows: list[AllocationRowIn],
    policy: LoadedPolicy,
    settings: Settings,
) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    by_id = {s.product_id: s for s in shelf or []}
    by_name = {s.product_name.strip().lower(): s for s in shelf or []}

    resolved: list[tuple[PackProduct, ShelfProduct]] = []
    for item in items:
        prod = _resolve(item, by_id, by_name)
        if prod is None:
            why = "the product shelf is unavailable" if shelf is None else "it is not on the product shelf"
            findings.append(policy.finding(
                "PROD.UNVERIFIED", "PRODUCT_UNVERIFIED",
                f"'{item.product_name}' cannot be checked because {why}.",
                fields=[f"products[{item.product_id or item.product_name}]"], observed=item.product_name,
            ))
        else:
            resolved.append((item, prod))

    if not resolved:
        return findings

    ref = a.reference_date
    limit = policy.t.product_stale_after_days
    for _, prod in resolved:
        age = (ref - prod.as_of_date).days if prod.as_of_date else None
        if age is None or age > limit:
            findings.append(policy.finding(
                "DATA.PRODUCTS_STALE", "PRODUCT_DATA_STALE",
                f"{prod.product_id}: product data is "
                + ("undated" if age is None else f"{age} days old; the policy allows {limit}") + ".",
                fields=[f"products[{prod.product_id}].as_of_date"],
                observed="unknown" if age is None else age, threshold=limit,
            ))

    result = gate(
        [prod for _, prod in resolved], p, a, ref, settings.product_stale_after_days,
        liquidity_need_months=settings.liquidity_need_months,
    )
    for ex in result.excluded:
        findings.append(policy.finding(
            "PROD.SUITABILITY", f"SUITABILITY_{ex.code}",
            f"{ex.product.product_id} ({ex.product.product_name}): {ex.reason}",
            fields=[f"products[{ex.product.product_id}]"], observed=ex.code,
        ))

    if rows:
        weight_by_class: dict[AssetClass, float] = {}
        for r in rows:
            ac = parse_asset_class(r.asset_class)
            if ac is not None:
                weight_by_class[ac] = weight_by_class.get(ac, 0.0) + r.new_taa
        for _, prod in resolved:
            ac = parse_asset_class(prod.asset_class)
            if ac is not None and weight_by_class.get(ac, 0.0) <= EPS:
                findings.append(policy.finding(
                    "PROD.CLASS_NOT_ALLOCATED", "PRODUCT_CLASS_NOT_IN_TAA",
                    f"{prod.product_id} is {ac.value}, which has no weight in the new TAA.",
                    fields=[f"products[{prod.product_id}]", f"allocation[{ac.value}].new_taa"], observed=0.0,
                ))

    findings += _check_weights(resolved, p, c, policy)
    return findings


def _check_weights(
    resolved: list[tuple[PackProduct, ShelfProduct]], p: ClientProfile, c: ClientConstraints, policy: LoadedPolicy,
) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    unweighted = [prod.product_id for item, prod in resolved if item.weight_pct is None]
    if unweighted:
        findings.append(policy.finding(
            "PROD.WEIGHTS_MISSING", "PRODUCT_WEIGHTS_MISSING",
            f"No weight for {', '.join(unweighted)}; single-product and currency caps are not checked for them.",
            fields=[f"products[{pid}].weight_pct" for pid in unweighted],
        ))

    for item, prod in resolved:
        if item.weight_pct is not None and item.weight_pct > c.max_single_product_pct + EPS:
            findings.append(policy.finding(
                "PROD.SINGLE_CAP", "SINGLE_PRODUCT_ABOVE_CAP",
                f"{prod.product_id} is {item.weight_pct:g}% of the portfolio; the cap is {c.max_single_product_pct:g}%.",
                fields=[f"products[{prod.product_id}].weight_pct"],
                observed=item.weight_pct, threshold=c.max_single_product_pct,
            ))

    # Currency exposure only adds up when every product has a weight; a
    # partial sum would understate it, so it is left to the note above.
    if not unweighted and p.base_currency:
        fx = sum(
            item.weight_pct for item, prod in resolved
            if prod.currency != p.base_currency and prod.currency_hedged is not True
        )
        if fx > c.max_currency_exposure_pct + EPS:
            findings.append(policy.finding(
                "PROD.FX_CAP", "CURRENCY_EXPOSURE_ABOVE_CAP",
                f"Unhedged non-{p.base_currency} products are {fx:g}% of the portfolio; "
                f"the cap is {c.max_currency_exposure_pct:g}%.",
                fields=["products[*].weight_pct", "maximum_currency_exposure"],
                observed=round(fx, 4), threshold=c.max_currency_exposure_pct,
            ))
    return findings


# --- Sections and gates ----------------------------------------------------------

def check_sections(
    sections: list[PackSectionIn], gates: dict[str, str], policy: LoadedPolicy,
) -> list[RiskFinding]:
    t = policy.t
    findings: list[RiskFinding] = []
    if not sections:
        findings.append(policy.finding(
            "PACK.SECTION_INCOMPLETE", "PACK_EMPTY", "The pack has no sections.", fields=["sections"],
        ))
    for s in sections:
        if s.kind == "signoff":
            continue  # signatures are the RM's G4 step itself
        field = f"sections[{s.n}]"
        if s.status == "flagged":
            findings.append(policy.finding(
                "PACK.SECTION_FLAGGED", "SECTION_FLAGGED",
                f"Section '{s.title}' is flagged and must be resolved before sign-off.",
                fields=[field], observed=s.status,
            ))
        elif s.status not in t.complete_section_statuses or not s.text.strip():
            findings.append(policy.finding(
                "PACK.SECTION_INCOMPLETE", "SECTION_INCOMPLETE",
                f"Section '{s.title}' is not complete (status '{s.status}'"
                + ("" if s.text.strip() else ", no text") + ").",
                fields=[field], observed=s.status,
                threshold=", ".join(t.complete_section_statuses),
            ))
    for g in t.required_prior_gates:
        state = gates.get(g)
        if state != "approved":
            findings.append(policy.finding(
                "PACK.PRIOR_GATE", "PRIOR_GATE_NOT_APPROVED",
                f"Gate {g} is {state or 'not recorded'}; it must be approved before G4.",
                fields=[f"gates.{g}"], observed=state or "unknown", threshold="approved",
            ))
    return findings


# --- Wording -----------------------------------------------------------------------

def allowed_numbers(req: ReviewPackCheckRequest, out: ReadinessOutcome) -> AllowedNumbers:
    """Figures the pack may state: every number the checks themselves used."""
    allowed = AllowedNumbers()
    for r in req.allocation:
        allowed.add_pct(r.saa, r.current, r.old_taa, r.new_taa, r.band, r.new_taa - r.old_taa, r.new_taa - r.saa)
    for item in req.products:
        allowed.add_pct(item.weight_pct)
    c = out.constraints
    allowed.add_pct(c.max_growth_pct, c.max_drawdown_pct, c.max_single_product_pct, c.max_currency_exposure_pct)
    p = req.client_profile
    allowed.add_pct(p.maximum_acceptable_drawdown, p.maximum_single_asset_allocation, p.maximum_currency_exposure)
    allowed.add_amount(p.total_aum, p.investable_assets, p.annual_income, p.monthly_expenses, p.liabilities,
                       p.emergency_fund, p.cash_balance, p.minimum_cash_reserve, p.target_amount)
    for g in p.financial_goals or []:
        allowed.add_amount(g.target_amount)
    plan = out.liquidity.plan
    allowed.add_amount(plan.minimum_cash_reserve_required, plan.reserve_carved_out,
                       plan.near_term_withdrawals_carved_out, plan.later_withdrawals_not_carved_out,
                       plan.eligible_portfolio_value)
    return allowed


def check_text(sections: list[PackSectionIn], allowed: AllowedNumbers, policy: LoadedPolicy) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    for s in sections:
        field = f"sections[{s.n}].text"
        claims = find_claim_violations(s.text)
        if claims:
            findings.append(policy.finding(
                "TEXT.CLAIM", "PROHIBITED_CLAIM",
                f"Section '{s.title}' contains {'; '.join(claims)}.",
                fields=[field], observed=len(claims), threshold=0,
            ))
        numbers = find_number_violations(s.text, allowed)
        if numbers:
            findings.append(policy.finding(
                "TEXT.NUMBERS", "UNRECONCILED_FIGURE",
                f"Section '{s.title}': {'; '.join(numbers)} does not match any checked figure.",
                fields=[field], observed=len(numbers), threshold=0,
            ))

    phrases = [ph.lower() for ph in policy.t.required_disclaimer_phrases]
    full_text = " ".join(s.text for s in sections).lower()
    if phrases and not any(ph in full_text for ph in phrases):
        findings.append(policy.finding(
            "TEXT.DISCLAIMER", "DISCLAIMER_MISSING",
            "No section carries a required disclaimer (e.g. that returns are not guaranteed).",
            fields=["sections[*].text"], threshold="; ".join(policy.t.required_disclaimer_phrases),
        ))
    return findings
