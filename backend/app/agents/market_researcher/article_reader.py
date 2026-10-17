"""
Reader view for the chat UI's news side panel: fetch one article that a run
cited, extract its main text (like a browser's reader mode), and return it
with the agent's own summary/tags.

Most news sites refuse to be embedded in an iframe (X-Frame-Options /
CSP frame-ancestors), so the panel shows extracted text instead of the live
page. This is the narrow fallback the design guide allows (§3.4): only
URLs the agent already cited, robots.txt respected, short timeouts,
paywalled/blocked pages fail gracefully back to the summary.

Safety: the URL must be one of the news URLs or event-explanation sources
recorded in that run's JSON file, so this can't be used as an open proxy. Every request (including
redirects) is also checked to resolve to a public IP address.
"""
import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.agents.market_researcher.cache import Cache

USER_AGENT = "Mozilla/5.0 (compatible; MarketResearcherReader/1.0; +reader-view)"
FETCH_TIMEOUT_SECONDS = 10.0
MAX_HTML_BYTES = 3_000_000
MIN_ARTICLE_CHARS = 400          # below this it's a video page, consent wall or paywall teaser
ARTICLE_TTL_SECONDS = 24 * 3600
UNAVAILABLE_TTL_SECONDS = 3600   # retry blocked/failed pages after an hour
RATE_LIMITED_TTL_SECONDS = 600   # a 429 is often a temporary throttle - retry sooner
RUN_ID_PATTERN = re.compile(r"^mr_\d{8}T\d{6}Z_[0-9a-f]{6}$")


class ArticleNotFoundError(LookupError):
    """The run doesn't exist, or the URL isn't one of its news / explanation sources."""


class BlockedAddressError(RuntimeError):
    pass


def find_news_item(output_dir: Path, run_id: str, url: str) -> dict:
    """The run's recorded news item - or event-explanation source - for `url`
    (raises ArticleNotFoundError)."""
    if not RUN_ID_PATTERN.match(run_id):
        raise ArticleNotFoundError(f"invalid run id {run_id!r}")
    path = output_dir / f"{run_id}.json"
    if not path.is_file():
        raise ArticleNotFoundError(f"unknown run {run_id}")
    output = json.loads(path.read_text(encoding="utf-8"))
    for item in output.get("news") or []:
        if item.get("url") == url:
            return item
    # Sources cited by event explanations come from the explainer's own targeted
    # searches, so they are usually not in `news`.
    for x in output.get("event_explanations") or []:
        sources = {s.get("url"): s for s in x.get("cited_sources") or []}
        if url in sources or url in (x.get("cited_urls") or []):
            src = sources.get(url, {})
            return {
                "url": url, "title": src.get("title"), "source": src.get("source") or urlsplit(url).netloc,
                "published_at": src.get("published_at"), "summary": x.get("explanation"), "topics": [],
                "sentiment": None, "market_impact": None,
            }
    raise ArticleNotFoundError("URL is not one of this run's news or explanation sources")


async def _ensure_public_host(host: str) -> None:
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise BlockedAddressError(f"{host} resolves to a non-public address")


async def _check_request(request: httpx.Request) -> None:
    if request.url.scheme not in ("http", "https"):
        raise BlockedAddressError(f"unsupported scheme {request.url.scheme}")
    await _ensure_public_host(request.url.host)


async def _robots_allows(client: httpx.AsyncClient, url: str) -> bool:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        resp = await client.get(robots_url, timeout=5.0)
    except httpx.HTTPError:
        return True  # unreachable robots.txt: no stated restriction
    if resp.status_code >= 400:
        return True  # RFC 9309: an unavailable robots.txt (4xx) means no restrictions
    parser = RobotFileParser()
    parser.parse(resp.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def extract_article(html: str, url: str) -> Optional[dict]:
    """Main text + metadata via trafilatura, or None if nothing usable."""
    import trafilatura

    raw = trafilatura.extract(
        html, url=url, output_format="json", with_metadata=True,
        include_comments=False, include_tables=False, favor_precision=True,
    )
    if not raw:
        return None
    data = json.loads(raw)
    text = (data.get("text") or "").strip()
    if len(text) < MIN_ARTICLE_CHARS:
        return None
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    title = data.get("title") or None
    if title and paragraphs and paragraphs[0].lower() == title.strip().lower():
        paragraphs = paragraphs[1:]  # the page's <h1> repeating the title
    return {
        "title": title,
        "author": data.get("author") or None,
        "published": data.get("date") or None,
        "paragraphs": paragraphs,
    }


async def fetch_article(url: str, client: Optional[httpx.AsyncClient] = None) -> dict:
    """{"status": "ok", ...article} or {"status": "unavailable", "reason": ...}."""
    own_client = client is None
    client = client or httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        follow_redirects=True,
        max_redirects=5,
        timeout=FETCH_TIMEOUT_SECONDS,
        event_hooks={"request": [_check_request]},
    )
    try:
        if not await _robots_allows(client, url):
            return {"status": "unavailable", "reason": "The site's robots.txt does not allow automated reading."}
        resp = await client.get(url)
        if resp.status_code in (401, 402, 403):
            return {"status": "unavailable", "reason": "The site blocks automated access or requires a subscription."}
        # Anti-bot systems often answer the first automated request with 429.
        if resp.status_code == 429:
            return {"status": "unavailable", "http_status": 429,
                    "reason": "The site limits automated readers right now; open the original to read it."}
        if resp.status_code in (404, 410):
            return {"status": "unavailable", "http_status": resp.status_code,
                    "reason": "The site says this page has moved or been removed."}
        if resp.status_code >= 400:
            return {"status": "unavailable", "reason": f"The site returned HTTP {resp.status_code}."}
        if "html" not in resp.headers.get("content-type", "html"):
            return {"status": "unavailable", "reason": "The link is not an HTML article."}
        if len(resp.content) > MAX_HTML_BYTES:
            return {"status": "unavailable", "reason": "The page is too large to process."}
        article = await asyncio.to_thread(extract_article, resp.text, str(resp.url))
        if article is None:
            return {"status": "unavailable",
                    "reason": "No readable article text found (it may be a video, a paywall or a consent page)."}
        return {"status": "ok", **article}
    except BlockedAddressError:
        return {"status": "unavailable", "reason": "The link points to a disallowed address."}
    except httpx.TimeoutException:
        return {"status": "unavailable", "reason": "The site took too long to respond."}
    except httpx.HTTPError:
        return {"status": "unavailable", "reason": "The site could not be reached."}
    finally:
        if own_client:
            await client.aclose()


async def read_article(output_dir: Path, run_id: str, url: str, cache: Cache) -> dict:
    """Reader-view payload for one cited article: the agent's own metadata
    always, plus extracted text when the page allows it."""
    item = find_news_item(output_dir, run_id, url)
    key = "article:" + hashlib.sha256(url.encode()).hexdigest()
    article = await cache.get(key)
    if article is None:
        article = await fetch_article(url)
        if article["status"] == "ok":
            ttl = ARTICLE_TTL_SECONDS
        elif article.get("http_status") == 429:
            ttl = RATE_LIMITED_TTL_SECONDS
        else:
            ttl = UNAVAILABLE_TTL_SECONDS
        await cache.set(key, article, ttl)
    return {
        "url": url,
        "source": item.get("source"),
        "title": article.get("title") or item.get("title"),
        "published": article.get("published") or item.get("published_at"),
        "author": article.get("author"),
        "summary": item.get("summary"),
        "topics": item.get("topics") or [],
        "sentiment": item.get("sentiment"),
        "market_impact": item.get("market_impact"),
        "status": article["status"],
        "reason": article.get("reason"),
        "paragraphs": article.get("paragraphs") or [],
    }
