"""
LLM narrative layer: success path, failures, invalid JSON, guardrail
rejections, timeouts, and what data the LLM is allowed to see.
"""
import asyncio

from conftest import FakeLLM
from portfolio_helpers import GENERATE, make_client, make_service, offered, request_with, settings
from app.agents.portfolio_manager.explain.explainer import LLMExplanation, OptionNarrative
from app.agents.portfolio_manager.explain.guardrails import AllowedNumbers, check_text, find_claim_violations

GOOD_TEXT = (
    "This option keeps most of the money in high-quality bonds and cash. Returns are not guaranteed and "
    "the portfolio can still lose value if interest rates rise or inflation picks up."
)


def _explanation(ids=("A", "B", "C"), text=GOOD_TEXT, summary=None):
    return LLMExplanation(
        option_narratives=[OptionNarrative(option_id=i, narrative=text) for i in ids],
        comparison_summary=summary or "Option A favours stability; Option B accepts more volatility for growth.",
        preferred_option_commentary="Option B balances the retirement goal against the drawdown limit.",
    )


def _run(fake, **settings_kw):
    service = make_service(llm_factory=lambda s: fake, settings=settings(**settings_kw))
    r = make_client(service).post(GENERATE, json=request_with())
    assert r.status_code == 200, r.text
    return r.json()


def test_valid_llm_output_is_used_and_labelled():
    fake = FakeLLM(_explanation())
    body = _run(fake)
    st = body["explanation_status"]
    assert st["source"] == "LLM" and st["llm_succeeded"] is True
    for o in offered(body):
        assert o["narrative"] == GOOD_TEXT
        assert o["narrative_source"] == "LLM_INTERPRETATION"
    assert "[LLM interpretation]" in body["preferred_option_rationale"]
    # Numbers still come from the engine, not the LLM.
    assert body["liquidity_plan"]["eligible_portfolio_value"] == 350000


def test_llm_never_receives_client_identifiers():
    fake = FakeLLM(_explanation())
    _run(fake)
    sent = " ".join(str(m) for call in fake.calls for m in call)
    assert "CLIENT_001" not in sent and "PM-REQ" not in sent and "PM-TEST" not in sent


def test_llm_exception_falls_back_without_claiming_success():
    body = _run(FakeLLM(RuntimeError("provider down")))
    st = body["explanation_status"]
    assert st["source"] == "DETERMINISTIC_FALLBACK"
    assert st["llm_attempted"] is True and st["llm_succeeded"] is False
    assert "RuntimeError" in st["detail"]
    for o in offered(body):
        assert o["narrative_source"] == "DETERMINISTIC_TEMPLATE" and o["narrative"]
    assert "[LLM interpretation]" not in body["preferred_option_rationale"]


def test_invalid_json_falls_back():
    body = _run(FakeLLM("this is {not valid json"))
    st = body["explanation_status"]
    assert st["source"] == "DETERMINISTIC_FALLBACK"
    assert "not valid JSON" in st["detail"]


def test_wrong_schema_dict_falls_back():
    body = _run(FakeLLM({"option_narratives": "oops"}))
    assert body["explanation_status"]["llm_succeeded"] is False


def test_guaranteed_return_language_rejected():
    body = _run(FakeLLM(_explanation(text="This portfolio offers guaranteed returns and steady income for life.")))
    st = body["explanation_status"]
    assert st["llm_succeeded"] is False and "guarantee" in st["detail"]


def test_fabricated_number_rejected():
    body = _run(FakeLLM(_explanation(text="This option is expected to return 12.5% a year with low risk overall.")))
    st = body["explanation_status"]
    assert st["llm_succeeded"] is False and "12.5%" in st["detail"]


def test_missing_option_narrative_rejected():
    body = _run(FakeLLM(_explanation(ids=("A",))))
    assert body["explanation_status"]["llm_succeeded"] is False


def test_claiming_live_verified_data_rejected():
    body = _run(FakeLLM(_explanation(text="Based on verified live market data, this option suits the client well.")))
    assert body["explanation_status"]["llm_succeeded"] is False


def test_timeout_falls_back():
    class SlowLLM:
        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, messages):
            await asyncio.sleep(5)

    body = _run(SlowLLM(), llm_timeout_seconds=0.05)
    assert body["explanation_status"]["source"] == "DETERMINISTIC_FALLBACK"
    assert "timed out" in body["explanation_status"]["detail"]


def test_llm_not_configured_is_reported_as_deterministic():
    body = make_client().post(GENERATE, json=request_with()).json()
    st = body["explanation_status"]
    assert st["source"] == "DETERMINISTIC" and st["llm_attempted"] is False


# --- Guardrail unit tests ----------------------------------------------------

def test_negated_caveats_are_allowed():
    assert find_claim_violations("Returns are not guaranteed and the option is not risk-free.") == []
    assert find_claim_violations("No option is mathematically optimal.") == []


def test_unnegated_claims_detected():
    assert find_claim_violations("A risk-free way to grow wealth.")
    assert find_claim_violations("The trades have been executed.")
    assert find_claim_violations("This is the optimal portfolio.")


def test_number_checks_allow_computed_figures_only():
    allowed = AllowedNumbers()
    allowed.add_pct(4.13)
    allowed.add_amount(350000)
    assert check_text("Expected return 4.1% on 350,000 by 2034.", allowed) == []
    assert check_text("Expected return 6% on 350,000.", allowed)
    assert check_text("Expected return 4.13% on 500,000.", allowed)


def test_narrative_for_option_not_offered_is_dropped_not_fatal():
    # Seen against a real model: it narrated an option that had been
    # withdrawn. The extra narrative is discarded; offered ones are kept.
    body = _run(FakeLLM(_explanation(ids=("A", "B", "C", "D"))))
    assert body["explanation_status"]["llm_succeeded"] is True
    d = next(o for o in body["portfolio_options"] if o["option_id"] == "D")
    assert d["narrative"] is None and d["narrative_source"] == "NONE"


def test_llm_only_sees_offered_options():
    fake = FakeLLM(_explanation())
    _run(fake)
    sent = " ".join(str(m) for call in fake.calls for m in call)
    assert '"options_to_narrate": ["A", "B", "C"]' in sent
