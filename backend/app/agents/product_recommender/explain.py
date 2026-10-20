"""
Reasons for each shortlisted product.

The deterministic reason is built only from the gate result, the score
components and the house view, so every statement is traceable. Each
bullet ends in a citation tag: the house-view page (HV-...) or the product
id (its factsheet). An LLM rewording layer can sit on top later; it must
fall back to this text whenever its output fails the guardrail.
"""
from app.agents.product_recommender.ranking import Objective, Ranked
from app.agents.product_recommender.schemas import HouseView, Reason

_OBJECTIVE_TEXT = {
    "income": "an income objective",
    "preservation": "a capital preservation objective",
    "growth": "a growth objective",
    "legacy": "a long-term legacy objective",
    "balanced": "a balanced objective",
}


def deterministic_reason(r: Ranked, hv: HouseView, objective: Objective, level: int | None,
                         base_currency: str | None) -> Reason:
    prod = r.sp.product
    pid = prod.product_id
    view = hv.for_class(r.sp.asset_class.value)
    lines: list[str] = []

    if prod.risk_rating is not None and level:
        where = "at" if prod.risk_rating == level else "within"
        lines.append(f"Risk {prod.risk_rating} of 5 is {where} the client's limit of {level} [{pid}].")
    if view is not None:
        stance = view.cio_term if view.basis == "rated" else f"{view.view} (read from the report, not a stated rating)"
        lines.append(f"The CIO house view on {view.asset_class.lower()} is {stance} [{view.citation_id}].")
    if r.components.get("objective_fit", 0) >= 5:
        why = getattr(prod, "why_buy", None) or prod.sub_asset_class or prod.asset_class
        lines.append(f"Fits {_OBJECTIVE_TEXT[objective]}: {why.rstrip('.')} [{pid}].")
    dealing = (prod.liquidity or "unknown").replace("_", " ").lower()
    if base_currency and r.sp.is_foreign_unhedged(base_currency):
        currency = f"unhedged {prod.currency}, so it carries currency risk for a {base_currency} client"
    elif prod.currency_hedged:
        currency = f"hedged to {base_currency or prod.currency}"
    else:
        currency = f"in {prod.currency}"
    lines.append(f"{dealing.capitalize()} dealing, {currency} [{pid}].")
    lines.append(f"The fee is shown for information only and was not used to rank this product [{pid}].")

    citations = sorted({pid} | ({view.citation_id} if view else set()))
    return Reason(text="\n".join(f"• {line}" for line in lines), source="deterministic", citations=citations)
