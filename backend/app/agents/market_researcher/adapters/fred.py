"""
FRED adapter - macro and rates series from the St. Louis Fed API.

FRED marks missing observations with "." - those are dropped, not zeroed.
Pass `vintage_date` to get ALFRED real-time data as it was known on that
date (avoids look-ahead bias from later revisions when replaying a past
`as_of`).
"""
from datetime import date
from typing import Optional

import httpx

from app.agents.market_researcher.adapters.base import (
    SeriesPoint,
    SourceError,
    TokenBucket,
    request_with_retry,
)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED documents 120 requests/minute per key.
_DEFAULT_BUCKET_RATE = 2.0


def parse_observations(payload: dict) -> list[SeriesPoint]:
    points: list[SeriesPoint] = []
    for obs in payload.get("observations", []):
        raw = obs.get("value")
        if raw in (None, "", "."):
            continue
        try:
            points.append(SeriesPoint(date.fromisoformat(obs["date"]), float(raw)))
        except (KeyError, ValueError):
            continue
    points.sort(key=lambda p: p.date)
    return points


class FredClient:
    def __init__(
        self,
        api_key: str,
        client: Optional[httpx.AsyncClient] = None,
        bucket: Optional[TokenBucket] = None,
        timeout: float = 10.0,
        retries: int = 3,
        base_delay: float = 0.5,
    ):
        if not api_key:
            raise ValueError("FRED_API_KEY is not set")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._bucket = bucket or TokenBucket(_DEFAULT_BUCKET_RATE, capacity=10)
        self._timeout = timeout
        self._retries = retries
        self._base_delay = base_delay

    async def get_series(
        self,
        series_id: str,
        start: date,
        end: Optional[date] = None,
        vintage_date: Optional[date] = None,
    ) -> list[SeriesPoint]:
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
        }
        if end is not None:
            params["observation_end"] = end.isoformat()
        if vintage_date is not None:
            params["realtime_start"] = vintage_date.isoformat()
            params["realtime_end"] = vintage_date.isoformat()

        response = await request_with_retry(
            self._client, "GET", FRED_OBSERVATIONS_URL,
            source=f"FRED:{series_id}", params=params, timeout=self._timeout,
            retries=self._retries, base_delay=self._base_delay, bucket=self._bucket,
        )
        try:
            return parse_observations(response.json())
        except ValueError as e:
            raise SourceError(f"FRED:{series_id}: invalid JSON") from e

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
