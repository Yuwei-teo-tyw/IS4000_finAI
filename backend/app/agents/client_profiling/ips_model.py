"""Structured IPS data model helpers (see the JSON contract at the top of schemas.py).

Pure functions, no LLM: goals sub-headings (IS-93), stated targets, canned review rules, signature fields,
section merging and rendering to the legacy text `parts`.
"""
import re
from datetime import date
from typing import Optional

from .ips_generate_labels import GOAL_LABELS
from .strategies import get_strategy, rate_of_return_text

PLACEHOLDER = "Not yet completed"
GOAL_KEYS = [("returnRequirements", "Return Requirements"), ("investmentTimeHorizon", "Investment Time Horizon"),
             ("primaryGoals", "Primary Goals"), ("secondaryGoals", "Secondary Goals"), ("liquidityNeeds", "Liquidity Needs"),
             ("taxConsiderations", "Tax Considerations"), ("uniqueCircumstances", "Unique Circumstances and Preferences")]
KEYS = [k for k, _ in GOAL_KEYS]
_LABEL_TO_KEY = {l.lower(): KEYS[i] for i, l in enumerate(GOAL_LABELS)}
_LABEL_TO_KEY.update({t.lower(): k for k, t in GOAL_KEYS})
RM_SIGNATURE_IMAGE = "/signature-isabel.png"

REVIEW_RULES = [
    {"title": "Review frequency", "text": "The IPS is reviewed at least annually, and the portfolio is monitored against it on an ongoing basis."},
    {"title": "Review triggers", "text": "An ad-hoc review is held on a material change in the client's circumstances (income, wealth, health, "
     "family, liabilities), on a major life event (for example retirement, a property purchase or a child starting university), "
     "on a significant market event, when the portfolio deviates from the Strategic Asset Allocation beyond the agreed tolerance "
     "bands, or on a regulatory change that affects the mandate."},
    {"title": "Who reviews", "text": "The Relationship Manager leads the review with the client; the Portfolio Manager confirms the "
     "allocation and the strategies; compliance sign-off is required for any change to the IPS."},
    {"title": "Documentation", "text": "Every review and every change is recorded as a new IPS version with its date, author, the reason "
     "for the change and the supporting meeting note."},
    {"title": "Communication to the client", "text": "The client receives the updated IPS after each review, and is told promptly of "
     "any breach of the tolerance bands or any change to the strategy; the client confirms it in writing."},
]


def empty_goals() -> list[dict]:
    return [{"key": k, "title": t, "bullets": [], "empty": True, "placeholder": PLACEHOLDER} for k, t in GOAL_KEYS]


def _finish(goals: list[dict]) -> list[dict]:
    for g in goals:
        g["bullets"] = [b for b in g["bullets"] if b]
        g["empty"] = not g["bullets"]
        g["placeholder"] = PLACEHOLDER
    return goals


def key_for_label(label: str) -> str:
    """Goal label -> key; anything that fits no sub-heading goes under Unique Circumstances and Preferences."""
    return _LABEL_TO_KEY.get((label or "").strip().rstrip(":").lower(), "uniqueCircumstances")


def goals_from_bullets(bullets: list[str]) -> list[dict]:
    """['Return requirements: ...', ...] -> the 7 ordered sub-headings."""
    goals = empty_goals()
    by_key = {g["key"]: g for g in goals}
    for b in bullets or []:
        m = re.match(r"\s*([A-Za-z &]+?)\s*:\s*(.+)$", str(b))
        label, text = (m.group(1), m.group(2).strip()) if m and m.group(1).strip().lower() in _LABEL_TO_KEY else ("", str(b).strip())
        if text and text not in by_key[key_for_label(label)]["bullets"]:
            by_key[key_for_label(label)]["bullets"].append(text)
    return _finish(goals)


def normalize_goals(x) -> list[dict]:
    """Accept the new shape, an old list of 'Label: text' strings, a {key|label: [bullets]} dict, or None."""
    if not x:
        return empty_goals()
    if isinstance(x, dict):
        goals = empty_goals()
        for k, v in x.items():
            key = k if k in KEYS else key_for_label(str(k))
            vals = v if isinstance(v, list) else [v]
            next(g for g in goals if g["key"] == key)["bullets"].extend(str(i) for i in vals if i)
        return _finish(goals)
    if isinstance(x, list) and all(isinstance(i, str) for i in x):
        return goals_from_bullets(x)
    goals = empty_goals()
    by_key = {g["key"]: g for g in goals}
    for g in x if isinstance(x, list) else []:
        if isinstance(g, dict):
            key = g.get("key") if g.get("key") in KEYS else key_for_label(str(g.get("title") or ""))
            by_key[key]["bullets"].extend(str(b) for b in (g.get("bullets") or []) if b and str(b) not in by_key[key]["bullets"])
    return _finish(goals)


# --- targets ----------------------------------------------------------------
_CCY_MAP = {"s$": "SGD", "sgd": "SGD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP",
            "hk$": "HKD", "hkd": "HKD"}
_MULT = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_TARGET_RE = re.compile(
    r"\b(?:hit|reach|grow(?:\s+\w+){0,3}?\s+to|target(?:ing)?|achieve|get\s+to)\s+(?:a\s+(?:value\s+of\s+)?)?"
    r"(?P<ccy>S\$|US\$|HK\$|\$|SGD|USD|EUR|GBP|€|£)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<unit>million|billion|mn|bn|m|b|k)\b"
    r"(?P<rest>[^.;\n]{0,80}?\b(?:in|within|over|by)\s+(?P<yrs>\d+)\s+(?:years?|yrs?))?", re.I)
_SPEAKER = re.compile(r"^\s*[A-Z][A-Za-z]+(?:\s\([A-Za-z]+\))?:\s*")


def _split(text: str) -> list[str]:
    return [_SPEAKER.sub("", x.strip()) for x in re.split(r"(?<=[.!?])\s+|\n+", text) if len(x.strip()) > 3]


def _src(n) -> dict:
    return {"id": n.id, "date": n.date, "title": n.title or n.source_file or n.id}


def _tgt_key(t: dict) -> tuple:
    return (t.get("amount"), t.get("horizonYears"))


def extract_targets(notes) -> list[dict]:
    """Stated investment targets, e.g. 'she wants to hit 800m in investment portfolio in 5 years'.

    Targets are the same kind of fact (a portfolio-value goal, per currency); when different meetings state different
    ones only the LATEST meeting's targets are returned, each carrying `superseded` (the earlier, replaced versions) so
    the UI can show the history. Each target's `source_note` is the note the sentence actually came from."""
    found: list[dict] = []
    for n in sorted(notes, key=lambda n: (n.date or "", n.id), reverse=True):  # newest first
        for sent in _split(n.text):
            for m in _TARGET_RE.finditer(sent):
                amount = float(m.group("num").replace(",", "")) * _MULT[m.group("unit").lower()]
                yrs = int(m.group("yrs")) if m.group("yrs") else None
                ccy = _CCY_MAP.get((m.group("ccy") or "").lower())
                token = f"{m.group('ccy') or ''}{m.group('num')}{m.group('unit')}".replace("million", "M")
                found.append({"amount": int(amount) if amount == int(amount) else amount, "currency": ccy, "horizonYears": yrs,
                              "text": m.group(0).strip(), "token": token, "source_note": _src(n)})
    out: list[dict] = []
    for t in found:  # newest note first
        same = [o for o in out if o["currency"] == t["currency"] or not o["currency"] or not t["currency"]]
        if any(_tgt_key(o) == _tgt_key(t) for o in same):
            continue  # same target restated in an older note
        latest = next((o for o in same if o["source_note"]["id"] != t["source_note"]["id"]), None)
        if latest is not None and (latest["source_note"]["date"], latest["source_note"]["id"]) > (t["source_note"]["date"], t["source_note"]["id"]):
            for o in same:  # an older meeting's different value of the same kind of target: superseded, not listed
                if o["source_note"]["id"] == latest["source_note"]["id"]:
                    o.setdefault("superseded", []).append({k: v for k, v in t.items() if k != "token"})
            continue
        out.append(t)
    return out


_AMOUNT_IN_TEXT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(million|billion|mn|bn|m|b|k)\b", re.I)


def _amounts(text: str) -> set:
    return {float(m.group(1).replace(",", "")) * _MULT[m.group(2).lower()] for m in _AMOUNT_IN_TEXT.finditer(text or "")}


def drop_superseded(bullets: list[str], targets: list[dict]) -> list[str]:
    """Remove bullets that state only an older meeting's (superseded) target value."""
    old = {float(s["amount"]) for t in targets for s in t.get("superseded") or []}
    cur = {float(t["amount"]) for t in targets}
    old -= cur
    return [b for b in bullets if not (old and _amounts(b) & old and not _amounts(b) & cur)]


def target_bullet(t: dict) -> str:
    h = f" within {t['horizonYears']} years" if t.get("horizonYears") else ""
    return f"The client wants the portfolio to reach {t.get('token') or t['text']}{h}"


def public_target(t: dict) -> dict:
    return {k: v for k, v in t.items() if k != "token"}


def apply_targets(goals: list[dict], targets: list[dict]) -> list[dict]:
    """Add each (latest) target to Return Requirements and Primary Goals unless a bullet there already states it;
    bullets that state only a superseded value are removed. Callers run the pronoun pass afterwards."""
    by_key = {g["key"]: g for g in goals}
    for g in goals:
        g["bullets"] = drop_superseded(g["bullets"], targets)
    for t in targets:
        token = (t.get("token") or "").lower()
        for key in ("returnRequirements", "primaryGoals"):
            if not any(token and token in b.lower().replace(" ", "") for b in by_key[key]["bullets"]):
                by_key[key]["bullets"].append(target_bullet(t))
    return _finish(goals)


# --- whole-IPS data ---------------------------------------------------------
def new_ips_data(today: Optional[date] = None) -> dict:
    return {"goals": empty_goals(), "targets": [], "reviewRules": [dict(r) for r in REVIEW_RULES],
            "threeL": [], "threeLStatus": "", "threeLMessage": "",
            "threeLProportion": None, "threeLProportionMessage": "", "riskScore": None, "model": None, "modelMessage": "",
            "notIncluded": [], "evidence": {}, "rmSignatureImage": RM_SIGNATURE_IMAGE,
            "rmSignedDate": (today or date.today()).isoformat()}


def _with_ror(b):
    """Every 3L bucket carries `rateOfReturn` (text), recomputed from its current strategy so it never goes stale."""
    if not isinstance(b, dict):
        return b
    return {**b, "rateOfReturn": rate_of_return_text(b.get("strategy") or "")}


def normalize_data(d: Optional[dict], signed: Optional[str] = None) -> dict:
    """Fill every contract field on loaded data (old IPS versions without `data` get the defaults; `signed` is the
    fallback rmSignedDate, e.g. the version's issue date)."""
    base = new_ips_data()
    if signed:
        base["rmSignedDate"] = signed
    out = {**base, **(d or {})}
    out["goals"] = normalize_goals(out.get("goals"))
    out.pop("lifeEvents", None)  # Life Events was removed from the IPS: old saved data that still has it just drops the key
    out["targets"] = out.get("targets") or []
    out["reviewRules"] = out.get("reviewRules") or base["reviewRules"]
    out["threeL"] = [_with_ror(b) for b in out.get("threeL") or []]
    if isinstance(out.get("philosophy"), dict):
        out["philosophy"] = {**out["philosophy"], "investmentPeriod": str(out["philosophy"].get("investmentPeriod") or "")}
    out["threeLProportion"] = out.get("threeLProportion") or None
    out["threeLProportionMessage"] = out.get("threeLProportionMessage") or ""
    out["notIncluded"] = out.get("notIncluded") or []
    out["evidence"] = out.get("evidence") or {}
    if not out.get("rmSignatureImage"):
        out["rmSignatureImage"] = RM_SIGNATURE_IMAGE
    if not out.get("rmSignedDate"):
        out["rmSignedDate"] = base["rmSignedDate"]
    return out


def _proportion_message(res: dict) -> str:
    missing = res.get("proportionMissing") or res.get("missing") or []
    if res.get("proportion") or not missing:
        return ""
    return "No 3L proportion was proposed. Missing information: " + "; ".join(missing) + "."


def merge_section(data: dict, res: dict) -> dict:
    """Fold one generation-section result into the structured IPS `data` (in place; returns it)."""
    sec = res.get("section")
    if res.get("status") == "ok":
        if sec == "demographics":
            data["demographics"] = {"fields": res.get("fields") or {}}
        elif sec == "philosophy":
            data["philosophy"] = res.get("philosophy") or {}
        elif sec == "risk":
            data["risk"] = {"fields": res.get("fields") or {}, "bullets": res.get("bullets") or []}
        elif sec == "goals":
            data["goals"] = res.get("goals") or empty_goals()
            data["targets"] = res.get("targets") or []
        elif sec == "allocation":
            data["threeL"] = res.get("threeL") or []
            data["riskScore"] = (res.get("allocation") or {}).get("riskScore")
            data["threeLBasis"] = (res.get("allocation") or {}).get("basis", "")
            data["threeLProportion"] = res.get("proportion")
            data["threeLProportionMessage"] = _proportion_message(res)
        if res.get("evidence"):
            data.setdefault("evidence", {})[sec] = res["evidence"]
    if sec == "allocation" and res.get("status") == "missing":  # IS-75: required section missing -> no proportion, say what is missing
        data["threeLProportion"] = None
        data["threeLProportionMessage"] = _proportion_message(res)
    if sec == "allocation":
        data["threeLStatus"] = res.get("status", "")
        data["threeLMessage"] = res.get("message", "")
    if res.get("model"):
        data["model"] = res["model"]
        data["modelMessage"] = ""
    elif res.get("status") == "unavailable" and not data.get("model"):
        data["modelMessage"] = res.get("modelMessage") or res.get("message", "")
    for s in res.get("notIncluded") or []:
        if s not in data["notIncluded"]:
            data["notIncluded"].append(s)
    return data


def render_parts(data: dict) -> list[dict]:
    """Legacy text parts (title, body) rendered from the structured data, so IPS search/indexing keeps working."""
    d = normalize_data(data)
    goals = []
    for g in d["goals"]:
        goals.append(f"{g['title']}: " + ("; ".join(g["bullets"]) if g["bullets"] else PLACEHOLDER))
    prop = d.get("threeLProportion")
    prop_txt = ("3L proportion (adds up to 100%): " + ", ".join(
        f"{lab} {prop[k]['pct']}%" + (f" ({prop[k]['reason']})" if prop[k].get("reason") else "")
        for k, lab in (("liquidity", "Liquidity"), ("longevity", "Longevity"), ("legacy", "Legacy")) if isinstance(prop.get(k), dict))
        if isinstance(prop, dict) else d.get("threeLProportionMessage") or "")
    threel = " ".join(f"{b['portfolio']}: Strategy {b['strategy']} ({b.get('strategyName', '')}). {b.get('reason', '')} {b.get('rateOfReturn', '')}".replace("  ", " ").strip() for b in d["threeL"])
    threel = (threel + "\n" + prop_txt).strip() if prop_txt and threel else threel
    risk = d.get("risk") or {}
    risk_txt = "; ".join(f"{k}: {v}" for k, v in (risk.get("fields") or {}).items()) + " " + "; ".join(risk.get("bullets") or [])
    rules = " ".join(f"{r['title']}: {r['text']}" for r in d["reviewRules"])
    sign = f"Signed by the RM on {d['rmSignedDate']}."
    ph = d.get("philosophy") or {}
    phil_txt = "; ".join(f"{lab}: {ph[key]}" for key, lab in (("approach", "Approach"), ("believes", "Believes"), ("avoids", "Avoids"),
                                                            ("investmentPeriod", "Investment period")) if ph.get(key))
    demo = "; ".join(f"{k}: {v}" for k, v in ((d.get("demographics") or {}).get("fields") or {}).items())
    # Part numbers are a stable contract with the frontend (part 1 goals, 2 3L, 3 risk, 5 review rules, 6 signature); never renumber.
    saa = d.get("saa") if isinstance(d.get("saa"), dict) else {}
    saa_txt = "\n".join((f"{lab}: Model {saa[k]['modelId']} {saa[k].get('modelName', '')} (Strategy {saa[k]['strategy']}), weights "
                         + ", ".join(f"{a} {w:g}%" for a, w in (saa[k].get("weights") or {}).items()) + ".")
                        if saa[k].get("modelId") else
                        f"{lab}: Strategy {saa[k]['strategy']} ({(get_strategy(saa[k]['strategy']) or {}).get('name', '')})."
                        for k, lab in (("longevity", "Longevity"), ("legacy", "Legacy"))
                        if isinstance(saa.get(k), dict) and saa[k].get("strategy"))
    return [{"part": 1, "title": "Client goals and objectives", "owner": "rm", "status": "filled", "body": "\n".join(goals)},
            {"part": 2, "title": "3L buckets and explanation", "owner": "pm", "status": "filled" if threel else "empty", "body": threel},
            {"part": 3, "title": "Client risk profile", "owner": "rm", "status": "filled" if risk_txt.strip() else "empty", "body": risk_txt.strip()},
            {"part": 4, "title": "Strategic Asset Allocation", "owner": "pm", "status": "filled" if saa_txt else "empty", "body": saa_txt},
            {"part": 5, "title": "Review rules", "owner": "rm", "status": "filled", "body": rules},
            {"part": 6, "title": "Signature line", "owner": "rm", "status": "filled", "body": sign},
            ] + ([{"part": 7, "title": "Investment philosophy", "owner": "rm", "status": "filled", "body": phil_txt}] if phil_txt else []) \
              + ([{"part": 8, "title": "Demographics", "owner": "rm", "status": "filled", "body": demo}] if demo else [])


# Sections that still show "Not yet completed" (IS-101): goals subheadings, philosophy fields, risk, 3L, demographics.
_PHIL_FIELDS = (("approach", "Approach"), ("believes", "Believes"), ("avoids", "Avoids"), ("investmentPeriod", "Investment period"))


def _blank(v) -> bool:
    return v is None or str(v).strip() in ("", PLACEHOLDER)


def empty_sections(data: Optional[dict]) -> list[str]:
    d = normalize_data(data)
    out = [g["title"] for g in d["goals"] if not g.get("bullets")]
    ph = d.get("philosophy")
    if not isinstance(ph, dict) or not ph:
        out.append("Investment philosophy")
    else:
        out += [f"Investment philosophy: {lab}" for key, lab in _PHIL_FIELDS if _blank(ph.get(key))]
    risk = d.get("risk") or {}
    if not (risk.get("fields") or risk.get("bullets")):
        out.append("Client risk profile")
    if not d["threeL"]:
        out.append("3L buckets and explanation")
    if not ((d.get("demographics") or {}).get("fields")):
        out.append("Demographics")
    return out
