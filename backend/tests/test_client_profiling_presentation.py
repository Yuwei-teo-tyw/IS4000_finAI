"""Presentation layer: few concept groups, one tight line each. Uses a constructed profile."""
import json
import re

from app.agents.client_profiling.presentation import build_sections, money, short_message
from app.agents.client_profiling.schemas import ClientProfile, Conflict, Fact, SourceRef, ToolResult

KINDS = ("documented", "calculated", "inferred", "missing")


def src(pid="note_1", passage="stated"):
    return SourceRef(type="meeting_note", id=pid, client_id="c1", date="2026-01-01", label=f"Note {pid}", passage=passage)


def F(field, value, kind="documented", cat="client_financial", note=None):
    return Fact(field=field, category=cat, value=value, kind=kind, sources=[src()] if kind != "missing" else [], note=note)


def profile(**over) -> ClientProfile:
    facts = [
        F("aum_managed_sgd", 2_000_000.0), F("other_assets_sgd", 1_000_000.0), F("liabilities_sgd", 500_000.0),
        F("annual_income_sgd", 300_000.0), F("monthly_cash_need_sgd", 10_000.0),
        F("annual_cash_need_sgd", 120_000.0, "calculated", note="Calculated: monthly cash need x 12."),
        F("goals", ["house_purchase", "retirement"], cat="objectives"),
        F("investment_horizon", ["in about three years"], cat="objectives"),
        F("liquidity_need_sgd", 1_000_000.0, cat="objectives"),
        F("liquidity_need_pct_of_aum", 50.0, "calculated", "objectives", "Calculated: liquidity need / managed assets x 100."),
        F("risk_classification", {"category": "Balanced", "risk_limit_of_5": 3}, cat="risk"),
        F("risk_capacity", "Moderate", cat="risk"),
        F("risk_tolerance", "moderate (inferred)", "inferred", "risk"),
        F("drawdown_tolerance_pct", 10.0, cat="risk"),
        F("max_loss_at_drawdown_sgd", 200_000.0, "calculated", "risk", "Calculated: managed assets x 10% drawdown tolerance."),
        F("risk_attitude_statements", ["He dislikes drops in value."], cat="risk"),
        F("knowledge_experience", ["Invested in funds for ten years."], cat="risk"),
        F("restrictions", ["tobacco"], cat="preferences"),
        F("currency_preference", ["SGD"], cat="preferences"),
        F("sustainability_preferences", None, "missing", "preferences"),
        F("asset_class_preferences", ["bonds"], cat="preferences"),
    ]
    p = ClientProfile(client_id="c1", client_name="Test Client", facts=facts, missing=["sustainability_preferences"],
                      outdated=["Meeting note note_2 (2026-02-01, Check-in) is newer than the last profile review."],
                      conflicts=[Conflict(field="drawdown_tolerance_pct", statements=[src("note_2")], explanation="One note says 10% but a later note says 8%.")])
    p.facts = [f for f in p.facts if f.field not in over] + list(over.values())
    return p


def sections_for(p=None):
    p = p or profile()
    r = ToolResult(tool="extract_key_facts", client_id="c1", data=p.model_dump(mode="json"))
    return build_sections(r, p)


def by_heading(secs):
    return {s.heading: s for s in secs}


def all_lines(secs):
    return [ln for s in secs for ln in s.lines]


def check_contract(secs):
    for s in secs:
        d = s.model_dump()
        assert "items" not in d and set(d) == {"heading", "meaning", "lines", "sources"}
        assert s.meaning.count(". ") == 0 and len(s.meaning) <= 161
        for ln in s.lines:
            assert set(ln.model_dump()) == {"text", "kind"} and ln.kind in KINDS
            assert 0 < len(ln.text) <= 140, ln.text


_OK = lambda s, u: __import__('json').dumps({'in_scope': True, 'broad': False, 'answerable': True, 'answer': 'ok', 'groups': [], 'cites': ['C0']})  # noqa: E731


def test_key_fact_groups_are_few_and_short():
    secs = sections_for()
    check_contract(secs)
    h = by_heading(secs)
    assert {"Cash flow & liquidity", "Wealth", "Goals & horizon", "Risk", "Preferences & restrictions", "To confirm"} <= set(h)
    assert len(secs) <= 6
    for s in secs:
        assert len(s.lines) <= (4 if s.heading == "To confirm" else 3), s.heading
    assert "<table" not in json.dumps([s.model_dump() for s in secs])


def test_cash_flow_wealth_lines_keep_numbers_with_context():
    h = by_heading(sections_for())
    cash = [ln.text for ln in h["Cash flow & liquidity"].lines]
    assert any("S$10,000/month" in t and "S$120,000/yr" in t and "40% of income" in t for t in cash)
    assert any("S$1.0m" in t and "50%" in t for t in cash)
    wealth = [ln.text for ln in h["Wealth"].lines]
    assert any("S$3.0m" in t and "67% managed" in t for t in wealth)
    assert any("S$500,000" in t and "25%" in t for t in wealth)
    assert money(1_500_000) == "S$1.5m" and money(38_000) == "S$38,000"


def test_drawdown_line_has_s_dollar_max_loss():
    risk = by_heading(sections_for())["Risk"]
    dd = next(ln for ln in risk.lines if "10%" in ln.text)
    assert "S$200,000" in dd.text and "S$2.0m" in dd.text and dd.kind == "calculated"
    first = risk.lines[0]
    assert "Balanced" in first.text and "capacity" in first.text and "tolerance" in first.text
    assert "unconfirmed" in first.text and first.kind == "inferred"


def test_missing_become_ask_and_conflict_staleness_one_line_each():
    tc = by_heading(sections_for())["To confirm"]
    texts = [ln.text for ln in tc.lines]
    assert any(t.startswith("Ask:") and ln.kind == "missing" for t, ln in zip(texts, tc.lines))
    assert sum(t.startswith("Conflict:") for t in texts) == 1 and sum(t.startswith("Check:") for t in texts) == 1
    assert any("unconfirmed" in t for t in texts)  # inferred tolerance flagged
    # missing facts are not repeated as rows under other groups
    for h, s in by_heading(sections_for()).items():
        if h != "To confirm":
            assert all(ln.kind != "missing" for ln in s.lines)


def test_sources_are_deduped_union():
    for s in sections_for():
        keys = [(x.id, x.passage) for x in s.sources]
        assert len(keys) == len(set(keys))
    assert by_heading(sections_for())["Wealth"].sources


def test_meeting_note_sections():
    s = src("note_9", "Deposit raised.")
    r = ToolResult(tool="get_meeting_note", client_id="c1", sources=[s], data={"notes": [
        {"note_id": "note_9", "date": "2026-03-01", "title": "Check-in", "source_file": "x.pdf", "excerpt": "Check-in with the client."}]})
    secs = build_sections(r, None)
    assert secs[0].heading == "Check-in · 2026-03-01" and secs[0].sources[0].id == "note_9"
    long = "A" * 300 + "\n\nSecond paragraph."
    r2 = ToolResult(tool="read_meeting_note", client_id="c1", sources=[s], data={"note_id": "note_9", "date": "d", "title": "T", "text": long})
    secs2 = build_sections(r2, None)
    check_contract(secs2)
    assert len(secs2[0].lines) == 2


def test_meeting_summary_groups_by_concept():
    p = profile()
    r = ToolResult(tool="get_meeting_note", client_id="c1", sources=[src()], data={"summarise": True, "notes": [{"note_id": "note_1", "date": "2026-01-01", "title": "T"}]})
    secs = build_sections(r, p)
    check_contract(secs)
    h = by_heading(secs)
    assert {"Cash Inflow", "Cash Outflow", "Risk appetite", "Asset-class preferences"} <= set(h) and "Open items" not in h
    assert all(len(s.lines) <= 3 for s in secs)


def test_short_message_is_one_sentence():
    assert short_message("First one. Second one.") == "First one."


def test_service_adds_sections_and_keeps_data_keys():
    from app.agents.client_profiling.service import handle_chat
    r2 = handle_chat("summarise the meeting notes", "jfr", answer_chat=_OK)
    # the summary carries the facts, so the key-facts sections are not sent alongside it (they would repeat the same headings)
    assert r2.tool == "get_meeting_note" and "summary" in r2.data and "sections" not in r2.data
