"""News tagging: batched structured LLM call, plus the keyword fallback."""
from datetime import datetime, timezone

import app.agents.market_researcher.news_tagging as tagging_module
from app.agents.market_researcher.adapters.news import RawNewsItem
from app.agents.market_researcher.news_tagging import NewsTag, NewsTagBatch, keyword_tag, tag_news

from conftest import FakeLLM, run_async

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)
ITEMS = [
    RawNewsItem("Fed signals another rate hike as inflation persists", "https://a.com/1", "a.com", NOW, "FOMC minutes...", "q"),
    RawNewsItem("Oil prices slump on demand fears", "https://b.com/2", "b.com", NOW, "Crude fell...", "q"),
]


def test_tag_news_uses_llm_tags_and_backfills_missing(monkeypatch):
    fake = FakeLLM(NewsTagBatch(items=[
        NewsTag(index=0, summary="The Fed hinted at further tightening.", topics=["Fed", "Rates"], sentiment="risk_off", market_impact="high"),
    ]))
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: fake)

    news, notes = run_async(tag_news(ITEMS))

    assert news[0].summary == "The Fed hinted at further tightening."
    assert news[0].topics == ["fed", "rates"] and news[0].market_impact == "high"
    assert news[1].url == "https://b.com/2" and news[1].summary == ITEMS[1].title  # keyword fallback
    assert notes and "1 news item" in notes[0]
    # every item went to the model in one batched call
    assert len(fake.calls) == 1 and "[1] Oil prices slump" in fake.calls[0][1].content


def test_tag_news_falls_back_when_llm_fails(monkeypatch):
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: FakeLLM(RuntimeError("groq down")))
    news, notes = run_async(tag_news(ITEMS))
    assert [n.url for n in news] == ["https://a.com/1", "https://b.com/2"]
    assert "keyword-based" in notes[0]


def test_keyword_tag():
    tagged = keyword_tag(ITEMS[1])
    assert "energy" in tagged.topics and tagged.sentiment == "risk_off"


def test_tag_news_empty():
    assert run_async(tag_news([])) == ([], [])
