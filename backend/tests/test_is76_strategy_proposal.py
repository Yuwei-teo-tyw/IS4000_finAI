"""IS-76: propose and choose a strategy (A-F) per 3L portfolio: boundary, missing info, out-of-date, ordering."""
from app.agents.client_profiling.ips_generate import generate_ips_section
from app.agents.client_profiling.ips_model import merge_section, new_ips_data
from app.agents.client_profiling.strategies import allowed_strategies, load_strategies
from app.agents.client_profiling.threel import (OUT_OF_DATE_MSG, cap_for, profile_fingerprint, risk_boundary, risk_views,
                                                 rule_based_strategy)
from app.endpoints.client_profiling import _flag_out_of_date
from ips_helpers import Chat, FakeStore, alloc_payload, note

N = note(1, "2026-10-20", "Jane: I want a cash reserve for expenses. I am a moderate investor with a long horizon for my children.")


def gen(store, payload=None):
    return generate_ips_section(store, "x", "allocation", Chat(payload if payload is not None else alloc_payload()))


def test_strategies_ordered_a_to_f_and_liquidity_only_a_b():
    assert [s["code"] for s in load_strategies()] == list("ABCDEF")
    assert allowed_strategies("liquidity") == ["A", "B"]
    assert allowed_strategies("longevity") == allowed_strategies("legacy") == list("ABCDEF")


def test_risk_score_extremes_map_to_valid_strategy():
    for score in (1, 5):
        assert rule_based_strategy("liquidity", "", score) in ("A", "B")
        for b in ("longevity", "legacy"):
            assert rule_based_strategy(b, "", score) in "ABCDEF" and cap_for(b, score) in "ABCDEF"
    assert rule_based_strategy("legacy", "", 5) == "F" and rule_based_strategy("liquidity", "", 1) == "A"


def test_boundary_presents_both_and_recommends_more_conservative():
    n = note(2, "2026-10-20", "Jane: My risk appetite is between conservative and moderate.")
    r = gen(FakeStore([n], risk_cap=1), alloc_payload(("A", "C", "D")))
    lng = r["threeL"][1]
    assert r["status"] == "ok" and r["allocation"]["riskScore"] == 1
    assert lng["eligible"] == ["B", "C"] and lng["strategy"] == "B"  # more conservative recommended
    assert "boundary" in lng["boundary"] and "more conservative" in lng["boundary"]
    assert "boundary" in r["message"]


def test_no_boundary_for_single_level_view():
    v = risk_views([note(3, "2026-10-01", "Jane: I am a conservative investor.")])
    assert risk_boundary(v, 1) is None


def test_missing_risk_profile_is_not_generated_and_lists_missing():
    chat = Chat(alloc_payload())
    r = generate_ips_section(FakeStore([note(4, "2026-10-01", "Hello, thanks for coming.")]), "x", "allocation", chat)
    assert r["status"] == "missing" and r["threeL"] == [] and chat.calls == 0
    assert r["missing"] and "Risk profile" in r["missing"][0] and "Risk profile" in r["message"]


def test_no_notes_asks_to_upload_first():
    r = gen(FakeStore([], risk_cap=2))
    assert r["status"] == "no_notes" and "pload" in r["message"]


def test_notes_not_supporting_proposal_use_default_marked():
    r = gen(FakeStore([note(5, "2026-10-01", "Hello, thanks for coming.")], risk_cap=3), {"riskCategory": "", "summary": "", "buckets": []})
    assert r["status"] == "ok" and all(b["default"] for b in r["threeL"])


def test_justification_links_score_horizon_and_source_note():
    r = gen(FakeStore([N], risk_cap=2), alloc_payload(("A", "B", "C"), quote="I am a moderate investor"))
    for b in r["threeL"]:
        assert b["source"]["noteId"] == "note_1" and b["source"]["date"] == "2026-10-20" and b["reason"]
    assert r["allocation"]["riskScore"] == 2


def test_out_of_date_when_profile_or_notes_change():
    store = FakeStore([N], risk_cap=2)
    r = gen(store, alloc_payload(("A", "B", "C")))
    data = merge_section(new_ips_data(), r)
    assert data["threeLBasis"] == profile_fingerprint(store.client, store.notes)

    def flagged():
        v = [{"data": dict(data)}]
        _flag_out_of_date(store, "x", v)
        return v[0]["data"]

    assert flagged()["threeLOutOfDate"] is False
    store.client.risk_cap = 4  # profile changed
    d = flagged()
    assert d["threeLOutOfDate"] is True and d["threeLOutOfDateMessage"] == OUT_OF_DATE_MSG
    store.client.risk_cap = 2
    store.notes.append(note(9, "2026-10-25", "Jane: new meeting."))  # new note
    assert flagged()["threeLOutOfDate"] is True
