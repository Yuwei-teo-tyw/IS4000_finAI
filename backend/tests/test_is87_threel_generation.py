"""IS-87: AI 3L generation (strategy per portfolio, reason, source note, default, conflict)."""
from app.agents.client_profiling.ips_generate import generate_ips_section
from app.agents.client_profiling.threel import cap_for, risk_conflict, risk_views, rule_based_strategy
from ips_helpers import Chat, FakeStore, alloc_payload, note

N = note(1, "2026-10-20", "Jane: I want to keep a cash reserve for emergencies and expenses. I am very risk averse.\n"
                          "I have a long horizon for my children and legacy.")


def gen(store, payload=None, chat=None):
    return generate_ips_section(store, "x", "allocation", chat or Chat(payload if payload is not None else alloc_payload()))


def test_proposal_per_portfolio_with_reason_source_and_letters():
    r = gen(FakeStore([N], risk_cap=3), alloc_payload(("A", "C", "D"), quote="I am very risk averse"))
    assert r["status"] == "ok" and [b["portfolio"] for b in r["threeL"]] == ["Liquidity", "Longevity", "Legacy"]
    assert [b["strategy"] for b in r["threeL"]] == ["A", "C", "D"]
    for b in r["threeL"]:
        assert b["reason"] and b["default"] is False and b["conflict"] is None
        assert b["source"]["noteId"] == "note_1" and b["source"]["date"] == "2026-10-20" and b["source"]["title"]
        assert b["strategyName"]


def test_liquidity_only_a_or_b_falls_back_to_default():
    r = gen(FakeStore([N], risk_cap=4), alloc_payload(("E", "C", "D")))
    liq = r["threeL"][0]
    assert liq["strategy"] in ("A", "B") and liq["default"] is True


def test_strategies_consistent_with_risk_score():
    # score 1: longevity max B, legacy max C; the model's E / F are rejected for the rule-based default
    r = gen(FakeStore([N], risk_cap=1), alloc_payload(("B", "E", "F")))
    lng, leg = r["threeL"][1], r["threeL"][2]
    assert lng["default"] and lng["strategy"] == cap_for("longevity", 1) == "B"
    assert leg["default"] and leg["strategy"] == cap_for("legacy", 1) == "C"
    assert r["allocation"]["riskScore"] == 1


def test_rule_based_default_marked_when_model_gives_nothing_usable():
    r = gen(FakeStore([N], risk_cap=3), {"riskCategory": "", "summary": "", "buckets": []})
    assert r["status"] == "ok" and all(b["default"] for b in r["threeL"])
    assert [b["strategy"] for b in r["threeL"]] == [rule_based_strategy(p, "", 3) for p in ("liquidity", "longevity", "legacy")]
    assert "Default" in r["message"]


def test_insufficient_notes_use_default():
    thin = note(2, "2026-10-01", "Hello, thanks for coming.")
    r = gen(FakeStore([thin], risk_cap=2), alloc_payload(quote="x", just="The client has a calm outlook zebra."))
    assert all(b["default"] for b in r["threeL"])


def test_no_notes_no_proposal_asks_to_upload():
    c = Chat(alloc_payload())
    r = gen(FakeStore([]), chat=c)
    assert r["status"] == "no_notes" and r["threeL"] == [] and "pload" in r["message"] and c.calls == 0


def test_conflicting_risk_views_use_latest_and_report_both_dates():
    old = note(3, "2026-09-01", "Jane: I am an aggressive investor and happy with high risk.")
    new = note(4, "2026-10-20", "Jane: I am very risk averse now and want to keep capital safe.")
    views = risk_views([old, new])
    assert [v["date"] for v in views] == ["2026-10-20", "2026-09-01"] and views[0]["level"] == 1 and views[1]["level"] == 5
    conflict = risk_conflict(views)
    assert conflict["dates"] == ["2026-10-20", "2026-09-01"] and "2026-10-20" in conflict["note"] and "2026-09-01" in conflict["note"]
    r = gen(FakeStore([old, new], risk_cap=5), alloc_payload(("A", "F", "F")))
    assert r["allocation"]["riskScore"] == 1  # latest meeting wins over the record
    assert all(b["conflict"]["dates"] == ["2026-10-20", "2026-09-01"] for b in r["threeL"])
    assert r["threeL"][1]["strategy"] == "B"  # the aggressive pick is replaced (capped by the latest view)
    assert "2026-09-01" in r["message"]


def test_no_conflict_when_views_agree():
    a, b = note(5, "2026-09-01", "Jane: I am very risk averse."), note(6, "2026-10-20", "Jane: I am very conservative.")
    assert risk_conflict(risk_views([a, b])) is None


def test_negated_statement_is_not_a_view():
    assert risk_views([note(7, "2026-10-01", "She will not accept an aggressive approach.")]) == []
