"""
Shared plumbing for every data adapter: normalized point type, retries with
exponential backoff + jitter (only on 429/5xx/timeouts/transport errors),
and a per-provider token bucket.

Every adapter returns plain `SeriesPoint` lists so the analytics layer
never sees provider-specific shapes.
"""
import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import httpx

logger = logging.getLogger("market_researcher")

# httpx logs every request URL at INFO, and FRED only accepts its API key
# as a query parameter - keep those lines out of the logs entirely.
logging.getLogger("httpx").setLevel(logging.WARNING)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class SeriesPoint:
    date: date
    value: float


class SourceError(Exception):
    """A data source failed in a way the pipeline should record and route around."""


class TokenBucket:
    """Async token bucket: `rate` tokens/second, bursting up to `capacity`."""

    def __init__(self, rate: float, capacity: Optional[float] = None):
        self.rate = rate
        self.capacity = capacity if capacity is not None else max(1.0, rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self.rate)


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    source: str,
    params: Optional[dict[str, Any]] = None,
    json: Optional[dict[str, Any]] = None,
    timeout: float = 10.0,
    retries: int = 3,
    base_delay: float = 0.5,
    bucket: Optional[TokenBucket] = None,
) -> httpx.Response:
    """Send a request, retrying transient failures. Raises SourceError when
    retries are exhausted or the failure isn't transient (e.g. a 400/401).

    `source` labels log lines; params are never logged since they can carry
    API keys.
    """
    last_error = "unknown error"
    for attempt in range(retries + 1):
        if bucket is not None:
            await bucket.acquire()
        started = time.monotonic()
        try:
            response = await client.request(method, url, params=params, json=json, timeout=timeout)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = f"{type(e).__name__}"
            logger.info("source=%s attempt=%d error=%s", source, attempt + 1, last_error)
        else:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info("source=%s attempt=%d status=%d latency_ms=%d", source, attempt + 1, response.status_code, elapsed_ms)
            if response.status_code < 400:
                return response
            last_error = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUS:
                raise SourceError(f"{source}: {last_error}")
        if attempt < retries:
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay + random.uniform(0, delay))
    raise SourceError(f"{source}: {last_error} after {retries + 1} attempts")
