"""
Optional LLM narrative layer.

The LLM receives only computed facts (no client identifiers) and writes a
plain-language narrative per offered option plus a comparison summary. Its
output must parse into `LLMExplanation`, cover exactly the offered
options, and pass the guardrails; otherwise the whole LLM result is
discarded and the deterministic templates are used, with
`explanation_status` saying so. The response never reports LLM success
unless generation *and* validation succeeded.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from app.prompts.prompt_builder import get_prompt
from app.agents.portfolio_manager.config import Settings
from app.agents.portfolio_manager.explain.guardrails import AllowedNumbers, check_text
from app.agents.portfolio_manager.explain.llm_client import LLMUnavailable, get_llm
from app.agents.portfolio_manager.schemas.response import ExplanationStatus

logger = logging.getLogger(__name__)


class OptionNarrative(BaseModel):
    option_id: Literal["A", "B", "C", "D", "E", "F"]
    narrative: str = Field(min_length=20, max_length=2000)


class LLMExplanation(BaseModel):
    option_narratives: list[OptionNarrative]
    comparison_summary: str = Field(min_length=20, max_length=2500)
    preferred_option_commentary: Optional[str] = Field(default=None, max_length=2000)


@dataclass
class ExplanationResult:
    status: ExplanationStatus
    option_narratives: dict[str, str] = field(default_factory=dict)
    comparison_summary: Optional[str] = None
    preferred_commentary: Optional[str] = None


class _Rejected(Exception):
    pass


def _coerce(raw: Any) -> LLMExplanation:
    if isinstance(raw, LLMExplanation):
        return raw
    if isinstance(raw, dict):
        return LLMExplanation.model_validate(raw)
    if isinstance(raw, str):
        return LLMExplanation.model_validate_json(raw)
    content = getattr(raw, "content", None)  # a bare chat message
    if isinstance(content, str):
        return LLMExplanation.model_validate_json(content)
    raise _Rejected(f"unexpected LLM output type {type(raw).__name__}")


def _validate(expl: LLMExplanation, offered_ids: set[str], allowed: AllowedNumbers) -> None:
    # Narratives for options that weren't offered are discarded rather than
    # shown; every offered option must still have exactly one.
    expl.option_narratives = [n for n in expl.option_narratives if n.option_id in offered_ids]
    ids = [n.option_id for n in expl.option_narratives]
    if len(ids) != len(set(ids)) or set(ids) != offered_ids:
        raise _Rejected(f"narratives cover options {sorted(ids)}, expected {sorted(offered_ids)}")
    problems = []
    texts = [n.narrative for n in expl.option_narratives] + [expl.comparison_summary]
    if expl.preferred_option_commentary:
        texts.append(expl.preferred_option_commentary)
    for t in texts:
        problems.extend(check_text(t, allowed))
    if problems:
        raise _Rejected("guardrail violations: " + "; ".join(sorted(set(problems))[:5]))


def _fallback(settings: Settings, attempted: bool, detail: str) -> ExplanationResult:
    return ExplanationResult(status=ExplanationStatus(
        source="DETERMINISTIC_FALLBACK" if attempted else "DETERMINISTIC",
        llm_attempted=attempted,
        llm_succeeded=False,
        model=settings.llm_model if attempted else None,
        detail=detail,
    ))


async def generate_explanations(
    facts: dict,
    offered_ids: set[str],
    allowed: AllowedNumbers,
    settings: Settings,
    llm_factory: Callable[[Settings], Any] = get_llm,
) -> ExplanationResult:
    if not offered_ids:
        return _fallback(settings, False, "No options were offered, so no narrative was generated.")
    try:
        llm = llm_factory(settings)
    except LLMUnavailable as e:
        return _fallback(settings, False, f"LLM not used: {e} Deterministic explanations provided.")

    messages = [
        ("system", get_prompt("portfolio_manager.explanation_system")),
        ("human", get_prompt("portfolio_manager.explanation_user", facts_json=json.dumps(facts, default=str))),
    ]
    try:
        raw = await asyncio.wait_for(
            llm.with_structured_output(LLMExplanation).ainvoke(messages), timeout=settings.llm_timeout_seconds
        )
        expl = _coerce(raw)
        _validate(expl, offered_ids, allowed)
    except asyncio.TimeoutError:
        return _fallback(settings, True, "LLM call timed out; deterministic explanations provided instead.")
    except (ValidationError, ValueError) as e:
        n = e.error_count() if isinstance(e, ValidationError) else 1
        return _fallback(settings, True, f"LLM output was not valid JSON for the schema ({n} errors); deterministic "
                                         "explanations provided instead.")
    except _Rejected as e:
        return _fallback(settings, True, f"LLM output rejected by validation ({e}); deterministic explanations "
                                         "provided instead.")
    except Exception as e:  # provider/network errors
        logger.warning("LLM explanation failed: %s", type(e).__name__)
        return _fallback(settings, True, f"LLM call failed ({type(e).__name__}); deterministic explanations "
                                         "provided instead.")

    return ExplanationResult(
        status=ExplanationStatus(
            source="LLM", llm_attempted=True, llm_succeeded=True, model=settings.llm_model,
            detail="Narratives generated by the LLM from computed figures and passed programmatic validation. "
                   "All numbers originate from the calculation engine.",
        ),
        option_narratives={n.option_id: n.narrative for n in expl.option_narratives},
        comparison_summary=expl.comparison_summary,
        preferred_commentary=expl.preferred_option_commentary,
    )
