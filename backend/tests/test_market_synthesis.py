"""Optional narrative: the number validator, the single retry, and the
deterministic template fallback."""
from datetime import date, datetime, timezone

import app.agents.market_researcher.synthesis as synthesis_module
from app.agents.market_researcher.schemas import (
    Event,
    Indicator,
    MarketResearchOutput,
    MarketResearchRequest,
    Regime,
)
from app.agents.market_researcher.synthesis import (
    Implication,
    SynthesisOut,
    allowed_numbers,
    build_payload,
    extract_numbers,
    invalid_numbers,
    synthesize,
)

from conftest import FakeLLM, run_async


def make_output():
    return MarketResearchOutput(
        run_id="mr_test", generated_at=datetime(2026, 10, 16, tzinfo=timezone.utc), as_of=date(2026, 10, 16),
        region="US", request=MarketResearchRequest(include_narrative=True),
        regime=Regime(phase="late_expansion", probabilities={"early_expansion": 0.2958, "late_expansion": 0.3859,
                                                             "recession": 0.1341, "late_recession": 0.1842},
                      confidence="low", recession_prob_12m=0.1281,
                      conflicting_signals=["Yield curve steep (T10Y3M) favors early_expansion"]),
        events=[Event(id="core_inflation_reaccelerating", severity="notable",
                      description="Core CPI re-accelerating: 3-month annualized 3.41% vs 2.57% YoY (2026-09-01).",
                      evidence=["CPILFESL"])],
        indicators=[Indicator(id="DGS10", name="10-Year Treasury Yield", category="rates", value=5.19, unit="%",
                              observation_date=date(2026, 10, 14), changes={"1m": 0.22, "1w": -0.09},
                              source="FRED", source_url="https://fred.stlouisfed.org/series/DGS10")],
    )


def draft(narrative, themes=("Rates high",)):
    return SynthesisOut(key_themes=list(themes), risks=["Inflation"], narrative=narrative,
                        implications=[Implication(area="duration", text="Long yields near highs.")])


def test_extract_numbers_ignores_dates_ids_tenors_and_years():
    text = "On 2026-10-14 the 10Y yield (DGS10) was 5.19%, up 22bp in 1 month, highest since 2007; 3-month annualized 3.41%."
    assert extract_numbers(text) == ["5.19", "22", "3.41"]


def test_validator_accepts_data_numbers_including_pct_and_bp_forms():
    allowed = allowed_numbers(build_payload(make_output()))
    ok = "The 10Y yield is 5.2% after rising 22bp over the past month; recession probability is 12.8% and late_expansion is at 39%."
    assert invalid_numbers([ok], allowed) == []


def test_validator_flags_invented_numbers():
    allowed = allowed_numbers(build_payload(make_output()))
    assert invalid_numbers(["Yields hit 6.75% and GDP grew 4.4%."], allowed) == ["4.4", "6.75"]


def test_synthesize_accepts_valid_draft(monkeypatch):
    fake = FakeLLM(draft("Late expansion, low confidence: 10Y at 5.19% [DGS10]."))
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: fake)
    out = make_output()
    run_async(synthesize(out))
    assert out.narrative.startswith("Late expansion") and out.implications == {"duration": "Long yields near highs."}
    assert not out.data_quality.notes and len(fake.calls) == 1


def test_synthesize_retries_once_with_offending_numbers(monkeypatch):
    fake = FakeLLM(draft("Yields at 6.75%."), draft("Yields at 5.19% [DGS10]."))
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: fake)
    out = make_output()
    run_async(synthesize(out))
    assert out.narrative == "Yields at 5.19% [DGS10]."
    assert "6.75" in fake.calls[1][-1].content


def test_synthesize_falls_back_to_template_after_second_failure(monkeypatch):
    fake = FakeLLM(draft("Yields at 6.75%."), draft("Yields at 7.1%."))
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: fake)
    out = make_output()
    run_async(synthesize(out))
    assert "late_expansion" in out.narrative and "13%" in out.narrative
    assert out.implications is None
    assert "deterministic template" in out.data_quality.notes[0] and "7.1" in out.data_quality.notes[0]
    # the template itself must pass the validator
    assert invalid_numbers([out.narrative, *out.key_themes, *out.risks], allowed_numbers(build_payload(out))) == []


def test_synthesize_falls_back_when_llm_errors(monkeypatch):
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: FakeLLM(RuntimeError("groq down")))
    out = make_output()
    run_async(synthesize(out))
    assert out.narrative and "LLM call failed" in out.data_quality.notes[0]


def test_unsupported_labels_trigger_retry(monkeypatch):
    fake = FakeLLM(draft("Tech is up 5.19% YTD."), draft("The 10Y yield is 5.19% [DGS10]."))
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: fake)
    out = make_output()
    run_async(synthesize(out))
    assert out.narrative == "The 10Y yield is 5.19% [DGS10]."
    assert "YTD" in fake.calls[1][-1].content


def test_retry_includes_rejected_draft(monkeypatch):
    fake = FakeLLM(draft("Yields at 6.75%."), draft("Yields at 5.19% [DGS10]."))
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: fake)
    run_async(synthesize(make_output()))
    retry_messages = fake.calls[1]
    assert retry_messages[-2].type == "ai" and "6.75" in retry_messages[-2].content
