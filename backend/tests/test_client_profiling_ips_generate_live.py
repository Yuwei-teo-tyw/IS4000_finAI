"""Opt-in: AI IPS generation against a REAL local model (LM Studio).

    RUN_LIVE_PROFILING_TESTS=1 pytest -m live tests/test_client_profiling_ips_generate_live.py
"""
import os

import pytest

from app.agents.client_profiling.ips_generate import SECTION_IDS, generate_ips_section
from app.agents.client_profiling.store import DocumentStore, MeetingNoteDoc

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("RUN_LIVE_PROFILING_TESTS"), reason="set RUN_LIVE_PROFILING_TESTS=1 (needs the local model)"),
]


def test_live_seeded_client_all_sections_grounded():
    s = DocumentStore()
    notes = " ".join(n.text for n in s.get_notes("jft"))
    for sec in SECTION_IDS:
        r = generate_ips_section(s, "jft", sec)  # real local model
        assert r["status"] == "ok", r
        for v in list(r["fields"].values()) + r["bullets"] + list(r.get("philosophy", {}).values()):
            assert v and (set(__import__("re").findall(r"\d+", v)) <= set(__import__("re").findall(r"\d+", notes)))
        assert all(src["id"].startswith("note_jft") for src in r["sources"])
    # seeded notes state an annual income, AUM and a 10 year horizon
    d = generate_ips_section(s, "jft", "demographics")
    assert "10m" in (d["fields"].get("Annual income") or "").lower() or "500m" in (d["fields"].get("AUM") or "").lower()


def test_live_quantified_goal_captured():
    class St:
        def get_notes(self, cid):
            return [MeetingNoteDoc(id="note_q", client_id=cid, date="2026-10-01", title="Onboarding",
                                   text="Tom is 45 years old. His goal is to grow the portfolio to 700M within 8 years. "
                                        "He avoids tobacco and prefers a long-term diversified approach.")]
    r = generate_ips_section(St(), "x", "goals")
    assert r["status"] == "ok"
    assert any("700M" in b and "8 years" in b for b in r["bullets"]), r
    assert r["sources"][0]["id"] == "note_q"


def _jft_notes(s):
    return {n.id: n for n in s.get_notes("jft")}


def test_live_jft_goals_have_700m_target_under_return_requirements():
    s = DocumentStore()
    r = generate_ips_section(s, "jft", "goals")
    assert r["status"] == "ok", r
    assert any(b.startswith("Return requirements:") and "700M" in b for b in r["bullets"]), r
    labels = {"Return requirements", "Investment time horizon", "Primary goals", "Secondary goals", "Liquidity needs",
              "Tax considerations", "Unique circumstances & preferences"}
    assert all(b.split(":")[0] in labels for b in r["bullets"]), r["bullets"]
    notes = _jft_notes(s)
    assert r["evidence"]
    for e in r["evidence"]:
        assert e["passage"] in notes[e["noteId"]].text and e["item"]


def test_live_jft_risk_tolerance_capacity_and_evidence():
    s = DocumentStore()
    r = generate_ips_section(s, "jft", "risk")
    assert r["status"] == "ok", r
    assert "Risk tolerance (willingness)" in r["fields"] and "Risk capacity (ability)" in r["fields"], r
    notes = _jft_notes(s)
    assert r["evidence"] and all(e["passage"] in notes[e["noteId"]].text for e in r["evidence"])
