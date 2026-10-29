"""
Checks on LLM-written text before it replaces the deterministic text.

The LLM only rewords facts the engine computed. A text is rejected, and
the deterministic text kept, if it:
  - makes a guarantee, risk-free, certainty, optimality, live-data or
    execution claim (the Portfolio Agent's checks, reused);
  - uses a number that is not in the facts it was given;
  - mentions fees (or, in a product reason, any cost: costs never justify a product);
  - gives advice to someone ("you should", "investors should") or calls a
    product the best;
  - names a product id or citation it was not given.
View narratives also have stance checks (see check_view_slot).
"""
import re
from typing import Iterable, Optional

from app.agents.portfolio_agent.explain.guardrails import find_claim_violations

_TAG = re.compile(r"\[([A-Za-z0-9-]+)\]")
# Illustrative ids (MOCK-CORP-001) and live ids (FND-<ISIN>, FND-ALT-001 for funds without an ISIN).
_PRODUCT_ID = re.compile(r"\b(?:MOCK-[A-Z]+-\d+|FND-(?:ALT-\d{3}|[A-Z]{2}[A-Z0-9]{9}\d))\b")
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_FEE = re.compile(r"\b(?:fees?|expense ratio|TER|commissions?)\b", re.I)
# Market prose may talk about financing costs; a product reason may not talk about any cost.
_COST = re.compile(r"\b(?:costs?|costly|charges?|cheap(?:er|est)?|expensive|pricey|value for money)\b", re.I)
_ADVICE = re.compile(r"\byou(?:r|rs)?\b|\b(?:investors|clients?|the client) (?:should|must|ought to)\b|"
                     r"\bshould (?:buy|sell|invest|hold|consider|add|switch)\b", re.I)
_SUPERLATIVE = re.compile(r"\bbest\b|\btop pick\b|\bmust[- ]have\b", re.I)
_FORECAST = re.compile(r"\bwill (?:rise|fall|reach|hit|climb|drop|return|rally|decline|outperform|underperform)\b|"
                       r"\bprice target\b|\bis expected to (?:rise|fall|reach|return)\b|\bby (?:the )?end of\b", re.I)
_STANCES = ("Buy", "Hold", "Sell")
# Models often write non-breaking or typographic hyphens ("10‑Year"), which would not match the engine's names.
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–−"})


def normalise(text: str) -> str:
    """LLM text with typographic hyphens as plain ones, so names, ids and numbers compare as the engine wrote them."""
    return text.translate(_DASHES).strip()


_PERCENT = re.compile(r"([+-]?\d+(?:\.\d+)?)\s?%")
_PP = re.compile(r"([+-]?\d+(?:\.\d+)?)\s?pp\b")


def pp_only_numbers(engine_text: str, percent_values: Iterable[float] = ()) -> set[float]:
    """Numbers the engine writes as pp and never as %, e.g. a 3-month rise in a yield."""
    pp = {abs(float(m.group(1))) for m in _PP.finditer(engine_text)}
    pct = {abs(float(m.group(1))) for m in _PERCENT.finditer(engine_text)} | {abs(v) for v in percent_values}
    return pp - pct


def stances_in(text: str) -> set[str]:
    return {w for w in _STANCES if re.search(rf"\b{w}\b", text)}
_SEGMENT_STANCES = ("Most preferred", "Least preferred")


def numbers_in(text: str) -> set[float]:
    """Every number in text, as absolute values; ids and tags are left out by the caller."""
    return {abs(float(m.group(0).replace(",", ""))) for m in _NUMBER.finditer(text)}


def _strip_ids(text: str) -> str:
    return _PRODUCT_ID.sub(" ", _TAG.sub(" ", text))


def _number_violations(text: str, allowed: set[float]) -> list[str]:
    bad = []
    for v in numbers_in(_strip_ids(text)):
        if not any(abs(v - a) <= 0.051 for a in allowed):
            bad.append(f"number {v:g} is not in the facts")
    return bad


def _common(text: str, allowed_numbers: set[float]) -> list[str]:
    problems = find_claim_violations(text) + _number_violations(text, allowed_numbers)
    if m := _FEE.search(text):
        problems.append(f"mentions fees: '{m.group(0)}'")
    if m := _ADVICE.search(text):
        problems.append(f"advice wording: '{m.group(0)}'")
    if m := _SUPERLATIVE.search(text):
        problems.append(f"superlative: '{m.group(0)}'")
    return problems


def check_bullet(text: str, product_id: str, allowed_citations: set[str], allowed_numbers: set[float],
                 other_names: Iterable[str]) -> list[str]:
    """One product-reason bullet: it must end in an allowed citation and talk only about its own product."""
    problems = _common(text, allowed_numbers)
    if m := _COST.search(text):
        problems.append(f"mentions cost: '{m.group(0)}'")
    tags = _TAG.findall(text)
    if not tags or not re.search(r"\]\s*\.?\s*$", text):
        problems.append("does not end in a citation tag")
    if unknown := sorted(set(tags) - allowed_citations):
        problems.append(f"unknown citation {', '.join(unknown)}")
    if others := sorted({i for i in _PRODUCT_ID.findall(_TAG.sub(" ", text)) if i != product_id}):
        problems.append(f"names another product {', '.join(others)}")
    lowered = text.lower()
    if named := sorted(n for n in other_names if n and n.lower() in lowered):
        problems.append(f"names another product '{named[0]}'")
    return problems


def check_view_slot(kind: str, text: str, allowed_numbers: set[float], *, agent_view: str, agent_confidence: str,
                    cio_view: str, cio_term: str, stance: Optional[str] = None, insufficient: bool = False,
                    evidence_names: Iterable[str] = (), slot_stances: Iterable[str] = (),
                    pp_only: set[float] = frozenset()) -> list[str]:
    """One text slot of an asset-class view. Stances and the CIO's wording are fixed by the engine.
    `slot_stances` are stance words the slot's own facts use, e.g. a scenario that "would move to Sell".
    `pp_only` are numbers the engine gives only in percentage points; writing them as % changes their meaning."""
    problems = _common(text, allowed_numbers)
    for m in _PERCENT.finditer(text):
        if abs(float(m.group(1))) in pp_only:
            problems.append(f"{m.group(0)} is a change in percentage points (pp), not %")
    if _TAG.search(text):
        problems.append("contains a citation tag (refs are attached by code)")
    if m := _FORECAST.search(text):
        problems.append(f"forecast wording: '{m.group(0)}'")
    if re.search(r"\bour (?:house )?view\b|\bwe (?:think|believe|expect|prefer|rate)\b", text, re.I):
        problems.append("presents the agent view as the bank's own")
    # A stance word may only be the agent's, the CIO's or one the slot's facts name; anything else contradicts the engine.
    for word in _STANCES:
        if re.search(rf"\b{word}\b", text) and word not in (agent_view, cio_view, *slot_stances):
            problems.append(f"stance '{word}' is not the agent's, the CIO's or this item's")
    if kind == "thesis":
        if insufficient:
            if not re.search(r"\bnot enough\b|\binsufficient\b", text, re.I):
                problems.append("insufficient evidence is not stated")
        else:
            if not re.search(rf"\b{agent_view}\b", text):
                problems.append(f"thesis does not state the agent view {agent_view}")
            if agent_confidence.lower() not in text.lower():
                problems.append(f"thesis does not state {agent_confidence.lower()} confidence")
    if kind == "segment" and stance:
        for s in _SEGMENT_STANCES:
            if s.lower() in text.lower() and s != stance:
                problems.append(f"segment text says '{s}' but the segment is {stance}")
    if kind == "agreement":
        if cio_term.lower() not in text.lower():
            problems.append(f"does not quote the CIO term '{cio_term}'")
        names = [n for n in evidence_names if n]
        if names and not any(n.lower() in text.lower() for n in names):
            problems.append("does not name the evidence behind the difference")
    return problems
