"""Versioned, metadata-only Trace-Eval correlation index contracts.

The index is a sidecar view over existing evidence. It never owns canonical state,
admission policy or scoring; every value is copied from, or a hash of, a cited file.
Unknown values are explicit: NOT_APPLICABLE (the concept does not exist for this
record) or UNAVAILABLE (it should exist but the evidence does not provide it).
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Final = "trace-eval-index/1.0"
MANIFEST_VERSION: Final = "trace-eval-manifest/1.0"
ADAPTER_VERSION: Final = "1.0.0"

Missing = Literal["NOT_APPLICABLE", "UNAVAILABLE"]
NA: Missing = "NOT_APPLICABLE"
UNAVAILABLE: Missing = "UNAVAILABLE"

EvidenceClass = Literal[
    "NATIVE",  # a real provider request with a receipt
    "NON_NATIVE_PREFLIGHT",  # a recorded row that stopped before any send
    "NOT_RUN",  # planned but never attempted
    "OFFLINE_TEST",  # deterministic local test node, no model call
    "SYNTHETIC_FIXTURE",  # native-shaped evidence declared synthetic by the manifest
]
DeclaredClass = Literal["NATIVE", "SYNTHETIC_FIXTURE", "OFFLINE_TEST"]
Severity = Literal["ERROR", "WARNING", "INFO"]
HashStatus = Literal["VERIFIED", "MISMATCH", "STALE", "MISSING_FILE", "NOT_LISTED", "NOT_PINNED"]
JoinStatus = Literal["JOINED", "PARTIAL", "UNJOINABLE", "NOT_APPLICABLE"]
Completeness = Literal["COMPLETE", "PARTIAL_STOPPED", "UNAVAILABLE", "NOT_APPLICABLE"]
Scalar = str | int | float | bool


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRef(Frozen):
    """A root-relative reference ("<root>:<relative path>") plus integrity status."""

    kind: str
    ref: str
    sha256: str | Missing
    source_manifest: HashStatus | Missing
    pin: HashStatus | Missing


class TraceLink(Frozen):
    trace_id: str | Missing
    agent_span_id: str | Missing
    llm_span_id: str | Missing
    request_id: str | Missing
    span_relationship: Literal["VERIFIED", "PARENT_MISMATCH", "SPAN_NOT_FOUND"] | Missing
    agent_span_status: str | Missing
    llm_span_status: str | Missing
    request_hash_match: bool | Missing


class Versions(Frozen):
    source_fingerprint: str | Missing
    prompt_ref: str | Missing
    prompt_sha256: str | Missing
    prompt_binding: Literal["EMBEDDED_IN_REQUEST", "AMBIGUOUS", "NOT_FOUND"] | Missing
    response_schema_name: str | Missing
    response_format_sha256: str | Missing
    dataset_freeze_sha256: str | Missing
    rubric_sha256: str | Missing
    scoring_spec_sha256: str | Missing


class ModelCall(Frozen):
    model_requested: str | Missing
    model_returned: str | Missing
    provider_requested: str | Missing
    provider_returned: str | Missing
    http_status: int | Missing
    finish_reason: str | Missing
    retries: int | Missing
    fallback: bool | Missing
    send_claimed: bool | Missing


class Validation(Frozen):
    native_schema_status: str | Missing
    observation_status: str | Missing
    rejection_reason: str | Missing
    canonical_accepted: bool | Missing
    canonical_readiness: str | Missing


class Score(Frozen):
    """Copied scorer outputs; this adapter never computes a score."""

    agent_success: bool | Missing
    canonical_state_success: bool | Missing
    schema_status: str | Missing
    raw_prose_status: str | Missing
    independent_assessment_status: str | Missing
    evaluator_identity: str | Missing
    evaluator_independent: bool | Missing
    assessment_rubric_sha256: str | Missing
    assessment_observation_binding: Literal["VERIFIED", "MISMATCH"] | Missing
    assessment_source_fingerprint_match: bool | Missing
    deterministic_display_is_model_credit: bool | Missing


class Effect(Frozen):
    action_kind: str | Missing
    specialist_dispatch: bool | Missing
    effect_classification: Literal["NO_EXTERNAL_EFFECT", "SPECIALIST_DISPATCH_RECORDED"] | Missing


class Usage(Frozen):
    """Provider-reported usage. Cost is the response-reported charge only."""

    input_tokens: int | Missing
    output_tokens: int | Missing
    reasoning_tokens: int | Missing
    token_usage_verified: bool | Missing
    native_latency_ms: float | Missing
    attempt_wall_latency_ms: float | Missing
    reported_cost_usd: str | Missing  # exact decimal string, never a float
    billing_status: str | Missing
    billing_verified: bool | Missing
    cost_scope: Literal["PROVIDER_RESPONSE_REPORTED"] | Missing


class IndexRecord(Frozen):
    record_id: str
    source_id: str
    campaign_id: str | Missing
    evaluation_id: str | Missing
    evidence_class: EvidenceClass
    model_performance_evidence: bool
    agent: str | Missing
    arm: str | Missing
    case_id: str | Missing
    dataset_case_id: str | Missing
    conversation_id: str | Missing
    turn_index: int | Missing
    stage: str | Missing
    test_node_id: str | Missing
    test_outcome: Literal["PASSED", "FAILED", "ERROR", "SKIPPED"] | Missing
    trace: TraceLink
    versions: Versions
    model_call: ModelCall
    validation: Validation
    score: Score
    effect: Effect
    usage: Usage
    artifacts: list[ArtifactRef]
    join_status: JoinStatus
    issues: list[str]


class Crosscheck(Frozen):
    name: str
    indexed: str | Missing
    reported: str | Missing
    status: Literal["MATCH", "MISMATCH", "UNAVAILABLE"]


class SourceSummary(Frozen):
    source_id: str
    kind: str
    declared_evidence_class: DeclaredClass
    campaign_id: str | Missing
    campaign_status: str | Missing
    completeness: Completeness
    record_counts: dict[str, int]
    crosschecks: list[Crosscheck]
    files: list[ArtifactRef]


class Finding(Frozen):
    severity: Severity
    code: str
    source_id: str
    record_id: str | None = None
    detail: str = ""


class ReferenceSummary(Frozen):
    ref_id: str
    artifact: ArtifactRef


class TraceEvalIndex(Frozen):
    schema_version: Literal["trace-eval-index/1.0"] = SCHEMA_VERSION
    adapter_version: str = ADAPTER_VERSION
    manifest_sha256: str
    index_status: Literal["COMPLETE", "INCOMPLETE"]
    references: list[ReferenceSummary]
    sources: list[SourceSummary]
    records: list[IndexRecord]
    findings: list[Finding]


# ---------------------------------------------------------------- manifest


class ReferenceSpec(Frozen):
    ref_id: str
    root: str
    path: str
    sha256: str | None = None


class SourceSpec(Frozen):
    source_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    kind: Literal["native_paired_campaign", "offline_junit"]
    root: str
    path: str
    declared_evidence_class: DeclaredClass
    evaluation_id: str
    campaign_id: str | None = None
    # Logical name -> path relative to the source directory.
    files: dict[str, str]
    # Campaign-owned path -> sha256 manifest (relative to the source directory).
    evidence_manifest: str | None = None
    # Key prefix the campaign manifest uses for this source directory (e.g. "A/").
    evidence_manifest_prefix: str = ""
    # Hashes recorded when this manifest was written; a later difference is STALE.
    pins: dict[str, str] = Field(default_factory=dict)
    prompt_candidates: list[str] = Field(default_factory=list)
    summary_fields: dict[str, str] = Field(default_factory=dict)
    completeness_map: dict[str, Completeness] = Field(default_factory=dict)
    action_kinds: dict[str, str] = Field(default_factory=dict)


class Manifest(Frozen):
    manifest_version: Literal["trace-eval-manifest/1.0"]
    roots: dict[str, str | None]
    references: list[ReferenceSpec] = Field(default_factory=list)
    sources: list[SourceSpec]
