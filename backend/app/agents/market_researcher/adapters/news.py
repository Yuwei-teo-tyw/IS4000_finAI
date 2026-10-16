"""
News search behind a provider-agnostic interface (guide §3.3).

`TavilyNewsProvider` reuses the TAVILY_API_KEY the chat agents already use
(see app/agents/tools.py), with `topic="news"`. `collect_news` fans out
the query templates, filters to the lookback window (Tavily's `days`
filter is loose), de-duplicates by URL and by title similarity, and keeps
the top N by keyword relevance + recency.
"""
import asyncio
import difflib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.agents.market_researcher.adapters.base import SourceError, TokenBucket, request_with_retry

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass
class RawNewsItem:
    title: str
    url: str
    source: str
    published_at: Optional[datetime]
    snippet: str
    query: str
    provider_score: float = 0.0
    relevance: float = 0.0


class NewsProvider(Protocol):
    name: str

    async def search(self, query: str, days: int, max_results: int) -> list[RawNewsItem]: ...


def parse_published(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), parts.path.rstrip("/"), "", ""))


def parse_tavily(payload: dict, query: str) -> list[RawNewsItem]:
    items = []
    for r in payload.get("results", []):
        url, title = r.get("url"), (r.get("title") or "").strip()
        if not url or not title:
            continue
        items.append(RawNewsItem(
            title=title,
            url=url,
            source=domain_of(url),
            published_at=parse_published(r.get("published_date")),
            snippet=(r.get("content") or "").strip()[:500],
            query=query,
            provider_score=float(r.get("score") or 0.0),
        ))
    return items


class TavilyNewsProvider:
    name = "Tavily"

    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None, timeout: float = 10.0,
                 base_delay: float = 0.5):
        if not api_key:
            raise ValueError("TAVILY_API_KEY is not set")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._timeout = timeout
        self._base_delay = base_delay
        self._bucket = TokenBucket(rate=4.0, capacity=4)

    async def search(self, query: str, days: int, max_results: int) -> list[RawNewsItem]:
        response = await request_with_retry(
            self._client, "POST", TAVILY_SEARCH_URL, source="Tavily",
            json={
                "api_key": self._api_key,
                "query": query,
                "topic": "news",
                "days": days,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=self._timeout, base_delay=self._base_delay, bucket=self._bucket,
        )
        try:
            return parse_tavily(response.json(), query)
        except ValueError as e:
            raise SourceError("Tavily: invalid JSON") from e

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


# --- collection, de-duplication, ranking ------------------------------------

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"or", "and", "the", "of", "a", "to", "in", "on", "for", "us"}


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def dedupe(items: list[RawNewsItem], title_similarity: float) -> list[RawNewsItem]:
    """Keep the first of each URL and of each cluster of near-identical titles
    (the same wire story syndicated across outlets)."""
    kept: list[RawNewsItem] = []
    seen_urls: set[str] = set()
    for item in items:
        url = normalize_url(item.url)
        if url in seen_urls:
            continue
        title = item.title.lower()
        if any(difflib.SequenceMatcher(None, title, k.title.lower()).ratio() >= title_similarity for k in kept):
            continue
        seen_urls.add(url)
        kept.append(item)
    return kept


# Items found by the caller's own query/focus terms outrank the generic
# macro queries - otherwise a "China" request gets 15 generic rates stories.
PRIORITY_BOOST = 0.4


def score(item: RawNewsItem, keywords: set[str], now: datetime, lookback_days: int) -> float:
    text_terms = _terms(f"{item.title} {item.snippet}")
    keyword_score = len(text_terms & keywords) / max(1, min(len(keywords), 8))
    if item.published_at is None:
        recency = 0.25
    else:
        age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600)
        recency = max(0.0, 1 - age_hours / (lookback_days * 24))
    return 0.5 * keyword_score + 0.3 * recency + 0.2 * item.provider_score


async def collect_news(
    provider: NewsProvider,
    queries: list[str],
    lookback_days: int,
    per_query: int,
    top_n: int,
    title_similarity: float,
    focus_terms: Optional[list[str]] = None,
    now: Optional[datetime] = None,
    priority_queries: Optional[list[str]] = None,
) -> tuple[list[RawNewsItem], list[str]]:
    """Run every query; return (top items, failed query labels). Results
    from `priority_queries` (the caller's own focus) get a ranking boost."""
    now = now or datetime.now(timezone.utc)
    results = await asyncio.gather(
        *(provider.search(q, lookback_days, per_query) for q in queries), return_exceptions=True
    )
    items: list[RawNewsItem] = []
    failures: list[str] = []
    for q, res in zip(queries, results):
        if isinstance(res, Exception):
            failures.append(f"{provider.name}: {q}")
            continue
        items.extend(res)
    if failures and len(failures) == len(queries):
        raise SourceError(f"{provider.name}: all {len(queries)} news queries failed")

    cutoff = now - timedelta(days=lookback_days)
    items = [i for i in items if i.published_at is None or i.published_at >= cutoff]

    keywords: set[str] = set()
    for q in queries + list(focus_terms or []):
        keywords |= _terms(q)
    priority = set(priority_queries or [])
    for item in items:
        item.relevance = score(item, keywords, now, lookback_days) + (PRIORITY_BOOST if item.query in priority else 0.0)
    items.sort(key=lambda i: i.relevance, reverse=True)
    return dedupe(items, title_similarity)[:top_n], failures
