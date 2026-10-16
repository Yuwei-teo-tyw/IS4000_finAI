"""
Market prices behind a provider-agnostic interface (guide §3.2).

`YFinanceProvider` is the default: free and keyless, but unofficial and
liable to break - keep it swappable. yfinance is synchronous, so calls run
in a worker thread. Symbols that fail come back missing from the result
rather than raising, so one bad ticker doesn't sink the whole snapshot.
"""
import asyncio
import math
from datetime import date, timedelta
from typing import Protocol

from app.agents.market_researcher.adapters.base import SeriesPoint, SourceError


class MarketDataProvider(Protocol):
    name: str

    async def get_histories(self, symbols: list[str], start: date, end: date) -> dict[str, list[SeriesPoint]]:
        """Daily closes per symbol for [start, end] inclusive; failed symbols are omitted."""
        ...


def _download_closes(symbols: list[str], start: date, end: date) -> dict[str, list[SeriesPoint]]:
    import yfinance as yf

    df = yf.download(
        symbols,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),  # yfinance's end is exclusive
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="column",
    )
    if df is None or df.empty or "Close" not in df:
        return {}
    closes = df["Close"]
    if not hasattr(closes, "items") or getattr(closes, "ndim", 2) == 1:  # single symbol -> Series
        closes = closes.to_frame(symbols[0])

    out: dict[str, list[SeriesPoint]] = {}
    for symbol, column in closes.items():
        points = [
            SeriesPoint(ts.date(), float(v))
            for ts, v in column.items()
            if v is not None and not math.isnan(v)
        ]
        if points:
            out[str(symbol)] = points
    return out


class YFinanceProvider:
    name = "Yahoo Finance (yfinance)"

    async def get_histories(self, symbols: list[str], start: date, end: date) -> dict[str, list[SeriesPoint]]:
        try:
            return await asyncio.to_thread(_download_closes, symbols, start, end)
        except Exception as e:  # yfinance raises a zoo of exception types
            raise SourceError(f"yfinance: {type(e).__name__}: {e}") from e


def get_market_data_provider(name: str) -> MarketDataProvider:
    if name == "yfinance":
        return YFinanceProvider()
    raise ValueError(f"Unknown MARKET_DATA_PROVIDER: {name!r}")
