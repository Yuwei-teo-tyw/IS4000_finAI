"""Offline V3 contract, identity, provenance and conservative eligibility tests."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from trace_eval_correlation.cli import generate, main, render
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
            source_id="v3", kind="orchestrator_eval_v3", root="evidence", path=".",
            declared_evidence_class="SYNTHETIC_FIXTURE", evaluation_id="v3/archive",
            campaign_id="orchestrator-eval-v3", files=self.files,
            pins={p: sha256_bytes((self.root / p).read_bytes()) for p in self.files.values()},
        )

    def manifest(self) -> Manifest:
        return Manifest(manifest_version="trace-eval-manifest/1.0",
                        roots={"evidence": str(self.root)}, sources=[self.spec()])

    def build(self, spec: SourceSpec | None = None) -> TraceEvalIndex:
        manifest = self.manifest()
        if spec is not None:
            manifest = manifest.model_copy(update={"sources": [spec]})
        return build_index(manifest, Resolver({"evidence": self.root}), "f" * 64)


@pytest.fixture
def v3(tmp_path: Path) -> V3:
    root = tmp_path / "evidence"
    files = {"archive_manifest": "archive/manifest.json", "scores": "archive/cases.json",
             "inputs": "frozen/inputs.json", "dataset_freeze": "frozen/manifest.json"}
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
                    "version": "synthetic-v3-evidence-1", "trace_id": f"trace-{number}",
                    "source_reference": f"trace-{number}", "reservation_id": request_id,
                    "expected_input_sha256": digest, "actual_input_sha256": digest,
                    "outbound_count": 1, "evidence_status": "COMPLETE", "evaluation_tree": "tree",
                    "receipt": {"request_id": request_id, "provider": "ollama",
                                "requested_model": model, "returned_model": model,
                                "role": "orchestrator", "status": "PASS", "input_tokens": 12,
                                "output_tokens": 3, "reasoning_tokens": None, "latency_ms": 2.5,
                                "retries": 0, "fallback": False, "schema_valid": True},
                    "admitted": False, "outcome": "ADMISSION_REJECTED",
                    "admission_code": "FORBIDDEN_CAPABILITY", "graph_duration_ms": 3.5,
                    "observation": {"proposal": {"reason": "PRIVATE_MODEL_OUTPUT"}},
                }
                path = f"archive/{phase}/case-{case}-{model.rsplit(':', 1)[1]}/evidence.json"
                archived.append({"archive": path, "sha256": _write(root, path, row)})
                files[f"evidence_{number}"] = path
                scores.append(identity | {"admitted": False, "outcome": "ADMISSION_REJECTED",
                                          "actual_schema_valid": True})
    frozen[files["inputs"]] = {"sha256": _write(root, files["inputs"], {"entries": inputs})}
    _write(root, files["dataset_freeze"], {"status": "FROZEN", "files": frozen})
    _write(root, files["scores"], scores)
    _write(root, files["archive_manifest"], {"files": archived, "actual_attempts": 28,
           "evaluation_tree": "tree", "status": "MEASURED_NOT_MODEL_ACCEPTANCE"})
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
    assert all(ref.source_manifest == "VERIFIED" for ref in row.artifacts
               if ref.kind in ("evidence", "prepared_input"))
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


@pytest.mark.parametrize("change,issue", [
    ({"reservation_id": "other-request"}, "RECEIPT_KEY_MISMATCH"),
    ({"outbound_count": 0}, "V3_REQUEST_EVIDENCE_INCOMPLETE"),
    ({"evaluation_tree": "other-tree"}, "V3_EVALUATION_TREE_MISMATCH"),
    ({"receipt": None}, "RECEIPT_MISSING"),
])
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
    spec = spec.model_copy(update={"pins": spec.pins | {
        bad: "0" * 64, v3.files["archive_manifest"]: digest}})
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
    assert main(["build", "--manifest", str(manifest), "--index",
                 str(v3.root / "forbidden.json")]) == 64


def test_actual_28_record_archive() -> None:
    root = os.environ.get("TRACE_EVAL_V3_ROOT")
    if not root:
        pytest.skip("UNAVAILABLE: bind TRACE_EVAL_V3_ROOT to the archived evidence repository")
    manifest = Path(__file__).resolve().parents[1] / "manifests/orchestrator-v3.json"
    index, _ = generate(manifest, [f"evidence={root}"])
    assert index.index_status == "COMPLETE"
    assert len(index.records) == 28
    assert all(r.trace.request_hash_match is True for r in index.records)
    assert all(r.join_status == "PARTIAL" and not r.model_performance_evidence
               for r in index.records)
