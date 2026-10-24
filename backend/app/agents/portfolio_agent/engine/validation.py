"""
Final programmatic check of every number in an assembled option, run just
before the response is returned. An option that fails is withheld (its
allocation is removed and it is marked INFEASIBLE with the errors) rather
than shown to the RM with figures that don't reconcile.
"""
from app.agents.portfolio_agent.schemas.response import PortfolioOption

PCT_TOLERANCE = 0.01


def validate_option(opt: PortfolioOption) -> list[str]:
    errors: list[str] = []
    if opt.suitability_status not in ("SUITABLE", "SUITABLE_WITH_MODIFICATIONS"):
        if opt.product_selections or opt.asset_allocation:
            errors.append("An option that is not offered must not carry allocations.")
        return errors

    value = opt.eligible_portfolio_value
    if value is None or value <= 0:
        return ["Offered option has no positive eligible portfolio value."]
    if not opt.product_selections:
        return ["Offered option has no product selections."]

    n = len(opt.product_selections)
    amount_tol = 0.01 * (n + 1)

    pct_total = sum(s.allocation_percentage for s in opt.product_selections)
    if abs(pct_total - 100) > PCT_TOLERANCE:
        errors.append(f"Product allocations sum to {pct_total:.4f}%, not 100%.")
    amt_total = sum(s.investment_amount for s in opt.product_selections)
    if abs(amt_total - value) > amount_tol:
        errors.append(f"Product amounts sum to {amt_total:,.2f}, not the eligible value {value:,.2f}.")

    for s in opt.product_selections:
        if s.allocation_percentage <= 0 or s.investment_amount <= 0:
            errors.append(f"{s.product_id}: non-positive allocation.")
        expected = value * s.allocation_percentage / 100
        if abs(expected - s.investment_amount) > amount_tol:
            errors.append(
                f"{s.product_id}: amount {s.investment_amount:,.2f} != {value:,.2f} x {s.allocation_percentage}% "
                f"({expected:,.2f})."
            )

    class_pct = sum(a.allocation_percentage for a in opt.asset_allocation)
    if abs(class_pct - 100) > PCT_TOLERANCE:
        errors.append(f"Asset-class allocations sum to {class_pct:.4f}%, not 100%.")
    class_amt = sum(a.investment_amount for a in opt.asset_allocation)
    if abs(class_amt - value) > amount_tol:
        errors.append(f"Asset-class amounts sum to {class_amt:,.2f}, not {value:,.2f}.")

    by_class: dict[str, float] = {}
    for s in opt.product_selections:
        by_class[s.asset_class] = by_class.get(s.asset_class, 0.0) + s.allocation_percentage
    for a in opt.asset_allocation:
        if abs(by_class.get(a.asset_class, 0.0) - a.allocation_percentage) > PCT_TOLERANCE:
            errors.append(f"Asset class {a.asset_class} does not match the sum of its products.")

    for c in opt.constraint_checks:
        if c.status == "FAIL":
            errors.append(f"Constraint breached: {c.constraint} (limit {c.limit}, actual {c.actual}).")
    return errors
