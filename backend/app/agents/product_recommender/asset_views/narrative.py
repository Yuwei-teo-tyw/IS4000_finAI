"""
LLM-written prose for an asset-class view.

The builder fixes every stance, number, trigger and ref. The LLM rewrites
only the text slots (thesis, thesis points, segment reasons, scenario
descriptions, risks, the CIO-agreement explanation) from that skeleton,
with the deterministic text as its draft. Refs stay attached by code. A
slot whose LLM text fails the guardrail keeps its deterministic text.
"""
from typing import Callable

from pydantic import BaseModel, Field

from app.agents.portfolio_agent.explain.llm_client import get_llm
from app.agents.product_recommender import guardrails, llm
from app.agents.product_recommender.asset_views.schemas import AssetClassView
from app.agents.product_recommender.config import Settings


class SlotText(BaseModel):
    id: str
    text: str = Field(min_length=10, max_length=400)


class NarrativeOut(BaseModel):
    items: list[SlotText]


def _slots(v: AssetClassView) -> list[dict]:
    """The text slots to write, each with the fixed facts it must agree with."""
    a = v.agent_view
    out = [{"id": "thesis", "kind": "thesis", "draft": a.thesis}]
    out += [{"id": f"point_{i}", "kind": "thesis_point", "draft": p.text} for i, p in enumerate(a.thesis_points)]
    out += [{"id": f"segment_{i}", "kind": "segment", "segment": s.segment, "stance": s.view, "draft": s.reason}
            for i, s in enumerate(v.segments) if s.score is not None]
    out += [{"id": f"scenario_{s.case}", "kind": "scenario", "case": s.case,
             "trigger": s.trigger and s.trigger.condition, "stance_implication": s.stance_implication, "draft": s.description}
            for s in v.scenarios]
    agreement_text = v.agreement.explanation if v.agreement else None
    out += [{"id": f"risk_{i}", "kind": "risk", "draft": r.text} for i, r in enumerate(v.risks) if r.text != agreement_text]
    if agreement_text:
        out.append({"id": "agreement", "kind": "agreement", "status": v.agreement.status, "draft": agreement_text})
    return out


def view_facts(v: AssetClassView) -> dict:
    a, cio = v.agent_view, v.cio_view
    return {
        "asset_class": v.asset_class,
        "is_illustrative": v.is_illustrative,
        "agent_view": {"view": a.view, "confidence": a.confidence, "insufficient_evidence": a.insufficient_evidence,
                       "anchored_on_cio_view": True, "cio_adjustment": a.cio_adjustment,
                       "coverage": a.coverage.model_dump(), "regime": {"phase": a.regime.phase, "confidence": a.regime.confidence}},
        "cio_view": {"view": cio.view, "cio_term": cio.cio_term, "basis": cio.basis, "confidence": cio.confidence,
                     "rationale": cio.rationale},
        "agreement": v.agreement.status if v.agreement else None,
        "evidence": [{"name": s.name, "value": s.value, "unit": s.unit, "change_3m": s.change_3m,
                      "percentile_10y": s.percentile_10y, "effect": s.effect, "why": s.why} for s in v.snapshot],
        "items": _slots(v),
    }


async def llm_narrative(v: AssetClassView, settings: Settings, llm_factory: Callable = get_llm) -> AssetClassView:
    """The view with LLM-written prose where it passes the guardrail; every stance and ref unchanged."""
    if v.agent_view is None or not v.snapshot:
        return v.model_copy(update={"explanation_status": llm.deterministic_status(
            "No market data behind the agent view, so no narrative was written.", settings)})
    facts = view_facts(v)
    slots = {s["id"]: s for s in facts["items"]}
    allowed = guardrails.numbers_in(str(facts))
    a = v.agent_view
    evidence = [s.name for s in v.snapshot if s.effect != "neutral"]
    pp_only = guardrails.pp_only_numbers(" ".join(i["draft"] for i in facts["items"]),
                                         [s.value for s in v.snapshot if s.unit == "%"])

    def check(out: NarrativeOut):
        ok, bad = {}, {}
        for item in out.items:
            slot = slots.get(item.id)
            if slot is None or item.id in ok:
                continue
            text = guardrails.normalise(item.text)
            problems = guardrails.check_view_slot(
                slot["kind"], text, allowed, agent_view=a.view, agent_confidence=a.confidence,
                cio_view=v.cio_view.view, cio_term=v.cio_view.cio_term, stance=slot.get("stance"),
                insufficient=a.insufficient_evidence, evidence_names=evidence,
                slot_stances=guardrails.stances_in(f"{slot['draft']} {slot.get('stance_implication', '')}"),
                pp_only=pp_only)
            if problems:
                bad[item.id] = problems
            else:
                ok[item.id] = text
        for sid in slots.keys() - ok.keys() - bad.keys():
            bad[sid] = ["no text was returned"]
        return ok, bad

    res = await llm.write(NarrativeOut, "asset_view", facts, list(slots), check, settings, llm_factory)
    t = res.accepted
    if not t:
        return v.model_copy(update={"explanation_status": res.status})

    def pick(sid: str, current: str) -> str:
        return t.get(sid, current)

    agreement = v.agreement
    if agreement and agreement.explanation and "agreement" in t:
        # No full stop after the tag: the page renders the tag as a chip, so it would sit alone after it.
        agreement = agreement.model_copy(update={"explanation": f"{t['agreement'].rstrip('.')} [{v.cio_view.citation_id}]"})
    risk_ids = {r["draft"]: r["id"] for r in facts["items"] if r["kind"] == "risk"}
    risks = []
    for r in v.risks:
        if v.agreement and r.text == v.agreement.explanation:
            risks.append(r.model_copy(update={"text": t.get("agreement", r.text)}))
        else:
            risks.append(r.model_copy(update={"text": pick(risk_ids.get(r.text, ""), r.text)}))
    seg_ids = {i: f"segment_{i}" for i, s in enumerate(v.segments) if s.score is not None}
    return v.model_copy(update={
        "agent_view": a.model_copy(update={
            "thesis": pick("thesis", a.thesis),
            "thesis_points": [p.model_copy(update={"text": pick(f"point_{i}", p.text)}) for i, p in enumerate(a.thesis_points)],
        }),
        "segments": [s.model_copy(update={"reason": pick(seg_ids[i], s.reason)}) if i in seg_ids else s
                     for i, s in enumerate(v.segments)],
        "scenarios": [s.model_copy(update={"description": pick(f"scenario_{s.case}", s.description)}) for s in v.scenarios],
        "risks": risks,
        "agreement": agreement,
        "narrative_source": "llm",
        "explanation_status": res.status,
    })
