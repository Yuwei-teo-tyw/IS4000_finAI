"""Event explanations: query templating, per-event lookback, reuse of fetched
news, article-number -> URL mapping, citation and number validation (cited
snippets only), the single retry, and the budget / replay defaults."""
import json
from datetime import date, datetime, timedelta, timezone

import app.agents.market_researcher.event_explainer as explainer_module
from app.agents.market_researcher.adapters.base import SeriesPoint
from app.agents.market_researcher.adapters.news import RawNewsItem
from app.agents.market_researcher.event_explainer import (
    ExplainBatch,
    ExplanationDraft,
    explain_events,
    fill_templates,
    spec_for,
)
from app.agents.market_researcher.features import shift_months
from app.agents.market_researcher.schemas import Event, MarketResearchRequest

from conftest import run_async
from test_market_service import TODAY, make_service, quiet_planner_and_explainer

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)

YIELD_EVENT = Event(id="dgs10_sharp_move_up", severity="notable", evidence=["DGS10"],
                    description="10-year Treasury yield moved sharply up: +31bp over 1 week (now 4.31%).")


def pts(*pairs) -> list[SeriesPoint]:
    return sorted((SeriesPoint(AS_OF - timedelta(days=d), v) for d, v in pairs), key=lambda p: p.date)


SERIES = {
    "DGS10": pts((30, 4.20), (7, 4.00), (0, 4.31)),
    "DFII10": pts((30, 2.00), (7, 1.80), (0, 2.04)),
    "T10YIE": pts((30, 2.20), (7, 2.20), (0, 2.27)),
    "DGS2": pts((30, 3.90), (7, 3.95), (0, 4.00)),
}
PRICES = {"TLT": pts((30, 90.0), (7, 89.0), (0, 87.0))}


def art(title: str, snippet: str = "", age_days: float = 1, url: str = "") -> RawNewsItem:
    slug = title.lower().replace(" ", "-")[:40]
    return RawNewsItem(title, url or f"https://news.example/{slug}", "news.example",
                       NOW - timedelta(days=age_days), snippet, "q")


class Provider:
    name = "Stub"

    def __init__(self, *items):
        self.items, self.calls = list(items), []

    async def search(self, query, days, max_results):
        self.calls.append((query, days))
        return [RawNewsItem(i.title, i.url, i.source, i.published_at, i.snippet, query) for i in self.items]


class ScriptLLM:
    """Structured-output stand-in whose responses can depend on the prompt
    (so tests can cite articles by title regardless of ranking order)."""

    def __init__(self, *steps):
        self.steps, self.calls = list(steps), []

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step(messages) if callable(step) else step


def use_llm(monkeypatch, *steps) -> ScriptLLM:
    llm = ScriptLLM(*steps)
    monkeypatch.setattr(explainer_module, "get_groq_model", lambda: llm)
    return llm


def articles_in(messages, event_id=YIELD_EVENT.id) -> list[dict]:
    payload = json.loads(messages[1].content)
    return next(e for e in payload if e["event_id"] == event_id)["articles"]


def n_of(messages, title: str) -> int:
    return next(a["n"] for a in articles_in(messages) if a["title"] == title)


def draft(cited, text="Reports attribute the rise to strong data and heavy Treasury supply.", **kw) -> ExplanationDraft:
    return ExplanationDraft(event_id=YIELD_EVENT.id, status="explained", explanation=text,
                            likely_drivers=kw.pop("drivers", ["Treasury supply"]), cited_articles=cited,
                            cited_indicators=kw.pop("indicators", ["DGS10", "DFII10"]), confidence="medium", **kw)


def run(provider, raw_news=(), events=(YIELD_EVENT,), budget=20.0, series=SERIES):
    return run_async(explain_events(list(events), series, PRICES, list(raw_news), AS_OF, budget, provider, now=NOW))


SUPPLY = art("Treasury yields climb after weak auction", "The 10-year auction tailed by 3.7bp as supply worries grew.")


def test_spec_lookup_uses_longest_prefix():
    assert spec_for("dgs10_sharp_move_up").decomposition == "yield_real_vs_breakeven"
    assert spec_for("t10y2y_uninverted").decomposition == "curve_front_vs_back"
    assert spec_for("unknown_event") is None


def test_query_templating():
    spec = spec_for(YIELD_EVENT.id)
    assert fill_templates(YIELD_EVENT, spec, SERIES, PRICES, AS_OF)[0] == '"10-year Treasury yield" rises why'
    falling = {**SERIES, "DGS10": pts((30, 4.6), (0, 4.31))}
    assert fill_templates(YIELD_EVENT, spec, falling, PRICES, AS_OF)[0] == '"10-year Treasury yield" falls why'

    cpi = [SeriesPoint(shift_months(date(2025, 1, 1), i), 300 + i) for i in range(21)]  # last obs 2026-09-01
    inflation = Event(id="core_inflation_reaccelerating", severity="notable", description="x", evidence=["CPILFESL"])
    queries = fill_templates(inflation, spec_for(inflation.id), {"CPILFESL": cpi}, {}, AS_OF)
    assert queries[0] == "core inflation CPI September 2026 shelter services"


def test_lookback_filter_reuse_and_url_mapping(monkeypatch):
    old = art("Treasury yields old story from weeks ago", age_days=20)        # beyond the 10-day lookback
    reused = art("Bond market selloff deepens as yields rise", "Treasury yields rose on Fed worries.")
    unrelated = art("Celebrity chef opens restaurant", "A new dining spot.")
    llm = use_llm(monkeypatch, lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title)])]))

    provider = Provider(SUPPLY, old)
    [x], notes = run(provider, raw_news=[reused, unrelated])

    titles = {a["title"] for a in articles_in(llm.calls[0])}
    assert SUPPLY.title in titles and reused.title in titles                   # searched + reused
    assert old.title not in titles and unrelated.title not in titles
    assert {days for _, days in provider.calls} == {10}
    assert [q for q, _ in provider.calls] == x.queries_run
    assert x.status == "explained" and x.cited_urls == [SUPPLY.url]           # number -> URL in code
    assert x.decomposition["name"] == "yield_real_vs_breakeven"
    assert notes == []


def test_invented_citations_dropped(monkeypatch):
    use_llm(monkeypatch, lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title), 9], indicators=["DGS10", "FAKE1"])]))
    [x], _ = run(Provider(SUPPLY))
    assert x.cited_urls == [SUPPLY.url] and x.cited_indicators == ["DGS10"]


def test_only_invented_citations_is_insufficient(monkeypatch):
    use_llm(monkeypatch, ExplainBatch(items=[draft([7, 8])]))
    [x], _ = run(Provider(SUPPLY))
    assert x.status == "insufficient_evidence" and x.explanation is None and x.decomposition is not None


def test_number_from_cited_snippet_accepted(monkeypatch):
    use_llm(monkeypatch, lambda m: ExplainBatch(items=[draft(
        [n_of(m, SUPPLY.title)], text="Reports tie the jump to a weak auction that tailed by 3.7bp.")]))
    [x], _ = run(Provider(SUPPLY))
    assert x.status == "explained" and "3.7bp" in x.explanation


def test_number_from_uncited_snippet_rejected_then_unavailable(monkeypatch):
    retail = art("Retail sales beat forecasts", "Retail sales rose 1.9% last month.")
    text = "Reports tie the move to retail sales rising 1.9% and a weak auction."
    llm = use_llm(monkeypatch,
                  lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title)], text=text)]),
                  lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title)], text=text)]))
    [x], notes = run(Provider(SUPPLY, retail))

    assert len(llm.calls) == 2                                                 # one retry
    retry_note = llm.calls[1][-1].content
    assert "numbers not in the data: 1.9" in retry_note and YIELD_EVENT.id in retry_note
    assert x.status == "unavailable" and x.explanation is None
    assert x.decomposition is not None                                         # code-derived, kept anyway
    assert any("unavailable" in n and "1.9" in n for n in notes)


def test_retry_fixes_invented_number(monkeypatch):
    use_llm(monkeypatch,
            lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title)], text="Yields jumped 57bp on supply.")]),
            lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title)])]))
    [x], notes = run(Provider(SUPPLY))
    assert x.status == "explained" and notes == []


def test_insufficient_evidence_passthrough(monkeypatch):
    use_llm(monkeypatch, ExplainBatch(items=[ExplanationDraft(event_id=YIELD_EVENT.id, status="insufficient_evidence")]))
    [x], _ = run(Provider(SUPPLY))
    assert x.status == "insufficient_evidence" and x.queries_run


def test_llm_failure_marks_unavailable(monkeypatch):
    llm = use_llm(monkeypatch, RuntimeError("groq down"), RuntimeError("still down"))
    [x], notes = run(Provider(SUPPLY))
    assert len(llm.calls) == 2                                                 # re-asked once
    assert x.status == "unavailable" and x.decomposition is not None
    assert any("LLM call failed" in n for n in notes)


def test_rejected_output_is_reasked_once(monkeypatch):
    """Groq 400s when the model answers in prose instead of the tool call."""
    llm = use_llm(monkeypatch, RuntimeError("tool_use_failed"),
                  lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title)])]))
    [x], notes = run(Provider(SUPPLY))
    assert len(llm.calls) == 2 and x.status == "explained" and notes == []


def test_selection_skips_info_and_unknown_events(monkeypatch):
    llm = use_llm(monkeypatch, lambda m: ExplainBatch(items=[draft([n_of(m, SUPPLY.title)])]))
    events = [YIELD_EVENT, Event(id="mystery_event", severity="notable", description="?"),
              Event(id="t10y3m_still_inverted", severity="info", description="info only")]
    out, _ = run(Provider(SUPPLY), events=events)
    assert [(x.event_id, x.status) for x in out] == [(YIELD_EVENT.id, "explained"), ("mystery_event", "skipped")]
    assert len(json.loads(llm.calls[0][1].content)) == 1


def test_no_articles_means_no_llm_call(monkeypatch):
    llm = use_llm(monkeypatch)
    [x], _ = run(Provider())
    assert x.status == "insufficient_evidence" and llm.calls == []


def test_budget_skip(monkeypatch):
    llm = use_llm(monkeypatch)
    provider = Provider(SUPPLY)
    [x], notes = run(provider, budget=2.0)
    assert x.status == "skipped" and provider.calls == [] and llm.calls == []
    assert "skipped" in notes[0]


def test_past_as_of_defaults_off_and_live_defaults_on(monkeypatch, tmp_path):
    _, explainer = quiet_planner_and_explainer(monkeypatch)
    past = run_async(make_service(tmp_path).run(MarketResearchRequest(as_of=TODAY - timedelta(days=60)))).output
    assert past.event_explanations == [] and explainer.calls == []

    forced = run_async(make_service(tmp_path).run(
        MarketResearchRequest(as_of=TODAY - timedelta(days=60), explain_events=True))).output
    assert any("today's news index" in n for n in forced.data_quality.notes)
