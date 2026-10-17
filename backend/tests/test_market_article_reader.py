"""
Reader view for cited news articles (chat side panel): the run-scoped URL
allowlist, robots.txt, extraction and fallbacks, SSRF guard, caching, and
the /articles endpoint. HTTP is mocked with httpx.MockTransport.
"""
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.market_researcher import article_reader as ar
from app.agents.market_researcher.cache import InMemoryCache
from app.agents.market_researcher.runs import InMemoryRunRegistry, MarketResearchRunner
from app.endpoints.market_researcher import ui_router

from conftest import run_async
from test_market_service import make_service

RUN_ID = "mr_20261016T072553Z_4faf42"
URL = "https://news.example.com/2026/10/15/yields"
ARTICLE_HTML = (
    "<html><head><title>Yields slide</title></head><body><article><h1>Yields slide to three-week lows</h1>"
    + "".join(f"<p>Paragraph {i}: Treasury yields fell as investors digested the latest inflation data "
              f"and weighed what it means for the Federal Reserve's next move.</p>" for i in range(8))
    + "</article></body></html>"
)


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / f"{RUN_ID}.json").write_text(json.dumps({"news": [{
        "title": "Yields slide", "url": URL, "source": "news.example.com", "published_at": "2026-10-15T08:00:00Z",
        "summary": "Ten-year yields fell to three-week lows.", "topics": ["rates"],
        "sentiment": "risk_on", "market_impact": "medium",
    }]}))
    return tmp_path


def client_for(routes):
    def handler(request):
        for path, response in routes.items():
            if request.url.path == path:
                return response
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


# --- allowlist ----------------------------------------------------------------

def test_find_news_item_only_allows_cited_urls(run_dir):
    assert ar.find_news_item(run_dir, RUN_ID, URL)["summary"].startswith("Ten-year")
    with pytest.raises(ar.ArticleNotFoundError):
        ar.find_news_item(run_dir, RUN_ID, "https://evil.example/x")
    with pytest.raises(ar.ArticleNotFoundError):
        ar.find_news_item(run_dir, "mr_20991231T000000Z_000000", URL)
    with pytest.raises(ar.ArticleNotFoundError):
        ar.find_news_item(run_dir, "../../etc/passwd", URL)


def test_explanation_sources_are_allowed(tmp_path):
    """'Why: ... [source]' links come from the explainer's own searches, not `news`."""
    src = "https://wire.example/2026/10/14/auction"
    (tmp_path / f"{RUN_ID}.json").write_text(json.dumps({"news": [], "event_explanations": [{
        "event_id": "dgs10_sharp_move_up", "status": "explained", "explanation": "Reports cite a weak auction.",
        "cited_urls": [src, "https://old-run.example/no-sources"],
        "cited_sources": [{"url": src, "title": "Weak auction lifts yields", "source": "wire.example",
                           "published_at": "2026-10-14T09:00:00Z"}],
    }]}))
    item = ar.find_news_item(tmp_path, RUN_ID, src)
    assert item["title"] == "Weak auction lifts yields" and item["summary"] == "Reports cite a weak auction."
    assert item["source"] == "wire.example" and item["topics"] == []
    # files written before cited_sources existed: allowed via cited_urls, minimal metadata
    assert ar.find_news_item(tmp_path, RUN_ID, "https://old-run.example/no-sources")["source"] == "old-run.example"
    with pytest.raises(ar.ArticleNotFoundError):
        ar.find_news_item(tmp_path, RUN_ID, "https://evil.example/x")


# --- fetching / extraction ----------------------------------------------------

def test_fetch_article_extracts_text():
    client = client_for({"/robots.txt": httpx.Response(404),
                         "/2026/10/15/yields": httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})})
    result = run_async(ar.fetch_article(URL, client=client))
    assert result["status"] == "ok"
    assert len(result["paragraphs"]) >= 8
    assert any("Treasury yields fell" in p for p in result["paragraphs"])
    assert "<p>" not in " ".join(result["paragraphs"])


def test_fetch_article_respects_robots_txt():
    client = client_for({"/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /")})
    result = run_async(ar.fetch_article(URL, client=client))
    assert result["status"] == "unavailable" and "robots.txt" in result["reason"]


@pytest.mark.parametrize("response,reason", [
    (httpx.Response(403), "subscription"),
    (httpx.Response(500), "HTTP 500"),
    (httpx.Response(429), "limits automated readers"),
    (httpx.Response(404), "moved or been removed"),
    (httpx.Response(410), "moved or been removed"),
    (httpx.Response(200, text="<html><body><p>Watch the video.</p></body></html>", headers={"content-type": "text/html"}),
     "No readable article text"),
    (httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}), "not an HTML"),
])
def test_fetch_article_unavailable_cases(response, reason):
    client = client_for({"/robots.txt": httpx.Response(404), "/2026/10/15/yields": response})
    result = run_async(ar.fetch_article(URL, client=client))
    assert result["status"] == "unavailable" and reason in result["reason"]


def test_requests_to_private_addresses_are_blocked():
    with pytest.raises(ar.BlockedAddressError):
        run_async(ar._check_request(httpx.Request("GET", "http://127.0.0.1/admin")))
    with pytest.raises(ar.BlockedAddressError):
        run_async(ar._check_request(httpx.Request("GET", "file:///etc/passwd")))


# --- read_article: metadata merge + caching -----------------------------------

def test_read_article_merges_metadata_and_caches(run_dir, monkeypatch):
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return {"status": "ok", "title": "Yields slide to three-week lows", "author": "A. Writer",
                "published": "2026-10-15", "paragraphs": ["One.", "Two."]}

    monkeypatch.setattr(ar, "fetch_article", fake_fetch)
    cache = InMemoryCache()
    first = run_async(ar.read_article(run_dir, RUN_ID, URL, cache))
    second = run_async(ar.read_article(run_dir, RUN_ID, URL, cache))

    assert first == second and len(calls) == 1
    assert first["summary"] == "Ten-year yields fell to three-week lows."
    assert first["sentiment"] == "risk_on" and first["paragraphs"] == ["One.", "Two."]


def test_read_article_unavailable_keeps_agent_summary(run_dir, monkeypatch):
    async def blocked(url):
        return {"status": "unavailable", "reason": "The site blocks automated access or requires a subscription."}

    monkeypatch.setattr(ar, "fetch_article", blocked)
    result = run_async(ar.read_article(run_dir, RUN_ID, URL, InMemoryCache()))
    assert result["status"] == "unavailable" and result["paragraphs"] == []
    assert result["title"] == "Yields slide" and result["summary"]


# --- endpoint -----------------------------------------------------------------

def test_articles_endpoint(run_dir, monkeypatch):
    async def fake_fetch(url):
        return {"status": "ok", "title": "T", "author": None, "published": None, "paragraphs": ["Body."]}

    monkeypatch.setattr(ar, "fetch_article", fake_fetch)
    monkeypatch.setenv("MARKET_RESEARCH_API_TOKEN", "s3cret")  # /articles is browser-facing: no token needed
    service = make_service(run_dir)
    app = FastAPI()
    app.include_router(ui_router)
    app.state.market_research = MarketResearchRunner(InMemoryRunRegistry(), service)

    with TestClient(app) as client:
        ok = client.get("/agents/market-researcher/articles", params={"run_id": RUN_ID, "url": URL})
        assert ok.status_code == 200 and ok.json()["paragraphs"] == ["Body."]
        missing = client.get("/agents/market-researcher/articles", params={"run_id": RUN_ID, "url": "https://other.example/"})
        assert missing.status_code == 404


def test_rate_limited_result_cached_briefly(run_dir, monkeypatch):
    ttls = []

    class RecordingCache(InMemoryCache):
        async def set(self, key, value, ttl):
            ttls.append(ttl)
            await super().set(key, value, ttl)

    async def throttled(url):
        return {"status": "unavailable", "http_status": 429, "reason": "limits automated readers"}

    async def gone(url):
        return {"status": "unavailable", "http_status": 404, "reason": "moved or been removed"}

    monkeypatch.setattr(ar, "fetch_article", throttled)
    result = run_async(ar.read_article(run_dir, RUN_ID, URL, RecordingCache()))
    assert result["status"] == "unavailable" and "limits automated readers" in result["reason"]
    monkeypatch.setattr(ar, "fetch_article", gone)
    run_async(ar.read_article(run_dir, RUN_ID, URL, RecordingCache()))
    assert ttls == [ar.RATE_LIMITED_TTL_SECONDS, ar.UNAVAILABLE_TTL_SECONDS]
