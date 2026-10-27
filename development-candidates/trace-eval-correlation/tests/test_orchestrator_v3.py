"""Offline V3 contract, identity, provenance and conservative eligibility tests."""

from __future__ import annotations

import json
import os
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from trace_eval_correlation import orchestrator_v3
from trace_eval_correlation.cli import generate, load_manifest, main, render
from trace_eval_correlation.correlate import build_index
from trace_eval_correlation.schema import Manifest, SourceSpec, TraceEvalIndex
from trace_eval_correlation.sources import Resolver, sha256_bytes


def _write(root: Path, path: str, value: object) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return sha256_bytes(target.read_bytes())


@dataclass
class V3:
    root: Path
    files: dict[str, str]

    def read(self, path: str) -> Any:
        return json.loads((self.root / path).read_text())

    def replace_evidence(self, logical: str, row: object) -> None:
        path = self.files[logical]
        digest = _write(self.root, path, row)
        archive = self.read(self.files["archive_manifest"])
        for entry in archive["files"]:
            if entry["archive"] == path:
                entry["sha256"] = digest
        _write(self.root, self.files["archive_manifest"], archive)

    def spec(self) -> SourceSpec:
        return SourceSpec(
            source_id="v3",
            kind="orchestrator_eval_v3",
            root="evidence",
            path=".",
            declared_evidence_class="SYNTHETIC_FIXTURE",
            evaluation_id="v3/archive",
            campaign_id="orchestrator-eval-v3",
            files=self.files,
            pins={p: sha256_bytes((self.root / p).read_bytes()) for p in self.files.values()},
        )

    def manifest(self) -> Manifest:
        return Manifest(
            manifest_version="trace-eval-manifest/1.0",
            roots={"evidence": str(self.root)},
            sources=[self.spec()],
        )

    def build(self, spec: SourceSpec | None = None) -> TraceEvalIndex:
        manifest = Manifest(
            manifest_version="trace-eval-manifest/1.0",
            roots={"evidence": str(self.root)},
            sources=[spec if spec is not None else self.spec()],
        )
        return build_index(manifest, Resolver({"evidence": self.root}), "f" * 64)


@pytest.fixture
def v3(tmp_path: Path) -> V3:
    root = tmp_path / "evidence"
    files = {
        "archive_manifest": "archive/manifest.json",
        "scores": "archive/cases.json",
        "inputs": "frozen/inputs.json",
        "dataset_freeze": "frozen/manifest.json",
    }
    scores, inputs, archived = [], [], []
    frozen: dict[str, dict[str, str]] = {}
    number = 0
    for phase, cases in (("smoke", 1), ("primary", 12), ("http", 1)):
        for case in range(cases):
            for model in ("model:4b", "model:9b"):
                number += 1
                identity = {"phase": phase, "case_id": f"case-{case}", "model": model}
                request_id = f"request-{number}"
                input_path = f"frozen/input-{number}.json"
                digest = _write(root, input_path, {"messages": ["PRIVATE_PROMPT"], "model": model})
                frozen[input_path] = {"sha256": digest}
                files[f"input_{number}"] = input_path
                inputs.append(identity | {"path": input_path, "sha256": digest})
                row = identity | {
                    "version": "synthetic-v3-evidence-1",
                    "trace_id": f"trace-{number}",
                    "source_reference": f"trace-{number}",
                    "reservation_id": request_id,
                    "expected_input_sha256": digest,
                    "actual_input_sha256": digest,
                    "outbound_count": 1,
                    "evidence_status": "COMPLETE",
                    "evaluation_tree": "tree",
                    "receipt": {
                        "request_id": request_id,
                        "provider": "ollama",
                        "requested_model": model,
                        "returned_model": model,
                        "role": "orchestrator",
                        "status": "PASS",
                        "input_tokens": 12,
                        "output_tokens": 3,
                        "reasoning_tokens": None,
                        "latency_ms": 2.5,
                        "retries": 0,
                        "fallback": False,
                        "schema_valid": True,
                    },
                    "admitted": False,
                    "outcome": "ADMISSION_REJECTED",
                    "admission_code": "FORBIDDEN_CAPABILITY",
                    "graph_duration_ms": 3.5,
                    "observation": {"proposal": {"reason": "PRIVATE_MODEL_OUTPUT"}},
                }
                path = f"archive/{phase}/case-{case}-{model.rsplit(':', 1)[1]}/evidence.json"
                archived.append({"archive": path, "sha256": _write(root, path, row)})
                files[f"evidence_{number}"] = path
                scores.append(
                    identity
                    | {
                        "admitted": False,
                        "outcome": "ADMISSION_REJECTED",
                        "admission_code": "FORBIDDEN_CAPABILITY",
                        "actual_schema_valid": True,
                    }
                )
    frozen[files["inputs"]] = {"sha256": _write(root, files["inputs"], {"entries": inputs})}
    _write(root, files["dataset_freeze"], {"status": "FROZEN", "files": frozen})
    _write(root, files["scores"], scores)
    for model in ("4b", "9b"):
        path = f"archive/http/case-0-{model}/http-receipt.json"
        (root / path).write_bytes(b"PRIVATE_HTTP_TRANSCRIPT: deliberately not JSON")
        files[f"http_{model}"] = path
        archived.append({"archive": path, "sha256": sha256_bytes((root / path).read_bytes())})
    _write(
        root,
        files["archive_manifest"],
        {
            "files": archived,
            "actual_attempts": 28,
            "evaluation_tree": "tree",
            "status": "MEASURED_NOT_MODEL_ACCEPTANCE",
        },
    )
    return V3(root, files)


def test_all_28_records_and_phase_sensitive_identity(v3: V3) -> None:
    index = v3.build()
    assert index.index_status == "COMPLETE"
    assert len(index.records) == len({r.record_id for r in index.records}) == 28
    assert len({r.case_id for r in index.records}) == 12
    assert all(r.join_status == "PARTIAL" for r in index.records)
    assert all(not r.model_performance_evidence for r in index.records)
    row = index.records[0]
    assert row.validation.canonical_accepted is False
    assert row.validation.observation_status == "ADMISSION_REJECTED"
    assert row.validation.rejection_reason == "FORBIDDEN_CAPABILITY"
    assert row.trace.request_hash_match is True
    assert all(
        ref.source_manifest == "VERIFIED"
        for ref in row.artifacts
        if ref.kind in ("evidence", "prepared_input")
    )
    assert row.model_call.retries == 0 and row.model_call.fallback is False
    assert row.agent == "orchestrator" and row.usage.input_tokens == 12


@pytest.mark.parametrize("duplicate", [False, True])
@pytest.mark.parametrize("logical", ["scores", "inputs"])
def test_missing_or_duplicate_join(v3: V3, logical: str, duplicate: bool) -> None:
    data = v3.read(v3.files[logical])
    rows = data["entries"] if logical == "inputs" else data
    if duplicate:
        rows.append(rows[0])
    else:
        rows.pop()
    _write(v3.root, v3.files[logical], data)
    index = v3.build()
    assert index.index_status == "INCOMPLETE"
    assert len(index.records) == 28
    assert not any(r.model_performance_evidence for r in index.records)


def test_duplicate_archive_identity_is_retained(v3: V3) -> None:
    archive = v3.read(v3.files["archive_manifest"])
    row = v3.read(v3.files["evidence_1"])
    path = "archive/duplicate/evidence.json"
    archive["files"].append({"archive": path, "sha256": _write(v3.root, path, row)})
    v3.files["duplicate"] = path
    _write(v3.root, v3.files["archive_manifest"], archive)
    index = v3.build()
    assert index.index_status == "INCOMPLETE" and len(index.records) == 29
    assert len({r.record_id for r in index.records}) == 29
    assert "DUPLICATE_CASE_ID" in {i for r in index.records for i in r.issues}


@pytest.mark.parametrize("logical", ["scores", "evidence_1", "input_1", "dataset_freeze"])
def test_hash_tampering(v3: V3, logical: str) -> None:
    spec = v3.spec()
    with (v3.root / v3.files[logical]).open("a") as stream:
        stream.write(" ")
    index = v3.build(spec)
    assert index.index_status == "INCOMPLETE"
    assert any(f.code == "SOURCE_PIN_STALE" for f in index.findings)
    assert not any(r.model_performance_evidence for r in index.records)


def test_missing_spans_costs_and_unverified_usage(v3: V3) -> None:
    for row in v3.build().records:
        assert row.trace.agent_span_id == row.trace.llm_span_id == "UNAVAILABLE"
        assert row.trace.span_relationship == "UNAVAILABLE"
        assert row.versions.prompt_binding == "UNAVAILABLE"
        assert row.usage.reported_cost_usd == row.usage.billing_verified == "UNAVAILABLE"
        assert row.usage.reasoning_tokens == row.usage.token_usage_verified == "UNAVAILABLE"


@pytest.mark.parametrize(
    "change,issue",
    [
        ({"reservation_id": "other-request"}, "RECEIPT_KEY_MISMATCH"),
        ({"outbound_count": 0}, "V3_REQUEST_EVIDENCE_INCOMPLETE"),
        ({"evaluation_tree": "other-tree"}, "V3_EVALUATION_TREE_MISMATCH"),
        ({"receipt": None}, "RECEIPT_MISSING"),
    ],
)
def test_evidence_integrity_is_separate_from_rejection(
    v3: V3, change: dict[str, Any], issue: str
) -> None:
    row = v3.read(v3.files["evidence_1"])
    v3.replace_evidence("evidence_1", row | change)
    index = v3.build()
    assert index.index_status == "INCOMPLETE"
    assert any(issue in r.issues and r.join_status == "UNJOINABLE" for r in index.records)


def test_duplicate_request_identity(v3: V3) -> None:
    first = v3.read(v3.files["evidence_1"])
    second = v3.read(v3.files["evidence_2"])
    second["receipt"]["request_id"] = second["reservation_id"] = first["reservation_id"]
    v3.replace_evidence("evidence_2", second)
    assert sum("DUPLICATE_REQUEST_ID" in r.issues for r in v3.build().records) == 2


def test_credential_shaped_metadata_is_redacted(v3: V3) -> None:
    row = v3.read(v3.files["evidence_1"])
    marker = "Bearer synthetic-sensitive-marker"
    row["receipt"]["finish_reason"] = marker
    v3.replace_evidence("evidence_1", row)
    index = v3.build()
    assert marker not in render(index)
    assert any(r.model_call.finish_reason == "REDACTED" for r in index.records)


def test_unpinned_dynamic_file_is_not_read(v3: V3) -> None:
    spec = v3.spec()
    pins = dict(spec.pins)
    del pins[v3.files["evidence_1"]]
    index = v3.build(spec.model_copy(update={"pins": pins}))
    assert len(index.records) == 27 and index.index_status == "INCOMPLETE"


def test_absolute_path_is_not_copied_or_read(v3: V3, tmp_path: Path) -> None:
    path = tmp_path / "outside-evidence.json"
    path.write_text("PRIVATE_OUTSIDE_CONTENT")
    archive = v3.read(v3.files["archive_manifest"])
    archive["files"][0]["archive"] = str(path)
    _write(v3.root, v3.files["archive_manifest"], archive)
    index = v3.build()
    assert index.index_status == "INCOMPLETE"
    assert str(path) not in render(index) and "PRIVATE_OUTSIDE_CONTENT" not in render(index)


def test_privacy_paths_and_no_network(v3: V3, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket, "socket", refuse)
    text = render(v3.build())
    assert "PRIVATE_PROMPT" not in text and "PRIVATE_MODEL_OUTPUT" not in text
    assert str(v3.root) not in text
    spec = v3.spec()
    bad = "../outside/evidence.json"
    archive = v3.read(v3.files["archive_manifest"])
    archive["files"][0]["archive"] = bad
    digest = _write(v3.root, v3.files["archive_manifest"], archive)
    spec = spec.model_copy(
        update={"pins": spec.pins | {bad: "0" * 64, v3.files["archive_manifest"]: digest}}
    )
    index = v3.build(spec)
    assert index.index_status == "INCOMPLETE"
    assert any(f.code == "UNJOINABLE_REFERENCE" for f in index.findings)


def test_deterministic_cli_reproduction_and_read_only(v3: V3, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(v3.manifest().model_dump_json())
    before = {p: sha256_bytes(p.read_bytes()) for p in v3.root.rglob("*") if p.is_file()}
    out = tmp_path / "index.json"
    args = ["--manifest", str(manifest), "--index", str(out)]
    assert main(["build", *args]) == 0
    assert main(["verify", *args]) == 0
    assert render(v3.build()) == render(v3.build())
    assert before == {p: sha256_bytes(p.read_bytes()) for p in before}
    assert (
        main(["build", "--manifest", str(manifest), "--index", str(v3.root / "forbidden.json")])
        == 64
    )


def test_actual_28_record_archive() -> None:
    root = _required_evidence_root()
    manifest = Path(__file__).resolve().parents[1] / "manifests/orchestrator-v3.json"
    index, _ = generate(manifest, [f"evidence={root}"])
    assert index.index_status == "COMPLETE"
    assert len(index.records) == 28
    assert all(r.trace.request_hash_match is True for r in index.records)
    assert all(
        r.join_status == "PARTIAL" and not r.model_performance_evidence for r in index.records
    )


def _required_evidence_root() -> Path:
    value = os.environ.get("TRACE_EVAL_V3_ROOT")
    if not value or not Path(value).is_dir():
        pytest.fail("UNAVAILABLE: required verification needs explicit TRACE_EVAL_V3_ROOT")
    return Path(value)


@pytest.mark.parametrize("logical", ["scores", "evidence_1"])
def test_admission_code_only_mismatch_with_consistent_pins(v3: V3, logical: str) -> None:
    if logical == "scores":
        rows = v3.read(v3.files[logical])
        rows[0]["admission_code"] = "MISSING_COVERAGE"
        _write(v3.root, v3.files[logical], rows)
    else:
        row = v3.read(v3.files[logical])
        v3.replace_evidence(logical, row | {"admission_code": "MISSING_COVERAGE"})
    index = v3.build()
    assert {f.code for f in index.findings if f.severity == "ERROR"} == {"SCORE_KEY_MISMATCH"}
    assert any(r.join_status == "UNJOINABLE" for r in index.records)


@pytest.mark.parametrize("logical", ["http_4b", "http_9b"])
@pytest.mark.parametrize("change", ["tampered", "missing", "declared_hash_mismatch"])
def test_every_http_archive_hash_is_checked(v3: V3, logical: str, change: str) -> None:
    spec = v3.spec()
    path = v3.root / v3.files[logical]
    if change == "missing":
        path.unlink()
    else:
        path.write_bytes(b"CHANGED_HTTP_TRANSCRIPT")
        if change == "declared_hash_mismatch":
            spec = v3.spec()  # Pins match changed bytes; archive's own hash still disagrees.
    index = v3.build(spec)
    assert index.index_status == "INCOMPLETE"
    assert any(f.code == "V3_DECLARED_HASH_MISMATCH" for f in index.findings)
    assert "CHANGED_HTTP_TRANSCRIPT" not in render(index)


def test_non_evidence_content_is_never_parsed(v3: V3) -> None:
    index = v3.build()
    assert index.index_status == "COMPLETE"
    refs = [r for r in index.sources[0].files if r.kind == "archive_file"]
    assert len(refs) == 2 and all(r.source_manifest == "VERIFIED" for r in refs)
    assert "PRIVATE_HTTP_TRANSCRIPT" not in render(index)


@pytest.mark.parametrize("unsafe", ["../outside.json", "../../../../outside.txt", "absolute"])
def test_non_evidence_archive_paths_are_checked(v3: V3, tmp_path: Path, unsafe: str) -> None:
    archive = v3.read(v3.files["archive_manifest"])
    path = str(tmp_path / "outside.json") if unsafe == "absolute" else unsafe
    archive["files"][-1]["archive"] = path
    _write(v3.root, v3.files["archive_manifest"], archive)
    index = v3.build()
    assert index.index_status == "INCOMPLETE"
    assert any(f.code == "UNJOINABLE_REFERENCE" for f in index.findings)
    assert len(index.records) == 28  # Detection must not depend on losing a case join.
    if unsafe == "absolute":
        assert path not in render(index)


@pytest.mark.parametrize(
    "admitted,code,expected",
    [
        (True, None, "NOT_APPLICABLE"),
        (False, "FORBIDDEN_CAPABILITY", "FORBIDDEN_CAPABILITY"),
        (False, None, "UNAVAILABLE"),
    ],
)
def test_rejection_reason_semantics(
    v3: V3, admitted: bool, code: str | None, expected: str
) -> None:
    row = v3.read(v3.files["evidence_1"])
    outcome = (
        "ADMITTED"
        if admitted
        else "ADMISSION_REJECTED"
        if code
        else "HTTP_PLAN_REJECTED_OR_UNAVAILABLE"
    )
    row.update(admitted=admitted, admission_code=code, outcome=outcome)
    v3.replace_evidence("evidence_1", row)
    scores = v3.read(v3.files["scores"])
    scores[0].update(admitted=admitted, admission_code=code, outcome=outcome)
    _write(v3.root, v3.files["scores"], scores)
    index = v3.build()
    match = next(r for r in index.records if r.trace.request_id == row["reservation_id"])
    assert index.index_status == "COMPLETE"
    assert match.validation.rejection_reason == expected


@pytest.mark.parametrize(
    "removed",
    [
        set(),
        {"V3_SPANS_UNAVAILABLE"},
        {"V3_PROMPT_BINDING_UNAVAILABLE"},
        {"V3_SPANS_UNAVAILABLE", "V3_PROMPT_BINDING_UNAVAILABLE"},
    ],
)
def test_native_eligibility_survives_warning_removal(
    v3: V3, monkeypatch: pytest.MonkeyPatch, removed: set[str]
) -> None:
    original = orchestrator_v3._record

    def without_warnings(*args: Any, **kwargs: Any) -> Any:
        row = original(*args, **kwargs)
        return row.model_copy(update={"issues": [i for i in row.issues if i not in removed]})

    monkeypatch.setattr(orchestrator_v3, "_record", without_warnings)
    spec = v3.spec().model_copy(update={"declared_evidence_class": "NATIVE"})
    index = v3.build(spec)
    assert index.index_status == "COMPLETE" and len(index.records) == 28
    assert all(
        r.evidence_class == "NATIVE"
        and r.join_status == "PARTIAL"
        and r.model_performance_evidence is False
        for r in index.records
    )


def test_committed_v3_index_reproduces() -> None:
    root = _required_evidence_root()
    here = Path(__file__).resolve().parents[1]
    index, _ = generate(here / "manifests/orchestrator-v3.json", [f"evidence={root}"])
    target = here / "index/orchestrator-v3-index.json"
    assert index.index_status == "COMPLETE"
    assert target.read_bytes() == render(index).encode("utf-8")
    sidecar = target.with_name(target.name + ".sha256").read_text().split()[0]
    assert sha256_bytes(target.read_bytes()) == sidecar


@pytest.mark.parametrize("change", ["admission_code", "http_tampered", "http_unsafe"])
def test_actual_archive_corruption_in_temporary_copy(tmp_path: Path, change: str) -> None:
    original = _required_evidence_root()
    here = Path(__file__).resolve().parents[1]
    manifest, _ = load_manifest(here / "manifests/orchestrator-v3.json")
    files = manifest.sources[0].files
    copied = tmp_path / "evidence"
    for path in files.values():
        target = copied / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / path, target)
    data = V3(copied, files)
    if change == "admission_code":
        row = data.read(files["evidence_02"])
        data.replace_evidence("evidence_02", row | {"admission_code": "OTHER_CODE"})
    elif change == "http_tampered":
        (copied / files["http_receipt_00"]).write_bytes(b"PRIVATE_CORRUPT_TRANSCRIPT")
    else:
        archive = data.read(files["archive_manifest"])
        next(e for e in archive["files"] if e["archive"].endswith("http-receipt.json"))[
            "archive"
        ] = "../outside.txt"
        _write(copied, files["archive_manifest"], archive)
    # Re-pin changed files so semantic/archive checks, rather than stale pins, detect corruption.
    before = {p: sha256_bytes(p.read_bytes()) for p in copied.rglob("*") if p.is_file()}
    index = data.build(data.spec().model_copy(update={"declared_evidence_class": "NATIVE"}))
    expected = {
        "admission_code": "SCORE_KEY_MISMATCH",
        "http_tampered": "V3_DECLARED_HASH_MISMATCH",
        "http_unsafe": "UNJOINABLE_REFERENCE",
    }[change]
    assert index.index_status == "INCOMPLETE"
    assert any(f.code == expected for f in index.findings)
    assert not any(r.model_performance_evidence for r in index.records)
    assert before == {p: sha256_bytes(p.read_bytes()) for p in before}
    assert "PRIVATE_CORRUPT_TRANSCRIPT" not in render(index)
