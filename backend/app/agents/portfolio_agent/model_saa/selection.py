"""
Suitability framework: evaluate every model in a bucket's library against one client and rank them.

Hard checks (any one makes a model unsuitable):
  1. risk level above the client's risk ceiling (IPS risk score, capped by the product risk limit);
  2. minimum horizon longer than the bucket's horizon;
  3. growth share above the cap for the client's risk level (library framework).
An asset class the client excludes is not a hard fail: the agent's recommended weights drop it and
spread its weight pro rata over the model's other classes, and say so.

Suitable models are scored out of 100 with the library's criterion weights:
  risk_alignment       full marks at the client's risk level, minus 1/4 per level below it;
  objective_alignment  share of the client's objectives for this bucket the model is built for;
  horizon_fit          full marks when the horizon exceeds the model's minimum by `horizon_comfort_years`;
  loss_tolerance       full marks when the model's recession-scenario loss is within the stated loss tolerance;
  liquidity_fit        lower illiquid share (hedge funds, private markets) scores higher.
An unknown input gives half marks on that criterion and is reported, so missing data never looks like a fit.
Market views and holdings are context only and never change the score.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.agents.portfolio_agent.model_saa.library import Library, ModelSaa, SaaBucket
from app.agents.portfolio_agent.model_saa.schemas import (
    Alternative, ClientContext, CriterionScore, Metrics, ModelEvaluation, Recommendation, WeightCheck,
)

_ASSUMPTIONS = Path(__file__).resolve().parent.parent / "assumptions" / "capital_market_assumptions.json"
CRITERION_LABEL = {"risk_alignment": "Risk alignment", "objective_alignment": "Objective alignment", "horizon_fit": "Horizon fit",
                   "loss_tolerance": "Loss tolerance", "liquidity_fit": "Liquidity"}
OBJECTIVE_LABEL = {"preservation": "capital preservation", "income": "income", "growth": "growth",
                   "inflation_protection": "protection against inflation", "transfer": "wealth transfer", "philanthropy": "philanthropy"}
_TAGS = {
    "preservation": r"\bsafe|safety|preserv|protect|risk[- ]averse|capital protection|stable|stability|avoid(?:ing)? loss",
    "income": r"\bincome|yield|dividend|coupon|cash ?flow|payout|steady",
    "growth": r"\bgrow|growth|apprecia|build (?:up )?wealth|reach\b",
    "inflation_protection": r"inflation|purchasing power|real value",
    "transfer": r"\bchild|children|heir|inherit|estate|legacy|grandchild|next generation|succession|family wealth|trust for",
    "philanthropy": r"charit|philanthrop|foundation|donat",
}
_LEGACY_RX = re.compile(_TAGS["transfer"] + "|" + _TAGS["philanthropy"], re.I)


@lru_cache(maxsize=1)
def _assumptions() -> dict:
    try:
        return json.loads(_ASSUMPTIONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def metrics(lib: Library, weights: dict[str, float]) -> Metrics:
    a = _assumptions()
    lt = a.get("long_term_expected_return") or {}
    rec = next((s for s in a.get("scenarios") or [] if s.get("uses_recession_probability")), None)
    known = all(k in lt for k in weights)

    def wsum(table: dict) -> Optional[float]:
        return round(sum(w * float(table[k]) for k, w in weights.items()) / 100, 2) if known and all(k in table for k in weights) else None
    return Metrics(growth_share_pct=lib.growth_share(weights), illiquid_share_pct=lib.illiquid_share(weights),
                   long_term_return_pct=wsum(lt) if lt else None,
                   recession_return_pct=wsum(rec["asset_class_returns"]) if rec else None,
                   assumptions_label=a.get("label"))


def tags_in(text: str) -> set[str]:
    return {t for t, rx in _TAGS.items() if re.search(rx, text or "", re.I)}


def bucket_objectives(ctx: ClientContext, bucket: SaaBucket) -> tuple[list[str], str]:
    """Client objectives for this bucket, from the IPS goals, targets and investment approach."""
    goals = ctx.goals + [t["text"] for t in ctx.targets if t.get("text")]
    legacy_lines = [g for g in goals if _LEGACY_RX.search(g)]
    approach = " ".join(x for x in (ctx.approach, ctx.believes) if x)
    growth_target = any((t.get("amount") or 0) > (ctx.total_wealth or float("inf")) for t in ctx.targets)
    if bucket == "longevity":
        lines = [g for g in goals if g not in legacy_lines]
        tags = tags_in(" ".join(lines + [approach])) - {"transfer", "philanthropy"}
        if growth_target:
            tags.add("growth")
        basis = "IPS goals, targets and investment approach" if (lines or approach) else "none stated in the IPS"
    else:
        tags = tags_in(" ".join(legacy_lines + [approach]))
        tags.add("transfer")  # the purpose of the Legacy bucket itself
        basis = ("IPS legacy goals and investment approach" if legacy_lines
                 else "no legacy goal is stated in the IPS; the client's investment approach and the Legacy bucket's purpose (wealth transfer) are used")
    order = ["preservation", "income", "growth", "inflation_protection", "transfer", "philanthropy"]
    return [t for t in order if t in tags], basis


def bucket_horizon(ctx: ClientContext, bucket: SaaBucket) -> tuple[Optional[float], str]:
    """Longevity: the nearest dated non-legacy target, else the IPS horizon. Legacy: a dated legacy target, else the IPS horizon."""
    dated = [t for t in ctx.targets if isinstance(t.get("horizon_years"), (int, float)) and t["horizon_years"] > 0]
    pick = [t for t in dated if bool(_LEGACY_RX.search(t.get("text") or "")) == (bucket == "legacy")]
    if pick:
        t = min(pick, key=lambda x: x["horizon_years"])
        return float(t["horizon_years"]), f"dated target in the IPS: {t['text']} ({t['horizon_years']:g} years)"
    if ctx.horizon_years is not None:
        return ctx.horizon_years, f"the client's investment horizon in the IPS: {ctx.horizon_text}"
    return None, "no investment horizon is stated in the IPS"


def agent_weights(model: ModelSaa, excluded: list[str]) -> tuple[dict[str, float], list[str]]:
    """The model's weights with client-excluded asset classes removed and spread pro rata over the rest."""
    drop = {k: v for k, v in model.weights.items() if k in excluded and v > 0}
    if not drop:
        return dict(model.weights), []
    keep = {k: v for k, v in model.weights.items() if k not in drop}
    base = sum(keep.values())
    out = {k: round(v * 100 / base, 2) for k, v in keep.items()}
    top = max(out, key=out.get)
    out[top] = round(out[top] + 100 - sum(out.values()), 2)
    notes = [f"{k} ({v:g}%) removed because the IPS excludes it; its weight is spread pro rata over the other classes." for k, v in drop.items()]
    return out, notes


def _criteria(lib: Library, m: ModelSaa, ctx: ClientContext, horizon: Optional[float], objectives: list[str], weights: dict[str, float]) -> list[CriterionScore]:
    fw = lib.framework
    W = fw.weights
    out = []
    level = ctx.risk_level
    if level is None:
        out.append(CriterionScore(criterion="risk_alignment", label=CRITERION_LABEL["risk_alignment"], score=W["risk_alignment"] / 2, max=W["risk_alignment"],
                                  detail="Client risk level unknown: half marks."))
    else:
        s = W["risk_alignment"] * max(0.0, 1 - (level - m.risk_level) / 4)
        out.append(CriterionScore(criterion="risk_alignment", label=CRITERION_LABEL["risk_alignment"], score=s, max=W["risk_alignment"],
                                  detail=f"Model risk level {m.risk_level} against the client's {level}" + ("" if m.risk_level == level else f": {level - m.risk_level} below.")))
    if objectives:
        hit = [o for o in objectives if o in m.objectives]
        s = W["objective_alignment"] * len(hit) / len(objectives)
        out.append(CriterionScore(criterion="objective_alignment", label=CRITERION_LABEL["objective_alignment"], score=s, max=W["objective_alignment"],
                                  detail=f"Built for {len(hit)} of the client's {len(objectives)} objectives" + (f" ({', '.join(OBJECTIVE_LABEL[o] for o in hit)})" if hit else "") + "."))
    else:
        out.append(CriterionScore(criterion="objective_alignment", label=CRITERION_LABEL["objective_alignment"], score=W["objective_alignment"] / 2, max=W["objective_alignment"],
                                  detail="No objective stated: half marks."))
    if horizon is None:
        out.append(CriterionScore(criterion="horizon_fit", label=CRITERION_LABEL["horizon_fit"], score=W["horizon_fit"] / 2, max=W["horizon_fit"], detail="Horizon unknown: half marks."))
    else:
        s = W["horizon_fit"] * max(0.0, min(1.0, (horizon - m.min_horizon_years) / fw.horizon_comfort_years))
        out.append(CriterionScore(criterion="horizon_fit", label=CRITERION_LABEL["horizon_fit"], score=s, max=W["horizon_fit"],
                                  detail=f"Needs {m.min_horizon_years:g} years; the bucket has {horizon:g}."))
    mt = metrics(lib, weights)
    if ctx.loss_tolerance_pct is None or mt.recession_return_pct is None:
        out.append(CriterionScore(criterion="loss_tolerance", label=CRITERION_LABEL["loss_tolerance"], score=W["loss_tolerance"] / 2, max=W["loss_tolerance"],
                                  detail="Loss tolerance not stated (or scenario unavailable): half marks." if ctx.loss_tolerance_pct is None else "Recession scenario unavailable: half marks."))
    else:
        loss, tol = max(0.0, -mt.recession_return_pct), ctx.loss_tolerance_pct
        s = W["loss_tolerance"] * (1.0 if loss <= tol else max(0.0, 1 - (loss - tol) / tol))
        out.append(CriterionScore(criterion="loss_tolerance", label=CRITERION_LABEL["loss_tolerance"], score=s, max=W["loss_tolerance"],
                                  detail=f"Recession scenario {mt.recession_return_pct:+.1f}% against a stated tolerance of -{tol:g}%."))
    il = lib.illiquid_share(weights)
    s = W["liquidity_fit"] * max(0.0, 1 - il / fw.max_illiquid_pct)
    out.append(CriterionScore(criterion="liquidity_fit", label=CRITERION_LABEL["liquidity_fit"], score=s, max=W["liquidity_fit"],
                              detail=f"{il:g}% in hedge funds and private markets (limit {fw.max_illiquid_pct:g}%)."))
    return [c.model_copy(update={"score": round(c.score, 1)}) for c in out]


def evaluate(lib: Library, bucket: SaaBucket, ctx: ClientContext) -> tuple[list[ModelEvaluation], Optional[float], list[str]]:
    horizon, _ = bucket_horizon(ctx, bucket)
    objectives, _ = bucket_objectives(ctx, bucket)
    evals: list[ModelEvaluation] = []
    for m in lib.bucket(bucket).models:
        weights, _notes = agent_weights(m, ctx.excluded_asset_classes)
        reasons = []
        if ctx.risk_level is not None and m.risk_level > ctx.risk_level:
            reasons.append(f"Risk level {m.risk_level} is above the client's risk level {ctx.risk_level}.")
        if horizon is not None and m.min_horizon_years > horizon:
            reasons.append(f"Needs at least {m.min_horizon_years:g} years; the {lib.bucket(bucket).label} horizon is {horizon:g} years.")
        for ac, cap in ctx.asset_class_caps.items():
            if weights.get(ac, 0) > cap + 1e-9:
                reasons.append(f"{ac} {weights[ac]:g}% is above the client's stated maximum of {cap:g}%.")
        if ctx.risk_level is not None and lib.growth_share(weights) > lib.growth_cap(ctx.risk_level) + 1e-9:
            reasons.append(f"Growth assets {lib.growth_share(weights):g}% exceed the {lib.growth_cap(ctx.risk_level):g}% cap for risk level {ctx.risk_level}.")
        crit = _criteria(lib, m, ctx, horizon, objectives, weights) if not reasons else []
        evals.append(ModelEvaluation(
            model_id=m.id, model_name=m.name, risk_level=m.risk_level, strategy_code=m.strategy_code, purpose=m.purpose, rationale=m.rationale,
            objectives=m.objectives, min_horizon_years=m.min_horizon_years, weights=dict(m.weights), suitable=not reasons, unsuitable_reasons=reasons,
            score=round(sum(c.score for c in crit), 1) if crit else None, criteria=crit, metrics=metrics(lib, weights)))
    ranked = sorted([e for e in evals if e.suitable], key=lambda e: (-(e.score or 0), -e.risk_level))
    for i, e in enumerate(ranked, 1):
        e.rank = i
    return evals, horizon, objectives


def _why_not(best: ModelEvaluation, alt: ModelEvaluation) -> list[str]:
    b = {c.criterion: c for c in best.criteria}
    out = []
    for c in alt.criteria:
        gap = b[c.criterion].score - c.score
        if gap > 0.4:
            out.append(f"{c.label}: {c.score:g} of {c.max:g} against {b[c.criterion].score:g} for {best.model_id}. {c.detail}")
    return out or [f"Scores {alt.score:g} against {best.score:g} overall; the difference is spread across the criteria."]


def holdings_lines(ctx: ClientContext, bucket: SaaBucket, weights: dict[str, float]) -> list[str]:
    hv = ctx.holdings
    if not hv.available:
        return [hv.message or "Holdings are unavailable."]
    cur = (hv.by_bucket.get(bucket) or {}).get("classes")
    if not cur:
        return [f"No priced holdings are held in the {bucket.title()} bucket yet, so the full allocation will be new money."]
    groups = {"Cash": ["Cash"], "Fixed Income": ["Fixed income"], "Equities": ["Equities"], "Alternatives": ["Hedge funds", "Private markets", "Real estate", "Gold"]}
    out = []
    for g, classes in groups.items():
        rec = round(sum(weights.get(c, 0) for c in classes), 1)
        held = cur.get(g, 0.0)
        if rec or held:
            d = round(rec - held, 1)
            out.append(f"{g}: held {held:g}% of the bucket, recommended {rec:g}% ({'+' if d > 0 else ''}{d:g}pp).")
    return out


def market_lines(market, weights: dict[str, float]) -> list[str]:
    if market.status == "UNAVAILABLE":
        return ["Market Analysis Agent output is unavailable, so no market considerations are included."]
    out = []
    if market.regime_phase:
        out.append(f"Market regime: {market.regime_phase.replace('_', ' ')} (confidence {market.regime_confidence or 'not stated'}), as of {market.as_of or market.generated_at}.")
    rel = {"duration": "Fixed income", "credit": "Fixed income", "equities": "Equities"}
    for k, txt in (market.implications or {}).items():
        if weights.get(rel.get(k, ""), 0) > 0:
            out.append(f"{rel[k]} ({weights[rel[k]]:g}%): {txt}")
    out += market.risks[:2]
    out.append("Market views inform this note only; they did not change the ranking, which follows client suitability.")
    return out


def ranked_suitable(evals: list[ModelEvaluation]) -> list[ModelEvaluation]:
    return sorted([e for e in evals if e.suitable], key=lambda e: e.rank or 99)


def no_recommendation(lib: Library, bucket: SaaBucket, ctx: ClientContext, evals: list[ModelEvaluation]) -> Optional[str]:
    """Why no model can be recommended, or None when the LLM / scoring may choose."""
    if not ctx.has_ips_data:
        return ("The client has no completed IPS from the Client Profiling Agent, so there is no profile to match a model against. "
                "The RM must complete and send the IPS first.")
    if ctx.risk_level is None:
        return "The IPS has no risk score and the client book has no product risk limit, so no model can be checked against the client's risk level."
    if not ranked_suitable(evals):
        why = sorted({r for e in evals for r in e.unsuitable_reasons})
        return ("No model in the " + lib.bucket(bucket).label + " library suits this client: " + " ".join(why[:4])
                + " The PM can amend the closest model, or the library needs a suitable model.")
    return None


def recommend(lib: Library, bucket: SaaBucket, ctx: ClientContext, evals: list[ModelEvaluation], horizon: Optional[float],
              objectives: list[str], market, pick=None, llm_note: Optional[str] = None,
              llm_model: Optional[str] = None) -> tuple[Optional[Recommendation], Optional[str]]:
    """`pick` (llm_pick.LlmPick): the LLM's guarded choice among the suitable models; None keeps the scored pick."""
    none_why = no_recommendation(lib, bucket, ctx, evals)
    if none_why:
        return None, none_why
    ranked = ranked_suitable(evals)
    best = next((e for e in ranked if pick and e.model_id == pick.model_id), ranked[0])
    m = lib.model(bucket, best.model_id)
    weights, notes = agent_weights(m, ctx.excluded_asset_classes)
    reasons = [f"{c.label} ({c.score:g}/{c.max:g}): {c.detail}" for c in sorted(best.criteria, key=lambda c: -c.score / c.max)]
    factors = []
    if ctx.risk_level is not None:
        factors.append(f"Risk level {ctx.risk_level} of 5 ({ctx.risk_level_basis}).")
    if ctx.risk_tolerance:
        factors.append(f"Risk tolerance: {ctx.risk_tolerance}")
    factors.append(f"Horizon: {horizon:g} years." if horizon is not None else "Horizon: not stated in the IPS.")
    factors.append("Objectives: " + (", ".join(OBJECTIVE_LABEL[o] for o in objectives) or "not stated") + ".")
    if ctx.restrictions:
        factors.append(f"Restrictions: {ctx.restrictions}" + ("" if ctx.excluded_asset_classes else " (sector or issuer screens, applied when choosing products)."))
    if ctx.asset_class_caps:
        factors.append("Stated allocation limits: " + ", ".join(f"{k} at most {c:g}%" for k, c in ctx.asset_class_caps.items()) + ".")
    if ctx.excluded_asset_classes:
        factors.append("Excluded asset classes: " + ", ".join(ctx.excluded_asset_classes) + ".")
    amt = ctx.three_l.get(bucket)
    if amt and amt.amount:
        factors.append(f"{lib.bucket(bucket).label} amount: S${amt.amount:,.0f} ({amt.pct:g}% of S${ctx.total_wealth:,.0f}).")
    mt = metrics(lib, weights)
    risks = [f"Growth assets are {mt.growth_share_pct:g}% of the bucket; equity markets can fall sharply."]
    if mt.recession_return_pct is not None:
        risks.append(f"In the recession scenario of the house assumptions the bucket returns {mt.recession_return_pct:+.1f}% over 12 months (illustrative).")
    if mt.illiquid_share_pct:
        risks.append(f"{mt.illiquid_share_pct:g}% is in less liquid assets (hedge funds, private markets) that may not be sold quickly.")
    if horizon is not None and horizon - m.min_horizon_years < lib.framework.horizon_comfort_years:
        risks.append(f"The horizon ({horizon:g} years) is close to the model's minimum ({m.min_horizon_years:g} years).")
    if ctx.missing:
        risks.append("Missing client information lowers confidence: " + ", ".join(ctx.missing) + ".")
    others = [a for a in ranked if a.model_id != best.model_id][:3 if pick else 2]
    alts = [Alternative(model_id=a.model_id, model_name=a.model_name, score=a.score or 0,
                        why_not=(pick.alternatives.get(a.model_id) if pick else None) or _why_not(best, a)) for a in others]
    fit = (f"is the only {lib.bucket(bucket).label} model that passes the client's constraints" if len(ranked) == 1
           else f"is the best fit of {len(ranked)} suitable {lib.bucket(bucket).label} models")
    summary = f"{best.model_id} {best.model_name} {fit} (score {best.score:g}/100). {m.purpose}"
    if pick:
        rank_note = f"Rule-based fit {best.score:g}/100, rank {best.rank} of {len(ranked)}."
        summary, reasons, risks = pick.summary, [*pick.reasons, rank_note], [*pick.risks, *risks]
    return Recommendation(
        decided_by="llm" if pick else "rules", llm_model=llm_model if pick else None, llm_note=llm_note,
        model_id=best.model_id, model_name=best.model_name, strategy_code=m.strategy_code, score=best.score or 0,
        model_weights=dict(m.weights), recommended_weights=weights, weight_adjustments=notes, summary=summary, reasons=reasons,
        client_factors=factors, market_considerations=market_lines(market, weights), risks=risks,
        existing_holdings=holdings_lines(ctx, bucket, weights), alternatives=alts), None


def check_weights(lib: Library, bucket: SaaBucket, ctx: ClientContext, model: ModelSaa, weights: dict[str, float]) -> list[WeightCheck]:
    fw = lib.framework
    total = round(sum(weights.values()), 2)
    out = [WeightCheck(id="total", label="Weights add to 100%", status="PASS" if abs(total - 100) <= 0.01 else "FAIL", detail=f"Total {total:g}%.")]
    bad = [k for k, v in weights.items() if v < 0 or v > 100]
    out.append(WeightCheck(id="range", label="Each weight between 0 and 100%", status="FAIL" if bad else "PASS", detail=", ".join(bad) or "All in range."))
    unknown = [k for k in weights if k not in lib.asset_classes]
    out.append(WeightCheck(id="classes", label="Known asset classes", status="FAIL" if unknown else "PASS", detail=", ".join(unknown) or "All recognised."))
    over = [f"{k} {weights[k]:g}% (client maximum {c:g}%)" for k, c in ctx.asset_class_caps.items() if weights.get(k, 0) > c + 1e-9]
    out.append(WeightCheck(id="caps", label="Client's stated allocation limits", status="FAIL" if over else "PASS",
                           detail=("Above the stated maximum: " + ", ".join(over) + ".") if over else
                           ("Within " + ", ".join(f"{k} {c:g}%" for k, c in ctx.asset_class_caps.items()) + "." if ctx.asset_class_caps else "No allocation limit is stated.")))
    ex = [k for k in ctx.excluded_asset_classes if weights.get(k, 0) > 0]
    out.append(WeightCheck(id="restrictions", label="Client restrictions", status="FAIL" if ex else "PASS",
                           detail=f"The IPS excludes {', '.join(ex)}." if ex else "No excluded asset class is held."))
    g = lib.growth_share(weights)
    if ctx.risk_level is None:
        out.append(WeightCheck(id="growth_cap", label="Growth cap for the client's risk level", status="WARN", detail=f"Growth {g:g}%; the client's risk level is unknown."))
    else:
        cap = lib.growth_cap(ctx.risk_level)
        out.append(WeightCheck(id="growth_cap", label="Growth cap for the client's risk level", status="PASS" if g <= cap + 1e-9 else "FAIL",
                               detail=f"Growth assets {g:g}% against a cap of {cap:g}% for risk level {ctx.risk_level}."))
    il = lib.illiquid_share(weights)
    out.append(WeightCheck(id="illiquid", label="Illiquid assets", status="PASS" if il <= fw.max_illiquid_pct + 1e-9 else "FAIL",
                           detail=f"{il:g}% in hedge funds and private markets (limit {fw.max_illiquid_pct:g}%)."))
    mt = metrics(lib, weights)
    if ctx.loss_tolerance_pct is not None and mt.recession_return_pct is not None:
        loss = -mt.recession_return_pct
        out.append(WeightCheck(id="loss", label="Loss tolerance (recession scenario)", status="PASS" if loss <= ctx.loss_tolerance_pct else "WARN",
                               detail=f"Scenario {mt.recession_return_pct:+.1f}% against a stated tolerance of -{ctx.loss_tolerance_pct:g}% (illustrative assumptions)."))
    big = [f"{k} {weights.get(k, 0) - model.weights.get(k, 0):+g}pp" for k in sorted(set(weights) | set(model.weights))
           if abs(weights.get(k, 0) - model.weights.get(k, 0)) > fw.max_change_pp_warning]
    out.append(WeightCheck(id="drift", label=f"Changes within {fw.max_change_pp_warning:g}pp of model {model.id}", status="WARN" if big else "PASS",
                           detail=("Large changes: " + ", ".join(big) + ". Record the reason.") if big else "All changes are moderate."))
    return out
