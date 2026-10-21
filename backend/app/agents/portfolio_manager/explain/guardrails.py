"""
Programmatic checks on LLM-generated narrative before it is accepted.

The LLM only writes prose around numbers the engine already computed, so
its output is rejected (and the deterministic fallback used) if it:
  - makes guarantee / risk-free / certainty claims,
  - claims optimality, live/verified data, or that a trade was executed,
  - states a percentage or amount that doesn't match a computed figure.

Negated forms ("returns are not guaranteed", "not risk-free") are allowed -
those are exactly the caveats we want the narrative to include.
"""
import re
from dataclasses import dataclass, field

_NEGATION = re.compile(r"\b(not|no|never|cannot|can't|without|isn't|aren't|nor|neither)\b[\w\s,'-]{0,25}$", re.I)

_CLAIM_PATTERNS = {
    "guarantee claim": re.compile(r"\bguarantee(?:d|s)?\b", re.I),
    "risk-free claim": re.compile(r"\brisk[- ]free\b|\bno risk\b|\bzero risk\b", re.I),
    "certainty claim": re.compile(
        r"\b(?:certain to|will definitely|sure to|assured return|cannot lose|can't lose|will (?:certainly|surely))\b",
        re.I,
    ),
    "optimality claim": re.compile(r"\b(?:mathematically )?optimal\b|\boptimi[sz]ed portfolio\b", re.I),
    "verified/live data claim": re.compile(
        r"\b(?:verified|real[- ]time|live|current market) (?:data|prices?|market data|yields?|figures|information|quotes?)\b"
        r"|\bactual market data\b|\b(?:data|figures|information|prices|yields) (?:is|are|has been|have been) verified\b",
        re.I,
    ),
    "execution claim": re.compile(
        r"\b(?:has|have) been (?:executed|purchased|bought|sold|placed)\b|\btrades? (?:was|were) executed\b|"
        r"\border(?:s)? (?:was|were|has been|have been) placed\b",
        re.I,
    ),
}

_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s?%")
_AMOUNT = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)(?![\d%])")

_SCALED = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s?(million|mn|m|billion|bn|thousand|k)\b", re.I)
_SCALE = {"million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}

_ANY_NUMBER = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")

PCT_TOLERANCE = 0.06  # allows one-decimal rounding of a 2dp figure
AMOUNT_REL_TOLERANCE = 0.01


@dataclass
class AllowedNumbers:
    percentages: set = field(default_factory=set)
    amounts: set = field(default_factory=set)

    def add_pct(self, *values):
        for v in values:
            if v is not None:
                self.percentages.add(float(v))
                self.percentages.add(abs(float(v)))

    def add_amount(self, *values):
        for v in values:
            if v is not None:
                self.amounts.add(abs(float(v)))

    def add_from_text(self, text: str):
        """Allow every number that appears in text the LLM was given, i.e.
        it may quote its inputs but not introduce new figures."""
        for m in _ANY_NUMBER.finditer(text):
            v = float(m.group(0).replace(",", ""))
            self.add_pct(v)
            self.add_amount(v)


def find_claim_violations(text: str) -> list[str]:
    found = []
    for label, pattern in _CLAIM_PATTERNS.items():
        for m in pattern.finditer(text):
            preceding = text[max(0, m.start() - 40):m.start()]
            if not _NEGATION.search(preceding):
                found.append(f"{label}: '{m.group(0)}'")
    return found


def find_number_violations(text: str, allowed: AllowedNumbers) -> list[str]:
    bad = []
    for m in _PCT.finditer(text):
        v = float(m.group(1))
        if not any(abs(v - a) <= PCT_TOLERANCE for a in allowed.percentages):
            bad.append(f"unsupported percentage {m.group(0)}")
    for m in _AMOUNT.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if v.is_integer() and 1900 <= v <= 2100:
            continue  # a year
        if not any(abs(v - a) <= max(1.0, a * AMOUNT_REL_TOLERANCE) for a in allowed.amounts):
            bad.append(f"unsupported amount {m.group(0)}")
    for m in _SCALED.finditer(text):  # "SGD 2.29 million": rounded, so a looser match
        v = float(m.group(1)) * _SCALE[m.group(2).lower()]
        decimals = len(m.group(1).split(".")[1]) if "." in m.group(1) else 0
        step = _SCALE[m.group(2).lower()] / 10 ** decimals
        if not any(abs(v - a) <= max(step, a * AMOUNT_REL_TOLERANCE) for a in allowed.amounts):
            bad.append(f"unsupported amount {m.group(0)}")
    return bad


def check_text(text: str, allowed: AllowedNumbers) -> list[str]:
    return find_claim_violations(text) + find_number_violations(text, allowed)
