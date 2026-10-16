"""
Tag news items with topic / sentiment / market impact and a short summary
in the agent's own words - one batched structured LLM call for all items
(guide §3.3). Falls back to a keyword tagger if the LLM call fails, so a
Groq outage degrades the tags instead of dropping the news.
"""
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.market_researcher.adapters.news import RawNewsItem
from app.agents.market_researcher.schemas import NewsItem
from app.core import get_groq_model
from app.prompts.prompt_builder import get_prompt

# gpt-oss is a reasoning model and its reasoning tokens count against
# max_tokens - the shared client's 1024 is too tight for a 15-item batch.
TAGGING_MAX_TOKENS = 4096


class NewsTag(BaseModel):
    index: int
    summary: str = Field(description="One sentence, own words, max 30 words.")
    topics: list[str] = Field(default_factory=list)
    sentiment: Literal["risk_on", "risk_off", "neutral"] = "neutral"
    market_impact: Literal["low", "medium", "high"] = "low"


class NewsTagBatch(BaseModel):
    items: list[NewsTag]


def with_max_tokens(llm, max_tokens: int):
    """A copy of the shared chat model with a bigger output budget (the
    test FakeLLM has no model_copy, so it's returned as-is)."""
    if hasattr(llm, "model_copy"):
        return llm.model_copy(update={"max_tokens": max_tokens})
    return llm


_TOPIC_KEYWORDS = {
    "rates": ("yield", "treasury", "treasuries", "bond", "rates"),
    "fed": ("federal reserve", "fed ", "fomc", "powell", "rate cut", "rate hike"),
    "inflation": ("inflation", "cpi", "pce", "prices"),
    "labor": ("jobs", "payroll", "unemployment", "jobless", "labor"),
    "energy": ("oil", "opec", "crude", "gas", "energy"),
    "credit": ("credit", "spread", "high-yield", "junk", "default"),
    "equities": ("stocks", "s&p", "nasdaq", "dow", "equities", "shares"),
    "growth": ("gdp", "recession", "growth", "economy", "slowdown"),
    "china": ("china", "chinese", "beijing"),
    "fx": ("dollar", "currency", "yen", "euro"),
}
_RISK_OFF = ("fall", "falls", "slump", "selloff", "sell-off", "plunge", "fears", "recession", "slide", "tumble", "worst", "crisis", "blow up")
_RISK_ON = ("rally", "rallies", "gains", "record high", "surge", "rebound", "beats", "optimism", "strong")
_HIGH_IMPACT = ("fed", "inflation", "labor")


def keyword_tag(item: RawNewsItem) -> NewsItem:
    text = f" {item.title} {item.snippet} ".lower()
    topics = [t for t, words in _TOPIC_KEYWORDS.items() if any(w in text for w in words)][:3]
    off = sum(w in text for w in _RISK_OFF)
    on = sum(w in text for w in _RISK_ON)
    sentiment = "risk_off" if off > on else "risk_on" if on > off else "neutral"
    impact = "medium" if any(t in _HIGH_IMPACT for t in topics) else "low"
    return NewsItem(
        title=item.title, source=item.source, url=item.url, published_at=item.published_at,
        summary=item.title, topics=topics, sentiment=sentiment, market_impact=impact,
    )


async def tag_news(items: list[RawNewsItem]) -> tuple[list[NewsItem], list[str]]:
    """Returns (tagged items, data-quality notes)."""
    if not items:
        return [], []
    listing = "\n\n".join(
        f"[{i}] {it.title}\nSource: {it.source}\nSnippet: {it.snippet[:300]}" for i, it in enumerate(items)
    )
    try:
        tagger = with_max_tokens(get_groq_model(), TAGGING_MAX_TOKENS).with_structured_output(NewsTagBatch)
        batch = await tagger.ainvoke([
            SystemMessage(content=get_prompt("market_researcher.news_tagging_system")),
            HumanMessage(content=listing),
        ])
        tags = {t.index: t for t in batch.items}
    except Exception as e:
        print(f"MARKET_RESEARCHER: news tagging LLM call failed, using keyword tags: {e}")
        return [keyword_tag(it) for it in items], ["News tags are keyword-based (LLM tagging failed)."]

    out, missing = [], 0
    for i, it in enumerate(items):
        tag = tags.get(i)
        if tag is None:
            missing += 1
            out.append(keyword_tag(it))
            continue
        out.append(NewsItem(
            title=it.title, source=it.source, url=it.url, published_at=it.published_at,
            summary=tag.summary.strip() or it.title, topics=[t.lower() for t in tag.topics[:3]],
            sentiment=tag.sentiment, market_impact=tag.market_impact,
        ))
    notes = [f"{missing} news item(s) keyword-tagged (missing from LLM output)."] if missing else []
    return out, notes
