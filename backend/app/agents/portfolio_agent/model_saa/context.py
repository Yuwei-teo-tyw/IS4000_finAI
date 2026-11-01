"""
Client context for the model SAA recommendation, assembled server-side from the agents that own the data:

  - Client Profiling Agent: the IPS the RM sent to the PM (cp_ips_sends snapshot; the latest IPS when nothing
    was sent): risk score, risk tolerance and capacity, loss tolerance, horizon, liquidity needs, goals,
    targets, investment approach, restrictions, demographics and the 3L split. The client book gives the
    client's total wealth (AUM) and product risk limit. The PM's working copy, when present, gives the 3L split
    the PM is reviewing.
  - Client Portfolio Agent: existing holdings, grouped by 3L bucket and asset class.

Nothing is invented: a field the data does not contain is None and listed in `missing`. Free-text IPS fields
are parsed only for explicit numbers (years, percentages) and stated asset-class exclusions.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.client_profiling.ips_model import normalize_data
from app.agents.portfolio_agent.model_saa.schemas import ClientContext, ClientFact, HoldingsView, ThreeLBucket

PROFILING = "Client Profiling Agent"
PORTFOLIO = "Client Portfolio Agent"
BOOK = "Client book (Client Profiling Agent)"
ALL_BUCKETS = ("liquidity", "longevity", "legacy")

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40}
_YEARS = re.compile(r"(\d+(?:\.\d+)?|" + "|".join(sorted(_NUM_WORDS, key=len, reverse=True)) + r")\s*\+?\s*(?:years?|yrs?)\b", re.I)
_LOSS = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_LOSS_WORDS = re.compile(r"\b(fall|falls|drop|drops|loss|losses|lose|decline|down|drawdown)\b", re.I)

# Stated exclusions that map onto a whole asset class. Sector or issuer exclusions (tobacco, coal, ...) are
# product-level screens and are reported as such, never treated as an asset-class exclusion.
_CLASS_EXCLUSIONS = {
    "Private markets": re.compile(r"private (?:equity|markets?|credit)|illiquid", re.I),
    "Hedge funds": re.compile(r"hedge funds?", re.I),
    "Gold": re.compile(r"\bgold\b|precious metals?|commodit", re.I),
    "Real estate": re.compile(r"real estate|propert(?:y|ies)|reits?\b", re.I),
}


def parse_years(text: Optional[str]) -> Optional[float]:
    """First explicit horizon in years ("at least ten years" -> 10, "8 years" -> 8); None when no number is stated."""
    if not text:
        return None
    m = _YEARS.search(text)
    if not m:
        return None
    tok = m.group(1).lower()
    return float(_NUM_WORDS[tok]) if tok in _NUM_WORDS else float(tok)


def parse_loss_pct(text: Optional[str]) -> Optional[float]:
    """A stated loss tolerance ("a fall of more than 10%" -> 10); only a % next to a loss word counts."""
    if not text or not _LOSS_WORDS.search(text):
        return None
    m = _LOSS.search(text)
    return float(m.group(1)) if m else None


def parse_age(text: Optional[str], today: Optional[datetime] = None) -> Optional[int]:
    if not text:
        return None
    today = today or datetime.now(timezone.utc)
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if m:
        return today.year - int(m.group(1))
    m = re.search(r"\b(?:aged?\s*)?(\d{2})\s*(?:years? old|yo)\b|\bage[d]?\s*(\d{2})\b", text, re.I)
    return int(m.group(1) or m.group(2)) if m else None


def excluded_classes(text: str) -> list[str]:
    return [ac for ac, rx in _CLASS_EXCLUSIONS.items() if rx.search(text or "")]


# "excludes hedge funds, private markets" inside a goal: only the clause after the cue counts.
_EXCLUDE_CLAUSE = re.compile(r"\b(?:exclud\w*|avoid\w*|no exposure to|does not want|never invest\w* in)\b([^;.]*)", re.I)
_CAP_CLASS = {
    "Equities": r"(?:blue[- ]chip\s+)?(?:equit\w*|stocks?|shares)", "Fixed income": r"(?:bonds?|fixed income)", "Cash": r"cash",
    "Gold": r"gold", "Real estate": r"(?:real estate|propert\w*)", "Hedge funds": r"hedge funds?", "Private markets": r"private (?:markets?|equity|credit)",
}
_CAP = re.compile(r"\b(?:up to|no more than|not more than|at most|maximum(?: of)?|max\.?|capped at)\s*(\d+(?:\.\d+)?)\s?%\s*(?:of\s+|in\s+|into\s+)?(?:the\s+)?("
                  + "|".join(f"(?P<c{i}>{rx})" for i, rx in enumerate(_CAP_CLASS.values())) + ")", re.I)


_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", " ": " "})


def _plain(lines: list[str]) -> list[str]:
    """IPS text often has non-breaking hyphens ("blue‑chip") and spaces; match on plain ones."""
    return [x.translate(_DASHES) for x in lines if x]


def stated_exclusions(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in _plain(lines):
        for m in _EXCLUDE_CLAUSE.finditer(line):
            out += [ac for ac in excluded_classes(m.group(1)) if ac not in out]
    return out


def stated_caps(lines: list[str]) -> dict[str, float]:
    """Explicit allocation caps the client stated ("up to 10% blue-chip equities" -> {"Equities": 10}); the lowest wins."""
    caps: dict[str, float] = {}
    names = list(_CAP_CLASS)
    for line in _plain(lines):
        for m in _CAP.finditer(line):
            ac = next(names[i] for i in range(len(names)) if m.group(f"c{i}"))
            caps[ac] = min(caps.get(ac, 100.0), float(m.group(1)))
    return caps


def _goal_lines(d: dict) -> list[str]:
    out: list[str] = []
    for g in d.get("goals") or []:
        if isinstance(g, dict):
            out += [str(b).strip() for b in g.get("bullets") or [] if str(b).strip()]
    return out


def _pick_ips(store, client_id: str) -> tuple[Optional[dict], Optional[int], Optional[str], str]:
    """(data, version, status, basis). The version sent to the PM wins; else the latest IPS."""
    rec = store.get_ips_send(client_id)
    if rec:
        snap = rec.get("snapshot") or {}
        data = snap.get("data")
        if not data:
            v = next((x for x in store.get_ips_versions(client_id) if x.version == rec.get("version")), None)
            data = v.data if v else None
        return data, rec.get("version"), rec.get("status"), f"IPS v{rec.get('version')} as sent by the RM ({rec.get('status')})"
    ips, _current = store.latest_ips(client_id)
    if ips is None:
        return None, None, None, "no IPS"
    return ips.data, ips.version, ips.status, f"IPS v{ips.version} ({ips.status}); it has not been sent to the PM"


def _holdings(client_id: str, portfolio_loader) -> HoldingsView:
    try:
        res = portfolio_loader(client_id)
    except Exception:  # noqa: BLE001 - the portfolio database is optional for a recommendation
        return HoldingsView(available=False, message="The Client Portfolio Agent could not be reached.")
    if not res.get("available", True):
        return HoldingsView(available=False, message=res.get("message") or "Holdings are unavailable.")
    priced = [h for h in res.get("holdings") or [] if h.get("market_value")]
    if not priced:
        return HoldingsView(available=True, message="No priced holdings yet.")
    by: dict[str, dict[str, float]] = {}
    for h in priced:
        b = str(h.get("portfolio") or "").lower()
        by.setdefault(b, {}).setdefault(str(h.get("asset_class") or "Other"), 0.0)
        by[b][str(h.get("asset_class") or "Other")] += float(h["market_value"])
    buckets = {}
    for b, classes in by.items():
        tot = sum(classes.values())
        buckets[b] = {"value": round(tot, 2), "classes": {k: round(v * 100 / tot, 1) for k, v in sorted(classes.items(), key=lambda x: -x[1])}}
    return HoldingsView(available=True, by_bucket=buckets, message=None)


def build_context(client_id: str, store=None, portfolio_loader=None) -> ClientContext:
    """Raises LookupError when the client is unknown. Missing IPS data never raises: it is listed in `missing`."""
    if store is None:
        from app.agents.client_profiling.store import get_default_store
        store = get_default_store()
    if portfolio_loader is None:
        from app.agents.client_portfolio.service import get_client_portfolio
        portfolio_loader = get_client_portfolio
    client = store.get_client(client_id)
    if client is None:
        raise LookupError(f"Unknown client {client_id}")
    raw, version, status, basis = _pick_ips(store, client_id)
    d = normalize_data(raw) if raw else {}
    missing: list[str] = []
    facts: list[ClientFact] = []

    def fact(label: str, value: Any, source: str = PROFILING):
        if value in (None, "", []):
            missing.append(label)
        else:
            facts.append(ClientFact(label=label, value=str(value), source=source))

    if not raw:
        missing.append("IPS (no IPS saved for this client)" if version is None else f"IPS content (IPS v{version} is empty)")
    risk = (d.get("risk") or {}).get("fields") or {}
    demo = (d.get("demographics") or {}).get("fields") or {}
    phil = d.get("philosophy") or {}
    score = d.get("riskScore")
    score = int(score) if isinstance(score, (int, float)) and not isinstance(score, bool) and 1 <= score <= 5 else None
    cap = client.risk_cap if isinstance(client.risk_cap, int) and 1 <= client.risk_cap <= 5 else None
    levels = [x for x in (score, cap) if x is not None]
    level = min(levels) if levels else None
    level_basis = (None if level is None else
                   f"IPS risk score {score} of 5" + (f", capped by the product risk limit {cap}" if cap is not None and cap < (score or 6) else "")
                   if score is not None else f"product risk limit {cap} from the client book (the IPS has no risk score)")
    tolerance = risk.get("Risk tolerance (willingness)")
    loss = parse_loss_pct(tolerance) or parse_loss_pct(" ".join((d.get("risk") or {}).get("bullets") or []))
    horizon_text = risk.get("Time horizon") or phil.get("investmentPeriod") or ""
    targets = [t for t in d.get("targets") or [] if isinstance(t, dict)]
    avoids = str(phil.get("avoids") or "")
    total = float(client.aum_sgd) if client.aum_sgd else None

    # 3L split: the PM's working copy for this send, else the IPS proportion.
    split_src = "IPS 3L proportion (set by the RM)"
    pcts: dict[str, Optional[float]] = {b: ((d.get("threeLProportion") or {}).get(b) or {}).get("pct") for b in ALL_BUCKETS}
    work = getattr(store, "get_pm_working", lambda _c: None)(client_id)
    if work and work.get("snapshotVersion") == version and isinstance(work.get("threeL"), dict):
        pcts = {b: (work["threeL"].get(b) or {}).get("pct") for b in ALL_BUCKETS}
        split_src = "3L split under PM review (from the RM's sent IPS)"
    three = {b: ThreeLBucket(pct=pcts[b], amount=round(total * pcts[b] / 100, 2) if total and pcts[b] is not None else None) for b in ALL_BUCKETS}
    if any(p is None for p in pcts.values()):
        missing.append("3L split")

    fact("Client", f"{client.name} {client.surname}".strip(), BOOK)
    fact("Total wealth (AUM)", f"S${total:,.0f}" if total else None, BOOK)
    fact("Risk level", f"{level} of 5 ({level_basis})" if level else None)
    fact("Risk tolerance (willingness)", tolerance)
    fact("Risk capacity (ability)", risk.get("Risk capacity (ability)"))
    fact("Loss tolerance", f"{loss:g}% in a year" if loss is not None else None)
    fact("Investment horizon", horizon_text)
    fact("Liquidity needs", risk.get("Liquidity needs"))
    fact("Investment approach", phil.get("approach"))
    fact("Restrictions", avoids)
    fact("Age", parse_age(demo.get("Date of birth / age")))
    fact("Income", demo.get("Annual income"))
    return ClientContext(
        client_id=client_id, client_name=f"{client.name} {client.surname}".strip(), ips_version=version, ips_status=status,
        ips_basis=basis if raw else f"{basis}; it is empty", has_ips_data=bool(raw), total_wealth=total, three_l=three, three_l_source=split_src,
        risk_level=level, risk_level_basis=level_basis, risk_score=score, product_risk_limit=cap,
        risk_tolerance=tolerance, risk_capacity=risk.get("Risk capacity (ability)"), loss_tolerance_pct=loss,
        horizon_text=horizon_text or None, horizon_years=parse_years(horizon_text), liquidity_needs=risk.get("Liquidity needs"),
        goals=_goal_lines(d), targets=[{"text": str(t.get("text") or ""), "amount": t.get("amount"), "horizon_years": t.get("horizonYears")} for t in targets],
        approach=phil.get("approach") or None, believes=phil.get("believes") or None, restrictions=avoids or None,
        excluded_asset_classes=list(dict.fromkeys(excluded_classes(avoids) + stated_exclusions(_goal_lines(d) + [phil.get("approach") or ""]))),
        asset_class_caps=stated_caps(_goal_lines(d) + [avoids, phil.get("approach") or "", phil.get("believes") or ""]),
        age=parse_age(demo.get("Date of birth / age")),
        holdings=_holdings(client_id, portfolio_loader), facts=facts, missing=missing,
    )
