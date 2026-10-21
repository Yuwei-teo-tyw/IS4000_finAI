"""
Answers chat questions about one stored proposal (the Geneva assistant's
"ask the Portfolio Manager" path).

The LLM sees only facts the engine computed for that proposal - plus the
workspace context the chat sends (picked portfolio, adjusted weights, current
holdings) - with no client identifiers. Its answer must pass the same
guardrails as the proposal narratives: no guarantee / optimality / live-data
/ execution claims, and no number that is not in the facts. Anything else
(no LLM configured, timeout, provider error, a second rejected draft) falls
back to a deterministic answer assembled from the same facts.
"""
import asyncio
import json
import logging
import re
from itertools import combinations
from typing import Any, Callable, Optional

from app.prompts.prompt_builder import get_prompt
from app.agents.portfolio_manager.assumptions import CapitalMarketAssumptions
from app.agents.portfolio_manager.config import Settings
from app.agents.portfolio_manager.engine.adjust import EvaluationError, evaluate_weights
from app.agents.portfolio_manager.engine.comparison import OFFERED
from app.agents.portfolio_manager.explain.guardrails import AllowedNumbers, check_text
from app.agents.portfolio_manager.explain.llm_client import LLMUnavailable, get_llm
from app.agents.portfolio_manager.schemas.adjust import WeightEvaluation
from app.agents.portfolio_manager.schemas.chat import PortfolioAnswer, PortfolioQuestion, WorkspaceContext
from app.agents.portfolio_manager.schemas.response import PortfolioOption, PortfolioResponse

logger = logging.getLogger(__name__)

_OPTION_REF = re.compile(r"\b(?:[Oo]ption|[Pp]ortfolio|[Tt]emplate)\s+([A-F])\b")
_METRIC_KEYS = ("expected_annual_return_pct", "estimated_volatility_pct", "estimated_stress_drawdown_pct",
                "growth_asset_share_pct", "estimated_annual_fee_pct", "high_liquidity_share_pct")
MAX_HISTORY_CHARS = 600
# The prompt fences user text in these tags; user text must not be able to close or forge them.
_FENCE_TAG = re.compile(r"<\s*/?\s*(?:question|chat_history)\s*>", re.I)


def _fenced(text: str) -> str:
    return _FENCE_TAG.sub(" ", text)


# --- facts ---------------------------------------------------------------------

def _offered(p: PortfolioResponse) -> list[PortfolioOption]:
    return [o for o in p.portfolio_options if o.suitability_status in OFFERED]


def _option_facts(o: PortfolioOption) -> dict:
    return {
        "option_id": o.option_id,
        "name": o.option_name,
        "objective": o.objective,
        "status": o.suitability_status,
        "status_explanation": o.suitability_explanation,
        "eligible_portfolio_value": o.eligible_portfolio_value,
        "base_currency": o.base_currency,
        "estimated_risk_level": o.estimated_risk_level,
        "asset_allocation": [a.model_dump() for a in o.asset_allocation],
        "sub_asset_allocation": [s.model_dump() for s in o.sub_asset_allocation],
        "products": [
            {
                "name": s.product_name, "asset_class": s.asset_class, "type": s.product_type,
                "allocation_pct": s.allocation_percentage, "amount": s.investment_amount, "currency": s.currency,
                "expected_return_assumption_pct": s.expected_return_assumption, "management_fee_pct": s.management_fee,
                "liquidity": s.liquidity, "why": s.key_rationale, "key_risks": s.key_risks[:3],
            }
            for s in o.product_selections
        ],
        "metrics": o.metrics.model_dump(exclude={"calculation_notes"}) if o.metrics else None,
        "scenarios": [s.model_dump() for s in o.scenario_analysis],
        "goal_alignment": [g.model_dump() for g in o.goal_alignment],
        "constraint_checks_not_passed": [c.model_dump() for c in o.constraint_checks if c.status != "PASS"],
        "liquidity_assessment": o.liquidity_assessment,
        "diversification_assessment": o.diversification_assessment,
        "advantages": o.advantages,
        "disadvantages": o.disadvantages,
        "key_differences_vs_more_cautious_option": o.key_differences,
        "warnings": o.warnings,
    }


def _differences(offered: list[PortfolioOption], evaluation: Optional[WeightEvaluation]) -> dict:
    """Pre-computed differences the LLM may quote (it must not do its own arithmetic)."""
    out: dict[str, dict[str, float]] = {}
    for a, b in combinations(offered, 2):
        wa = {x.asset_class: x.allocation_percentage for x in a.asset_allocation}
        wb = {x.asset_class: x.allocation_percentage for x in b.asset_allocation}
        d = {f"{ac} (pp)": round(wb.get(ac, 0) - wa.get(ac, 0), 2) for ac in sorted(set(wa) | set(wb))}
        if a.metrics and b.metrics:
            for k in _METRIC_KEYS:
                va, vb = getattr(a.metrics, k), getattr(b.metrics, k)
                if va is not None and vb is not None:
                    d[k] = round(vb - va, 2)
        out[f"{b.option_id} minus {a.option_id}"] = {k: v for k, v in d.items() if v != 0}
    if evaluation:
        d = {f"{ln.asset_class} (pp)": ln.change_pp for ln in evaluation.lines if ln.change_pp}
        for k in ("model_volatility_pct", "model_expected_return_pct", "product_expected_return_pct",
                  "stress_drawdown_pct", "growth_asset_share_pct", "estimated_annual_fee_pct"):
            va, vb = getattr(evaluation.original, k), getattr(evaluation.adjusted, k)
            if va is not None and vb is not None and round(vb - va, 2):
                d[k] = round(vb - va, 2)
        out[f"adjusted minus proposed {evaluation.option_id}"] = d
    return out


def evaluate_workspace(p: PortfolioResponse, ws: Optional[WorkspaceContext], cma: CapitalMarketAssumptions):
    """The IC's adjusted weights re-checked by the engine, or (None, reason-or-None)."""
    if not ws or not ws.selected_option or not ws.adjusted_weights:
        return None, None
    try:
        return evaluate_weights(p, ws.selected_option, ws.adjusted_weights, cma), None
    except EvaluationError as e:
        return None, str(e)


def build_facts(p: PortfolioResponse, ws: Optional[WorkspaceContext], evaluation: Optional[WeightEvaluation],
                evaluation_error: Optional[str]) -> dict:
    """Anonymised facts: no client_id, request_id, residency or account details."""
    offered = _offered(p)
    c = p.client_profile_summary
    mkt = p.market_context_summary
    workspace: dict[str, Any] = {
        "selected_option": ws.selected_option if ws else None,
        "sent_back_to_rm": ws.sent_to_rm if ws else False,
        "current_holdings": [h.model_dump() for h in ws.holdings] if ws else [],
    }
    if evaluation:
        workspace["adjusted_weights"] = {
            "option_id": evaluation.option_id,
            "lines": [ln.model_dump() for ln in evaluation.lines],
            "proposed_point": evaluation.original.model_dump(),
            "adjusted_point": evaluation.adjusted.model_dump(),
            "all_checks_pass": evaluation.valid,
            "checks_not_passed": [ch.model_dump() for ch in evaluation.checks if ch.status != "PASS"],
        }
    elif evaluation_error:
        workspace["adjusted_weights_error"] = evaluation_error
    return {
        "data_provenance": "Market and product data are ILLUSTRATIVE MOCK data; expected and scenario returns are "
                           "illustrative house assumptions, not forecasts or guarantees.",
        "proposal_status": p.status,
        "client": {
            "base_currency": c.base_currency, "risk_appetite": c.risk_appetite, "risk_capacity": c.risk_capacity,
            "risk_tolerance_score": c.risk_tolerance_score, "effective_risk_level": c.effective_risk_level,
            "effective_risk_label": c.effective_risk_label, "effective_risk_basis": c.effective_risk_basis,
            "maximum_acceptable_drawdown_pct": c.maximum_acceptable_drawdown, "goals": c.primary_goals,
            "shortest_goal_horizon_years": c.shortest_goal_horizon_years, "review_trigger": c.review_trigger,
        },
        "liquidity_plan": p.liquidity_plan.model_dump(exclude={"notes"}) if p.liquidity_plan else None,
        "market": {
            "source": mkt.data_source_label, "as_of": str(mkt.as_of) if mkt.as_of else None,
            "cycle_phase": mkt.regime.phase if mkt.regime else None,
            "cycle_confidence": mkt.regime.confidence if mkt.regime else None,
            "recession_prob_12m": mkt.regime.in_recession_prob if mkt.regime else None,
            "key_themes": mkt.key_themes, "risks": mkt.risks, "implications": mkt.implications,
            "long_term_return_assumptions_pct": mkt.long_term_return_assumptions,
        },
        "preferred_option": p.preferred_option,
        "preferred_option_rationale": p.preferred_option_rationale,
        "comparison_summary": p.comparison_summary,
        "comparison_matrix": [r.model_dump() for r in p.comparison_matrix],
        "options": [_option_facts(o) for o in offered],
        "options_not_offered": {
            o.option_id: {"name": o.option_name, "reason": o.suitability_explanation}
            for o in p.portfolio_options if o.suitability_status not in OFFERED
        },
        "workspace": workspace,
        "differences": _differences(offered, evaluation),
        "key_risks": p.key_risks,
        "missing_information": [m.model_dump() for m in p.missing_information],
        "warnings": p.warnings,
    }


def allowed_numbers(facts: dict) -> AllowedNumbers:
    allowed = AllowedNumbers()
    allowed.add_pct(0, 100)
    allowed.add_from_text(json.dumps(facts, default=str))
    return allowed


def options_in(text: str, p: PortfolioResponse) -> list[str]:
    ids = {o.option_id for o in p.portfolio_options}
    return sorted({m.group(1) for m in _OPTION_REF.finditer(text)} & ids)


# --- deterministic answer --------------------------------------------------------

def _pct(v: Optional[float], dp: int = 1) -> str:
    return "not calculated" if v is None else f"{round(v, dp):g}%"


def _amt(v: Optional[float], ccy: Optional[str]) -> str:
    return "not calculated" if v is None else f"{ccy or 'SGD'} {v:,.0f}"


def _label(o: PortfolioOption) -> str:
    return f"**{o.option_id} · {o.option_name}**"


_TOPICS: list[tuple[str, re.Pattern]] = [
    ("not_offered", re.compile(r"not (offered|proposed)|withdrawn|left out|excluded|why not|rejected|missing option", re.I)),
    ("why", re.compile(r"\bwhy\b|prefer|recommend|choose|chosen|pick|best|suit", re.I)),
    ("compare", re.compile(r"compar|differ|versus|\bvs\.?\b|trade-?off", re.I)),
    ("allocation", re.compile(r"allocat|weight|asset class|\bmix\b|split|breakdown|equit|bond|fixed income|\bcash\b|gold|real estate|hedge fund|private market", re.I)),
    ("risk", re.compile(r"risk|drawdown|volatil|stress|downside|lose|loss", re.I)),
    ("return", re.compile(r"return|perform|scenario|yield|grow", re.I)),
    ("fees", re.compile(r"\bfees?\b|cost|charge|expens", re.I)),
    ("products", re.compile(r"product|fund|\betf\b|instrument|security|securities", re.I)),
    ("goals", re.compile(r"goal|retire|education|target|on track|shortfall", re.I)),
    ("liquidity", re.compile(r"liquid|withdraw|reserve|dealing|redeem", re.I)),
    ("market", re.compile(r"market|regime|recession|macro|cycle|inflation|rates?\b", re.I)),
    ("current", re.compile(r"current|existing|today|holdings?|now\b|change", re.I)),
]


def _focus(p: PortfolioResponse, q: str, ws: Optional[WorkspaceContext]) -> Optional[PortfolioOption]:
    offered = {o.option_id: o for o in _offered(p)}
    for oid in options_in(q, p):
        if oid in offered:
            return offered[oid]
    for oid in ((ws.selected_option if ws else None), p.preferred_option):
        if oid and oid in offered:
            return offered[oid]
    return next(iter(offered.values()), None)


def _section(topic: str, p: PortfolioResponse, o: PortfolioOption, ws, evaluation) -> list[str]:
    ccy = o.base_currency
    m = o.metrics
    if topic == "not_offered":
        rest = [x for x in p.portfolio_options if x.suitability_status not in OFFERED]
        if not rest:
            return ["Every template was offered for this client."]
        return ["Not offered for this client:"] + [f"- {x.option_id} · {x.option_name}: {x.suitability_explanation}" for x in rest]
    if topic == "why":
        lines = [f"{_label(o)}: {o.suitability_explanation}"]
        if p.preferred_option == o.option_id:
            lines.append(f"It is the agent's preferred option. {p.preferred_option_rationale}")
        elif p.preferred_option:
            lines.append(f"The agent's preferred option is {p.preferred_option}. {p.preferred_option_rationale}")
        lines += [f"- {s.statement}" for s in o.rationale[:3]]
        return lines
    if topic == "compare":
        lines = [p.comparison_summary] if p.comparison_summary else []
        for x in _offered(p):
            diff = "; ".join(x.key_differences) if x.key_differences else x.objective
            lines.append(f"- {_label(x)}: {diff}")
        return lines
    if topic == "allocation":
        lines = [f"{_label(o)} allocation of {_amt(o.eligible_portfolio_value, ccy)}:"]
        lines += [f"- {a.asset_class}: {_pct(a.allocation_percentage)} ({_amt(a.investment_amount, ccy)})" for a in o.asset_allocation]
        if evaluation and evaluation.option_id == o.option_id:
            moved = [f"{ln.asset_class} {_pct(ln.original_pct)} to {_pct(ln.adjusted_pct)}" for ln in evaluation.lines if ln.change_pp]
            if moved:
                lines.append(f"The Investment Counsellor adjusted the weights: {'; '.join(moved)}. "
                             f"{'All checks pass.' if evaluation.valid else 'Some checks do not pass yet.'}")
        return lines
    if topic == "risk":
        if not m:
            return [f"Risk figures could not be calculated for {_label(o)}."]
        limit = p.client_profile_summary.maximum_acceptable_drawdown
        return [f"{_label(o)} risk: level {o.estimated_risk_level or 'not rated'}, estimated volatility "
                f"{_pct(m.estimated_volatility_pct)} a year, stress drawdown {_pct(m.estimated_stress_drawdown_pct)}"
                + (f" against the client's {_pct(limit)} limit." if limit is not None else ".")]
    if topic == "return":
        lines = [f"{_label(o)} expected return: {_pct(o.expected_portfolio_return, 2)} a year (house assumption, after fees)."]
        lines += [f"- {s.scenario}: {_pct(s.portfolio_return_pct)} ({_amt(s.portfolio_value_change, ccy)})" for s in o.scenario_analysis]
        return lines
    if topic == "fees":
        if not m:
            return [f"Fees could not be calculated for {_label(o)}."]
        return [f"{_label(o)} ongoing fees: {_pct(m.estimated_annual_fee_pct, 2)} a year "
                f"({_amt(m.estimated_annual_fee_amount, ccy)}), plus one-off transaction costs of "
                f"{_amt(m.estimated_one_off_transaction_cost, ccy)}."]
    if topic == "products":
        lines = [f"{_label(o)} holds {len(o.product_selections)} products:"]
        lines += [f"- {s.product_name} ({s.asset_class}): {_pct(s.allocation_percentage)}, {_amt(s.investment_amount, ccy)}"
                  for s in o.product_selections]
        return lines
    if topic == "goals":
        if not o.goal_alignment:
            return ["The client has no dated goals to assess."]
        return [f"{_label(o)} against the client's goals:"] + [f"- {g.goal}: {g.status.replace('_', ' ').lower()}. {g.note}" for g in o.goal_alignment]
    if topic == "liquidity":
        lines = [o.liquidity_assessment]
        if p.liquidity_plan:
            lines.append(f"Eligible to invest after the liquidity carve-out: {_amt(p.liquidity_plan.eligible_portfolio_value, ccy)}.")
        return lines
    if topic == "market":
        r = p.market_context_summary.regime
        head = (f"Market context ({p.market_context_summary.data_source_label}): cycle phase {r.phase or 'unknown'}, "
                f"confidence {r.confidence}.") if r else "No market regime was available for this proposal."
        return [head] + [f"- {t}" for t in p.market_context_summary.key_themes[:3]]
    if topic == "current":
        changes = [a for a in o.asset_allocation if a.change_from_current_pp]
        lines = []
        if ws and ws.holdings:
            lines.append("Current holdings: " + "; ".join(f"{h.name} {_pct(h.weight_pct)}" for h in ws.holdings[:8]) + ".")
        if changes:
            lines.append(f"Moving to {_label(o)} changes:")
            lines += [f"- {a.asset_class}: {'+' if a.change_from_current_pp > 0 else ''}{round(a.change_from_current_pp, 1):g} pp" for a in changes]
        return lines or ["The current allocation was not provided, so changes cannot be shown."]
    return []


def deterministic_answer(p: PortfolioResponse, q: PortfolioQuestion, evaluation: Optional[WeightEvaluation]) -> str:
    ws = q.workspace
    offered = _offered(p)
    if not offered:
        missing = "; ".join(f"{m.field} ({m.severity.lower()})" for m in p.missing_information[:4])
        return (f"The Portfolio Manager could not offer any portfolio for this client (status {p.status}). "
                + (f"Information still needed: {missing}." if missing else p.preferred_option_rationale))
    o = _focus(p, q.question, ws)
    topics = [t for t, rx in _TOPICS if rx.search(q.question)][:3]
    if not topics:
        names = ", ".join(_label(x) for x in offered)
        lines = [f"The Portfolio Manager proposed {len(offered)} portfolio{'s' if len(offered) != 1 else ''}: {names}."]
        if p.preferred_option:
            lines.append(f"Preferred: {p.preferred_option}. {p.preferred_option_rationale}")
        if ws and ws.selected_option:
            lines.append(f"The Investment Counsellor selected portfolio {ws.selected_option}"
                         + (" and sent it back to the RM." if ws.sent_to_rm else "."))
        topics_lines = lines
    else:
        topics_lines = []
        for t in topics:
            topics_lines += _section(t, p, o, ws, evaluation)
    return "\n".join(x for x in topics_lines if x)


# --- LLM answer ---------------------------------------------------------------------

def _history_text(q: PortfolioQuestion) -> str:
    if not q.history:
        return "None."
    return "\n".join(f"Q: {_fenced(t.question[:MAX_HISTORY_CHARS])}\nA: {_fenced(t.answer[:MAX_HISTORY_CHARS])}"
                     for t in q.history)


def _content(raw: Any) -> str:
    content = getattr(raw, "content", raw)
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content or "").strip()


async def answer_question(
    p: PortfolioResponse,
    q: PortfolioQuestion,
    settings: Settings,
    cma: CapitalMarketAssumptions,
    llm_factory: Callable[[Settings], Any] = get_llm,
) -> PortfolioAnswer:
    evaluation, evaluation_error = evaluate_workspace(p, q.workspace, cma)

    def fallback(attempted: bool, detail: str) -> PortfolioAnswer:
        text = deterministic_answer(p, q, evaluation)
        return PortfolioAnswer(
            request_id=p.request_id, answer=text,
            source="DETERMINISTIC_FALLBACK" if attempted else "DETERMINISTIC",
            model=settings.llm_model if attempted else None, detail=detail,
            options_referenced=options_in(text, p),
        )

    try:
        llm = llm_factory(settings)
    except LLMUnavailable as e:
        return fallback(False, f"LLM not used: {e} Answer assembled from the computed proposal.")

    facts = build_facts(p, q.workspace, evaluation, evaluation_error)
    allowed = allowed_numbers(facts)
    messages = [
        ("system", get_prompt("portfolio_manager.chat_system")),
        ("human", get_prompt("portfolio_manager.chat_user", facts_json=json.dumps(facts, default=str),
                             history=_history_text(q), question=_fenced(q.question))),
    ]
    problems: list[str] = []
    for _attempt in range(2):  # one retry, told what was wrong
        try:
            raw = await asyncio.wait_for(llm.ainvoke(messages), timeout=settings.llm_timeout_seconds)
        except asyncio.TimeoutError:
            return fallback(True, "LLM call timed out; answer assembled from the computed proposal instead.")
        except Exception as e:  # provider/network errors
            logger.warning("Portfolio chat LLM call failed: %s", type(e).__name__)
            return fallback(True, f"LLM call failed ({type(e).__name__}); answer assembled from the computed proposal instead.")
        text = _content(raw)
        problems = check_text(text, allowed) if text else ["empty answer"]
        if not problems:
            return PortfolioAnswer(
                request_id=p.request_id, answer=text, source="LLM", model=settings.llm_model,
                detail="Written by the LLM from the computed proposal and checked: every number appears in the "
                       "proposal, and no guarantee, optimality, live-data or execution claims.",
                options_referenced=options_in(text, p),
            )
        messages += [("ai", text), ("human", "Your answer failed validation: " + "; ".join(sorted(set(problems))[:5])
                                    + ". Answer again using only numbers that appear in the facts, without those claims.")]
    return fallback(True, "LLM answer rejected by validation ("
                    + "; ".join(sorted(set(problems))[:3]) + "); answer assembled from the computed proposal instead.")
