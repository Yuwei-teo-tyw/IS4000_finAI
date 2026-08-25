"""
Finance term glossary - maps common financial shorthand/acronyms to their
full form, so the finance agent's scope check and reasoning aren't tripped
up by jargon a user types instead of the full term (e.g. "what's a good
P/E" instead of "what's a good price-to-earnings ratio").

There's no standard external API for this kind of term normalization -
market-data APIs (Alpha Vantage, IEX, FRED, etc.) return prices/fundamentals,
not glossary lookups - so this is a small static local mapping. Extend
FINANCIAL_TERM_GLOSSARY as new shorthand comes up in practice.
"""
import re
from typing import Dict

FINANCIAL_TERM_GLOSSARY: Dict[str, str] = {
    "p/e": "price-to-earnings ratio",
    "pe ratio": "price-to-earnings ratio",
    "eps": "earnings per share",
    "roi": "return on investment",
    "roe": "return on equity",
    "roa": "return on assets",
    "yoy": "year-over-year",
    "qoq": "quarter-over-quarter",
    "mtd": "month-to-date",
    "ytd": "year-to-date",
    "aum": "assets under management",
    "capex": "capital expenditures",
    "opex": "operating expenses",
    "ebitda": "earnings before interest, taxes, depreciation, and amortization",
    "cagr": "compound annual growth rate",
    "dca": "dollar-cost averaging",
    "etf": "exchange-traded fund",
    "ipo": "initial public offering",
    "div yield": "dividend yield",
    "mcap": "market capitalization",
    "nav": "net asset value",
    "apr": "annual percentage rate",
    "apy": "annual percentage yield",
    "401k": "401(k) retirement account",
    "ira": "individual retirement account",
    "hoa": "homeowners association fee",
    "fomo": "fear of missing out",
    "bull": "bullish (expecting prices to rise)",
    "bear": "bearish (expecting prices to fall)",
}

# Longest phrase first so multi-word terms (e.g. "div yield") match before
# any shorter term that could be a substring of them.
_PATTERN = re.compile(
    "|".join(
        rf"(?<!\w){re.escape(term)}(?!\w)"
        for term in sorted(FINANCIAL_TERM_GLOSSARY, key=len, reverse=True)
    ),
    re.IGNORECASE,
)


def normalize_financial_terms(text: str) -> str:
    """
    Expand recognized financial shorthand/acronyms in `text`, appending
    the full term in parentheses next to each match. Leaves the original
    wording intact and ignores anything not in the glossary.

    e.g. "is this a good p/e?" -> "is this a good p/e (price-to-earnings
    ratio)?"
    """
    if not text:
        return text

    def _expand(match: re.Match) -> str:
        expansion = FINANCIAL_TERM_GLOSSARY[match.group(0).lower()]
        return f"{match.group(0)} ({expansion})"

    return _PATTERN.sub(_expand, text)
