"""Post-processing of every generated IPS section result.

* IS-75 + IS-76 applied automatically: the "allocation" section result also carries the 3L PROPORTION
  (`proportion`, `proportionMissing`, `proportionTotal`) next to the strategy A-F picks, and the two are kept consistent.
* `reasoning`: 2-6 short plain-language lines on HOW the section was derived (notes read, facts used, rules applied).
  Built deterministically from the real inputs/results - no extra model call, no invented figures.
Never raises: a failure here only means a result without the extra keys.
"""
from typing import Optional

from .llm import ChatFn, fallback_model_name, model_name
from .proportion import TOTAL, gather_profile, propose_proportion
from .threel import BUCKETS, CODES, cap_for, strategy_name

SMALL_PCT = 5  # a portfolio the proportion sets at or below this share is "~0%"
HIGH_RISK_FROM = CODES.index("E")  # strategies E / F are high-risk
SMALL_PORTFOLIO_CAP = "D"
_LABEL = dict(BUCKETS)
_MAX_LINES = 6
_PHIL_LABEL = {"investmentPeriod": "Investment period"}


# --- helpers ---------------------------------------------------------------------
def _money(v) -> str:
    return f"S${v:,.0f}"


def _dates(notes) -> list[str]:
    return sorted({n.date for n in notes if getattr(n, "date", None)})


def _notes_line(notes) -> str:
    ds = _dates(notes)
    n = len(notes)
    span = f"dated {ds[0]}" if len(ds) == 1 else f"dated {ds[0]} to {ds[-1]}" if ds else "without dates"
    return f"Read {n} meeting note{'s' if n != 1 else ''} ({span}), newest first; when notes disagree the newest is preferred."


def _pad(lines: list[str]) -> list[str]:
    lines = [x for x in lines if x]
    return lines[:_MAX_LINES]


# --- IS-75 proportion on the allocation section -------------------------------------
def _harmonise(res: dict, proportion: dict) -> list[str]:
    """A longevity/legacy portfolio the proportion sets to ~0% must not carry a high-risk strategy (E/F): hold it at D.
    Liquidity carries no strategy. Returns the adjusted bucket ids (also recorded on the result)."""
    adjusted = []
    for b in (res.get("allocation") or {}).get("buckets") or []:
        pct = (proportion.get(b["id"]) or {}).get("pct")
        if b["id"] == "liquidity" or pct is None or pct > SMALL_PCT or b["strategy"] not in CODES:
            continue
        if CODES.index(b["strategy"]) < HIGH_RISK_FROM:
            continue
        old = b["strategy"]
        b["strategy"], b["strategyName"] = SMALL_PORTFOLIO_CAP, strategy_name(SMALL_PORTFOLIO_CAP)
        note = (f" Because the 3L proportion sets {b['portfolio']} at only {pct}%, the strategy is held at "
                f"{SMALL_PORTFOLIO_CAP} instead of the high-risk {old}.")
        b["reason"] = b["justification"] = (b.get("reason") or "") + note
        b["adjustedFrom"] = old
        adjusted.append(b["id"])
    if adjusted:
        by_id = {b["id"]: b for b in res["allocation"]["buckets"]}
        for entry in res.get("threeL") or []:
            src = next((x for x in by_id.values() if x["portfolio"] == entry.get("portfolio")), None)
            if src and src["id"] in adjusted:
                entry.update({"strategy": src["strategy"], "strategyName": src["strategyName"], "reason": src["reason"]})
        res["allocation"]["proportionAdjusted"] = adjusted
    return adjusted


def attach_proportion(store, client_id: str, res: dict, chat: Optional[ChatFn] = None) -> Optional[dict]:
    """Add proportion / proportionMissing / proportionTotal to an allocation result. Returns the gathered profile (or None)."""
    gathered = None
    try:
        gathered = gather_profile(store, client_id)
    except Exception:
        pass
    try:
        out = propose_proportion(store, client_id, chat, gathered=gathered, refine=False)  # rule reasons cite the facts; no 2nd LLM call
    except Exception:
        out = {"status": "unavailable", "proportion": None, "missing": [], "total": TOTAL}
    prop = out.get("proportion") if out.get("status") == "ok" else None
    res["proportion"] = prop
    res["proportionMissing"] = list(out.get("missing") or []) if prop is None else []
    res["proportionTotal"] = TOTAL
    res["proportionMessage"] = (
        "No 3L proportion was proposed. Missing information: " + "; ".join(res["proportionMissing"]) + "."
        if res["proportionMissing"] else "")
    if prop and res.get("status") == "ok":
        _harmonise(res, prop)
    return gathered[0] if gathered and not gathered[1] else None


# --- reasoning ---------------------------------------------------------------------
def _proportion_lines(res: dict, profile: Optional[dict]) -> list[str]:
    prop = res.get("proportion")
    if not prop:
        miss = res.get("proportionMissing") or []
        if miss:
            return ["3L proportion not proposed: " + "; ".join(miss) + " is missing. Per the IS-75 rule nothing is guessed; "
                    "add it and generate again."]
        return ["3L proportion was not proposed because the client profile could not be read."]
    pcts = {k: prop[k]["pct"] for k in prop if isinstance(prop.get(k), dict)}
    total = sum(pcts.values())
    lines = [f"3L proportion adds up to {total}%: " + ", ".join(f"{_LABEL[b]} {pcts[b]}%" for b, _ in BUCKETS if b in pcts) + "."]
    if profile:
        facts = [f"age {profile['age']}", f"risk score {profile['risk_score']} of 5", f"managed assets {_money(profile['aum'])}"]
        if profile.get("reserve"):
            facts.append(f"cash reserve {_money(profile['reserve'])}")
        if profile.get("monthly"):
            facts.append(f"monthly spending {_money(profile['monthly'])}")
        if profile.get("goals"):
            facts.append("goals: " + ", ".join(sorted(g.replace("_", " ") for g in profile["goals"])))
        liq = ("Liquidity covers the stated cash reserve plus a year of spending against managed assets"
               if (profile.get("reserve") or profile.get("monthly")) else "No cash need is stated, so Liquidity follows age and risk score")
        leg = ("a legacy or family goal is stated, so Legacy is set aside"
               if set(profile.get("goals") or []) & {"legacy", "family_foundation"} else "no legacy goal is stated, so Legacy stays small")
        lines.append(f"Based on {', '.join(facts)}. {liq}; {leg}; Longevity takes the remainder for the client's lifestyle.")
    return lines


def _allocation_reasoning(res: dict, notes, profile: Optional[dict]) -> list[str]:
    a = res.get("allocation") or {}
    buckets = a.get("buckets") or []
    lines = [_notes_line(notes)]
    if res.get("status") == "ok" and buckets:
        score, cat = a.get("riskScore"), a.get("riskCategory")
        conflict, boundary = a.get("conflict"), a.get("boundary")
        src = (f"from the latest meeting ({conflict['latest']['date']})" if conflict
               else "on the boundary between two scores" if boundary else "from the client record or the stated risk view")
        lines.append(f"Risk score {score} of 5{f' ({cat})' if cat else ''}, taken {src}. Strategy cap: Longevity up to "
                     f"{cap_for('longevity', score)}, Legacy up to {cap_for('legacy', score)}; Liquidity gets no strategy or SAA.")
        special = []
        if conflict:
            special.append(f"The meetings conflict ({conflict['dates'][0]} vs {conflict['dates'][1]}): the latest one is used.")
        if boundary:
            lo, hi = boundary["levels"]
            special.append(f"The risk view sits between score {lo} and {hi}, so both strategies are eligible and the more "
                           f"conservative (score {lo}) is chosen.")
        defaults = [b["portfolio"] for b in buckets if b.get("default")]
        if defaults:
            special.append(f"{', '.join(defaults)} fell back to the rule-based Default for the risk score because the notes did not support a pick.")
        if special:
            lines.append(" ".join(special))
        picks = ", ".join(f"{b['portfolio']} {b['strategy']} ({b.get('strategyName', '')})" for b in buckets)
        adj = a.get("proportionAdjusted") or []
        lines.append(f"Strategies picked: {picks}." + (
            f" {', '.join(_LABEL[i] for i in adj)} kept below high-risk because the proportion gives it {SMALL_PCT}% or less." if adj else ""))
    elif res.get("status") == "missing":
        lines.append("Required information is missing: " + "; ".join(res.get("missing") or []) + ". Per the IS-76 rule no strategy was proposed.")
    elif res.get("status") == "unavailable":
        lines.append("The local model was not available, so no strategy picks were made; the 3L proportion below uses the rule-based baseline.")
    else:
        lines = ["No meeting notes were found for this client, so nothing was read and no strategy was proposed."]
    return _pad(_fit(lines, _proportion_lines(res, profile)))


def _fit(lines: list[str], extra: list[str]) -> list[str]:
    """Keep the proportion lines within the line budget (they are required; earlier lines are merged if needed)."""
    room = _MAX_LINES - len(extra)
    if len(lines) > room:
        lines = lines[:room - 1] + [" ".join(lines[room - 1:])]
    return lines + extra


def _generic_reasoning(section: str, res: dict, notes) -> list[str]:
    label = section if section != "risk" else "risk profile"
    st = res.get("status")
    if st == "no_notes":
        return ["No meeting notes were found for this client, so nothing was read.",
                f"Nothing was generated for {label}; upload a meeting note and generate again."]
    lines = [_notes_line(notes)]
    if st == "unavailable":
        lines += [f"The local model was not available, so no AI content was produced for {label}.",
                  "Nothing was invented and existing content is left unchanged."]
        return lines
    fields, bullets = res.get("fields") or {}, res.get("bullets") or []
    phil = {k: v for k, v in (res.get("philosophy") or {}).items() if v}
    if section == "goals":
        goals = [g for g in res.get("goals") or [] if g.get("bullets")]
        tg = res.get("targets") or []
        lines.append(f"Filled {len(goals)} of 7 goal headings ({', '.join(g['title'] for g in goals) or 'none'}) from statements in the notes.")
        if tg:
            lines.append(f"Stated target{'s' if len(tg) != 1 else ''}: " + "; ".join(
                f"{t['text']} (from the {t['source_note']['date']} meeting)" for t in tg[:2]) + "; an older meeting's different value is replaced by the latest.")
    elif fields or bullets or phil:
        names = list(fields) or [_PHIL_LABEL.get(k, k.capitalize()) for k in phil]
        lines.append(f"Filled {len(names)} item{'s' if len(names) != 1 else ''} ({', '.join(names)})"
                     + (f" and {len(bullets)} statement{'s' if len(bullets) != 1 else ''}" if bullets and names else "") + " that the notes state.")
    else:
        lines.append(f"The notes do not state anything for {label}, so it was left empty rather than guessed.")
    srcs = res.get("sources") or []
    if srcs:
        lines.append("Facts came from the " + ", ".join(sorted({s["date"] for s in srcs})) + " meeting"
                     + ("s" if len({s["date"] for s in srcs}) > 1 else "") + ", each one cited in the evidence list.")
    lines.append("Rules applied: every figure, currency and key word must appear in the note text, and statements are written about the client in the third person.")
    if res.get("notIncluded"):
        lines.append(f"{len(res['notIncluded'])} statement(s) could not be rewritten safely in the third person and were left out.")
    if "could not be verified" in (res.get("message") or ""):
        lines.append("Some statements could not be verified against the notes and were removed.")
    return _pad(lines)


def build_reasoning(section: str, res: dict, notes, profile: Optional[dict] = None) -> list[str]:
    lines = _allocation_reasoning(res, notes, profile) if section == "allocation" else _generic_reasoning(section, res, notes)
    return lines if len(lines) >= 2 else lines + ["Generated from this client's own meeting notes only."]


def _flag_fallback(res: dict) -> None:
    """Never silent: when the LM Studio fallback model (not the primary) wrote the section, say so in reasoning and status fields."""
    used = res.get("model")
    if used and used == fallback_model_name() and used != model_name():
        msg = f"The primary model ({model_name()}) was not available, so the fallback model {used} wrote this section."
        res["modelFallback"] = True
        res["modelMessage"] = msg
        res["reasoning"] = list(res.get("reasoning") or []) + [msg]


def finish_section(store, client_id: str, section: str, res: dict, chat: Optional[ChatFn] = None, notes=None) -> dict:
    """Add the IS-75 proportion (allocation only) and `reasoning` to a section result. Never raises."""
    profile = None
    if section == "allocation":
        try:
            profile = attach_proportion(store, client_id, res, chat)
        except Exception:
            res.setdefault("proportion", None)
            res.setdefault("proportionMissing", [])
            res["proportionTotal"] = TOTAL
    try:
        notes = list(notes if notes is not None else store.get_notes(client_id) or [])
    except Exception:
        notes = []
    try:
        res["reasoning"] = build_reasoning(section, res, notes, profile)
    except Exception:
        res["reasoning"] = [f"Generated from the client's meeting notes for {section}.", "Reasoning details were not available."]
    _flag_fallback(res)
    return res
