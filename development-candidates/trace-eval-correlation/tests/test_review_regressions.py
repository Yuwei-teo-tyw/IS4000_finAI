"""Regressions for the attempt-1 independent review findings (P1-1, P2-1..P2-4, P3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import Campaign, Lab, codes, record, render_index, source_spec
from trace_eval_correlation.cli import main


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("relative", ["evaluation/freeze-manifest.json", "evaluation/rubric.json"])
def test_p1_missing_hashed_binding_file_is_an_error(
    lab: Lab, campaign: Campaign, relative: str
) -> None:
    base = campaign.write(lab.evidence / "camp")
    (base / relative).unlink()
    index = lab.build(lab.manifest())
    assert "SOURCE_FILE_MISSING" in codes(index, "ERROR")
    assert index.index_status == "INCOMPLETE"
    assert not any(r.model_performance_evidence for r in index.records)
    assert all("SOURCE_INTEGRITY_GAP" in r.issues for r in index.records)


def test_p1_missing_pinned_file_without_campaign_manifest(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    pins = {"evaluation/freeze-manifest.json": _sha(base / "evaluation/freeze-manifest.json")}
    (base / "evaluation/freeze-manifest.json").unlink()
    index = lab.build(lab.manifest(source_spec(evidence_manifest=None, pins=pins)))
    assert "SOURCE_FILE_MISSING" in codes(index, "ERROR")


def test_p2_1_edited_bound_prompt_is_stale(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    pins = {"prompts/p1.txt": _sha(base / "prompts/p1.txt")}
    (base / "prompts/p1.txt").write_bytes(b"SYNTHETIC CLARIFIER PROMPT v1")  # still embedded
    index = lab.build(lab.manifest(source_spec(evidence_manifest=None, pins=pins)))
    assert "SOURCE_PIN_STALE" in codes(index, "ERROR")
    assert not any(r.model_performance_evidence for r in index.records)


def test_p2_1_edited_unused_candidate_breaks_campaign_manifest(
    lab: Lab, campaign: Campaign
) -> None:
    base = campaign.write(lab.evidence / "camp")
    (base / "prompts/p0.txt").write_bytes(b"EDITED")
    index = lab.build(lab.manifest())
    assert "SOURCE_HASH_MISMATCH" in codes(index, "ERROR")
    prompt = [f for f in index.sources[0].files if f.ref.endswith("p0.txt")]
    assert prompt and prompt[0].source_manifest == "MISMATCH"


def test_p2_2_receipt_files_not_listed_are_not_model_evidence(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    path = base / "reports/EVIDENCE_MANIFEST.json"
    listed = json.loads(path.read_text())
    rid = "11111111-1111-4111-8111-111111111111"
    for name in ("receipt.json", "request.json", "public-output.txt"):
        del listed[f"reports/requests/{rid}/{name}"]
    path.write_text(json.dumps(listed))
    a = record(lab.build(lab.manifest()), "A:case-1")
    assert "ARTIFACT_NOT_LISTED" in a.issues
    assert a.join_status == "PARTIAL" and a.model_performance_evidence is False


def test_p2_2_stale_trace_pin_degrades_every_record(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest(source_spec(pins={"reports/traces.jsonl": "0" * 64})))
    assert "SOURCE_PIN_STALE" in codes(index, "ERROR")
    assert all("SOURCE_INTEGRITY_GAP" in r.issues for r in index.records)
    assert not any(r.model_performance_evidence for r in index.records)


def test_p2_2_unterminated_llm_span_is_not_model_evidence(lab: Lab, campaign: Campaign) -> None:
    campaign.trace_lines = [
        line
        for line in campaign.trace_lines
        if '"span_id": "b0000000-0000-4000-8000-000000000001", "status"' not in line
    ]
    campaign.write(lab.evidence / "camp")
    a = record(lab.build(lab.manifest()), "A:case-1")
    assert a.trace.llm_span_status == "UNAVAILABLE"
    assert "TRACE_SPAN_STATUS_UNAVAILABLE" in a.issues and a.model_performance_evidence is False


def test_p2_3_not_run_ids_are_unique(lab: Lab, campaign: Campaign) -> None:
    campaign.status = "STOPPED"
    campaign.not_run = [
        {"arm": "A", "case_id": "A:case-3"},
        {"arm": "A", "case_id": "A:case-3"},
        {"arm": "A", "case_id": "A:case-1"},
        {"arm": "A", "case_id": ["x"]},
    ]
    campaign.derive()
    campaign.scope = [s for s in campaign.scope if isinstance(s["id"], str)]
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    ids = [r.record_id for r in index.records]
    assert len(ids) == len(set(ids))
    assert "DUPLICATE_RECORD_ID" not in codes(index)
    dup = [r for r in index.records if r.case_id == "A:case-3"]
    assert len(dup) == 2 and all("DUPLICATE_CASE_ID" in r.issues for r in dup)
    conflict = [
        r for r in index.records if r.case_id == "A:case-1" and r.evidence_class == "NOT_RUN"
    ]
    assert conflict and "NOT_RUN_CONFLICT" in conflict[0].issues
    assert any(
        "MISSING_CASE_ID" in r.issues for r in index.records if r.evidence_class == "NOT_RUN"
    )


def test_p2_4_source_summary_is_privacy_filtered(lab: Lab, campaign: Campaign) -> None:
    campaign.status = "pat@example.com"
    campaign.derive()
    campaign.summary["campaign"] = "Bearer sk-abcdefghijklmnop"
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    text = render_index(index)
    assert "pat@example.com" not in text and "sk-abcdefghijklmnop" not in text
    assert index.sources[0].campaign_status == "REDACTED"
    assert "PRIVACY_REDACTED" in codes(index, "WARNING")


def test_p3_receipt_keys_must_match_observation(lab: Lab, campaign: Campaign) -> None:
    campaign.receipts["11111111-1111-4111-8111-111111111111"]["case_id"] = "B:case-1"
    campaign.write(lab.evidence / "camp")
    assert "RECEIPT_KEY_MISMATCH" in record(lab.build(lab.manifest()), "A:case-1").issues


def test_p3_unpinned_source_is_visible(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest(source_spec(evidence_manifest=None)))
    assert "SOURCE_UNPINNED" in codes(index, "WARNING")
    assert not any(r.model_performance_evidence for r in index.records)


def test_p3_junit_non_integer_count(lab: Lab) -> None:
    (lab.evidence / "off").mkdir(parents=True)
    (lab.evidence / "off/tests.xml").write_text(
        '<testsuite tests="many"><testcase classname="a" name="b"/></testsuite>'
    )
    spec = {
        "source_id": "off",
        "kind": "offline_junit",
        "root": "evidence",
        "path": "off",
        "declared_evidence_class": "OFFLINE_TEST",
        "evaluation_id": "off/t",
        "files": {"junit": "tests.xml"},
    }
    index = lab.build(lab.manifest(spec))
    assert index.sources[0].crosschecks[0].status == "UNAVAILABLE"


def test_p3_freeze_path_escape_does_not_crash(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    spec = source_spec()
    spec["files"]["dataset_freeze"] = "../../outside.json"
    index = lab.build(lab.manifest(spec))
    assert "UNJOINABLE_REFERENCE" in codes(index, "ERROR")


def test_p3_verify_requires_sidecar_and_bad_manifest_is_usage_error(
    lab: Lab, campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    campaign.write(lab.evidence / "camp")
    manifest = lab.write_manifest(lab.manifest())
    index = lab.root / "out" / "index.json"
    root = f"evidence={lab.evidence}"
    assert main(["build", "--manifest", str(manifest), "--index", str(index), "--root", root]) == 0
    (index.parent / "index.json.sha256").unlink()
    assert main(["verify", "--manifest", str(manifest), "--index", str(index), "--root", root]) == 1
    bad = lab.root / "out" / "bad.json"
    bad.write_text(json.dumps({"manifest_version": "nope", "secret_field": "sk-zzzzzzzzzzzz"}))
    capsys.readouterr()
    assert main(["build", "--manifest", str(bad), "--index", str(index), "--root", root]) == 64
    err = capsys.readouterr().err
    assert "manifest invalid" in err and "sk-zzzz" not in err and "Traceback" not in err


def test_attempt2_p2_pinned_source_without_campaign_manifest_is_unanchored(
    lab: Lab, campaign: Campaign
) -> None:
    base = campaign.write(lab.evidence / "camp")
    pins = {"reports/observations.json": _sha(base / "reports/observations.json")}
    receipt = base / "reports/requests/11111111-1111-4111-8111-111111111111/receipt.json"
    data = json.loads(receipt.read_text())
    data["input_tokens"] = 999999
    receipt.write_text(json.dumps(data))
    a = record(lab.build(lab.manifest(source_spec(evidence_manifest=None, pins=pins))), "A:case-1")
    assert "ARTIFACT_UNANCHORED" in a.issues
    assert a.join_status == "PARTIAL" and a.model_performance_evidence is False


def test_attempt2_p3_unreadable_freeze_manifest_is_reported(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    (base / "evaluation/freeze-manifest.json").write_text('{"no_files": true}')
    index = lab.build(lab.manifest(source_spec(evidence_manifest=None)))
    assert "DATASET_FREEZE_UNREADABLE" in codes(index, "ERROR")
    assert not any(r.model_performance_evidence for r in index.records)


def test_attempt2_p3_empty_sidecar_and_pin_escape_are_usage_errors(
    lab: Lab, campaign: Campaign
) -> None:
    campaign.write(lab.evidence / "camp")
    manifest = lab.write_manifest(lab.manifest())
    index = lab.root / "out" / "index.json"
    root = f"evidence={lab.evidence}"
    assert main(["build", "--manifest", str(manifest), "--index", str(index), "--root", root]) == 0
    (index.parent / "index.json.sha256").write_text("")
    assert main(["verify", "--manifest", str(manifest), "--index", str(index), "--root", root]) == 1
    escaping = lab.write_manifest(lab.manifest(source_spec(prompt_candidates=["../../x.txt"])))
    out = lab.root / "out" / "pinned.json"
    assert main(["pin", "--manifest", str(escaping), "--out", str(out), "--root", root]) == 64
