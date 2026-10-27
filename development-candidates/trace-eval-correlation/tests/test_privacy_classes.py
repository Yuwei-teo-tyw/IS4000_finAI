"""10-11: privacy filtering and native/synthetic/offline/NOT_RUN classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import Campaign, Lab, codes, record, render_index, source_spec
from trace_eval_correlation import privacy


def test_free_text_and_account_metadata_never_reach_the_index(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    text = render_index(lab.build(lab.manifest()))
    for sentinel in (
        "SENTINEL_HUMAN_TEXT",
        "SENTINEL_MODEL_OUTPUT",
        "SENTINEL_DISPLAY",
        "SENTINEL_OWNER",
        "SENTINEL_BALANCE",
        "SENTINEL_RATIONALE",
        "SENTINEL_REQUEST_TEXT",
        "pat@example.com",
        "spendable",
        "key_remaining",
        str(lab.root),
    ):
        assert sentinel not in text


def test_credentials_and_identifiers_in_copied_fields_are_redacted(
    lab: Lab, campaign: Campaign
) -> None:
    secret = "sk-or-v1-abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105 - synthetic sentinel
    campaign.observations[0]["arm"] = f"Bearer {secret}"
    campaign.observations[1]["dataset_case_id"] = "client pat@example.com"
    campaign.observations[1]["case_id"] = "B:S1234567D"
    campaign.scores[1]["case_id"] = "B:S1234567D"
    campaign.assessments["A:case-1"]["reviewer_identity"] = "reviewer +65 9123 4567"
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest())
    text = render_index(index)
    for leaked in (secret, "pat@example.com", "S1234567D", "9123 4567"):
        assert leaked not in text
    a = record(index, "A:case-1")
    assert a.arm == "REDACTED" and "PRIVACY_REDACTED" in a.issues
    assert a.score.evaluator_identity == "REDACTED"
    redacted = [r for r in index.records if r.record_id.endswith("row-1")]
    assert redacted and redacted[0].case_id == "UNAVAILABLE"
    details = [f.detail for f in index.findings if f.code == "PRIVACY_REDACTED"]
    assert details and all(secret not in d and "@" not in d for d in details)


def test_error_codes_with_secrets_are_not_copied(lab: Lab, campaign: Campaign) -> None:
    campaign.turns[1].error_code = "auth failed: Authorization: Bearer abc.def"
    campaign.derive()
    campaign.write(lab.evidence / "camp")
    text = render_index(lab.build(lab.manifest()))
    assert "abc.def" not in text and "Authorization" not in text


@pytest.mark.parametrize(
    "value",
    [
        "Bearer abc123",
        "api_key=xyz",
        "sk-0123456789abcdef",
        "ghp_" + "a" * 36,
        "AKIAABCDEFGHIJKLMNOP",
        "lsv2_pt_0123456789abcdef0123",
        "a@b.co",
        "+65 9123 4567",
        "S1234567D",
        "123-45-6789",
        "eyJhbGciOiJI.eyJzdWIiOiIx.sig",
    ],
)
def test_sensitive_patterns(value: str) -> None:
    assert privacy.is_sensitive(value)


@pytest.mark.parametrize(
    "value",
    [
        "8380460c-388b-47db-86ab-ca36f3146d2f",
        "f" * 64,
        "2026-10-25T01:16:40.862084+00:00",
        "openai/gpt-oss-120b",
        "A:h93-history-request",
        "REPORTED_NUMERIC_COST",
        "0.00873900",
        "/root/v93_paired_final_audit",
        "main_dev_candidates:v9.3-readiness/reports/scores.json",
    ],
)
def test_metadata_is_not_flagged(value: str) -> None:
    assert not privacy.is_sensitive(value)


def test_declared_synthetic_fixture_is_not_model_performance(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    index = lab.build(lab.manifest(source_spec(declared_evidence_class="SYNTHETIC_FIXTURE")))
    assert {r.evidence_class for r in index.records} == {"SYNTHETIC_FIXTURE"}
    assert not any(r.model_performance_evidence for r in index.records)
    assert record(index, "A:case-1").join_status == "JOINED"


def _junit(base: Path, body: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "tests.xml").write_text(body, encoding="utf-8")


JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="4"
errors="0" failures="1" skipped="1"><testcase classname="t.a" name="ok"/>
<testcase classname="t.a" name="bad"><failure message="x"/></testcase>
<testcase classname="t.a" name="skip"><skipped/></testcase>
<testcase classname="t.b" name="err"><error/></testcase></testsuite></testsuites>"""


def _junit_spec(**kw: object) -> dict[str, object]:
    spec: dict[str, object] = {
        "source_id": "offline-1",
        "kind": "offline_junit",
        "root": "evidence",
        "path": "off",
        "declared_evidence_class": "OFFLINE_TEST",
        "evaluation_id": "offline-1/tests",
        "files": {"junit": "tests.xml"},
    }
    spec.update(kw)
    return spec


def test_offline_junit_records_carry_no_model_fields(lab: Lab) -> None:
    _junit(lab.evidence / "off", JUNIT)
    index = lab.build(lab.manifest(_junit_spec()))
    outcomes = {r.test_node_id: r.test_outcome for r in index.records}
    assert outcomes == {
        "t.a::ok": "PASSED",
        "t.a::bad": "FAILED",
        "t.a::skip": "SKIPPED",
        "t.b::err": "ERROR",
    }
    for r in index.records:
        assert r.evidence_class == "OFFLINE_TEST" and not r.model_performance_evidence
        assert r.model_call.model_requested == "NOT_APPLICABLE"
        assert r.usage.input_tokens == "NOT_APPLICABLE" and r.trace.trace_id == "NOT_APPLICABLE"
    assert index.sources[0].crosschecks[0].status == "MATCH"


def test_junit_duplicate_nodes_count_mismatch_and_dtd(lab: Lab) -> None:
    dup = (
        JUNIT.replace('tests="4"', 'tests="9"')
        .replace('name="err"', 'name="ok"')
        .replace('classname="t.b"', 'classname="t.a"')
    )
    _junit(lab.evidence / "off", dup)
    index = lab.build(lab.manifest(_junit_spec()))
    assert {"DUPLICATE_TEST_NODE", "CROSSCHECK_MISMATCH"} <= codes(index, "ERROR")
    _junit(lab.evidence / "off", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
    index = lab.build(lab.manifest(_junit_spec()))
    assert "SOURCE_UNREADABLE" in codes(index, "ERROR") and index.records == []


def test_mixed_manifest_keeps_classes_apart(lab: Lab, campaign: Campaign) -> None:
    campaign.status = "STOPPED"
    campaign.not_run = [{"arm": "A", "case_id": "A:case-3"}]
    campaign.derive()
    campaign.write(lab.evidence / "camp")
    _junit(lab.evidence / "off", JUNIT)
    index = lab.build(lab.manifest(source_spec(), _junit_spec()))
    by_class: dict[str, list[bool]] = {}
    for r in index.records:
        by_class.setdefault(r.evidence_class, []).append(r.model_performance_evidence)
    assert by_class["NATIVE"] == [True, True]
    assert set(by_class) == {"NATIVE", "NOT_RUN", "OFFLINE_TEST"}
    assert not any(by_class["NOT_RUN"] + by_class["OFFLINE_TEST"])
