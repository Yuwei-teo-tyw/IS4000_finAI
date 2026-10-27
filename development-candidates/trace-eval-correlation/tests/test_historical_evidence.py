"""Read-only checks against the real historical evidence named by the representative manifest.

These tests skip with an UNAVAILABLE reason when the evidence roots are not present on
this machine; they never write to, replay or re-score that evidence.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from trace_eval_correlation.cli import bind_roots, generate, load_manifest, render

HERE = Path(__file__).resolve().parents[1]
MANIFEST = HERE / "manifests" / "representative.json"
INDEX = HERE / "index" / "representative-index.json"


def _roots_available() -> bool:
    manifest, _ = load_manifest(MANIFEST)
    return all(p.is_dir() for p in bind_roots(manifest, MANIFEST, []).roots.values())


pytestmark = pytest.mark.skipif(
    not _roots_available(), reason="UNAVAILABLE: historical evidence roots not present"
)


def _consumed_hashes() -> dict[str, str | None]:
    manifest, _ = load_manifest(MANIFEST)
    out: dict[str, str | None] = {}
    roots = bind_roots(manifest, MANIFEST, []).roots
    for spec in manifest.sources:
        base = roots[spec.root] / spec.path
        for rel in spec.pins:
            p = base / rel
            out[f"{spec.source_id}:{rel}"] = (
                hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
            )
    return out


def test_historical_index_correlates_all_36_native_receipts() -> None:
    before = _consumed_hashes()
    index, _ = generate(MANIFEST, [])
    assert _consumed_hashes() == before
    assert index.index_status == "COMPLETE"
    native = [r for r in index.records if r.evidence_class == "NATIVE"]
    assert len(native) == 36
    assert all(r.join_status == "JOINED" and r.model_performance_evidence for r in native)
    assert all(r.trace.span_relationship == "VERIFIED" for r in native)
    assert all(r.trace.request_hash_match is True for r in native)
    assert all(r.score.assessment_observation_binding == "VERIFIED" for r in native)
    assert all(r.versions.prompt_binding == "EMBEDDED_IN_REQUEST" for r in native)
    assert all(r.model_call.retries == 0 and r.model_call.fallback is False for r in native)
    by_source = {s.source_id: s for s in index.sources}
    assert by_source["v93-paired-1"].record_counts == {"NATIVE": 24}
    assert by_source["v93-paired-1"].completeness == "COMPLETE"
    assert by_source["pair-v942-v93b-1"].record_counts == {
        "NATIVE": 12,
        "NON_NATIVE_PREFLIGHT": 1,
        "NOT_RUN": 35,
    }
    assert by_source["pair-v942-v93b-1"].completeness == "PARTIAL_STOPPED"
    assert by_source["v943-offline-tests"].record_counts == {"OFFLINE_TEST": 87}
    for summary in index.sources:
        assert all(c.status == "MATCH" for c in summary.crosschecks), summary.crosschecks
        assert all(f.source_manifest in ("VERIFIED", "NOT_APPLICABLE") for f in summary.files)
        assert all(f.pin in ("VERIFIED", "NOT_APPLICABLE") for f in summary.files)


def test_committed_representative_index_reproduces() -> None:
    index, _ = generate(MANIFEST, [])
    assert INDEX.read_bytes() == render(index).encode("utf-8")
