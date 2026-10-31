"""
Review pack generator: builds the sections A-G of a periodic review pack for one client.

Every number (weights, bands, tilts, holding shifts, product ranking) is computed by code
from the saved IPS, the client's holdings, the curated CIO house view and the asset-class
views. The LLM only writes short narratives from those facts; each text is checked by the
Product Recommender's guardrail and an item that fails keeps its rule-based text. If the
model is unavailable the pack is not generated (PackGenerationError), never faked.

Rules that hold everywhere in this module:
  - Liquidity has no SAA and no TAA. Only Longevity and Legacy appear in either.
  - The RM's optional context is advisory prose. It is echoed and may colour the narrative,
    but no computation reads it, so it can never override the IPS, risk profile or suitability.
  - The market stance (portfolio_agent/upstream/market_analysis.py) is still a MOCK and is
    labelled as such in the sources and in section B.
  - Facts the data does not contain are stated as unknown, never invented.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field, ValidationError

from app.agents.client_portfolio.service import get_client_portfolio, apportion
from app.agents.client_profiling.extract import extract_key_facts
from app.agents.client_profiling.embeddings import chunk_text
from app.agents.client_profiling.hybrid import rrf_fuse
from app.agents.client_profiling.ips_model import normalize_data
from app.agents.client_profiling.store import StoreUnavailableError, get_default_store
from app.agents.portfolio_agent.taxonomy import parse_risk_capacity
from app.agents.client_profiling.strategies import get_strategy
from app.agents.portfolio_agent.explain.llm_client import LLMUnavailable
from app.agents.portfolio_agent.schemas.client import ClientProfile
from app.agents.portfolio_agent.upstream.market_analysis import MARKET_ANALYSIS_SOURCE
from app.agents.product_recommender import guardrails
from app.agents.product_recommender.house_view import HouseViewError
from app.agents.product_recommender.llm import _coerce
from app.agents.product_recommender.schemas import RecommendOptions, RecommendRequest
from app.agents.product_recommender.service import ProductRecommenderService, ShelfUnavailable

logger = logging.getLogger(__name__)

BUCKETS = ("longevity", "legacy")  # Liquidity never has an SAA or TAA
BUCKET_LABEL = {"longevity": "Longevity", "legacy": "Legacy"}
CATEGORIES = ("Bonds", "Equities", "Alternative Investments", "Other")
GROWTH = ("Equities", "Alternative Investments")
HOLDING_CATEGORY = {"Fixed Income": "Bonds", "Equities": "Equities", "Alternatives": "Alternative Investments"}
# House-view asset classes behind each SAA category (Other has no view and is held at its SAA weight).
HV_CLASSES = {"Bonds": ("Fixed income",), "Equities": ("Equities",),
              "Alternative Investments": ("Hedge funds", "Private markets", "Real estate", "Gold")}
BAND_PP = 5.0          # a TAA weight stays within SAA +/- this many percentage points
SHIFT_MIN_PP = 2.0     # a category gap smaller than this is "retain"
CONCENTRATION_PCT = 20.0
RM_CONTEXT_MAX = 2000
IPS_TOP_K = 4
IPS_TOPIC_QUERY = "market view tactical asset allocation TAA products holdings strategic allocation objectives"
IPS_EXCERPT_CHARS = 240


# --- IPS retrieval (hybrid: dense via store.search_ips + lexical term overlap, fused with RRF) ---------------

def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1}


def retrieve_ips_passages(ips, store, client_id: str, rm_context: Optional[str], k: int = IPS_TOP_K) -> list[dict]:
    """Top-k chunks of the client's current IPS: [{chunk_id, part, text}]. Dense ranking from store.search_ips (None when
    embeddings/pgvector are unavailable -> lexical ranking only). Never raises; returns [] when nothing matches."""
    try:
        # Same chunking as the IPS vector index, so chunk ids line up with cp_ips_chunks (part_n, chunk_idx).
        cands = {}
        for p in ips.parts:
            for i, c in enumerate(chunk_text(f"{p.title}. {p.body}")):
                cands[f"ips:v{ips.version}:p{p.part}:c{i}"] = (p.part, c)
        if not cands:
            return []
        query = " ".join(x for x in ((rm_context or "")[:300], IPS_TOPIC_QUERY) if x)
        by_text = {(pn, t): cid for cid, (pn, t) in cands.items()}
        dense = []
        for h in store.search_ips(client_id, query, k * 3) or []:
            cid = by_text.get((h.get("part_n"), h.get("text")))
            if cid and cid not in dense:
                dense.append(cid)
        qterms = _terms(query)
        lexical = [cid for cid, score in sorted(
            ((cid, len(qterms & _terms(t))) for cid, (_, t) in cands.items()), key=lambda x: -x[1]) if score > 0]
        fused = [cid for cid, _ in rrf_fuse([dense, lexical], top=k)]
        return [{"chunk_id": cid, "part": cands[cid][0], "text": cands[cid][1]} for cid in fused]
    except Exception:
        logger.warning("Review pack IPS retrieval failed; continuing without IPS passages")
        return []
CONFIDENCE_FACTOR = {"High": 1.0, "Medium": 0.6, "Low": 0.3}
VIEW_SCORE = {"Buy": 1.0, "Hold": 0.0, "Sell": -1.0}
MOCK_NOTE = ("The market stance behind the agent views and the macro read is MOCK data "
             "(the Market Researcher is not yet connected), so treat it as illustrative.")


class PackGenerationError(Exception):
    """A pack that cannot be generated; `status` is the HTTP status the endpoint answers with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --- small helpers ----------------------------------------------------------

def _r1(x: float) -> float:
    return round(x + 0.0, 1)


def _pp(x: Optional[float]) -> str:
    return "not available" if x is None else f"{x:.1f}%"


def _category(asset_class: str) -> str:
    return HOLDING_CATEGORY.get(asset_class, "Other")


def _apportion(values: dict[str, float]) -> dict[str, float]:
    keys = list(values)
    if sum(values.values()) <= 0:
        return {k: 0.0 for k in keys}
    out = apportion([Decimal(str(values[k])) for k in keys])
    return {k: float(v) for k, v in zip(keys, out)}


def _saa_from_strategy(code: str) -> Optional[dict[str, float]]:
    """Strategy weights without the Liquidity line, renormalised to 100 (Liquidity has no SAA)."""
    s = get_strategy(code) if code else None
    if not s:
        return None
    alloc = s.get("allocation") or {}
    kept = {"Bonds": alloc.get("Bonds", 0), "Equities": alloc.get("Equities", 0),
            "Alternative Investments": alloc.get("Alternative Investments", 0), "Other": alloc.get("Other", 0)}
    return _apportion({k: float(v) for k, v in kept.items()})


# --- data gathering ---------------------------------------------------------

def _facts_by_field(profile_facts) -> dict[str, Any]:
    return {f.field: f.value for f in profile_facts.facts if f.kind != "missing" and f.value not in (None, "", [])}


_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_CCY_CAP = re.compile(r"\b(no more than|maximum|max\.?|up to|limit|cap)\b", re.I)


def _first_pct(s: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s?%", s)
    return float(m.group(1)) if m else None


def _first_sgd(s: str) -> Optional[float]:
    m = re.search(r"S\$\s?([\d,]+(?:\.\d+)?)\s?(m|k)?\b", s, re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", "")) * {"m": 1e6, "k": 1e3}.get((m.group(2) or "").lower(), 1.0)


def _profile_extras(client, notes, ips, facts: dict[str, Any]) -> dict[str, Any]:
    """Profile fields the review pack passes beyond the note key facts, read from the meeting notes (oldest first) and
    then the Active IPS text, which is the signed record and wins on conflict. Only stated values are returned."""
    out: dict[str, Any] = {}
    sents: list[str] = []
    for n in sorted(notes or [], key=lambda n: (n.date, n.id)):
        sents += [s.strip() for s in _SENT_SPLIT.split(n.text or "") if s.strip()]
    for p in (ips.parts if ips else []):
        sents += [s.strip() for s in _SENT_SPLIT.split(p.body or "") if s.strip()]
    zero_withdrawals = False
    for s in sents:
        if m := re.search(r"\b(\d{2}) years old\b|\bAge (\d{2})\b", s, re.I):
            out["age"] = int(m.group(1) or m.group(2))
        if m := re.search(r"\b([A-Z][a-z]+) tax resident\b", s):
            out["residency"] = m.group(1)
        if re.search(r"\bnot (an? )?accredited investor\b", s, re.I):
            out["accredited_investor"] = False
        elif re.search(r"\baccredited investor\b", s, re.I):
            out["accredited_investor"] = True
        if re.search(r"\bsingle (holding|asset|investment|product|position)s?\b", s, re.I) and _first_pct(s) is not None:
            out["maximum_single_asset_allocation"] = _first_pct(s)
        if re.search(r"currenc", s, re.I) and _CCY_CAP.search(s) and _first_pct(s) is not None:
            out["maximum_currency_exposure"] = _first_pct(s)
        if m := re.search(r"risk capacity:?\s*([A-Za-z][A-Za-z -]*[A-Za-z])", s, re.I):
            if parse_risk_capacity(m.group(1)) is not None:
                out["risk_capacity"] = m.group(1).strip()
        if re.search(r"planned withdrawal|withdraw|drawn", s, re.I) and _first_sgd(s) is not None:
            out["planned_withdrawals"] = _first_sgd(s)
        elif re.search(r"\bno (regular )?withdrawals?\b", s, re.I):
            zero_withdrawals = True
        alloc = re.findall(r"(\d+(?:\.\d+)?)%\s+in\s+(cash|fixed income|equities|real estate|gold|hedge funds|private markets)\b", s, re.I)
        if len(alloc) >= 2:
            out["current_asset_allocation"] = {k.lower(): float(v) for v, k in alloc}
        if re.search(r"\b(buy|reach|target|goal)\b", s, re.I) and re.search(r"within (?:the next )?\d+ (months|years)", s, re.I):
            m = re.search(r"within (?:the next )?(\d+) (months|years)", s, re.I)
            years = float(m.group(1)) / (12 if m.group(2).lower() == "months" else 1)
            name = "Buy a home" if re.search(r"\b(home|house)\b", s, re.I) else "Investment target"
            goal = {"goal": name, "years_to_goal": years, "priority": "High"}
            if (amt := _first_sgd(s)) is not None and name == "Buy a home":
                goal["target_amount"] = amt  # "Buy a S$15m home within 12 months": the price, not the deposit
            out.setdefault("_goals", {})[name] = goal
    if "planned_withdrawals" not in out and zero_withdrawals:
        out["planned_withdrawals"] = 0.0
    goals = out.pop("_goals", None)
    if goals:
        out["financial_goals"] = list(goals.values())
    liab = facts.get("liabilities_sgd")
    if isinstance(liab, (int, float)) and not isinstance(liab, bool) and liab >= 0:
        out["liabilities"] = float(liab)
    aum = facts.get("aum_managed_sgd") or client.aum_sgd
    if aum:
        out["investable_assets"] = float(aum)
    return out


def _read_ips(ips, current: bool) -> dict:
    data = normalize_data(ips.data, ips.issued_on)
    prop = data.get("threeLProportion") if isinstance(data.get("threeLProportion"), dict) else {}
    buckets: dict[str, dict] = {}
    for b in data.get("threeL") or []:
        label = str(b.get("id") or b.get("portfolio") or "").strip().lower()
        if label in ("liquidity", "longevity", "legacy"):
            buckets[label] = b
    out = {"version": ips.version, "status": ips.status, "is_current": current, "issued_on": ips.issued_on,
           "goals": [{"title": g.get("title"), "bullets": g.get("bullets") or []} for g in data.get("goals") or []
                     if g.get("bullets")],
           "proportion": {}, "saa": {}, "strategy": {}}
    for k in ("liquidity", "longevity", "legacy"):
        v = prop.get(k)
        v = v.get("pct") if isinstance(v, dict) else v
        out["proportion"][k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    for k in BUCKETS:
        code = (buckets.get(k) or {}).get("strategy")
        meta = get_strategy(code) if code else None
        out["strategy"][k] = {"code": code, "name": (meta or {}).get("name")} if meta else None
        out["saa"][k] = _saa_from_strategy(code) if meta else None
    return out


def _existing_by_bucket(portfolio: dict) -> dict[str, Optional[dict]]:
    """Per bucket: category weights of the priced non-cash holdings (sum 100), plus the holdings themselves."""
    out: dict[str, Optional[dict]] = {}
    holdings = [h for h in portfolio.get("holdings") or [] if h.get("price_available")]
    for b in BUCKETS:
        hs = [h for h in holdings if h["portfolio"] == b and h["asset_class"] != "Cash"]
        total = sum(h["market_value"] for h in hs)
        if not hs or total <= 0:
            out[b] = None
            continue
        cats = {c: 0.0 for c in CATEGORIES}
        for h in hs:
            cats[_category(h["asset_class"])] += h["market_value"]
        out[b] = {"weights": _apportion(cats), "holdings": hs, "total": total}
    return out


# --- house view -> category stance and TAA tilt ----------------------------------

def _category_views(hv, headlines: dict) -> dict[str, dict]:
    """Per SAA category: a score in [-1, 1] from the CIO view (Buy/Hold/Sell x confidence), halved where the
    agent's own view opposes the CIO's. Returns the evidence used so the reason can quote it."""
    out = {}
    for cat, classes in HV_CLASSES.items():
        parts, scores = [], []
        for ac in classes:
            v = hv.for_class(ac)
            if v is None:
                continue
            s = VIEW_SCORE[v.view] * CONFIDENCE_FACTOR[v.confidence]
            h = headlines.get(ac)
            agent = getattr(h, "agent_view", None)
            if h is not None and getattr(h, "agreement", None) == "opposed":
                s *= 0.5
            scores.append(s)
            parts.append({"asset_class": ac, "view": v.view, "cio_term": v.cio_term, "confidence": v.confidence,
                          "basis": v.basis, "citation_id": v.citation_id, "agent_view": agent,
                          "agreement": getattr(h, "agreement", None)})
        out[cat] = {"score": sum(scores) / len(scores) if scores else 0.0, "views": parts}
    return out


def compute_tilts(saa: dict[str, float], cat_views: dict[str, dict]) -> tuple[dict[str, float], Optional[str]]:
    """Rule-based tilt of the SAA: relative to the average stance of the tilted categories, scaled by BAND_PP,
    net zero, never beyond the band, and never adding to growth assets overall (equities + alternatives).
    Returns ({category: tilt_pp}, note). Falls back to no tilt rather than break a rule."""
    live = [c for c in HV_CLASSES if saa.get(c, 0) > 0]
    zero = {c: 0.0 for c in CATEGORIES}
    if len(live) < 2:
        return zero, "Too few asset classes in the SAA to tilt; held at SAA."
    mean = sum(cat_views[c]["score"] for c in live) / len(live)
    t = dict(zero)
    for c in live:
        t[c] = max(-BAND_PP, min(BAND_PP, (cat_views[c]["score"] - mean) * BAND_PP))
    g = sum(t[c] for c in GROWTH)
    if g > 0:  # growth cannot rise overall: fund it from bonds
        pos = sum(t[c] for c in GROWTH if t[c] > 0)
        f = max(0.0, 1 - g / pos) if pos else 0.0
        for c in GROWTH:
            if t[c] > 0:
                t[c] *= f
        t["Bonds"] = -sum(t[c] for c in t if c != "Bonds")
    t = {c: _r1(v) for c, v in t.items()}
    t["Bonds"] = _r1(-sum(v for c, v in t.items() if c != "Bonds"))  # exact net zero after rounding
    ok = (all(abs(v) <= BAND_PP + 1e-9 for v in t.values())
          and sum(t[c] for c in GROWTH) <= 1e-9
          and all(saa.get(c, 0) + t[c] >= -1e-9 for c in t))
    if not ok:
        return zero, "A tilt would break a band or risk limit; held at SAA."
    return t, None


def _taa_reason(cat: str, saa: float, proposed: float, existing: Optional[float], cv: Optional[dict],
                ctx: Optional[dict] = None) -> str:
    """CIO-style rationale, one bullet per line. Only the tilt size is quoted (no weights, no holdings), except for
    categories with no house view, which are held at their SAA weight."""
    ctx = ctx or {}
    if cat == "Other" or not cv or not cv["views"]:
        return "\n".join([
            f"No house view covers {cat}, so it is held at its SAA weight of {saa:.1f}% with no tilt.",
            "With no CIO or agent view to lean on, we make no tactical call on this category.",
            "We recommend leaving it unchanged while the tilts are funded within the equity, bond and alternatives sleeves."])
    delta = proposed - saa
    risk_asset = cat in GROWTH
    lines = []
    if abs(delta) < 0.05:
        lines.append(f"We propose holding {cat} in line with the strategic allocation, with no tilt.")
    else:
        lines.append(f"We propose {'increasing' if delta > 0 else 'reducing'} {cat} by {abs(delta):.1f}pp.")
    # macro backdrop and why it matters for this asset class
    phase, conf, rec = ctx.get("phase"), ctx.get("confidence"), ctx.get("recession_prob")
    if phase:
        txt = f"Macro backdrop: the economy is in a {phase} phase ({conf} confidence)"
        txt += f" with a 12-month recession probability of {rec * 100:.1f}%." if rec is not None else "."
        lines.append(txt)
        if risk_asset:
            lines.append(f"{cat} is a risk asset, so it is more exposed to growth and earnings risk in a {phase} phase; "
                         "a softer cycle would weigh on it and a resilient one would support it.")
        else:
            lines.append(f"{cat} is a defensive asset class, so it tends to cushion the portfolio if growth slows in a {phase} phase; "
                         "its main sensitivity is to rates and yields.")
    else:
        lines.append("Macro backdrop: the macro read is not available, so this view rests on the house view alone.")
        lines.append(f"{cat} is a {'risk' if risk_asset else 'defensive'} asset class.")
    if MARKET_ANALYSIS_SOURCE == "MOCK":
        lines.append("Note: the market data behind the macro and agent reads is MOCK, so treat it as illustrative.")
    lines.append("CIO house view: " + "; ".join(
        f"{v['asset_class']}: {v['cio_term']} ({v['view']}, {v['confidence']} confidence) [{v['citation_id']}]" for v in cv["views"]) + ".")
    buys = [v["asset_class"] for v in cv["views"] if v["view"] == "Buy"]
    sells = [v["asset_class"] for v in cv["views"] if v["view"] == "Sell"]
    if buys and not sells:
        lines.append(f"This is a favoured asset class: the CIO is Buy on {', '.join(buys)}.")
    elif sells and not buys:
        lines.append(f"This is not a favoured asset class: the CIO is Sell on {', '.join(sells)}.")
    elif buys or sells:
        lines.append(f"The CIO is mixed, with Buy on {', '.join(buys) or 'none'} and Sell on {', '.join(sells) or 'none'}.")
    else:
        lines.append("This is a neutral asset class: the CIO view is Hold.")
    for v in cv["views"]:
        av = v.get("agent_view")
        if av:
            rel = "agrees with the CIO" if av == v["view"] else "is opposed to the CIO" if {av, v["view"]} == {"Buy", "Sell"} else "differs from the CIO"
            lines.append(f"The agent view on {v['asset_class']} is {av} and {rel}.")
    imp = [str(ctx.get("implications", {}).get(v["asset_class"], "")).strip() for v in cv["views"]]
    imp = [i for i in imp if i]
    themes = [t for t in (ctx.get("themes") or [])[:2] if t]
    if imp:
        lines.append("Outlook for the next few months: " + " ".join(imp[:2]))
    if themes:
        lines.append("Key themes to watch: " + "; ".join(themes) + ".")
    top = ctx.get("top_class")
    if abs(delta) < 0.05:
        rec_txt = "We recommend staying at the strategic allocation until the house view gives a clearer signal."
    elif delta > 0:
        rec_txt = ("We recommend funding the increase from the least favoured classes" +
                   (f", keeping {top} as the most favoured" if top and top != cat else "") + ", and staying within the tactical band.")
    else:
        rec_txt = ("We recommend pairing the reduction with the most favoured class" +
                   (f" ({top})" if top and top != cat else "") + " and staying within the tactical band.")
    lines.append(rec_txt)
    return "\n".join(lines)


def build_taa(saa: dict[str, float], existing: Optional[dict[str, float]], cat_views: dict[str, dict],
              ctx: Optional[dict] = None) -> dict:
    tilts, note = compute_tilts(saa, cat_views)
    live = [c for c in HV_CLASSES if saa.get(c, 0) > 0 and cat_views.get(c)]
    ctx = dict(ctx or {})
    if live:
        ctx["top_class"] = max(live, key=lambda c: cat_views[c]["score"])
    rows = []
    for c in CATEGORIES:
        if saa.get(c, 0) <= 0 and (existing or {}).get(c, 0) <= 0:
            continue
        proposed = _r1(saa[c] + tilts[c])
        ex = None if existing is None else existing.get(c, 0.0)
        rows.append({"asset_class": c, "existing": ex, "proposed": proposed, "saa": saa[c], "tilt_pp": tilts[c],
                     "band_low": _r1(max(0.0, saa[c] - BAND_PP)), "band_high": _r1(saa[c] + BAND_PP),
                     "reason": _taa_reason(c, saa[c], proposed, ex, cat_views.get(c), ctx)})
    return {"rows": rows, "note": note}


# --- holdings shifts ---------------------------------------------------------

def build_shifts(existing: dict[str, Optional[dict]], taa: dict[str, dict], shortlist: list) -> list[dict]:
    shifts = []
    for b in BUCKETS:
        ex = existing.get(b)
        rows = {r["asset_class"]: r for r in (taa.get(b) or {}).get("rows", [])}
        if not ex:
            continue  # no priced non-cash holdings; unpriced and cash are added by add_unpriced
        for h in sorted(ex["holdings"], key=lambda h: -h["market_value"]):
            cat = _category(h["asset_class"])
            row = rows.get(cat)
            w = _r1(h["market_value"] / ex["total"] * 100)
            cat_now = ex["weights"].get(cat, 0.0)
            gap = (row["proposed"] - cat_now) if row else 0.0
            action, proposed_w = "retain", w
            if row and gap <= -SHIFT_MIN_PP and cat_now > 0:
                action, proposed_w = "reduce", _r1(w * row["proposed"] / cat_now)
            elif row and gap >= SHIFT_MIN_PP and cat_now > 0:
                action, proposed_w = "increase", _r1(w * row["proposed"] / cat_now)
            name = f"{h['name']} ({h['ticker']})"
            why = (f"{BUCKET_LABEL[b]} {cat} is {cat_now:.1f}% of the bucket against a proposed {row['proposed']:.1f}% "
                   f"in the TAA" if row else f"{cat} has no TAA weight in the {BUCKET_LABEL[b]} bucket")
            why += (f"; this holding is {w:.1f}% of the bucket." if action == "retain" else
                    f"; this holding moves from {w:.1f}% to about {proposed_w:.1f}% of the bucket, pro rata with its category.")
            risks = []
            if w >= CONCENTRATION_PCT:
                risks.append(f"Concentration: {w:.1f}% of the {BUCKET_LABEL[b]} bucket.")
            if h.get("instrument_type") == "stock":
                risks.append("Single-stock exposure.")
            if h.get("pnl_pct") is not None and h["pnl_pct"] > 0 and action == "reduce":
                risks.append(f"Selling realises a gain of {h['pnl_pct']:.1f}% on cost, which may have tax or cost consequences.")
            if h.get("pnl_pct") is not None and h["pnl_pct"] < 0 and action == "reduce":
                risks.append(f"Selling realises a loss of {abs(h['pnl_pct']):.1f}% on cost.")
            shifts.append({"holding": name, "ticker": h["ticker"], "bucket": b, "asset_class": cat, "industry": h.get("sector") or "n/a", "action": action,
                           "current_pct": w, "proposed_pct": proposed_w,
                           "proposed": {"retain": f"Keep at about {w:.1f}% of the {BUCKET_LABEL[b]} bucket",
                                        "reduce": f"Reduce to about {proposed_w:.1f}% of the {BUCKET_LABEL[b]} bucket",
                                        "increase": f"Increase to about {proposed_w:.1f}% of the {BUCKET_LABEL[b]} bucket"}[action],
                           "rationale": why, "risks": risks or ["No holding-specific risk flagged from the data held."]})
    return shifts


def add_unpriced(shifts: list[dict], portfolio: dict, shortlist: list) -> None:
    """Holdings with no stored price are excluded from weights; if the screened shortlist has a product in the same
    category, propose replacing the holding with it, otherwise retain-and-review."""
    for h in portfolio.get("holdings") or []:
        if h.get("portfolio") not in BUCKETS:
            continue
        industry = h.get("sector") or "n/a"
        if h.get("asset_class") == "Cash":  # cash has no SAA/TAA: always listed, as retain, so the page tallies with the database
            shifts.append({"holding": f"{h['name']} ({h['ticker']})", "ticker": h["ticker"], "bucket": h["portfolio"], "asset_class": "Cash",
                           "industry": industry, "action": "retain", "current_pct": None, "proposed_pct": None,
                           "proposed": "Keep as cash", "rationale": "Cash is excluded from the SAA and TAA, so no shift is proposed.",
                           "risks": ["No holding-specific risk flagged from the data held."]})
            continue
        if h.get("price_available"):
            continue
        cat = _category(h["asset_class"])
        cand = next((s for s in shortlist if _hv_category(s.product.asset_class) == cat), None)
        name = f"{h['name']} ({h['ticker']})"
        if cand:
            shifts.append({"holding": name, "ticker": h["ticker"], "bucket": h["portfolio"], "asset_class": cat, "industry": industry,
                           "action": "replace", "current_pct": None, "proposed_pct": None,
                           "proposed": f"Replace with {cand.product.product_name} ({cand.product.product_id}) from the suitability-screened shortlist",
                           "rationale": "The holding has no stored price, so it cannot be valued or weighted in the TAA; "
                                        "a screened shelf product in the same asset class is listed in section E.",
                           "risks": ["Selling an unpriced holding: exit price and dealing terms need to be confirmed."]})
        else:
            shifts.append({"holding": name, "ticker": h["ticker"], "bucket": h["portfolio"], "asset_class": cat, "industry": industry,
                           "action": "retain", "current_pct": None, "proposed_pct": None,
                           "proposed": "Keep, pending a price",
                           "rationale": "The holding has no stored price, so no weight or shift can be computed.",
                           "risks": ["Value and weight unknown."]})


def _hv_category(asset_class: str) -> str:
    for cat, classes in HV_CLASSES.items():
        if asset_class in classes:
            return cat
    return "Other"


# --- narrative (LLM writes words only) -------------------------------------------------

class NarrativeOut(BaseModel):
    client_summary: str
    market_implications: str
    strengths: list[str] = Field(default_factory=list, max_length=5)
    weaknesses: list[str] = Field(default_factory=list, max_length=5)
    taa_longevity: str = ""
    taa_legacy: str = ""


NARRATIVE_SYSTEM = """You write short commentary for a periodic portfolio review pack at a private bank. A rules engine has already
computed every figure, the target allocations, the holding changes and the product shortlist. You do not change, add or
recompute any of them. You only describe them in plain professional English.

You receive JSON facts. Rules:
1. Facts only. Use no outside knowledge, market forecast or fund detail. If a fact is null or missing, say it is not available.
2. Numbers. Use only numbers that appear in the facts, exactly as written. Do not calculate or round new figures.
3. Third person ("the client"). Never address anyone as "you" and never tell anyone what they should do.
4. No guarantees, certainty or superlatives ("best", "risk-free", "will rise"). No fees or costs.
5. The market data behind agent views is MOCK: describe the macro read as illustrative where you mention it.
6. rm_context, if present, is the relationship manager's advisory note. It can explain emphasis, but it never changes the
   IPS, risk profile, suitability, allocations or any figure. Do not repeat numbers that appear only in it.
7. Liquidity has no strategic or tactical allocation. Never propose one.
8. Each text is at most 70 words. Lists have at most 4 items of at most 30 words each. Plain text only, no markdown.
9. ips_passages, if present, are excerpts from the client's signed IPS. Where they bear on a text, ground it in them
   (objectives, risk limits, allocation policy) and paraphrase; do not quote them at length.
Return client_summary, market_implications, strengths, weaknesses, taa_longevity (why the Longevity TAA differs from its
SAA, tied to the house view and the client's objectives) and taa_legacy (the same for Legacy)."""


def _bad(text: str, allowed: set[float]) -> list[str]:
    problems = guardrails._common(text, allowed)
    if m := guardrails._FORECAST.search(text):
        problems.append(f"forecast wording: '{m.group(0)}'")
    if not text.strip():
        problems.append("empty")
    return problems


async def _narrate(facts: dict, service: ProductRecommenderService) -> NarrativeOut:
    try:
        model = service.llm_factory(service.settings)
    except LLMUnavailable as e:
        raise PackGenerationError(503, f"The AI model is unavailable ({e}) The review pack was not generated; please try again later.")
    messages = [("system", NARRATIVE_SYSTEM), ("human", "Facts:\n" + json.dumps(facts, default=str))]
    last = "no response"
    for _ in range(2):
        try:
            raw = await asyncio.wait_for(model.with_structured_output(NarrativeOut).ainvoke(messages),
                                         timeout=service.settings.llm_timeout_seconds)
            return _coerce(NarrativeOut, raw)
        except asyncio.TimeoutError:
            last = "the model timed out"
            break
        except (ValidationError, ValueError):
            last = "the model returned malformed output"
        except Exception as e:  # provider or network failure
            logger.warning("Review pack LLM call failed: %s", type(e).__name__)
            last = f"the model call failed ({type(e).__name__})"
    raise PackGenerationError(503, f"The AI model did not produce usable text ({last}). The review pack was not generated; please try again later.")


def _checked(text: str, fallback: str, allowed: set[float]) -> tuple[str, bool]:
    text = guardrails.normalise(text or "")
    return (text, True) if text and not _bad(text, allowed) else (fallback, False)


def _checked_list(items: list[str], fallback: list[str], allowed: set[float]) -> tuple[list[str], bool]:
    good = [guardrails.normalise(i) for i in items if i and not _bad(guardrails.normalise(i), allowed)]
    return (good, True) if good else (fallback, False)


# --- main ------------------------------------------------------------------------

def _money(v) -> str:
    return f"S${float(v):,.0f}"


async def generate_review_pack(client_id: str, rm_context: Optional[str] = None, *, service: ProductRecommenderService,
                               store=None, portfolio: Optional[dict] = None,
                               clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    rm_context = (rm_context or "").strip()[:RM_CONTEXT_MAX] or None
    try:
        store = store or get_default_store()
        client = store.get_client(client_id)
        if client is None:
            raise PackGenerationError(404, "Client not found.")
        ips, current = store.latest_ips(client_id)
        notes = store.get_notes(client_id)
    except StoreUnavailableError:
        raise PackGenerationError(503, "Client data is unavailable right now, so the review pack was not generated.")
    if ips is None or not current:
        raise PackGenerationError(409, "This client has no Active (signed) IPS, so a review pack cannot be generated. "
                                       "Activate the IPS first.")
    ipsd = _read_ips(ips, current)
    try:
        facts = _facts_by_field(extract_key_facts(store, client_id))
    except Exception:
        facts = {}

    if portfolio is None:
        portfolio = get_client_portfolio(client_id, profiling_store=store)
    if not portfolio.get("available", False):
        raise PackGenerationError(503, "Portfolio data is unavailable right now, so the review pack was not generated.")
    existing = _existing_by_bucket(portfolio)

    try:
        hv = service.house_view()
        headlines = {h.asset_class: h for h in await service.asset_class_headlines()}
        market_res = await service.market_fetcher(None)
    except HouseViewError as e:
        raise PackGenerationError(503, str(e))
    market = market_res.data if market_res.status != "UNAVAILABLE" else None

    cat_views = _category_views(hv, headlines)
    _reg = getattr(market, "regime", None)
    taa_ctx = {"macro": (f"{_reg.phase.replace('_', ' ')} phase ({_reg.confidence} confidence), 12-month recession probability "
                         f"{_reg.recession_prob_12m * 100:.1f}%." if _reg and _reg.phase and _reg.recession_prob_12m is not None else ""),
               "phase": (_reg.phase.replace("_", " ") if _reg and _reg.phase else ""), "confidence": getattr(_reg, "confidence", None),
               "recession_prob": getattr(_reg, "recession_prob_12m", None),
               "themes": list(getattr(market, "key_themes", None) or []),
               "implications": dict(getattr(market, "implications", None) or {})}
    taa: dict[str, dict] = {}
    for b in BUCKETS:
        saa = ipsd["saa"].get(b)
        taa[b] = build_taa(saa, (existing[b] or {}).get("weights"), cat_views, taa_ctx) if saa else {"rows": [], "note": None}

    # Products: the existing recommender, from what is documented about the client.
    products, product_note = None, None
    try:
        prof: dict[str, Any] = {"client_id": client_id, "base_currency": "SGD"}
        if client.aum_sgd:
            prof["total_aum"] = client.aum_sgd
        if client.risk_category:
            prof["risk_appetite"] = client.risk_category
        if client.risk_cap:
            prof["risk_tolerance_score"] = client.risk_cap
        for src, dst in (("annual_income_sgd", "annual_income"), ("monthly_cash_need_sgd", "monthly_expenses"),
                         ("drawdown_tolerance_pct", "maximum_acceptable_drawdown"), ("liquidity_need_sgd", "minimum_cash_reserve")):
            if isinstance(facts.get(src), (int, float)) and facts[src] > 0:
                prof[dst] = facts[src]
        prof.update(_profile_extras(client, notes, ips, facts))
        req = RecommendRequest(client_id=client_id, client_profile=ClientProfile.model_validate(prof),
                               options=RecommendOptions())
        products = (await service.recommend_explained(req)).model_dump(mode="json")
    except (ShelfUnavailable, HouseViewError) as e:
        product_note = f"Product recommendations are unavailable: {e}"
    shortlist = []
    if products:
        from app.agents.product_recommender.schemas import RecommendResponse
        shortlist = RecommendResponse.model_validate(products).shortlist

    shifts = build_shifts(existing, taa, shortlist)
    add_unpriced(shifts, portfolio, shortlist)

    # --- deterministic text -------------------------------------------------------
    unknown = "Not documented"
    regime = getattr(market, "regime", None)
    macro = (f"Macro phase: {regime.phase.replace('_', ' ')} ({regime.confidence} confidence), "
             f"12-month recession probability {regime.recession_prob_12m * 100:.1f}%." if regime and regime.phase and regime.recession_prob_12m is not None
             else "Macro phase: not available.")
    concerns = list(getattr(market, "risks", None) or [])
    themes = list(getattr(market, "key_themes", None) or [])
    favoured = [f"{v.asset_class} ({v.cio_term}, {v.view})" for v in hv.views if v.view == "Buy"]
    headwinds = [f"{v.asset_class} ({v.cio_term}, {v.view})" for v in hv.views if v.view == "Sell"]
    for h in headlines.values():
        if h.agent_view == "Sell" and h.asset_class not in [v.asset_class for v in hv.views if v.view == "Sell"]:
            headwinds.append(f"{h.asset_class} (agent view Sell, {MARKET_ANALYSIS_SOURCE} market data)")
    implications = dict(getattr(market, "implications", None) or {})

    weaknesses_d, strengths_d = [], []
    for b in BUCKETS:
        ex = existing[b]
        rows = taa[b]["rows"]
        if not ex:
            weaknesses_d.append(f"No priced non-cash holdings recorded in the {BUCKET_LABEL[b]} bucket.")
            continue
        for r in rows:
            if r["existing"] is None:
                continue
            gap = r["existing"] - r["saa"]
            msg = f"{BUCKET_LABEL[b]} {r['asset_class']}: held {r['existing']:.1f}% against an SAA of {r['saa']:.1f}%."
            (strengths_d if abs(gap) <= SHIFT_MIN_PP else weaknesses_d).append(msg)
        for h in ex["holdings"]:
            w = h["market_value"] / ex["total"] * 100
            if w >= CONCENTRATION_PCT:
                weaknesses_d.append(f"{h['name']} ({h['ticker']}) is {w:.1f}% of the {BUCKET_LABEL[b]} bucket.")
    for b in BUCKETS:
        if ipsd["saa"].get(b) is None:
            weaknesses_d.append(f"No SAA strategy is saved in the IPS for the {BUCKET_LABEL[b]} bucket, so it cannot be compared.")
    unpriced = [h for h in portfolio.get("holdings") or [] if not h.get("price_available")]
    if unpriced:
        weaknesses_d.append(f"{len(unpriced)} holding(s) have no stored price and are excluded from weights.")
    if portfolio.get("status") == "no_holdings":
        weaknesses_d = ["No holdings are recorded for this client."]
    if not strengths_d:
        strengths_d = ["No bucket-level strength can be stated from the data held."]
    if not weaknesses_d:
        weaknesses_d = ["No weakness flagged against the SAA from the data held."]

    # --- narrative (LLM), numbers guarded ------------------------------------------------
    nfacts = {
        "client": {"name": client.name, "risk_category": client.risk_category, "risk_limit": client.risk_cap,
                   "annual_income_sgd": facts.get("annual_income_sgd"), "monthly_cash_need_sgd": facts.get("monthly_cash_need_sgd"),
                   "liquidity_need_sgd": facts.get("liquidity_need_sgd")},
        "three_l_proportion_pct": ipsd["proportion"], "strategies": ipsd["strategy"],
        "macro": macro, "market_data_label": MARKET_ANALYSIS_SOURCE, "key_themes": themes, "risks": concerns,
        "favoured_by_house_view": favoured, "headwinds": headwinds, "market_implications": implications,
        "portfolio_findings": {"strengths": strengths_d, "weaknesses": weaknesses_d},
        "taa": {b: [{k: r[k] for k in ("asset_class", "existing", "saa", "proposed")} for r in taa[b]["rows"]] for b in BUCKETS},
        "taa_reasons": {b: [r["reason"] for r in taa[b]["rows"]] for b in BUCKETS},
    }
    allowed = guardrails.numbers_in(json.dumps(nfacts, default=str)) | {1.0, 2.0, 3.0}
    ips_passages = await asyncio.to_thread(retrieve_ips_passages, ips, store, client_id, rm_context)
    out = await _narrate({**nfacts, **({"rm_context": rm_context} if rm_context else {}),
                          **({"ips_passages": [{"id": p["chunk_id"], "text": p["text"]} for p in ips_passages]} if ips_passages else {})},
                         service)
    summary_d = f"{client.name} has a {client.risk_category or 'not documented'} risk category with a limit of {client.risk_cap if client.risk_cap else 'not documented'} of 5."
    market_d = " ".join(implications.values()) or "No market implications are available."
    summary, ok1 = _checked(out.client_summary, summary_d, allowed)
    mkt, ok2 = _checked(out.market_implications, market_d, allowed)
    if portfolio.get("status") == "no_holdings":  # nothing to describe: keep the stated fact, not model prose
        strengths, ok3, weaknesses, ok4 = strengths_d, False, weaknesses_d, False
    else:
        strengths, ok3 = _checked_list(out.strengths, strengths_d, allowed)
        weaknesses, ok4 = _checked_list(out.weaknesses, weaknesses_d, allowed)
    taa_text = {}
    oks = [ok1, ok2, ok3, ok4]
    for b, raw in (("longevity", out.taa_longevity), ("legacy", out.taa_legacy)):
        fb = " ".join(r["reason"] for r in taa[b]["rows"]) or f"No SAA is available for {BUCKET_LABEL[b]}, so no TAA is proposed."
        taa_text[b], ok = _checked(raw if taa[b]["rows"] else "", fb, allowed)
        oks.append(ok)

    # --- sections -------------------------------------------------------------------
    def kv(label, value):
        return f"{label}: {value}"

    a_lines = [kv("Client", client.name), kv("Risk category", client.risk_category or unknown),
               kv("Risk limit", f"{client.risk_cap} of 5" if client.risk_cap else unknown),
               kv("Managed assets", _money(client.aum_sgd) if client.aum_sgd else unknown),
               kv("Annual income", _money(facts["annual_income_sgd"]) if "annual_income_sgd" in facts else unknown),
               kv("Monthly expenses", _money(facts["monthly_cash_need_sgd"]) if "monthly_cash_need_sgd" in facts else unknown),
               kv("Liquidity need", _money(facts["liquidity_need_sgd"]) if "liquidity_need_sgd" in facts else unknown),
               kv("Drawdown tolerance", f"{facts['drawdown_tolerance_pct']:g}%" if "drawdown_tolerance_pct" in facts else unknown)]
    goals = [f"{g['title']}: {'; '.join(g['bullets'])}" for g in ipsd["goals"]]
    a_lines.append("Objectives: " + (" | ".join(goals) if goals else unknown))
    prop = ipsd["proportion"]
    a_lines.append("3L proportion: " + (", ".join(f"{k.title()} {_pp(prop[k])}" for k in ("liquidity", "longevity", "legacy"))
                                         if any(v is not None for v in prop.values()) else "not saved in the IPS"))
    saa_blocks = []
    for b in BUCKETS:
        st = ipsd["strategy"].get(b)
        saa = ipsd["saa"].get(b)
        if saa:
            a_lines.append(f"SAA {BUCKET_LABEL[b]} (Strategy {st['code']} - {st['name']}; Liquidity excluded): " +
                           ", ".join(f"{c} {saa[c]:.1f}%" for c in CATEGORIES if saa[c] > 0))
        else:
            a_lines.append(f"SAA {BUCKET_LABEL[b]}: not saved in the IPS")
        saa_blocks.append({"bucket": b, "strategy": st, "weights": saa})
    a_lines.append(f"IPS: version {ipsd['version']} ({ipsd['status']}{'' if ipsd['is_current'] else ', not the current active IPS'}).")
    a_lines.append(summary)
    if rm_context:
        a_lines.append("RM context (advisory only; it does not change the IPS, risk profile, suitability or any figure): " + rm_context)

    b_lines = [macro, f"Source: {MARKET_ANALYSIS_SOURCE} market data. " + (MOCK_NOTE if MARKET_ANALYSIS_SOURCE == "MOCK" else ""),
               "Main concerns: " + ("; ".join(concerns) if concerns else "not available"),
               "Favoured by the CIO house view: " + (", ".join(favoured) or "none"),
               "Headwinds: " + (", ".join(headwinds) if headwinds else "no asset class is rated Sell"),
               "Implications: " + mkt,
               f"House view: {hv.source_document}, as of {hv.as_of}."]
    c_lines = ["Strengths:"] + [f"- {s}" for s in strengths] + ["Weaknesses:"] + [f"- {w}" for w in weaknesses]
    d_lines = []
    for b in BUCKETS:
        d_lines.append(f"{BUCKET_LABEL[b]}: {taa_text[b]}")
        for r in taa[b]["rows"]:
            d_lines.append(f"- {r['asset_class']}: existing {_pp(r['existing'])}, SAA {r['saa']:.1f}%, proposed {r['proposed']:.1f}%")
        if taa[b]["note"]:
            d_lines.append(taa[b]["note"])
    d_lines.append("Liquidity has no SAA or TAA.")
    if products:
        e_lines = [f"Objective: {products['client_summary']['objective']}; risk level {products['client_summary']['risk_level']}. "
                   f"Shelf: {products['sources'].get('shelf')}."]
        for it in products["shortlist"]:
            e_lines.append(f"{it['rank']}. {it['product']['product_name']} ({it['product']['product_id']}, {it['product']['asset_class']})\n{it['reason']['text']}")
        if not products["shortlist"]:
            e_lines.append("No product on the shelf passed the suitability gate for this client.")
        if products.get("missing_information"):
            e_lines.append("Missing information: " + ", ".join(products["missing_information"]))
        e_lines += products.get("limitations") or []
    else:
        e_lines = [product_note or "Product recommendations are unavailable."]
    f_lines = [f"{s['holding']} ({BUCKET_LABEL[s['bucket']]}): {s['action']}. {s['proposed']}. {s['rationale']} Risks: {' '.join(s['risks'])}"
               for s in shifts] or ["No holding shifts: no priced holdings in the Longevity or Legacy buckets."]
    g_lines = ["Relationship Manager: ____ (name, signature, date)", "Portfolio Manager: ____ (name, signature, date)"]

    sources = [
        {"id": "ips", "label": f"IPS version {ipsd['version']} ({ipsd['status']})", "status": "ok"},
        {"id": "holdings", "label": "Client portfolio holdings (client_portfolio store)", "status": portfolio.get("status", "ok")},
        {"id": "meeting_notes", "label": f"Meeting notes ({len(notes)} on file)", "status": "ok" if notes else "none"},
        {"id": "house_view", "label": f"{hv.source_document}, as of {hv.as_of}", "status": "CURATED"},
        {"id": "market_stance", "label": "Market Researcher output (portfolio_agent upstream market_analysis)",
         "status": MARKET_ANALYSIS_SOURCE, "run_id": getattr(market, "run_id", None),
         "note": MOCK_NOTE if MARKET_ANALYSIS_SOURCE == "MOCK" else ""},
        {"id": "shelf", "label": "Product shelf", "status": (products or {}).get("sources", {}).get("shelf", "unavailable")},
    ]
    if rm_context:
        sources.append({"id": "rm_context", "label": "RM context (advisory only)", "status": "advisory"})

    return {
        "client_id": client_id,
        "sections": [
            {"id": "A", "title": "Client Summary", "body": "\n".join(a_lines), "blocks": [{"type": "saa", "items": saa_blocks}]},
            {"id": "B", "title": "Market View", "body": "\n".join(b_lines),
             "blocks": [{"type": "market", "source": MARKET_ANALYSIS_SOURCE, "concerns": concerns, "favoured": favoured, "headwinds": headwinds}]},
            {"id": "C", "title": "Current Portfolio: Strengths and Weaknesses", "body": "\n".join(c_lines), "blocks": []},
            {"id": "D", "title": "Existing vs Proposed TAA", "body": "\n".join(d_lines), "blocks": [{"type": "taa", "buckets": list(BUCKETS)}]},
            {"id": "E", "title": "Product Recommendations", "body": "\n".join(e_lines), "blocks": []},
            {"id": "F", "title": "Individual Holdings Shifts", "body": "\n".join(f_lines), "blocks": []},
            {"id": "G", "title": "Sign-off", "body": "\n".join(g_lines), "blocks": [{"type": "signoff", "roles": ["RM", "PM"]}]},
        ],
        "taa": {b: [{k: r[k] for k in ("asset_class", "existing", "proposed", "reason", "saa", "tilt_pp", "band_low", "band_high")}
                    for r in taa[b]["rows"]] for b in BUCKETS},
        "products": products,
        "holdings_shifts": [{k: s[k] for k in ("holding", "action", "proposed", "rationale", "risks")} | {
            "bucket": s["bucket"], "ticker": s["ticker"], "asset_class": s["asset_class"], "industry": s["industry"], "current_pct": s["current_pct"], "proposed_pct": s["proposed_pct"]} for s in shifts],
        "sources": sources,
        "narrative_status": {"llm_texts_accepted": sum(oks), "llm_texts_total": len(oks),
                             "detail": "Figures come from code; the LLM wrote only the commentary, and any text that failed the guardrail was replaced by rule-based text."},
        "ips_sources": [{"chunk_id": p["chunk_id"], "part": p["part"],
                         "excerpt": p["text"][:IPS_EXCERPT_CHARS]} for p in ips_passages],
        "generated_at": clock().isoformat(),
    }
