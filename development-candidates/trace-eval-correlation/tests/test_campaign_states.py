"""6-9: partial/stopped campaigns, preflight separation, missing usage/cost, trace outages."""

from __future__ import annotations

import json

from conftest import Campaign, Lab, Turn, codes, record, source_spec


def _stopped(campaign: Campaign) -> Campaign:
    campaign.status = "STOPPED"
    campaign.turns.append(
        Turn(
            "B:case-2",
            None,
            "a0000000-0000-4000-8000-000000000003",
            None,
            arm="B",
            status="REJECTED",
            error_code="ROUTE_METADATA_UNAVAILABLE",
        )
    )
    campaign.not_run = [
        {"arm": "A", "case_id": "A:case-3", "dataset_case_id": "case-3", "status": "NOT_RUN"}
    ]
    campaign.derive()
    return campaign


def test_partial_stopped_campaign(lab: Lab, campaign: Campaign) -> None:
    _stopped(campaign).write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    summary = index.sources[0]
    assert summary.completeness == "PARTIAL_STOPPED" and summary.campaign_status == "STOPPED"
    assert summary.record_counts == {"NATIVE": 2, "NON_NATIVE_PREFLIGHT": 1, "NOT_RUN": 1}
    assert "CAMPAIGN_PARTIAL" in codes(index, "INFO")
    assert index.index_status == "COMPLETE"  # partial campaign, intact evidence
    nr = record(index, "A:case-3")
    assert nr.evidence_class == "NOT_RUN" and nr.join_status == "NOT_APPLICABLE"
    assert nr.agent == "clarifier" and nr.usage.input_tokens == "NOT_APPLICABLE"
    assert nr.validation.observation_status == "NOT_RUN" and not nr.model_performance_evidence
    checks = {c.name: c for c in summary.crosschecks}
    assert checks["planned_rows"].indexed == "4" and checks["planned_rows"].status == "MATCH"


def test_complete_status_with_not_run_rows_is_inconsistent(lab: Lab, campaign: Campaign) -> None:
    campaign.not_run = [{"arm": "A", "case_id": "A:case-3"}]
    campaign.derive()
    campaign.write(lab.evidence / "camp")
    assert "CAMPAIGN_STATUS_INCONSISTENT" in codes(lab.build(lab.manifest()), "ERROR")


def test_not_run_row_that_was_observed_conflicts(lab: Lab, campaign: Campaign) -> None:
    campaign.status = "STOPPED"
    campaign.not_run = [{"arm": "A", "case_id": "A:case-1"}]
    campaign.derive()
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    conflict = [r for r in index.records if r.evidence_class == "NOT_RUN"]
    assert conflict and "NOT_RUN_CONFLICT" in conflict[0].issues


def test_unmapped_status_and_planned_row_mismatch(lab: Lab, campaign: Campaign) -> None:
    campaign.status = "SOMETHING_NEW"
    campaign.derive()
    campaign.scope.append({"id": "A:extra", "role": "clarifier"})
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    assert index.sources[0].completeness == "UNAVAILABLE"
    assert "CAMPAIGN_STATUS_UNMAPPED" in codes(index, "WARNING")
    assert "CROSSCHECK_MISMATCH" in codes(index, "ERROR")


def test_preflight_row_is_not_a_native_request(lab: Lab, campaign: Campaign) -> None:
    _stopped(campaign).write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    pre = record(index, "B:case-2")
    assert pre.evidence_class == "NON_NATIVE_PREFLIGHT" and pre.join_status == "JOINED"
    assert pre.model_performance_evidence is False
    assert pre.trace.request_id == "NOT_APPLICABLE" and pre.trace.llm_span_id == "NOT_APPLICABLE"
    assert pre.trace.agent_span_id == "a0000000-0000-4000-8000-000000000003"
    assert pre.model_call.send_claimed == "NOT_APPLICABLE"
    assert pre.usage.reported_cost_usd == "NOT_APPLICABLE"
    assert pre.validation.rejection_reason == "ROUTE_METADATA_UNAVAILABLE"
    attempts = {c.name: c for c in index.sources[0].crosschecks}["native_attempts"]
    assert attempts.indexed == "2" and attempts.status == "MATCH"


def test_preflight_with_llm_span_is_flagged(lab: Lab, campaign: Campaign) -> None:
    _stopped(campaign)
    campaign.trace_lines.append(
        json.dumps(
            {
                "event": "START",
                "kind": "LLM",
                "span_id": "c0000000-0000-4000-8000-000000000003",
                "parent_span_id": "a0000000-0000-4000-8000-000000000003",
                "case_id": "B:case-2",
            }
        )
    )
    campaign.write(lab.evidence / "camp")
    assert "PREFLIGHT_HAS_LLM_SPAN" in record(lab.build(lab.manifest()), "B:case-2").issues


def test_unverified_tokens_and_missing_cost_stay_unavailable(lab: Lab, campaign: Campaign) -> None:
    receipt = campaign.receipts["11111111-1111-4111-8111-111111111111"]
    receipt["token_usage_verified"] = False
    del receipt["reported_cost_usd_exact"]
    other = campaign.receipts["22222222-2222-4222-8222-222222222222"]
    other["billing_verified"] = False
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    a, b = record(index, "A:case-1"), record(index, "B:case-1")
    assert a.usage.input_tokens == "UNAVAILABLE" and a.usage.output_tokens == "UNAVAILABLE"
    assert a.usage.reported_cost_usd == "UNAVAILABLE" and a.usage.cost_scope == "UNAVAILABLE"
    assert {"TOKEN_USAGE_UNAVAILABLE", "COST_UNAVAILABLE"} <= set(a.issues)
    assert b.usage.reported_cost_usd == "UNAVAILABLE" and b.usage.input_tokens == 100
    assert a.join_status == "PARTIAL" and a.model_performance_evidence is False
    cost = {c.name: c for c in index.sources[0].crosschecks}["reported_cost_usd"]
    assert cost.indexed == "UNAVAILABLE" and cost.status == "UNAVAILABLE"
    assert '"reported_cost_usd": 0' not in json.dumps(index.model_dump(mode="json"))


def test_non_string_cost_is_not_coerced(lab: Lab, campaign: Campaign) -> None:
    campaign.receipts["11111111-1111-4111-8111-111111111111"]["reported_cost_usd_exact"] = 0.0
    campaign.write(lab.evidence / "camp")
    assert record(lab.build(lab.manifest()), "A:case-1").usage.reported_cost_usd == "UNAVAILABLE"


def test_trace_file_unavailable_marks_index_incomplete(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    (base / "reports/traces.jsonl").unlink()
    index = lab.build(lab.manifest())
    assert "TRACE_UNAVAILABLE" in codes(index, "ERROR") and index.index_status == "INCOMPLETE"
    a = record(index, "A:case-1")
    assert a.trace.llm_span_id == "UNAVAILABLE" and a.trace.trace_id == "UNAVAILABLE"
    assert a.usage.input_tokens == 100  # receipts still join; only trace fields are unknown
    assert a.join_status == "PARTIAL" and a.model_performance_evidence is False


def test_trace_writer_crash_truncated_line(lab: Lab, campaign: Campaign) -> None:
    # Simulate a writer that died mid-record: last END lines lost, final line truncated.
    campaign.trace_lines = [*campaign.trace_lines[:-3], '{"event": "END", "span_id": "a0']
    campaign.trace_lines.append(json.dumps({"event": "END", "span_id": "never-started"}))
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    assert "TRACE_LINE_MALFORMED" in codes(index, "ERROR")
    assert {"TRACE_SPAN_UNTERMINATED", "TRACE_END_WITHOUT_START"} <= codes(index, "WARNING")
    b = record(index, "B:case-1")
    assert b.trace.agent_span_status == "UNAVAILABLE"


def test_no_trace_file_declared(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    spec = source_spec()
    del spec["files"]["traces"]
    index = lab.build(lab.manifest(spec))
    assert "TRACE_UNAVAILABLE" in codes(index, "ERROR")
