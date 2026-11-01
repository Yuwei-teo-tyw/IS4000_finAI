"""Final quality gate: advice-language screen (explanations and narrative)
and the consistency / completeness / freshness / sources assessment."""
from datetime import date, datetime, timezone

import pytest

from app.agents.market_researcher.quality import advice_problems, assess, screen_explanations, screen_narrative
from app.agents.market_researcher.schemas import (
    CitedSource,
    DataQuality,
    Event,
    EventExplanation,
    Indicator,
    MarketResearchOutput,
    MarketResearchRequest,
    NewsItem,
    Regime,
)


def ind(sid: str, stale: bool = False, source: str = "FRED") -> Indicator:
    return Indicator(id=sid, name=sid, category="x", value=1.0, unit="%", observation_date=date(2026, 10, 14),
                     stale=stale, source=source, source_url=f"https://example/{sid}")


def make_output(**kw) -> MarketResearchOutput:
    base = dict(
        run_id="mr_test", generated_at=datetime(2026, 10, 15, tzinfo=timezone.utc), as_of=date(2026, 10, 15),
        region="US", request=MarketResearchRequest(),
        regime=Regime(phase="late_expansion", probabilities={"early_expansion": 0.3, "late_expansion": 0.7}),
        indicators=[ind(s) for s in ("DGS10", "T10Y3M", "UNRATE", "CPILFESL", "PAYEMS")],
        market_snapshot=[ind("SPY", source="Yahoo")],
        news=[NewsItem(title="t", source="s", url="https://n.example/1", summary="s")],
        events=[Event(id="dgs10_sharp_move_up", severity="notable", description="d", evidence=["DGS10"])],
    )
    base.update(kw)
    return MarketResearchOutput(**base)


def explained(text="Reports attribute it to Treasury supply.", **kw) -> EventExplanation:
    url = "https://wire.example/a"
    return EventExplanation(event_id=kw.pop("event_id", "dgs10_sharp_move_up"), status="explained", explanation=text,
                            likely_drivers=kw.pop("drivers", ["Treasury supply"]), cited_urls=[url],
                            cited_sources=[CitedSource(url=url, title="A", source="wire.example")],
                            decomposition={"description": "code"}, **kw)


@pytest.mark.parametrize("text,label", [
    ("You should add duration here.", "direct instruction"),
    ("We recommend trimming equities.", "recommendation"),
    ("Investors may consider rotating into energy.", "trade suggestion"),
    ("This argues to overweight utilities.", "positioning call"),
    ("A clear buy signal for banks.", "buy/sell call"),
    ("Treasuries offer guaranteed returns.", "guarantee"),
])
def test_advice_patterns_flag(text, label):
    assert label in advice_problems([text])


@pytest.mark.parametrize("text", [
    "The selloff deepened as sellers dominated and buyers stepped back.",
    "Real yields rose above the risk-free rate benchmark; the risk-free yield curve steepened.",
    "Reports attribute the move to heavy Treasury supply and strong data.",
    "Equities fell 2% as the 10-year yield hit 5%.",
])
def test_descriptive_market_language_is_not_flagged(text):
    assert advice_problems([text]) == []


def test_flagged_explanation_withheld_but_decomposition_kept():
    out, notes = screen_explanations([explained("Investors should consider buying duration now."), explained()])
    assert out[0].status == "unavailable" and out[0].explanation is None and out[0].decomposition == {"description": "code"}
    assert out[1].status == "explained"
    assert len(notes) == 1 and "withheld" in notes[0] and "trade suggestion" in notes[0]


def test_flagged_narrative_replaced_by_template():
    out = make_output(narrative="Given this, you should overweight energy.", key_themes=["x"], risks=["y"],
                      implications={"equities": "fine"})
    found = screen_narrative(out)
    assert "direct instruction" in found and "positioning call" in found
    assert "you should" not in out.narrative and out.implications is None
    assert any("deterministic template" in n and "advice-like wording" in n for n in out.data_quality.notes)
    assert advice_problems([out.narrative]) == []


def test_clean_narrative_untouched():
    out = make_output(narrative="Yields rose on supply [DGS10].", key_themes=[], risks=[], implications={})
    assert screen_narrative(out) == [] and out.narrative == "Yields rose on supply [DGS10]."


def test_clean_run_is_ok():
    report = assess(make_output(event_explanations=[explained()]), news_expected=True, screened=[])
    assert report.status == "ok" and report.issues == [] and all(report.checks.values())


def test_degraded_cases():
    out = make_output(
        regime=Regime(phase="recession", probabilities={"recession": 0.5, "late_recession": 0.3}),
        indicators=[ind("DGS10", stale=True), ind("T10Y3M"), ind("UNRATE"), ind("CPILFESL")],
        events=[Event(id="oil_shock", severity="notable", description="d", evidence=["CL=F"])],
        event_explanations=[explained(event_id="ghost_event")],
        news=[],
        data_quality=DataQuality(failed_sources=["FRED:PAYEMS", "planned:FRED:JTSJOL"]),
    )
    report = assess(out, news_expected=True, screened=["explanation withheld"])
    assert report.status == "degraded"
    assert not any(report.checks.values())
    text = " | ".join(report.issues)
    assert "probabilities sum to 0.800" in text
    assert "oil_shock cites evidence not in the output: CL=F" in text
    assert "unknown event ghost_event" in text
    assert "key series missing: PAYEMS" in text and "no news items" in text
    assert "key indicators stale: DGS10" in text
    assert "FRED:PAYEMS" in text and "planned:" not in text                  # planner extras don't count
    assert "advice_language: explanation withheld" in text


def test_news_not_expected_for_replays():
    assert assess(make_output(news=[]), news_expected=False, screened=[]).status == "ok"


def test_unusable_without_indicators_or_phase():
    assert assess(make_output(indicators=[], events=[]), news_expected=True, screened=[]).status == "unusable"
    no_phase = make_output(regime=Regime(phase=None))
    assert assess(no_phase, news_expected=True, screened=[]).status == "unusable"


def test_explained_without_matching_sources_is_inconsistent():
    x = explained()
    x.cited_sources = []
    report = assess(make_output(event_explanations=[x]), news_expected=True, screened=[])
    assert not report.checks["consistency"] and "without matching sources" in report.issues[0]


@pytest.mark.parametrize("text", [
    "Long-duration bonds could favor investors now.", "Clients may want to add duration.", "Credit looks attractive here.",
    "Yields are high. Favor short duration.", "Energy offers an attractive entry point.",
])
def test_soft_advice_is_flagged(text):
    assert advice_problems([text])


@pytest.mark.parametrize("text", [
    "Investors favored energy last month.", "Markets prefer clarity from the Fed.", "Traders avoid long bonds.",
    "The selloff lacks a catalyst.", "Valuations are not attractive to everyone.",
])
def test_descriptive_text_passes_the_advice_screen(text):
    assert not advice_problems([text])
