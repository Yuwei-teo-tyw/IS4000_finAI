"""4-5: source hashes (missing, mismatched, stale) and unjoinable references."""

from __future__ import annotations

import hashlib
import json

from conftest import Campaign, Lab, codes, record, source_spec


def test_file_changed_after_campaign_manifest_is_a_mismatch(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    scores = base / "reports/scores.json"
    scores.write_text(scores.read_text().replace("PASS", "FAIL"))
    index = lab.build(lab.manifest())
    assert "SOURCE_HASH_MISMATCH" in codes(index, "ERROR")
    ref = next(f for f in index.sources[0].files if f.kind == "scores")
    assert ref.source_manifest == "MISMATCH"
    assert index.index_status == "INCOMPLETE"


def test_pin_recorded_earlier_detects_stale_source(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    pins = {"reports/observations.json": "0" * 64}
    index = lab.build(lab.manifest(source_spec(pins=pins)))
    assert "SOURCE_PIN_STALE" in codes(index, "ERROR")
    ref = next(f for f in index.sources[0].files if f.kind == "observations")
    assert ref.pin == "STALE" and ref.source_manifest == "VERIFIED"


def test_pin_matching_current_file_verifies(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    digest = hashlib.sha256((base / "reports/observations.json").read_bytes()).hexdigest()
    index = lab.build(lab.manifest(source_spec(pins={"reports/observations.json": digest})))
    ref = next(f for f in index.sources[0].files if f.kind == "observations")
    assert ref.pin == "VERIFIED" and index.index_status == "COMPLETE"


def test_file_absent_from_campaign_manifest_is_reported(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    path = base / "reports/EVIDENCE_MANIFEST.json"
    listed = json.loads(path.read_text())
    del listed["reports/scores.json"]
    path.write_text(json.dumps(listed))
    index = lab.build(lab.manifest())
    assert "NOT_IN_CAMPAIGN_MANIFEST" in codes(index, "WARNING")


def test_missing_required_file_and_missing_campaign_manifest(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    (base / "reports/scores.json").unlink()
    (base / "reports/EVIDENCE_MANIFEST.json").unlink()
    index = lab.build(lab.manifest())
    found = codes(index, "ERROR")
    assert {"SOURCE_FILE_MISSING", "CAMPAIGN_MANIFEST_UNAVAILABLE", "MISSING_SCORE"} <= found
    assert record(index, "A:case-1").score.agent_success == "UNAVAILABLE"


def test_dataset_freeze_drift(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    (base / "evaluation/cases.json").write_text("[]")
    index = lab.build(lab.manifest(source_spec(evidence_manifest=None)))
    assert "DATASET_FREEZE_MISMATCH" in codes(index, "ERROR")
    check = {c.name: c for c in index.sources[0].crosschecks}["dataset_freeze_files"]
    assert check.status == "MISMATCH"


def test_reference_hash_mismatch_and_missing_reference(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    refs = [
        {
            "ref_id": "audit",
            "root": "evidence",
            "path": "camp/reports/summary.json",
            "sha256": "0" * 64,
        },
        {"ref_id": "gone", "root": "evidence", "path": "camp/absent.md", "sha256": "0" * 64},
    ]
    index = lab.build(lab.manifest(source_spec(), references=refs))
    assert {"REFERENCE_STALE", "REFERENCE_MISSING_FILE"} <= codes(index, "ERROR")


def test_request_id_path_traversal_is_unjoinable(lab: Lab, campaign: Campaign) -> None:
    campaign.observations[0]["request_id"] = "../../outside"
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    a = record(index, "A:case-1")
    assert "UNJOINABLE_REQUEST_ID" in a.issues and a.join_status == "UNJOINABLE"
    assert all("outside" not in x.ref for x in a.artifacts)


def test_source_path_escaping_root_is_unjoinable(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest(source_spec(path="../elsewhere")))
    assert "SOURCE_UNJOINABLE" in codes(index, "ERROR") and index.records == []


def test_missing_receipt_and_receipt_id_mismatch(lab: Lab, campaign: Campaign) -> None:
    campaign.receipts["22222222-2222-4222-8222-222222222222"]["request_id"] = "not-the-dir"
    base = campaign.write(lab.evidence / "camp")
    rid = "11111111-1111-4111-8111-111111111111"
    for name in ("receipt.json", "request.json", "public-output.txt"):
        (base / f"reports/requests/{rid}/{name}").unlink()
    (base / f"reports/requests/{rid}").rmdir()
    index = lab.build(lab.manifest(source_spec(evidence_manifest=None)))
    a = record(index, "A:case-1")
    assert "RECEIPT_MISSING" in a.issues
    assert a.model_call.model_returned == "UNAVAILABLE" and a.usage.input_tokens == "UNAVAILABLE"
    assert "RECEIPT_ID_MISMATCH" in codes(index, "ERROR")
    assert "RECEIPT_MISSING" in record(index, "B:case-1").issues


def test_request_bytes_differing_from_receipt_hash(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    rid = "11111111-1111-4111-8111-111111111111"
    (base / f"reports/requests/{rid}/request.json").write_text('{"model": "changed"}')
    (base / f"reports/requests/{rid}/public-output.txt").write_text("changed")
    a = record(lab.build(lab.manifest(source_spec(evidence_manifest=None))), "A:case-1")
    assert {"REQUEST_HASH_MISMATCH", "PUBLIC_OUTPUT_HASH_MISMATCH"} <= set(a.issues)


def test_assessment_bound_to_different_observation(lab: Lab, campaign: Campaign) -> None:
    campaign.assessments["A:case-1"]["observation_sha256"] = "0" * 64
    campaign.assessments["B:case-1"]["rubric_sha256"] = "1" * 64
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    assert "ASSESSMENT_OBSERVATION_MISMATCH" in record(index, "A:case-1").issues
    assert "RUBRIC_HASH_MISMATCH" in record(index, "B:case-1").issues
