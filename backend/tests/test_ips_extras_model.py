"""IPS extras: targets, life events, review rules, signature fields, reasons (pure model + seed data)."""
from datetime import date

from app.agents.client_profiling.ips_model import (REVIEW_RULES, apply_targets, empty_goals, extract_life_events, extract_targets,
                                                    merge_section, new_ips_data, normalize_data, render_parts)
from app.agents.client_profiling.ips_generate import generate_ips_section, third_person
from app.agents.client_profiling.store import DocumentStore
from ips_helpers import Chat, FakeStore, note

N = note(1, "2026-10-20", "Jane: She wants to hit 800m in investment portfolio in 5 years.\n"
                          "Jane: My daughter starts university overseas in September 2029. I plan to buy a holiday home in 2028.\n"
                          "Jane: I intend to retire in 2041, when I turn 60. I may relocate in the future. We will retire in 2050.")


def test_target_extracted_with_structure():
    (t,) = extract_targets([N])
    assert t["amount"] == 800_000_000 and t["horizonYears"] == 5 and "800m" in t["text"] and t["currency"] is None
    assert t["source_note"] == {"id": "note_1", "date": "2026-10-20", "title": "Meeting"}


def test_seed_target_captured_and_in_goals():
    st = DocumentStore()
    ts = extract_targets(st.get_notes("jfr"))
    assert len(ts) == 1 and ts[0]["amount"] == 700_000_000 and ts[0]["horizonYears"] == 8  # same target in 3 sentences, de-duplicated
    goals = {g["key"]: g for g in apply_targets(empty_goals(), ts)}
    assert any("700M" in b and "8 years" in b for b in goals["returnRequirements"]["bullets"])
    assert any("700M" in b for b in goals["primaryGoals"]["bullets"])


def test_target_not_duplicated_in_bullets():
    t = extract_targets([N])
    g = apply_targets(apply_targets(empty_goals(), t), t)
    assert len(g[0]["bullets"]) == 1


def test_life_events_with_dates_and_third_person():
    skipped = []
    ev = extract_life_events([N], third_person, skipped)
    by = {e["label"]: e for e in ev}
    assert by["Daughter starts university"]["date"] == "2029-09" and by["Daughter starts university"]["year"] == 2029
    assert by["Property purchase"]["year"] == 2028 and by["Retirement"]["year"] == 2041
    assert all(e["manual"] is False and e["source_note"]["id"] == "note_1" and e["id"] for e in ev)
    assert "The client plans to buy" in by["Property purchase"]["detail"]
    assert [e["year"] for e in ev] == sorted(e["year"] for e in ev)
    assert any("We will retire" in s for s in skipped)  # unsafe first-person-plural sentence is listed, not used


def test_seed_notes_have_life_events():
    ev = extract_life_events(DocumentStore().get_notes("jfr"), third_person)
    assert {e["label"] for e in ev} >= {"Daughter starts university", "Property purchase", "Retirement"}
    assert all(e["year"] and e["detail"].startswith("The client") or "the client" in e["detail"].lower() for e in ev)


def test_generation_goals_include_targets_and_life_events():
    r = generate_ips_section(FakeStore([N]), "x", "goals", Chat({"bullets": []}))
    assert r["targets"][0]["amount"] == 800_000_000 and r["lifeEvents"]
    g = {x["key"]: x for x in r["goals"]}
    assert g["returnRequirements"]["bullets"] and g["primaryGoals"]["bullets"]


def test_review_rules_and_signature_defaults_no_llm():
    d = new_ips_data()
    titles = [r["title"] for r in d["reviewRules"]]
    assert d["reviewRules"] == REVIEW_RULES and {"title", "text"} == set(d["reviewRules"][0])
    text = " ".join(r["text"] for r in d["reviewRules"]).lower()
    for kw in ("annually", "material change", "life event", "market event", "tolerance band", "regulatory", "recorded"):
        assert kw in text, kw
    assert d["rmSignatureImage"] == "/signature-isabel.png" and d["rmSignedDate"] == date.today().isoformat()


def test_signed_date_fallback_for_old_versions_and_defaults():
    d = normalize_data({}, signed="2026-01-02")
    assert d["rmSignedDate"] == "2026-01-02" and d["rmSignatureImage"] == "/signature-isabel.png" and len(d["goals"]) == 7
    assert normalize_data({"rmSignedDate": "2026-05-05"})["rmSignedDate"] == "2026-05-05"


def test_manual_life_events_survive_regeneration_and_normalization():
    d = new_ips_data()
    d["lifeEvents"] = [{"id": "m1", "year": 2035, "label": "Sabbatical", "detail": "x", "manual": True}]
    merge_section(d, {"section": "goals", "status": "ok", "goals": empty_goals(), "targets": [],
                      "lifeEvents": [{"id": "le_1", "year": 2029, "label": "Retirement", "detail": "d", "manual": False}]})
    assert [(e["id"], e["manual"]) for e in d["lifeEvents"]] == [("le_1", False), ("m1", True)]
    assert normalize_data(d)["lifeEvents"][1]["manual"] is True


def test_three_l_reason_rendered_in_parts():
    d = new_ips_data()
    d["threeL"] = [{"portfolio": "Liquidity", "strategy": "A", "strategyName": "Fixed Income", "reason": "RM-written reason", "default": False}]
    body = {p["part"]: p["body"] for p in render_parts(d)}
    assert "RM-written reason" in body[2] and "Not yet completed" in body[1] and "Signed by the RM" in body[6]


from app.agents.client_profiling.ips_model import goals_from_bullets  # noqa: E402


def test_later_meeting_target_supersedes_earlier_and_attribution_is_per_note():
    a = note(1, "2026-10-13", "Jane: I want to reach 700M within 8 years.", title="First meeting")
    b = note(2, "2026-10-20", "Jane: I want to hit 800M in my investment portfolio in 5 years.", title="Follow-up")
    for notes in ([a, b], [b, a]):
        (t,) = extract_targets(notes)
        assert (t["amount"], t["horizonYears"], t["source_note"]["id"]) == (800_000_000, 5, "note_2")
        assert [(s["amount"], s["source_note"]["id"]) for s in t["superseded"]] == [(700_000_000, "note_1")]
    goals = apply_targets(goals_from_bullets(["Return requirements: The client wants to reach 700M within 8 years"]), extract_targets([a, b]))
    assert goals[0]["bullets"] == ["The client wants the portfolio to reach 800M within 5 years"]


def test_same_note_keeps_both_targets():
    n = note(1, "2026-10-13", "Jane: I want to reach 700M within 8 years. Later I want to hit 900M in 12 years.")
    assert len(extract_targets([n])) == 2
