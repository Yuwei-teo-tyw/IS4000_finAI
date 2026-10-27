"""Rule-based key-fact extraction for the Client Profiling Agent.

Regex over meeting-note sentences ONLY (IPS text is never read). Every Fact carries SourceRef(s) with a
verbatim passage. kind is "documented" only when the text states it; "calculated" for
arithmetic over documented facts; "inferred" for heuristic readings (never documented);
"missing" when nothing in the sources supports the field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .retrieval import note_ref, split_sentences
from .schemas import ClientProfile, Conflict, Fact, SourceRef
from .store import DocumentStore

AMT = r"S\$\s?([\d,]+(?:\.\d+)?)(?:\s?(m|k)\b)?"
_SKIP_PREFIX = ("next steps", "open question")
ASSET_CLASSES = ["private markets", "hedge funds", "real estate", "fixed income", "equities", "bonds", "cash", "gold", "alternatives"]
EXCLUDABLE = ["tobacco", "thermal coal", "fossil fuels", "fossil fuel", "weapons", "gambling", "hedge funds", "private markets", "real estate", "gold"]
SECTOR_EXCL = {"tobacco", "thermal coal", "fossil fuels", "fossil fuel", "weapons", "gambling"}


def _money_last(m: re.Match) -> float:
    """Value of the AMT groups, which are always the last two groups of the pattern."""
    n = m.re.groups
    v = float(m.group(n - 1).replace(",", ""))
    suf = (m.group(n) or "").lower()
    return v * (1_000_000 if suf == "m" else 1_000 if suf == "k" else 1)


def _first_amt(s: str, start_pat: str) -> Optional[float]:
    m = re.search((start_pat + r"[^.]*?" if start_pat else "") + AMT, s, re.I)
    return _money_last(m) if m else None


# ---- sentence rules: fn(sentence) -> scalar value / list of values / None ----
def _aum(s):
    if re.search(r"investable assets", s, re.I):
        return _first_amt(s, r"investable assets")
    m = re.search(r"\bhas " + AMT + r" to invest", s, re.I)
    return _money_last(m) if m else None


def _other_assets(s):
    return _first_amt(s, r"other assets") if re.search(r"other assets", s, re.I) else None


def _liabilities(s):
    if re.search(r"\bno outstanding (liabilities|loans?|debts?|mortgage)", s, re.I):
        return 0.0
    return _first_amt(s, r"\b(?:mortgage|loan|liabilit\w*|debt)") if re.search(r"mortgage|\bloan|liabilit|\bdebt", s, re.I) else None


def _income(s):
    if re.search(r"salary|income|earns|bonus", s, re.I) and re.search(r"a year|per year|annual|p\.a\.", s, re.I):
        return _first_amt(s, r"(?:salary|income|earns|bonus)")
    return None


def _monthly_need(s):
    if re.search(r"expenses|spending|spends|cash need|living costs", s, re.I) and re.search(r"a month|per month|monthly|each month", s, re.I):
        # the amount that follows the spending word, so "reserve of S$400,000 and spends S$20,000 a month" reads 20,000
        return _first_amt(s, r"(?:expenses|spending|spends|cash need|living costs)") or _first_amt(s, "")
    return None


def _savings(s):
    return _first_amt(s, r"\bsaves") if re.search(r"\bsaves", s, re.I) else None


def _liquidity_need(s):
    m = re.search(r"cash reserve[^.]*?" + AMT, s, re.I)
    if m:
        return _money_last(m)
    if not re.search(r"deposit", s, re.I):
        return None
    m = re.search(AMT + r"\s+deposit", s, re.I)
    if m:
        return _money_last(m)
    return _first_amt(s, r"deposit")


_GOALS = [
    ("house_purchase", r"\b(?:buy|buying|purchase)\b"),
    ("retirement", r"retir"),
    ("income", r"\bincome\b"),
    ("education", r"education|tuition"),
    ("family_foundation", r"foundation|philanthrop"),
    ("legacy", r"legacy|bequest|inheritance"),
    ("capital_preservation", r"capital safe|preserve|capital preservation"),
    ("growth", r"\bgrow\b|long-term growth"),
]


def _goals(s):
    out = [g for g, p in _GOALS if re.search(p, s, re.I)]
    return out or None


_HORIZON = [r"at least \w+ years", r"within (?:the next )?\w+ (?:months|years)", r"\bin (?:about )?\w+ years", r"\d+\+\s?years", r"\bover \d+ years"]


def _horizon(s):
    out = []
    for p in _HORIZON:
        out += [m.group(0) for m in re.finditer(p, s, re.I)]
    return out or None


def _knowledge(s):
    if re.search(r"experienced investor|has been investing|has invested|invested in|familiar with|new to investing|first-time investor|novice|no prior investment", s, re.I):
        return s
    return None


def _risk_statement(s):
    return s if re.search(r"volatility|large swings|uncomfortable|dislikes|risk appetite|risk[- ]averse|comfortable with|worries", s, re.I) else None


def _note_drawdown(s):
    if re.search(r"\b(fall|drop|decline|loss)\b", s, re.I) and re.search(r"uncomfortable|prompt (?:him|her) to sell|dislike", s, re.I):
        m = re.search(r"(\d+(?:\.\d+)?)\s?%", s)
        return float(m.group(1)) if m else None
    return None


def _asset_pref(s):
    if re.search(r"\bprefer|would like to hold|more in|open to adding|interested in|wants to hold", s, re.I):
        found = [a for a in ASSET_CLASSES if re.search(rf"\b{a}\b", s, re.I)]
        return found or None
    return None


def _restrictions(s):
    if re.search(r"\b(avoid|exclude|excluding|no|without|removed?|not want)\b", s, re.I):
        found = [e.lower() for e in EXCLUDABLE if re.search(rf"\b{e}\b", s, re.I)]
        return found or None
    return None


def _sustainability(s):
    out = [m.group(0).lower() for m in re.finditer(r"\bESG(?:-aligned)?\b|sustainab\w+|responsible investing|ethical", s, re.I)]
    if re.search(r"\b(avoid|exclude|excluding)\b", s, re.I):
        out += [f"exclude {e.lower()}" for e in EXCLUDABLE if e in SECTOR_EXCL and re.search(rf"\b{e}\b", s, re.I)]
    return out or None


def _currency(s):
    if re.search(r"prefer|keep|hold|mainly|only|stay in|wants", s, re.I):
        return re.findall(r"\b(SGD|USD|EUR|GBP|HKD|CHF)\b", s) or None
    return None


@dataclass
class Rule:
    field: str
    category: str
    fn: Callable[[str], Any]
    mode: str = "scalar"          # scalar: latest note value; list: union of values
    notes: bool = True


RULES = [
    Rule("aum_managed_sgd", "client_financial", _aum),
    Rule("other_assets_sgd", "client_financial", _other_assets),
    Rule("liabilities_sgd", "client_financial", _liabilities),
    Rule("annual_income_sgd", "client_financial", _income),
    Rule("monthly_cash_need_sgd", "client_financial", _monthly_need),
    Rule("monthly_savings_sgd", "client_financial", _savings),
    Rule("goals", "objectives", _goals, "list", (1,)),
    Rule("investment_horizon", "objectives", _horizon, "list"),
    Rule("liquidity_need_sgd", "objectives", _liquidity_need, "scalar", (1,)),
    Rule("risk_attitude_statements", "risk", _risk_statement, "list"),
    Rule("drawdown_tolerance_pct", "risk", _note_drawdown, "scalar"),
    Rule("knowledge_experience", "risk", _knowledge, "list"),
    Rule("asset_class_preferences", "preferences", _asset_pref, "list"),
    Rule("restrictions", "preferences", _restrictions, "list", (1,)),
    Rule("sustainability_preferences", "preferences", _sustainability, "list", (1,)),
    Rule("currency_preference", "preferences", _currency, "list"),
]
REQUIRED = ["aum_managed_sgd", "other_assets_sgd", "liabilities_sgd", "annual_income_sgd", "monthly_cash_need_sgd", "goals",
            "investment_horizon", "liquidity_need_sgd", "knowledge_experience",
            "sustainability_preferences", "currency_preference", "restrictions"]
CATEGORY = {r.field: r.category for r in RULES} | {
    "risk_classification": "risk", "risk_capacity": "risk", "risk_tolerance": "risk",
    "annual_cash_need_sgd": "client_financial", "max_loss_at_drawdown_sgd": "risk", "liquidity_need_pct_of_aum": "objectives"}
CONFLICT_FIELDS = {"liquidity_need_sgd": "S${:,.0f}", "drawdown_tolerance_pct": "{:g}%"}


@dataclass
class Cand:
    field: str
    value: Any
    ref: SourceRef
    date: str


def _collect(notes) -> list[Cand]:
    cands: list[Cand] = []
    for rule in RULES:
        if rule.notes:
            for n in notes:
                for s in split_sentences(n.text):
                    v = None if s.lower().startswith(_SKIP_PREFIX) else rule.fn(s)
                    if v is not None:
                        cands.append(Cand(rule.field, v, note_ref(n, s), n.date))
    return cands


def _same(a, b) -> bool:
    return abs(a - b) < 1e-9 if isinstance(a, (int, float)) and isinstance(b, (int, float)) else a == b


def extract_key_facts(store: DocumentStore, client_id: str, ips_version: Optional[int] = None) -> ClientProfile:
    """Key facts from meeting notes only. `ips_version` is accepted for compatibility and ignored."""
    client = store.get_client(client_id)
    if not client:
        raise ValueError(f"Unknown client_id '{client_id}'")
    notes = sorted(store.get_notes(client_id), key=lambda n: (n.date, n.id))
    profile = ClientProfile(client_id=client.id, client_name=client.name, ips_version_used=None, ips_status=None)
    cands = _collect(notes)
    facts: list[Fact] = []
    conflicts: list[Conflict] = []
    outdated: list[str] = []

    # ---- documented facts ----
    for rule in RULES:
        cs = [c for c in cands if c.field == rule.field]
        if not cs:
            continue
        if rule.mode == "list":
            values: list = []
            srcs: list[SourceRef] = []
            seen = set()
            for c in sorted(cs, key=lambda c: c.date):
                key = (c.ref.id, c.ref.passage)
                if key in seen:
                    continue
                seen.add(key)
                for v in (c.value if isinstance(c.value, list) else [c.value]):
                    if v not in values:
                        values.append(v)
                srcs.append(c.ref)
            note = "Union of statements across the meeting notes; later notes may refine earlier ones." if rule.field != "risk_attitude_statements" else "Client's own words, verbatim; not a confirmed risk classification."
            facts.append(Fact(field=rule.field, category=rule.category, value=values, kind="documented", sources=srcs,
                              note=note))
            continue
        note_cs = sorted(cs, key=lambda c: c.date)
        if True:
            chosen = note_cs[-1]
            diff = [c for c in note_cs[:-1] if not _same(c.value, chosen.value)]
            note = f"Latest statement used ({chosen.date})."
            if diff:
                note += " Earlier notes stated different values: " + ", ".join(f"{c.value} ({c.ref.id})" for c in diff) + "."
            if rule.field == "aum_managed_sgd" and "to invest" in (chosen.ref.passage or ""):
                note += " Stated as an amount to invest; confirm it is booked with the bank."
            facts.append(Fact(field=rule.field, category=rule.category, value=chosen.value, kind="documented",
                              sources=[chosen.ref] + [c.ref for c in diff], note=note))
    by = {f.field: f for f in facts}

    # ---- risk tolerance: inferred from the client's own statements, else missing ----
    if "risk_attitude_statements" in by:
        txt = " ".join(by["risk_attitude_statements"].value).lower()
        if re.search(r"comfortable with large swings", txt):
            label = "high (inferred)"
        elif re.search(r"risk[- ]averse", txt):
            label = "low (inferred)"
        elif re.search(r"dislikes|uncomfortable|worries", txt):
            label = "low-to-moderate (inferred)"
        else:
            label = "moderate (inferred)"
        facts.append(Fact(field="risk_tolerance", category="risk", value=label, kind="inferred", sources=by["risk_attitude_statements"].sources,
                          note="INFERRED from the client's statements in the meeting notes; not a documented classification. Run the risk questionnaire."))

    # ---- calculated facts ----
    def num(f):
        return by[f].value if f in by and isinstance(by[f].value, (int, float)) else None
    if (m := num("monthly_cash_need_sgd")) is not None:
        facts.append(Fact(field="annual_cash_need_sgd", category="client_financial", value=m * 12, kind="calculated",
                          sources=by["monthly_cash_need_sgd"].sources, note="Calculated: monthly cash need x 12."))
    if (aum := num("aum_managed_sgd")) and (dd := num("drawdown_tolerance_pct")) is not None:
        facts.append(Fact(field="max_loss_at_drawdown_sgd", category="risk", value=round(aum * dd / 100, 2), kind="calculated",
                          sources=by["aum_managed_sgd"].sources + by["drawdown_tolerance_pct"].sources,
                          note=f"Calculated: managed assets x {dd:g}% drawdown tolerance (capacity evidence, not a forecast)."))
    if aum and (liq := num("liquidity_need_sgd")):
        facts.append(Fact(field="liquidity_need_pct_of_aum", category="objectives", value=round(liq / aum * 100, 1), kind="calculated",
                          sources=by["liquidity_need_sgd"].sources + by["aum_managed_sgd"].sources,
                          note="Calculated: liquidity need / managed assets x 100."))

    # ---- missing ----
    have = {f.field for f in facts}
    for field in REQUIRED:
        if field not in have:
            profile.missing.append(field)
            where = "the meeting notes"
            facts.append(Fact(field=field, category=CATEGORY[field], value=None, kind="missing",
                              note=f"Not stated in {where}. Confirm with the client."))
    if "risk_tolerance" not in {f.field for f in facts}:
        profile.missing.append("risk_tolerance")
        facts.append(Fact(field="risk_tolerance", category="risk", value=None, kind="missing",
                          note="No risk statement found in the meeting notes. Run the risk questionnaire."))

    profile.facts = facts
    profile.conflicts = conflicts
    profile.outdated = outdated
    seen, srcs = set(), []
    for f in facts:
        for s in f.sources:
            k = (s.type, s.id, s.passage)
            if k not in seen:
                seen.add(k)
                srcs.append(s)
    for c in conflicts:
        for s in c.statements:
            k = (s.type, s.id, s.passage)
            if k not in seen:
                seen.add(k)
                srcs.append(s)
    profile.sources = srcs
    return profile
