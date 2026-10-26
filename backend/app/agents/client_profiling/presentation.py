"""Presentation layer: turns tool results into a few concept groups of tight lines.

Deterministic templates only, keyed by fact field names. Each Section is
{heading, meaning (one short sentence), lines: [{text, kind}], sources (deduped union)}.
Figures are computed from the actual values; nothing here invents numbers.
Output goes into ToolResult.data["sections"] (schemas.py is unchanged).
"""
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from .schemas import ClientProfile, Fact, SourceRef, ToolResult

Kind = str  # documented | calculated | inferred | missing
_RANK = {"documented": 0, "calculated": 1, "inferred": 2, "missing": 3}
LINE_MAX = 140


class Line(BaseModel):
    text: str
    kind: Kind = "documented"


class Section(BaseModel):
    heading: str
    meaning: str = ""
    lines: list[Line] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


# --------------------------------------------------------------------------- formatting
def money(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1_000_000 and round(x) % 10_000 == 0:
        return f"{sign}S${x / 1_000_000:.1f}m"
    return f"{sign}S${x:,.0f}"


def pct(v: Any) -> str:
    try:
        return f"{float(v):g}%"
    except (TypeError, ValueError):
        return str(v)


def _words(s: str) -> str:
    return s.replace("_", " ").strip()


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _clip(s: str, n: int = LINE_MAX) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _listing(v: Any, n: int = 6) -> str:
    items = v if isinstance(v, list) else [v]
    out = [_words(str(i)) for i in items if i not in (None, "")]
    return ", ".join(out[:n]) + (f" (+{len(out) - n} more)" if len(out) > n else "")


def _num(f: Optional[Fact]) -> Optional[float]:
    return float(f.value) if f and isinstance(f.value, (int, float)) and not isinstance(f.value, bool) else None


def short_message(msg: str) -> str:
    """First sentence only, clipped: result.message stays one short sentence."""
    first = re.split(r"(?<=[.!?])\s+", " ".join((msg or "").split()), maxsplit=1)[0]
    return _clip(first, 110)


# --------------------------------------------------------------------------- builders
Row = tuple  # (text, kind, [SourceRef])


def _worst(kinds: list[str]) -> Kind:
    return max(kinds or ["documented"], key=lambda k: _RANK.get(k, 0))


def _row(text: str, *facts: Optional[Fact], kind: Optional[str] = None) -> Row:
    fs = [f for f in facts if f is not None]
    srcs = [s for f in fs for s in f.sources]
    return (text, kind or _worst([f.kind for f in fs]), srcs)


def _plain(text: str, kind: str, srcs: Optional[list[SourceRef]] = None) -> Row:
    return (text, kind, list(srcs or []))


def _dedupe(srcs: list[SourceRef]) -> list[SourceRef]:
    out: list[SourceRef] = []
    seen = set()
    for s in srcs:
        k = (s.id, s.passage)
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def _sec(heading: str, meaning: str, rows: list[Row]) -> Section:
    return Section(heading=heading, meaning=_clip(meaning, 160),
                   lines=[Line(text=_clip(t), kind=k) for t, k, _ in rows],
                   sources=_dedupe([s for _, _, ss in rows for s in ss]))


def _ask_rows(asks: list[tuple[str, str]], cap: int = 2) -> list[Row]:
    """asks = [(question, short label)]. At most `cap` lines; extras merged into one 'Ask: also ...' line."""
    if len(asks) <= cap:
        return [_plain("Ask: " + q, "missing") for q, _ in asks]
    rows = [_plain("Ask: " + q, "missing") for q, _ in asks[: cap - 1]]
    rest = ", ".join(lbl for _, lbl in asks[cap - 1:])
    rows.append(_plain(f"Ask: also about {rest}?", "missing"))
    return rows


# --------------------------------------------------------------------------- key facts
_ASK = {
    "aum_managed_sgd": ("how much the client has with the bank to invest?", "managed assets"),
    "other_assets_sgd": ("what the client holds outside the bank (property, other portfolios)?", "other assets"),
    "liabilities_sgd": ("any mortgages or loans (they limit loss capacity)?", "liabilities"),
    "annual_income_sgd": ("annual income, before or after tax and bonus?", "income"),
    "monthly_cash_need_sgd": ("monthly household spending?", "spending"),
    "goals": ("what the money is for (home, retirement, income, legacy)?", "goals"),
    "investment_horizon": ("when the money is needed?", "horizon"),
    "liquidity_need_sgd": ("any large payment due soon, and how much?", "liquidity need"),
    "risk_classification": ("complete the risk questionnaire to record a classification?", "risk questionnaire"),
    "risk_capacity": ("assets, debts and income to assess loss capacity?", "risk capacity"),
    "risk_tolerance": ("how the client felt in past market falls?", "risk tolerance"),
    "knowledge_experience": ("past investing experience?", "experience"),
    "sustainability_preferences": ("any sustainability or exclusion preferences?", "sustainability"),
    "currency_preference": ("which currencies to hold?", "currencies"),
    "restrictions": ("any exclusions (no note is not confirmation of none)?", "restrictions"),
    "asset_class_preferences": ("which asset classes are favoured or avoided?", "asset-class preferences"),
    "drawdown_tolerance_pct": ("the largest fall the client could accept?", "drawdown limit"),
}
LABELS = {
    "aum_managed_sgd": "Managed assets", "other_assets_sgd": "Other assets", "liabilities_sgd": "Liabilities",
    "annual_income_sgd": "Annual income", "monthly_cash_need_sgd": "Monthly spending", "annual_cash_need_sgd": "Annual spending",
    "goals": "Goals", "investment_horizon": "Horizon", "liquidity_need_sgd": "Liquidity need",
    "risk_classification": "Risk classification", "risk_capacity": "Risk capacity", "risk_tolerance": "Risk tolerance",
    "drawdown_tolerance_pct": "Drawdown limit", "knowledge_experience": "Knowledge & experience",
    "asset_class_preferences": "Asset class preferences", "restrictions": "Restrictions",
    "sustainability_preferences": "Sustainability", "currency_preference": "Currencies",
}


def _ask_for(field: str) -> tuple[str, str]:
    return _ASK.get(field) or (f"the client's {_words(field)}?", _words(field))


def _as_list(v: Any) -> list[str]:
    items = v if isinstance(v, list) else [v]
    return [str(i) for i in items if i not in (None, "")]


def _stale_line(outdated: list[str]) -> Optional[Row]:
    parts: list[str] = []
    for o in outdated:
        parts.append(_clip(o, 70).rstrip("."))
    parts = list(dict.fromkeys(parts))
    return _plain("Check: " + "; ".join(parts), "calculated") if parts else None


def _conflict_line(conflicts: list[Any]) -> Optional[Row]:
    if not conflicts:
        return None
    bits, srcs = [], []
    for c in conflicts:
        field = c.field if hasattr(c, "field") else c.get("field", "")
        expl = c.explanation if hasattr(c, "explanation") else c.get("explanation", "")
        bits.append(f"{LABELS.get(field, _words(field)).lower()} ({_clip(expl, 60).rstrip('.')})")
        sts = c.statements if hasattr(c, "statements") else c.get("statements", [])
        srcs += [x if isinstance(x, SourceRef) else (SourceRef.model_validate(x) if isinstance(x, dict) else None) for x in sts]
    return _plain("Conflict: " + "; ".join(dict.fromkeys(bits)), "documented", [s for s in srcs if s])


def _key_fact_sections(p: ClientProfile, only_note_facts: bool = False) -> list[Section]:
    by = {f.field: f for f in p.facts}
    g = lambda k: by.get(k) if k in by and by[k].kind != "missing" else None  # noqa: E731
    n = lambda k: _num(g(k))  # noqa: E731
    aum, other, liab = n("aum_managed_sgd"), n("other_assets_sgd"), n("liabilities_sgd")
    inc, mon, ann = n("annual_income_sgd"), n("monthly_cash_need_sgd"), n("annual_cash_need_sgd")
    liq, liqp = n("liquidity_need_sgd"), n("liquidity_need_pct_of_aum")
    out: list[Section] = []

    # 1 Cash flow & liquidity
    rows: list[Row] = []
    if inc:
        rows.append(_row(f"Earns {money(inc)} a year", g("annual_income_sgd")))
    if mon or ann:
        yr = ann or mon * 12
        mo = mon or ann / 12
        share = f", {yr / inc * 100:.0f}% of income" if inc else ""
        rows.append(_row(f"Spends {money(mo)}/month ({money(yr)}/yr{share})", g("monthly_cash_need_sgd"), g("annual_cash_need_sgd")))
    if liq:
        lp = liqp if liqp is not None else (liq / aum * 100 if aum else None)
        rows.append(_row(f"Needs {money(liq)} liquid as a cash buffer" + (f" ({pct(round(lp, 1))} of managed assets)" if lp is not None else ""),
                         g("liquidity_need_sgd"), g("liquidity_need_pct_of_aum")))
    if rows:
        if inc and (ann or mon):
            m = "Income covers spending, so the portfolio is not needed for living costs." if inc >= (ann or mon * 12) \
                else "Spending exceeds income, so the portfolio may have to fund the gap."
        elif liqp is not None and liqp >= 25:
            m = "A large share must stay accessible, which limits growth assets."
        else:
            m = "Shows how much cash comes in, goes out and must stay accessible."
        out.append(_sec("Cash flow & liquidity", m, rows))

    # 2 Wealth
    rows = []
    if aum and other:
        tot = aum + other
        rows.append(_row(f"Managed {money(aum)} + other {money(other)} = {money(tot)} known wealth ({aum / tot * 100:.0f}% managed)",
                         g("aum_managed_sgd"), g("other_assets_sgd")))
    elif aum:
        rows.append(_row(f"Managed with the bank: {money(aum)}", g("aum_managed_sgd")))
    elif other:
        rows.append(_row(f"Other assets outside the bank: {money(other)}", g("other_assets_sgd")))
    if liab:
        rows.append(_row(f"Liabilities {money(liab)}" + (f" ({liab / aum * 100:.0f}% of managed assets)" if aum else ""), g("liabilities_sgd")))
    if rows:
        out.append(_sec("Wealth", "Every percentage in the plan is measured on managed assets" + ("; debt cuts loss capacity." if liab else "."), rows))

    # 3 Goals & horizon
    rows = []
    if g("goals"):
        rows.append(_row("Goals: " + _listing(g("goals").value), g("goals")))
    if g("investment_horizon"):
        rows.append(_row("Horizon: " + "; ".join(_as_list(g("investment_horizon").value)[:3]), g("investment_horizon")))
    if rows:
        out.append(_sec("Goals & horizon", "What the client wants the money to do, and by when.", rows))

    # 4 Risk
    rows = []
    rc, cap, tol = g("risk_classification"), g("risk_capacity"), g("risk_tolerance")
    segs, fs = [], []
    cat = None
    if rc:
        v = rc.value if isinstance(rc.value, dict) else {"category": rc.value}
        cat = str(v.get("category"))
        lim = v.get("risk_limit_of_5")
        segs.append(f"Classified {cat}" + (f" (limit {lim:g} of 5)" if isinstance(lim, (int, float)) else ""))
        fs.append(rc)
    if cap:
        segs.append(f"capacity {str(cap.value).lower()}")
        fs.append(cap)
    if tol and not (cat and str(tol.value).strip().lower() == cat.lower()):
        segs.append(f"tolerance {str(tol.value).lower()}" + (" (unconfirmed)" if tol.kind == "inferred" else ""))
        fs.append(tol)
    if segs:
        rows.append(_row("; ".join(segs), *fs))
    dd, ml = n("drawdown_tolerance_pct"), n("max_loss_at_drawdown_sgd")
    if dd is not None:
        if ml is None and aum:
            ml = aum * dd / 100
        rows.append(_row(f"Accepts a fall of up to {pct(dd)}" + (f", i.e. up to {money(ml)} lost" + (f" on {money(aum)}" if aum else "") if ml is not None else ""),
                         g("drawdown_tolerance_pct"), g("max_loss_at_drawdown_sgd")))
    elif ml is not None:
        rows.append(_row(f"Maximum loss accepted: {money(ml)}", g("max_loss_at_drawdown_sgd")))
    if g("knowledge_experience"):
        rows.append(_row("Experience: " + _clip(" ".join(_as_list(g("knowledge_experience").value)), 110), g("knowledge_experience")))
    if rows:
        out.append(_sec("Risk", "How the client describes their comfort with losses, as recorded in the meeting notes.", rows))

    # 5 Preferences & restrictions
    rows = []
    if g("asset_class_preferences"):
        rows.append(_row("Prefers " + _listing(g("asset_class_preferences").value), g("asset_class_preferences")))
    excl = _as_list(g("restrictions").value) if g("restrictions") else []
    extra = []
    for sv in (_as_list(g("sustainability_preferences").value) if g("sustainability_preferences") else []):
        if sv.lower().startswith("exclude "):
            if sv[8:].strip().lower() not in [e.lower() for e in excl]:
                excl.append(sv[8:].strip())
        else:
            extra.append(sv)
    if excl or extra:
        txt = ("Excludes " + _listing(excl) if excl else "") + (("; " if excl else "") + "also " + _listing(extra) if extra else "")
        rows.append(_row(txt, g("restrictions"), g("sustainability_preferences")))
    if g("currency_preference"):
        rows.append(_row("Currencies: " + _listing(g("currency_preference").value), g("currency_preference")))
    if rows:
        out.append(_sec("Preferences & restrictions", "Preferences tilt the mix; exclusions narrow what may be held.", rows))

    # 6 To confirm
    asks = [_ask_for(f.field) for f in p.facts if f.kind == "missing"]
    if tol and tol.kind == "inferred":
        asks.insert(0, (f"confirm risk tolerance ({str(tol.value).lower()} is unconfirmed, inferred from the client's words)?", "risk tolerance"))
    rows = _ask_rows(asks)
    for r in (_conflict_line(p.conflicts), _stale_line(p.outdated)):
        if r:
            rows.append(r)
    if rows:
        out.append(_sec("To confirm", "Resolve these before relying on this profile.", rows))
    return out


# --------------------------------------------------------------------------- notes
def _para_lines(text: str, n: int = 6) -> list[str]:
    return [_clip(x, 135) for x in [" ".join(x.split()) for x in re.split(r"\n\s*\n|\n", text)] if x][:n]


def _note_refs(r: ToolResult, nid: Optional[str], n: int = 3) -> list[SourceRef]:
    return _dedupe([s for s in r.sources if s.id == nid])[:n]


def _summary_sections(r: ToolResult, profile: ClientProfile) -> list[Section]:
    """Group the note content by concept, using the extracted facts for the notes in `r`."""
    ids = {n.get("note_id") for n in (r.data.get("notes") or [])}
    by_f = {}
    for f in profile.facts:
        if f.kind == "missing":
            continue
        if any(s.type == "meeting_note" and (not ids or s.id in ids) for s in f.sources):
            by_f[f.field] = f
    msrc = lambda fs: _dedupe([s for f in fs if f for s in f.sources if s.type == "meeting_note"])  # noqa: E731
    n = lambda k: _num(by_f.get(k))  # noqa: E731
    g = by_f.get
    out: list[Section] = []

    def add(head, meaning, parts):
        rows = [(t, _worst([f.kind for f in fs if f]), msrc(fs)) for t, *fs in parts if t]
        if rows:
            s = _sec(head, meaning, rows)
            s.lines = s.lines[:2]
            out.append(s)

    inc = n("annual_income_sgd")
    add("Cash Inflow", "What comes in each year.", [(f"Income {money(inc)} a year" if inc else "", g("annual_income_sgd"))])
    mon, ann, liq = n("monthly_cash_need_sgd"), n("annual_cash_need_sgd"), n("liquidity_need_sgd")
    yr = ann or (mon * 12 if mon else None)
    add("Cash Outflow", "What goes out and what must stay liquid.", [
        (f"Spends {money(mon or yr / 12)}/month ({money(yr)}/yr" + (f", {yr / inc * 100:.0f}% of income" if inc else "") + ")" if yr else "", g("monthly_cash_need_sgd"), g("annual_cash_need_sgd")),
        (f"Wants {money(liq)} kept liquid as a cash reserve" if liq else "", g("liquidity_need_sgd"))])
    st = _as_list(g("risk_attitude_statements").value) if g("risk_attitude_statements") else []
    dd = n("drawdown_tolerance_pct")
    add("Risk appetite", "How the client feels about losses.", [
        ("In their words: “" + _clip(st[0], 100) + "”" if st else "", g("risk_attitude_statements")),
        (f"Uncomfortable with a fall beyond {pct(dd)}" if dd is not None else "", g("drawdown_tolerance_pct"))])
    excl = _as_list(g("restrictions").value) if g("restrictions") else []
    add("Asset-class preferences", "What the client favours or rules out.", [
        ("Prefers " + _listing(g("asset_class_preferences").value) if g("asset_class_preferences") else "", g("asset_class_preferences")),
        ("Excludes " + _listing(excl) if excl else "", g("restrictions"))])
    return out


def _notes_sections(r: ToolResult, profile: Optional[ClientProfile] = None) -> list[Section]:
    d = r.data
    if d.get("summarise") and profile is not None:
        secs = _summary_sections(r, profile)
        if secs:
            return secs
    notes = d.get("notes") or ([d] if d.get("note_id") else [])
    out = []
    for n in notes:
        refs = _note_refs(r, n.get("note_id"))
        rows: list[Row] = []
        passages = n.get("matched_passages") or [p["text"] for p in d.get("passages", [])]
        if passages:
            rows = [_plain(_clip(p, 135), "documented", refs[:1]) for p in passages[:3]]
        elif n.get("text") or d.get("text"):
            rows = [_plain(x, "documented", refs[:1]) for x in _para_lines(n.get("text") or d.get("text"))]
        elif n.get("excerpt"):
            rows = [_plain(_clip(n["excerpt"], 135), "documented", refs[:1])]
        out.append(_sec(f"{n.get('title', 'Meeting note')} · {n.get('date', '')}",
                        f"Note {n.get('note_id')}" + (f" ({n['source_file']})" if n.get("source_file") else ""), rows))
    return out


# --------------------------------------------------------------------------- entry point
def build_sections(result: ToolResult, profile: Optional[ClientProfile] = None) -> list[Section]:
    d, tool = result.data or {}, result.tool
    if tool == "extract_key_facts":
        p = profile
        if p is None and d.get("facts") is not None:
            p = ClientProfile.model_validate(d)
        return _key_fact_sections(p) if p else []
    if tool in ("get_meeting_note", "read_meeting_note"):
        return _notes_sections(result, profile)
    return []
