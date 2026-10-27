"""Synthetic, native-shaped campaign fixtures written to a temporary directory.

Every value here is invented test data. It exercises join and integrity rules only and
is never evidence of model behaviour.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from trace_eval_correlation.cli import render
from trace_eval_correlation.correlate import build_index
from trace_eval_correlation.schema import Manifest, TraceEvalIndex
from trace_eval_correlation.sources import Resolver, canonical_sha256

PROMPT = "SYNTHETIC CLARIFIER PROMPT v1\nReturn only the schema.\n"
SESSION = "00000000-0000-4000-8000-000000000001"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Turn:
    case_id: str
    request_id: str | None
    agent_span: str
    llm_span: str | None
    role: str = "clarifier"
    arm: str = "A"
    status: str = "ACCEPTED"
    error_code: str | None = None
    cost: str | None = "0.0001"


@dataclass
class Campaign:
    """Mutable description of one campaign; write() materialises files."""

    turns: list[Turn] = field(default_factory=list)
    not_run: list[dict[str, Any]] = field(default_factory=list)
    status: str = "CAMPAIGN_COMPLETE"
    observations: list[dict[str, Any]] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    assessments: dict[str, dict[str, Any]] = field(default_factory=dict)
    receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    trace_lines: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    scope: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def default(cls) -> Campaign:
        camp = cls(
            turns=[
                Turn(
                    "A:case-1",
                    "11111111-1111-4111-8111-111111111111",
                    "a0000000-0000-4000-8000-000000000001",
                    "b0000000-0000-4000-8000-000000000001",
                ),
                Turn(
                    "B:case-1",
                    "22222222-2222-4222-8222-222222222222",
                    "a0000000-0000-4000-8000-000000000002",
                    "b0000000-0000-4000-8000-000000000002",
                    arm="B",
                    role="orchestrator",
                    status="REJECTED",
                    error_code="FORBIDDEN_CAPABILITY",
                ),
            ]
        )
        camp.derive()
        return camp

    def derive(self) -> None:
        """Populate evidence documents consistently from the turn list."""
        self.observations, self.scores, self.assessments = [], [], {}
        self.receipts, self.requests, self.trace_lines, self.scope = {}, {}, [], []
        self._trace(
            {
                "event": "START",
                "kind": "SESSION",
                "span_id": SESSION,
                "parent_span_id": None,
                "source_fingerprint": "f" * 64,
            }
        )
        native = 0
        for idx, t in enumerate(self.turns):
            obs: dict[str, Any] = {
                "case_id": t.case_id,
                "arm": t.arm,
                "role": t.role,
                "stage": "paired",
                "conversation_id": "conv-1",
                "dataset_case_id": t.case_id.split(":")[-1],
                "turn_index": idx,
                "status": t.status,
                "canonical_accepted": t.status == "ACCEPTED",
                "specialist_dispatch": False,
                "text": "SENTINEL_HUMAN_TEXT my email is pat@example.com",
                "raw_output": "SENTINEL_MODEL_OUTPUT",
                "display": "SENTINEL_DISPLAY",
                "after": {"readiness": "READY", "owner_id": "SENTINEL_OWNER"},
            }
            if t.request_id is not None:
                obs["request_id"] = t.request_id
            if t.error_code is not None:
                obs["error_code"] = t.error_code
            self.observations.append(obs)
            self.scope.append({"id": t.case_id, "role": t.role})
            self.scores.append(
                {
                    "case_id": t.case_id,
                    "arm": t.arm,
                    "role": t.role,
                    "turn_index": idx,
                    "conversation_id": "conv-1",
                    "agent_success": t.status == "ACCEPTED",
                    "canonical_state_success": True,
                    "schema_status": "PASS",
                    "raw_prose_status": "PASS",
                    "deterministic_display_is_model_credit": False,
                }
            )
            self._trace(
                {
                    "event": "START",
                    "kind": "AGENT",
                    "span_id": t.agent_span,
                    "parent_span_id": SESSION,
                    "case_id": t.case_id,
                    "arm": t.arm,
                    "name": t.role,
                }
            )
            if t.request_id is not None and t.llm_span is not None:
                native += 1
                request = {
                    "model": "synthetic/model",
                    "messages": [
                        {"role": "system", "content": "prefix\n" + PROMPT.strip()},
                        {"role": "user", "content": "SENTINEL_REQUEST_TEXT"},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "SyntheticProposal", "schema": {"type": "object"}},
                    },
                }
                raw = json.dumps(request).encode()
                self.requests[t.request_id] = request
                self._trace(
                    {
                        "event": "START",
                        "kind": "LLM",
                        "span_id": t.llm_span,
                        "parent_span_id": t.agent_span,
                        "case_id": t.case_id,
                        "request_id": t.request_id,
                        "request_sha256": _sha(raw),
                    }
                )
                self._trace({"event": "END", "span_id": t.llm_span, "status": "PASS"})
                self.receipts[t.request_id] = {
                    "request_id": t.request_id,
                    "case_id": t.case_id,
                    "llm_span_id": t.llm_span,
                    "request_sha256": _sha(raw),
                    "public_output_sha256": _sha(b"SENTINEL_OUT"),
                    "model_requested": "synthetic/model",
                    "returned_model": "synthetic/model",
                    "upstream_requested": "synthetic-upstream",
                    "returned_provider": "Synthetic",
                    "http_status": 200,
                    "finish_reason": "stop",
                    "retries": 0,
                    "fallback": False,
                    "send_claimed": True,
                    "native_schema_status": "PASS",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "reasoning_tokens": 5,
                    "token_usage_verified": True,
                    "native_latency_ms": 12.5,
                    "attempt_wall_latency_ms": 13.0,
                    "billing_status": "REPORTED_NUMERIC_COST",
                    "billing_verified": True,
                    "reported_cost_usd_exact": t.cost,
                    "metadata": {"key_remaining": "SENTINEL_BALANCE", "spendable_credits": "9.9"},
                }
            self._trace({"event": "END", "span_id": t.agent_span, "status": t.status})
            self.assessments[t.case_id] = {
                "case_id": t.case_id,
                "status": "PASS",
                "reviewer_identity": "/root/synthetic",
                "independent_of_implementation": True,
                "source_fingerprint": "f" * 64,
                "rubric_sha256": None,
                "observation_sha256": canonical_sha256(obs),
                "rationale": "SENTINEL_RATIONALE",
            }
        self._trace({"event": "END", "span_id": SESSION, "status": "COMPLETE"})
        for row in self.not_run:
            self.scope.append({"id": row["case_id"], "role": "clarifier"})
        costs = [t.cost for t in self.turns if t.request_id and t.cost is not None]
        self.summary = {
            "campaign": "synthetic-campaign-1",
            "status": self.status,
            "attempts": native,
            "source_fingerprint": "f" * 64,
            "reported_cost": str(sum((Decimal(c) for c in costs), Decimal(0))) if costs else None,
        }

    def _trace(self, event: dict[str, Any]) -> None:
        self.trace_lines.append(json.dumps(event, sort_keys=True))

    def write(self, base: Path, *, rubric_into_assessments: bool = True) -> Path:
        base.mkdir(parents=True, exist_ok=True)
        files: dict[str, bytes] = {}
        rubric = json.dumps({"rubric": "synthetic"}).encode()
        files["evaluation/rubric.json"] = rubric
        cases = json.dumps([{"id": "case-1"}]).encode()
        files["evaluation/cases.json"] = cases
        files["evaluation/freeze-manifest.json"] = json.dumps(
            {"files": {"cases.json": _sha(cases), "rubric.json": _sha(rubric)}}
        ).encode()
        assessments = copy.deepcopy(self.assessments)
        if rubric_into_assessments:
            for a in assessments.values():
                if a.get("rubric_sha256") is None:
                    a["rubric_sha256"] = _sha(rubric)
        files["reports/observations.json"] = json.dumps(self.observations).encode()
        files["reports/scores.json"] = json.dumps(self.scores).encode()
        files["reports/assessments.json"] = json.dumps(assessments).encode()
        files["reports/not-run.json"] = json.dumps(self.not_run).encode()
        files["reports/summary.json"] = json.dumps(self.summary).encode()
        files["reports/traces.jsonl"] = ("\n".join(self.trace_lines) + "\n").encode()
        files["campaign/scope.json"] = json.dumps({"paired": self.scope}).encode()
        files["prompts/p1.txt"] = PROMPT.replace("\n", "\r\n").encode()
        files["prompts/p0.txt"] = b"UNUSED OTHER PROMPT"
        for rid, receipt in self.receipts.items():
            files[f"reports/requests/{rid}/receipt.json"] = json.dumps(receipt).encode()
            files[f"reports/requests/{rid}/request.json"] = json.dumps(self.requests[rid]).encode()
            files[f"reports/requests/{rid}/public-output.txt"] = b"SENTINEL_OUT"
        for rel, data in files.items():
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        manifest = {rel: _sha(data) for rel, data in sorted(files.items())}
        (base / "reports/EVIDENCE_MANIFEST.json").write_text(json.dumps(manifest))
        return base


def source_spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "source_id": "synthetic-1",
        "kind": "native_paired_campaign",
        "root": "evidence",
        "path": "camp",
        "declared_evidence_class": "NATIVE",
        "evaluation_id": "synthetic-1/eval",
        "files": {
            "observations": "reports/observations.json",
            "scores": "reports/scores.json",
            "traces": "reports/traces.jsonl",
            "requests_dir": "reports/requests",
            "prose_assessments": "reports/assessments.json",
            "not_run": "reports/not-run.json",
            "summary": "reports/summary.json",
            "scope": "campaign/scope.json",
            "dataset_freeze": "evaluation/freeze-manifest.json",
            "rubric": "evaluation/rubric.json",
        },
        "evidence_manifest": "reports/EVIDENCE_MANIFEST.json",
        "prompt_candidates": ["prompts/p0.txt", "prompts/p1.txt"],
        "summary_fields": {
            "status": "status",
            "native_attempts": "attempts",
            "reported_cost_usd": "reported_cost",
        },
        "completeness_map": {"CAMPAIGN_COMPLETE": "COMPLETE", "STOPPED": "PARTIAL_STOPPED"},
        "action_kinds": {"clarifier": "OBJECTIVE_STATE_PROPOSAL", "orchestrator": "PLAN_PROPOSAL"},
    }
    spec.update(overrides)
    return spec


@dataclass
class Lab:
    root: Path

    @property
    def evidence(self) -> Path:
        return self.root / "evidence"

    def manifest(
        self, *specs: dict[str, Any], references: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        return {
            "manifest_version": "trace-eval-manifest/1.0",
            "roots": {"evidence": None},
            "references": references or [],
            "sources": list(specs) or [source_spec()],
        }

    def build(self, manifest: dict[str, Any]) -> TraceEvalIndex:
        model = Manifest.model_validate(manifest)
        resolver = Resolver({"evidence": self.evidence})
        return build_index(model, resolver, canonical_sha256(manifest))

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        path = self.root / "out" / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path)


@pytest.fixture
def campaign() -> Campaign:
    return Campaign.default()


def codes(index: TraceEvalIndex, severity: str | None = None) -> set[str]:
    return {f.code for f in index.findings if severity is None or f.severity == severity}


def record(index: TraceEvalIndex, case_id: str) -> Any:
    matches = [r for r in index.records if r.case_id == case_id]
    assert len(matches) == 1, [r.record_id for r in index.records]
    return matches[0]


RenderFn = Callable[[TraceEvalIndex], str]
render_index: RenderFn = render
