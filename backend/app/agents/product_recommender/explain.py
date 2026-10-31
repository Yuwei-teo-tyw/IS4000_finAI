"""
Reasons for each shortlisted product.

The deterministic reason is built only from the role plan, the gate result,
the house view and the agent view, so every statement is traceable. Each
bullet ends in a citation tag: the house-view page (HV-...) or the product
id (its factsheet).

`llm_reasons` rewrites the shortlist's reasons with the LLM, from the same
facts, with the deterministic bullets as its draft. A product whose LLM text
fails the guardrail keeps its deterministic reason. The fee line is always
added by code, so the LLM never writes about fees.
"""
import re
from typing import Callable

from pydantic import BaseModel, Field

from app.agents.portfolio_agent.explain.llm_client import get_llm
from app.agents.portfolio_agent.schemas.response import ExplanationStatus
from app.agents.product_recommender import guardrails, llm
from app.agents.product_recommender.config import Settings
from app.agents.product_recommender.ranking import Ranked
from app.agents.product_recommender.roles import ROLE_LABELS
from app.agents.product_recommender.schemas import HouseView, Reason, RecommendResponse

_ADJUSTED = {"softened": "softens it to Hold", "upgraded": "raises it to Buy", "downgraded": "lowers it to Sell"}


def role_line(r: Ranked, role_why: str) -> str:
    pid = r.sp.product_id
    # Not why_buy: shelf copy can mention cost, which a product reason never may.
    what = r.sp.product.sub_asset_class or r.sp.product.product_type or r.sp.asset_class.value
    if r.passed_from:
        lead = (f"Takes a {ROLE_LABELS[r.passed_from]} slot no eligible product could fill, as "
                f"{ROLE_LABELS[r.role]}")
    else:
        lead = f"Fills a {ROLE_LABELS[r.role]} slot ({role_why})"
    return f"{lead}: {what.rstrip('.')} [{pid}]."


def deterministic_reason(r: Ranked, hv: HouseView, level: int | None, base_currency: str | None,
                         role_why: str = "", stance=None) -> Reason:
    prod = r.sp.product
    pid = prod.product_id
    view = hv.for_class(r.sp.asset_class.value)
    lines: list[str] = [role_line(r, role_why)]

    if prod.risk_rating is not None and level:
        where = "at" if prod.risk_rating == level else "within"
        lines.append(f"Risk {prod.risk_rating} of 5 is {where} the client's limit of {level} [{pid}].")
    if view is not None:
        cio = view.cio_term if view.basis == "rated" else f"{view.view} (read from the report, not a stated rating)"
        if stance is not None and stance.adjustment in _ADJUSTED:
            lines.append(f"The CIO house view on {view.asset_class.lower()} is {cio}; the agent view starts from it and "
                         f"current market data {_ADJUSTED[stance.adjustment]} [{view.citation_id}].")
        else:
            lines.append(f"The CIO house view on {view.asset_class.lower()} is {cio} [{view.citation_id}].")
    dealing = (prod.liquidity or "unknown").replace("_", " ").lower()
    if base_currency and r.sp.is_foreign_unhedged(base_currency):
        currency = f"unhedged {prod.currency}, so it carries currency risk for a {base_currency} client"
    elif prod.currency_hedged:
        currency = f"hedged to {base_currency or prod.currency}"
    else:
        currency = f"in {prod.currency}"
    lines.append(f"{dealing.capitalize()} dealing, {currency} [{pid}].")
    lines.append(fee_line(pid))

    citations = sorted({pid} | ({view.citation_id} if view else set()))
    return Reason(text=_bullets(lines), source="deterministic", citations=citations)


def fee_line(pid: str) -> str:
    return f"The fee is shown for information only and was not used to rank this product [{pid}]."


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"• {line}" for line in lines)


# --- LLM layer ---------------------------------------------------------------

class ProductReasonOut(BaseModel):
    product_id: str
    bullets: list[str] = Field(min_length=3, max_length=5)


class ReasonsOut(BaseModel):
    reasons: list[ProductReasonOut]


_STOP_BEFORE_TAGS = re.compile(r"\.\s*((?:\[[A-Za-z0-9-]+\]\s*)+)\.?$")


def _clean(bullet: str) -> str:
    """One bullet as '... [TAG].': no bullet character, and the full stop after the tags, not before."""
    line = guardrails.normalise(bullet).lstrip("•-* ").strip()
    line = _STOP_BEFORE_TAGS.sub(lambda m: f" {m.group(1).strip()}.", line)
    return line if line.endswith(".") else f"{line}."


def reasons_facts(resp: RecommendResponse) -> dict:
    """Everything the LLM may say, and nothing else: no client id or name, no scores, no fees."""
    c = resp.client_summary
    products = []
    for s in resp.shortlist:
        p = s.product
        hv = resp.house_view.for_class(p.asset_class)
        draft = [line.removeprefix("• ") for line in s.reason.text.splitlines()]
        products.append({
            "product_id": p.product_id, "product_name": p.product_name, "role": s.role, "asset_class": p.asset_class,
            "sub_asset_class": p.sub_asset_class, "product_type": p.product_type, "risk_rating": p.risk_rating,
            "dealing": p.liquidity, "lock_in_period": p.lock_in_period, "currency": p.currency,
            "currency_hedged": p.currency_hedged, "why_buy": p.why_buy, "suitability_note": p.suitability_note,
            "gate_notes": s.notes,
            "house_view": hv and {"cio_term": hv.cio_term, "basis": hv.basis, "citation_id": hv.citation_id,
                                  "rationale": hv.rationale},
            "allowed_citations": s.reason.citations,
            "draft_bullets": [d for d in draft if d != fee_line(p.product_id)],
        })
    return {
        "client": {"risk_level": c.risk_level, "risk_category": c.risk_category, "objective": c.objective,
                   "shortest_horizon_years": c.shortest_horizon_years, "base_currency": c.base_currency},
        "is_illustrative": resp.is_illustrative,
        "products": products,
    }


async def llm_reasons(resp: RecommendResponse, settings: Settings,
                      llm_factory: Callable = get_llm) -> tuple[RecommendResponse, ExplanationStatus]:
    """The response with LLM-written reasons where they pass the guardrail; ranking and membership unchanged."""
    if not resp.shortlist:
        status = llm.deterministic_status("Nothing was shortlisted, so no reasons were written.", settings)
        return resp.model_copy(update={"explanation_status": status}), status
    facts = reasons_facts(resp)
    by_id = {s.product.product_id: s for s in resp.shortlist}
    names = {pid: s.product.product_name for pid, s in by_id.items()}
    allowed = {f["product_id"]: guardrails.numbers_in(str(f) + str(facts["client"])) for f in facts["products"]}

    def check(out: ReasonsOut):
        ok, bad = {}, {}
        for r in out.reasons:
            s = by_id.get(r.product_id)
            if s is None or r.product_id in ok:
                continue
            others = [n for pid, n in names.items() if pid != r.product_id]
            lines = [_clean(b) for b in r.bullets]
            problems = [f"{p} in '{line[:60]}'" for line in lines
                        for p in guardrails.check_bullet(line, r.product_id, set(s.reason.citations),
                                                         allowed[r.product_id], others)]
            if problems:
                bad[r.product_id] = problems
            else:
                ok[r.product_id] = lines
        for pid in by_id.keys() - ok.keys() - bad.keys():
            bad[pid] = ["no reason was returned"]
        return ok, bad

    res = await llm.write(ReasonsOut, "reasons", facts, list(by_id), check, settings, llm_factory, trace_id=resp.request_id)
    shortlist = [
        s.model_copy(update={"reason": Reason(text=_bullets([*res.accepted[s.product.product_id], fee_line(s.product.product_id)]),
                                              source="llm", citations=s.reason.citations)})
        if s.product.product_id in res.accepted else s
        for s in resp.shortlist
    ]
    return resp.model_copy(update={"shortlist": shortlist, "explanation_status": res.status}), res.status
