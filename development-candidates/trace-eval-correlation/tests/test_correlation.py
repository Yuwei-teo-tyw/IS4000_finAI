"""1-3: correct joins, missing/duplicate identifiers, parent/child span integrity."""

from __future__ import annotations

import json

from conftest import SESSION, Campaign, Lab, codes, record


def test_case_to_trace_to_score_correlation(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    assert index.index_status == "COMPLETE", index.findings
    a = record(index, "A:case-1")
    assert a.evidence_class == "NATIVE" and a.join_status == "JOINED"
    assert a.model_performance_evidence is True
    assert a.trace.trace_id == SESSION
    assert a.trace.agent_span_id == "a0000000-0000-4000-8000-000000000001"
    assert a.trace.llm_span_id == "b0000000-0000-4000-8000-000000000001"
    assert a.trace.request_id == "11111111-1111-4111-8111-111111111111"
    assert a.trace.span_relationship == "VERIFIED" and a.trace.request_hash_match is True
    assert a.score.agent_success is True and a.score.raw_prose_status == "PASS"
    assert a.score.assessment_observation_binding == "VERIFIED"
    assert a.score.assessment_source_fingerprint_match is True
    assert a.score.assessment_rubric_sha256 == a.versions.rubric_sha256
    assert a.versions.prompt_binding == "EMBEDDED_IN_REQUEST"
    assert a.versions.prompt_ref == "evidence:camp/prompts/p1.txt"
    assert a.versions.response_schema_name == "SyntheticProposal"
    assert a.model_call.model_returned == "synthetic/model" and a.model_call.retries == 0
    assert a.usage.input_tokens == 100 and a.usage.reported_cost_usd == "0.0001"
    assert a.effect.effect_classification == "NO_EXTERNAL_EFFECT"
    assert {x.kind for x in a.artifacts} == {
        "observation_row",
        "receipt.json",
        "request.json",
        "public-output.txt",
    }
    assert all(x.source_manifest == "VERIFIED" for x in a.artifacts if x.kind != "observation_row")

    b = record(index, "B:case-1")
    assert b.validation.observation_status == "REJECTED"
    assert b.validation.rejection_reason == "FORBIDDEN_CAPABILITY"
    assert b.effect.action_kind == "PLAN_PROPOSAL"
    summary = index.sources[0]
    assert {c.name: c.status for c in summary.crosschecks} == {
        "native_attempts": "MATCH",
        "reported_cost_usd": "MATCH",
        "planned_rows": "MATCH",
        "dataset_freeze_files": "MATCH",
    }


def test_missing_request_id_without_preflight_code_is_unjoinable(
    lab: Lab, campaign: Campaign
) -> None:
    campaign.write(lab.evidence / "camp")
    obs_path = lab.evidence / "camp/reports/observations.json"
    rows = json.loads(obs_path.read_text())
    del rows[0]["request_id"]
    obs_path.write_text(json.dumps(rows))
    index = lab.build(lab.manifest(_unlisted()))
    a = record(index, "A:case-1")
    assert "MISSING_REQUEST_ID" in a.issues and a.join_status == "UNJOINABLE"
    assert a.model_performance_evidence is False
    assert "ORPHAN_RECEIPT" in codes(index, "ERROR")
    assert index.index_status == "INCOMPLETE"


def test_duplicate_and_missing_case_ids(lab: Lab, campaign: Campaign) -> None:
    campaign.observations.append(dict(campaign.observations[0]))
    campaign.observations.append(
        {k: v for k, v in campaign.observations[1].items() if k not in ("case_id", "request_id")}
    )
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    dupes = [r for r in index.records if r.case_id == "A:case-1"]
    assert len(dupes) == 2
    assert len({r.record_id for r in index.records}) == len(index.records)
    assert all({"DUPLICATE_CASE_ID", "DUPLICATE_REQUEST_ID"} <= set(r.issues) for r in dupes)
    assert all(r.join_status == "UNJOINABLE" for r in dupes)
    missing = [r for r in index.records if r.record_id.endswith("row-3")]
    assert missing and "MISSING_CASE_ID" in missing[0].issues
    assert index.index_status == "INCOMPLETE"


def test_duplicate_span_and_score_rows(lab: Lab, campaign: Campaign) -> None:
    campaign.trace_lines.insert(2, campaign.trace_lines[1])
    campaign.scores.append(dict(campaign.scores[0]))
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    assert "DUPLICATE_SPAN_ID" in codes(index, "ERROR")
    assert "DUPLICATE_SCORE" in record(index, "A:case-1").issues


def test_llm_span_parented_to_session_is_a_parent_mismatch(lab: Lab, campaign: Campaign) -> None:
    campaign.trace_lines = [
        line.replace(
            '"parent_span_id": "a0000000-0000-4000-8000-000000000001"',
            f'"parent_span_id": "{SESSION}"',
        )
        for line in campaign.trace_lines
    ]
    campaign.write(lab.evidence / "camp")
    a = record(lab.build(lab.manifest()), "A:case-1")
    assert a.trace.span_relationship == "PARENT_MISMATCH"
    assert "SPAN_PARENT_MISMATCH" in a.issues and a.model_performance_evidence is False


def test_agent_span_for_other_case_and_receipt_span_mismatch(lab: Lab, campaign: Campaign) -> None:
    campaign.trace_lines = [
        line.replace(
            '"case_id": "A:case-1", "event": "START", "kind": "AGENT"',
            '"case_id": "Z:other", "event": "START", "kind": "AGENT"',
        )
        for line in campaign.trace_lines
    ]
    campaign.receipts["22222222-2222-4222-8222-222222222222"]["llm_span_id"] = "wrong-span"
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    assert "SPAN_PARENT_MISMATCH" in record(index, "A:case-1").issues
    assert "RECEIPT_SPAN_MISMATCH" in record(index, "B:case-1").issues


def test_orphan_llm_span_and_orphan_score(lab: Lab, campaign: Campaign) -> None:
    campaign.trace_lines.append(
        json.dumps(
            {
                "event": "START",
                "kind": "LLM",
                "span_id": "c0000000-0000-4000-8000-000000000009",
                "parent_span_id": "a0000000-0000-4000-8000-000000000001",
                "case_id": "A:case-1",
                "request_id": "99999999-9999-4999-8999-999999999999",
            }
        )
    )
    campaign.scores.append({"case_id": "Q:ghost"})
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    assert "ORPHAN_LLM_SPAN" in codes(index, "ERROR")
    assert "ORPHAN_SCORE" in codes(index, "WARNING")


def test_score_with_different_join_keys_is_rejected(lab: Lab, campaign: Campaign) -> None:
    campaign.scores[0]["turn_index"] = 7
    campaign.write(lab.evidence / "camp")
    assert "SCORE_KEY_MISMATCH" in record(lab.build(lab.manifest()), "A:case-1").issues


def _unlisted() -> dict[str, object]:
    """A spec with no campaign manifest, for tests that edit evidence after writing it."""
    from conftest import source_spec

    return source_spec(evidence_manifest=None)
