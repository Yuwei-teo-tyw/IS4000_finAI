"""Read pinned Orchestrator V3 archives without importing the evaluation runtime.

The V3 trace identifier is a correlation label, not an agent/LLM span tree.
Input bytes and saved outcomes can be joined; native performance eligibility
cannot be established by this format. No scoring or admission code is executed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from trace_eval_correlation.correlate import Context, _b, _dicts, _f, _i, _na_score, _s
from trace_eval_correlation.schema import (
    NA,
    UNAVAILABLE,
    ArtifactRef,
    Crosscheck,
    Effect,
    IndexRecord,
    ModelCall,
    SourceSummary,
    TraceLink,
    Usage,
    Validation,
    Versions,
)
from trace_eval_correlation.sources import UnjoinableReference, is_safe_id, read_json

Key = tuple[str, str, str]


def _key(row: dict[str, Any]) -> Key | None:
    values = tuple(row.get(k) for k in ("phase", "case_id", "model"))
    if all(is_safe_id(v) for v in values):
        return str(values[0]), str(values[1]), str(values[2])
    return None


def _read(
    ctx: Context, kind: str, path: str, listed_hash: str | None = None, *, parse: bool = True
) -> tuple[object | None, ArtifactRef]:
    """Every consumed artifact needs a pin; archive/freeze hashes are extra anchors."""
    try:
        ctx.path(path)
    except UnjoinableReference:
        ctx.add("ERROR", "UNJOINABLE_REFERENCE", detail=kind)
        return None, ArtifactRef(
            kind=kind,
            ref=f"{ctx.spec.root}:UNAVAILABLE",
            sha256=UNAVAILABLE,
            source_manifest=NA,
            pin=NA,
        )
    if path not in ctx.spec.pins:
        ctx.add("ERROR", "V3_ARTIFACT_UNPINNED_OR_STALE", detail=kind)
        return None, ArtifactRef(
            kind=kind, ref=ctx.rel(path), sha256=UNAVAILABLE, source_manifest=NA, pin="NOT_PINNED"
        )
    ref = ctx.check(kind, path, required=True)
    if listed_hash is not None:
        ref = ref.model_copy(
            update={"source_manifest": "VERIFIED" if ref.sha256 == listed_hash else "MISMATCH"}
        )
    ctx.files.append(ref)
    if ref.pin != "VERIFIED":
        ctx.add("ERROR", "V3_ARTIFACT_UNPINNED_OR_STALE", detail=kind)
    if listed_hash is not None and ref.sha256 != listed_hash:
        ctx.add("ERROR", "V3_DECLARED_HASH_MISMATCH", detail=kind)
    if not parse:
        return None, ref
    try:
        value, error = read_json(ctx.path(path))
    except UnjoinableReference:
        return None, ref
    if error:
        ctx.add("ERROR", "V3_ARTIFACT_UNAVAILABLE", detail=kind)
    return value, ref


def _object(ctx: Context, logical: str) -> tuple[dict[str, Any], ArtifactRef | None]:
    path = ctx.spec.files.get(logical)
    if path is None:
        ctx.add("ERROR", "SOURCE_FILE_UNDECLARED", detail=logical)
        return {}, None
    value, ref = _read(ctx, logical, path)
    if not isinstance(value, dict):
        ctx.add("ERROR", "V3_OBJECT_REQUIRED", detail=logical)
        return {}, ref
    return value, ref


def _rows(ctx: Context, value: object, name: str) -> list[dict[str, Any]]:
    rows = _dicts(value)
    if rows is None:
        ctx.add("ERROR", "V3_ROWS_REQUIRED", detail=name)
        return []
    return rows


def _groups(ctx: Context, rows: list[dict[str, Any]], name: str) -> dict[Key, list[dict[str, Any]]]:
    result: dict[Key, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = _key(row)
        if key is None:
            ctx.add("ERROR", "V3_IDENTITY_INVALID", detail=name)
        else:
            result[key].append(row)
    for matches in result.values():
        if len(matches) != 1:
            ctx.add("ERROR", "V3_DUPLICATE_JOIN", detail=name)
    return result


def _schema_status(row: dict[str, Any], name: str) -> str:
    value = _b(row, name)
    return "VALID" if value is True else "INVALID" if value is False else UNAVAILABLE


def build_v3(ctx: Context) -> tuple[list[IndexRecord], SourceSummary]:
    if ctx.spec.declared_evidence_class not in ("NATIVE", "SYNTHETIC_FIXTURE"):
        ctx.add("ERROR", "V3_EVIDENCE_CLASS_INVALID")
    archive, archive_ref = _object(ctx, "archive_manifest")
    inputs, inputs_ref = _object(ctx, "inputs")
    freeze, freeze_ref = _object(ctx, "dataset_freeze")
    score_path = ctx.spec.files.get("scores")
    score_value, score_ref = _read(ctx, "scores", score_path) if score_path else (None, None)
    scores = _groups(ctx, _rows(ctx, score_value, "scores"), "scores")
    prepared = _groups(ctx, _rows(ctx, inputs.get("entries"), "inputs"), "inputs")
    frozen_files = freeze.get("files")
    frozen_files = frozen_files if isinstance(frozen_files, dict) else {}
    if freeze.get("status") != "FROZEN":
        ctx.add("ERROR", "V3_DATASET_NOT_FROZEN")
    input_listing = frozen_files.get(ctx.spec.files.get("inputs", ""), {})
    if (
        not isinstance(input_listing, dict)
        or inputs_ref is None
        or input_listing.get("sha256") != inputs_ref.sha256
    ):
        ctx.add("ERROR", "V3_INPUT_MANIFEST_HASH_MISMATCH")

    observations: dict[Key, list[tuple[dict[str, Any], ArtifactRef]]] = defaultdict(list)
    paths: set[str] = set()
    for entry in _rows(ctx, archive.get("files"), "archive.files"):
        path, digest = entry.get("archive"), entry.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            ctx.add("ERROR", "V3_ARCHIVE_ENTRY_INVALID")
            continue
        if path in paths:
            ctx.add("ERROR", "V3_DUPLICATE_ARCHIVE_PATH")
            continue
        paths.add(path)
        # Validate every archive entry, but never parse/copy non-evidence content.
        if not path.endswith("/evidence.json"):
            _read(ctx, "archive_file", path, digest, parse=False)
            continue
        value, ref = _read(ctx, "evidence", path, digest)
        if not isinstance(value, dict) or value.get("version") != "synthetic-v3-evidence-1":
            ctx.add("ERROR", "V3_EVIDENCE_INVALID")
            continue
        key = _key(value)
        if key is None:
            ctx.add("ERROR", "V3_IDENTITY_INVALID", detail="evidence")
            continue
        observations[key].append((value, ref))

    for name, keys in (("scores", scores), ("inputs", prepared)):
        if set(keys) != set(observations):
            ctx.add("ERROR", "V3_JOIN_KEYS_MISMATCH", detail=name)
    request_ids: Counter[str] = Counter()
    for matches in observations.values():
        for row, _ in matches:
            receipt = row.get("receipt")
            if isinstance(receipt, dict) and is_safe_id(receipt.get("request_id")):
                request_ids[receipt["request_id"]] += 1

    records: list[IndexRecord] = []
    common = [ref for ref in (archive_ref, inputs_ref, freeze_ref, score_ref) if ref]
    for key, matches in sorted(observations.items()):
        # Ambiguous rows are retained individually; none is selected as the winner.
        for ordinal, (row, evidence_ref) in enumerate(matches):
            issues = ["V3_SPANS_UNAVAILABLE", "V3_PROMPT_BINDING_UNAVAILABLE"]
            if len(matches) != 1:
                ctx.add("ERROR", "V3_DUPLICATE_JOIN", detail="evidence")
                issues.append("DUPLICATE_CASE_ID")
            record_id = f"{ctx.spec.source_id}:{key[0]}:{key[1]}:{key[2]}"
            if len(matches) > 1:
                record_id += f":duplicate-{ordinal + 1}"
            receipt = row.get("receipt")
            receipt = receipt if isinstance(receipt, dict) else {}
            if not receipt:
                issues.append("RECEIPT_MISSING")
            request_id = _s(receipt, "request_id")
            if not is_safe_id(receipt.get("request_id")):
                issues.append("MISSING_REQUEST_ID")
            elif request_ids[request_id] != 1:
                issues.append("DUPLICATE_REQUEST_ID")
            if (
                request_id != row.get("reservation_id")
                or receipt.get("requested_model") != key[2]
                or receipt.get("role") != "orchestrator"
                or receipt.get("provider") != "ollama"
                or (receipt.get("status") == "PASS" and receipt.get("returned_model") != key[2])
            ):
                issues.append("RECEIPT_KEY_MISMATCH")
            if row.get("evidence_status") != "COMPLETE" or row.get("outbound_count") != 1:
                issues.append("V3_REQUEST_EVIDENCE_INCOMPLETE")
            if not is_safe_id(row.get("evaluation_tree")) or row.get(
                "evaluation_tree"
            ) != archive.get("evaluation_tree"):
                issues.append("V3_EVALUATION_TREE_MISMATCH")
            score_matches = scores.get(key, [])
            score = score_matches[0] if len(score_matches) == 1 else {}
            if len(score_matches) != 1:
                issues.append("DUPLICATE_SCORE" if score_matches else "MISSING_SCORE")
            if score and any(
                score.get(k) != row.get(k) for k in ("admitted", "outcome", "admission_code")
            ):
                issues.append("SCORE_KEY_MISMATCH")
            input_matches = prepared.get(key, [])
            input_row = input_matches[0] if len(input_matches) == 1 else {}
            refs = [*common, evidence_ref]
            input_ok = False
            input_path = input_row.get("path")
            if isinstance(input_path, str):
                frozen = frozen_files.get(input_path, {})
                frozen_hash = frozen.get("sha256") if isinstance(frozen, dict) else None
                _, input_ref = _read(
                    ctx,
                    "prepared_input",
                    input_path,
                    frozen_hash if isinstance(frozen_hash, str) else None,
                )
                refs.append(input_ref)
                input_ok = (
                    isinstance(frozen, dict)
                    and input_ref.sha256 != UNAVAILABLE
                    and input_ref.sha256 == input_row.get("sha256")
                    and input_ref.sha256 == frozen.get("sha256")
                    and input_ref.sha256 == row.get("actual_input_sha256")
                    and input_ref.sha256 == row.get("expected_input_sha256")
                    and input_ref.pin == "VERIFIED"
                )
            if not input_ok:
                issues.append("REQUEST_HASH_MISMATCH")
            records.append(
                _record(ctx, row, receipt, score, record_id, refs, issues, input_ok, freeze_ref)
            )
    expected = archive.get("actual_attempts")
    count_match = type(expected) is int and len(records) == expected
    if not count_match:
        ctx.add("ERROR", "V3_RECORD_COUNT_MISMATCH")
    return records, SourceSummary(
        source_id=ctx.spec.source_id,
        kind=ctx.spec.kind,
        declared_evidence_class=ctx.spec.declared_evidence_class,
        campaign_id=ctx.spec.campaign_id or UNAVAILABLE,
        campaign_status=_s(archive, "status"),
        completeness="COMPLETE" if count_match else "UNAVAILABLE",
        record_counts=dict(Counter(r.evidence_class for r in records)),
        crosschecks=[
            Crosscheck(
                name="archived_records",
                indexed=str(len(records)),
                reported=str(expected) if type(expected) is int else UNAVAILABLE,
                status="MATCH" if count_match else "MISMATCH",
            )
        ],
        files=sorted(ctx.files, key=lambda ref: (ref.ref, ref.kind)),
    )


def _record(
    ctx: Context,
    row: dict[str, Any],
    receipt: dict[str, Any],
    score: dict[str, Any],
    record_id: str,
    refs: list[ArtifactRef],
    issues: list[str],
    input_ok: bool,
    freeze_ref: ArtifactRef | None,
) -> IndexRecord:
    return IndexRecord(
        record_id=record_id,
        source_id=ctx.spec.source_id,
        campaign_id=ctx.spec.campaign_id or UNAVAILABLE,
        evaluation_id=ctx.spec.evaluation_id,
        evidence_class=ctx.spec.declared_evidence_class,
        model_performance_evidence=False,
        agent=_s(receipt, "role"),
        arm=UNAVAILABLE,
        case_id=_s(row, "case_id"),
        dataset_case_id=_s(row, "case_id"),
        conversation_id=UNAVAILABLE,
        turn_index=UNAVAILABLE,
        stage=_s(row, "phase"),
        test_node_id=UNAVAILABLE,
        test_outcome=UNAVAILABLE,
        trace=TraceLink(
            trace_id=_s(row, "trace_id"),
            request_id=_s(receipt, "request_id"),
            agent_span_id=UNAVAILABLE,
            llm_span_id=UNAVAILABLE,
            span_relationship=UNAVAILABLE,
            agent_span_status=UNAVAILABLE,
            llm_span_status=UNAVAILABLE,
            request_hash_match=input_ok,
        ),
        versions=Versions(
            source_fingerprint=_s(row, "evaluation_tree"),
            prompt_ref=UNAVAILABLE,
            prompt_sha256=UNAVAILABLE,
            prompt_binding=UNAVAILABLE,
            response_schema_name=UNAVAILABLE,
            response_format_sha256=UNAVAILABLE,
            dataset_freeze_sha256=freeze_ref.sha256 if freeze_ref else UNAVAILABLE,
            rubric_sha256=UNAVAILABLE,
            scoring_spec_sha256=UNAVAILABLE,
        ),
        model_call=ModelCall(
            model_requested=_s(receipt, "requested_model"),
            model_returned=_s(receipt, "returned_model"),
            provider_requested=_s(receipt, "provider"),
            provider_returned=_s(receipt, "backend_provider"),
            http_status=UNAVAILABLE,
            finish_reason=_s(receipt, "finish_reason"),
            retries=_i(receipt, "retries"),
            fallback=_b(receipt, "fallback"),
            send_claimed=True if row.get("outbound_count") == 1 else UNAVAILABLE,
        ),
        validation=Validation(
            native_schema_status=_schema_status(receipt, "schema_valid"),
            observation_status=_s(row, "outcome"),
            rejection_reason=NA if row.get("admitted") is True else _s(row, "admission_code"),
            canonical_accepted=_b(row, "admitted"),
            canonical_readiness=UNAVAILABLE,
        ),
        score=_na_score().model_copy(
            update={
                "schema_status": _schema_status(score, "actual_schema_valid"),
                "independent_assessment_status": UNAVAILABLE,
                "evaluator_identity": UNAVAILABLE,
                "evaluator_independent": UNAVAILABLE,
                "assessment_rubric_sha256": UNAVAILABLE,
                "assessment_observation_binding": UNAVAILABLE,
                "assessment_source_fingerprint_match": UNAVAILABLE,
                "agent_success": UNAVAILABLE,
                "canonical_state_success": UNAVAILABLE,
                "raw_prose_status": UNAVAILABLE,
                "deterministic_display_is_model_credit": UNAVAILABLE,
            }
        ),
        effect=Effect(
            action_kind="PLAN_PROPOSAL",
            specialist_dispatch=UNAVAILABLE,
            effect_classification=UNAVAILABLE,
        ),
        usage=Usage(
            input_tokens=_i(receipt, "input_tokens"),
            output_tokens=_i(receipt, "output_tokens"),
            reasoning_tokens=_i(receipt, "reasoning_tokens"),
            token_usage_verified=UNAVAILABLE,
            native_latency_ms=_f(receipt, "latency_ms"),
            attempt_wall_latency_ms=_f(row, "graph_duration_ms"),
            reported_cost_usd=UNAVAILABLE,
            billing_status=UNAVAILABLE,
            billing_verified=UNAVAILABLE,
            cost_scope=UNAVAILABLE,
        ),
        artifacts=refs,
        join_status="PARTIAL",
        issues=sorted(set(issues)),
    )
