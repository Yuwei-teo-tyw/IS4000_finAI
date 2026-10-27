"""Correlate existing evaluation rows with their execution evidence.

Read-only. The adapter joins and verifies; it never re-scores, re-admits, replays a
request or writes into a source directory. Integrity problems become findings and
explicit UNAVAILABLE values, never repaired or invented data.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from trace_eval_correlation import privacy
from trace_eval_correlation.schema import (
    NA,
    UNAVAILABLE,
    ArtifactRef,
    Completeness,
    Crosscheck,
    Effect,
    EvidenceClass,
    Finding,
    IndexRecord,
    JoinStatus,
    Manifest,
    Missing,
    ModelCall,
    ReferenceSummary,
    Score,
    Severity,
    SourceSpec,
    SourceSummary,
    TraceEvalIndex,
    TraceLink,
    Usage,
    Validation,
    Versions,
)
from trace_eval_correlation.sources import (
    Resolver,
    UnjoinableReference,
    artifact,
    canonical_sha256,
    file_sha256,
    is_safe_id,
    read_json,
    ref_text,
    sha256_bytes,
)

CODE = re.compile(r"^[A-Z0-9_]{2,80}$")

# Issues that break identity or integrity make a record UNJOINABLE and the index
# INCOMPLETE. Everything else is a visible gap that leaves the record PARTIAL.
ERROR_CODES = frozenset(
    {
        "ARTIFACT_HASH_MISMATCH",
        "ARTIFACT_MISSING",
        "DUPLICATE_AGENT_SPAN",
        "DUPLICATE_CASE_ID",
        "DUPLICATE_REQUEST_ID",
        "DUPLICATE_SCORE",
        "DUPLICATE_TEST_NODE",
        "MISSING_CASE_ID",
        "MISSING_REQUEST_ID",
        "MISSING_SCORE",
        "NOT_RUN_CONFLICT",
        "PREFLIGHT_HAS_LLM_SPAN",
        "PUBLIC_OUTPUT_HASH_MISMATCH",
        "RECEIPT_MISSING",
        "RECEIPT_SPAN_MISMATCH",
        "REQUEST_HASH_MISMATCH",
        "RUBRIC_HASH_MISMATCH",
        "SCORE_KEY_MISMATCH",
        "SPAN_PARENT_MISMATCH",
        "TRACE_SPAN_MISSING",
        "UNJOINABLE_REQUEST_ID",
        "ASSESSMENT_OBSERVATION_MISMATCH",
        "RECEIPT_KEY_MISMATCH",
        "TRACE_REQUEST_HASH_MISMATCH",
        "V3_REQUEST_EVIDENCE_INCOMPLETE",
        "V3_EVALUATION_TREE_MISMATCH",
    }
)

# Source-level findings that leave a source's records unverifiable as a whole. Any
# source-level ERROR also qualifies. Records then carry SOURCE_INTEGRITY_GAP.
SOURCE_GAP_WARNINGS = frozenset(
    {"NOT_IN_CAMPAIGN_MANIFEST", "SOURCE_FILE_MISSING", "SOURCE_UNPINNED"}
)


# ---------------------------------------------------------------- helpers


def _s(d: dict[str, Any] | None, key: str) -> str | Missing:
    v = None if d is None else d.get(key)
    return v if isinstance(v, str) else UNAVAILABLE


def _i(d: dict[str, Any] | None, key: str) -> int | Missing:
    v = None if d is None else d.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else UNAVAILABLE


def _f(d: dict[str, Any] | None, key: str) -> float | Missing:
    v = None if d is None else d.get(key)
    if isinstance(v, bool) or not isinstance(v, int | float):
        return UNAVAILABLE
    return float(v)


def _b(d: dict[str, Any] | None, key: str) -> bool | Missing:
    v = None if d is None else d.get(key)
    return v if isinstance(v, bool) else UNAVAILABLE


def _first_s(d: dict[str, Any] | None, *keys: str) -> str | Missing:
    for k in keys:
        v = _s(d, k)
        if v != UNAVAILABLE:
            return v
    return UNAVAILABLE


def _native_only(native_like: bool, value: Any) -> Any:
    """Model-call values exist only for a native-shaped request; otherwise NOT_APPLICABLE."""
    return value if native_like else NA


def _dicts(value: object) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and all(isinstance(x, dict) for x in value):
        return value
    return None


@dataclass
class Span:
    span_id: str
    kind: str | None
    parent: str | None
    case_id: str | None
    request_id: str | None
    request_sha256: str | None
    end_status: str | None = None


@dataclass
class Traces:
    available: bool
    spans: dict[str, Span] = field(default_factory=dict)
    llm_by_request: dict[str, list[Span]] = field(default_factory=lambda: defaultdict(list))
    llm_by_case: dict[str, list[Span]] = field(default_factory=lambda: defaultdict(list))
    agents_by_case: dict[str, list[Span]] = field(default_factory=lambda: defaultdict(list))

    def root_of(self, span: Span) -> Span | None:
        seen: set[str] = set()
        cur: Span | None = span
        while cur is not None and cur.parent is not None:
            if cur.span_id in seen:
                return None
            seen.add(cur.span_id)
            cur = self.spans.get(cur.parent)
        return cur


class Context:
    def __init__(self, spec: SourceSpec, resolver: Resolver) -> None:
        self.spec = spec
        self.resolver = resolver
        self.findings: list[Finding] = []
        self.listed: dict[str, str] | None = None
        self.files: list[ArtifactRef] = []

    def add(
        self, severity: Severity, code: str, record_id: str | None = None, detail: str = ""
    ) -> None:
        self.findings.append(
            Finding(
                severity=severity,
                code=code,
                source_id=self.spec.source_id,
                record_id=record_id,
                detail=detail,
            )
        )

    def rel(self, relative: str) -> str:
        return ref_text(self.spec.root, self.spec.path, relative)

    def path(self, relative: str) -> Path:
        return self.resolver.resolve(self.spec.root, f"{self.spec.path}/{relative}")

    def check(
        self, kind: str, relative: str, record_id: str | None = None, *, required: bool = False
    ) -> ArtifactRef:
        """Hash one evidence file and raise integrity findings for it."""
        try:
            target = self.path(relative)
        except UnjoinableReference as exc:
            self.add("ERROR", "UNJOINABLE_REFERENCE", record_id, f"{kind}: {exc}")
            return ArtifactRef(
                kind=kind, ref=self.rel(relative), sha256=UNAVAILABLE, source_manifest=NA, pin=NA
            )
        ref = artifact(
            kind,
            self.rel(relative),
            target,
            listed=self.listed,
            listed_key=self.spec.evidence_manifest_prefix + relative,
            pins=self.spec.pins,
            pin_key=relative,
        )
        if ref.source_manifest == "MISMATCH":
            self.add("ERROR", "SOURCE_HASH_MISMATCH", record_id, f"{kind}: {relative}")
        elif ref.source_manifest == "NOT_LISTED":
            self.add("WARNING", "NOT_IN_CAMPAIGN_MANIFEST", record_id, f"{kind}: {relative}")
        if ref.pin == "STALE":
            self.add("ERROR", "SOURCE_PIN_STALE", record_id, f"{kind}: {relative}")
        if ref.sha256 == UNAVAILABLE and record_id is None:
            # A declared source file that is gone. If it is required, or the campaign
            # manifest or a pin vouched for it, evidence was lost; otherwise a visible gap.
            listed_key = self.spec.evidence_manifest_prefix + relative
            vouched = (self.listed is not None and listed_key in self.listed) or (
                relative in self.spec.pins
            )
            severity: Severity = "ERROR" if vouched or required else "WARNING"
            self.add(severity, "SOURCE_FILE_MISSING", None, f"{kind}: {relative}")
        return ref


# ---------------------------------------------------------------- traces


def _parse_traces(ctx: Context, relative: str | None) -> Traces:
    if relative is None:
        ctx.add("ERROR", "TRACE_UNAVAILABLE", detail="no trace file declared")
        return Traces(available=False)
    ctx.files.append(ctx.check("traces", relative))
    try:
        raw = ctx.path(relative).read_bytes()
    except (OSError, UnjoinableReference):
        ctx.add("ERROR", "TRACE_UNAVAILABLE", detail=relative)
        return Traces(available=False)
    traces = Traces(available=True)
    ends: dict[str, str | None] = {}
    for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = privacy_safe_json(line)
        except ValueError:
            ctx.add("ERROR", "TRACE_LINE_MALFORMED", detail=f"line {number}")
            continue
        span_id = event.get("span_id")
        if not is_safe_id(span_id):
            ctx.add("ERROR", "TRACE_LINE_MALFORMED", detail=f"line {number}: span_id")
            continue
        if event.get("event") == "START":
            if span_id in traces.spans:
                ctx.add("ERROR", "DUPLICATE_SPAN_ID", detail=f"line {number}")
                continue
            span = Span(
                span_id=span_id,
                kind=event.get("kind") if isinstance(event.get("kind"), str) else None,
                parent=event.get("parent_span_id")
                if isinstance(event.get("parent_span_id"), str)
                else None,
                case_id=event.get("case_id") if isinstance(event.get("case_id"), str) else None,
                request_id=event.get("request_id")
                if isinstance(event.get("request_id"), str)
                else None,
                request_sha256=event.get("request_sha256")
                if isinstance(event.get("request_sha256"), str)
                else None,
            )
            traces.spans[span_id] = span
            if span.kind == "LLM":
                if span.request_id:
                    traces.llm_by_request[span.request_id].append(span)
                if span.case_id:
                    traces.llm_by_case[span.case_id].append(span)
            elif span.kind == "AGENT" and span.case_id:
                traces.agents_by_case[span.case_id].append(span)
        elif event.get("event") == "END":
            status = event.get("status")
            ends[span_id] = status if isinstance(status, str) else None
    for span_id, status in ends.items():
        if span_id in traces.spans:
            traces.spans[span_id].end_status = status
        else:
            ctx.add("WARNING", "TRACE_END_WITHOUT_START", detail=span_id)
    for span in traces.spans.values():
        if span.span_id not in ends:
            ctx.add("WARNING", "TRACE_SPAN_UNTERMINATED", detail=span.span_id)
    return traces


def privacy_safe_json(line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed") from exc
    if not isinstance(value, dict):
        raise ValueError("malformed")
    return value


# ---------------------------------------------------------------- native campaign


@dataclass
class NativeInputs:
    observations: list[dict[str, Any]]
    scores: dict[str, list[dict[str, Any]]]
    assessments: dict[str, dict[str, Any]]
    receipts: dict[str, dict[str, Any]]
    not_run: list[dict[str, Any]]
    scope_roles: dict[str, str]
    planned: int | None
    traces: Traces
    summary: dict[str, Any] | None
    rubric_sha: str | Missing
    dataset_sha: str | Missing
    scoring_sha: str | Missing
    prompts: dict[str, bytes]


def _load_json_file(ctx: Context, logical: str, *, required: bool) -> object | None:
    relative = ctx.spec.files.get(logical)
    if relative is None:
        if required:
            ctx.add("ERROR", "SOURCE_FILE_UNDECLARED", detail=logical)
        return None
    ctx.files.append(ctx.check(logical, relative, required=required))
    try:
        value, error = read_json(ctx.path(relative))
    except UnjoinableReference:
        return None
    if error is not None:
        if error != "MISSING_FILE":  # a missing file was already reported by check()
            ctx.add("ERROR", f"SOURCE_{error}", detail=logical)
        return None
    return value


def _load_evidence_manifest(ctx: Context) -> None:
    """The campaign's own path->sha256 manifest, against which consumed files are checked."""
    relative = ctx.spec.evidence_manifest
    if relative is None:
        return
    ctx.files.append(ctx.check("campaign_evidence_manifest", relative))
    try:
        listed, error = read_json(ctx.path(relative))
    except UnjoinableReference:
        listed, error = None, "UNJOINABLE"
    if (
        error is None
        and isinstance(listed, dict)
        and all(isinstance(v, str) for v in listed.values())
    ):
        ctx.listed = {str(k): v for k, v in listed.items()}
    else:
        ctx.add("ERROR", "CAMPAIGN_MANIFEST_UNAVAILABLE", detail=error or "not a path->sha256 map")
        ctx.listed = {}


def _load_native(ctx: Context) -> NativeInputs | None:
    spec = ctx.spec
    observations = _dicts(_load_json_file(ctx, "observations", required=True))
    if observations is None:
        ctx.add("ERROR", "OBSERVATIONS_UNAVAILABLE")
        return None

    scores: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _dicts(_load_json_file(ctx, "scores", required=True)) or []:
        if isinstance(row.get("case_id"), str):
            scores[row["case_id"]].append(row)

    assessments: dict[str, dict[str, Any]] = {}
    raw_assess = _load_json_file(ctx, "prose_assessments", required=False)
    if isinstance(raw_assess, dict):
        assessments = {k: v for k, v in raw_assess.items() if isinstance(v, dict)}

    not_run = _dicts(_load_json_file(ctx, "not_run", required=False)) or []

    scope_roles: dict[str, str] = {}
    planned: int | None = None
    scope = _load_json_file(ctx, "scope", required=False)
    if isinstance(scope, dict) and _dicts(scope.get("paired")) is not None:
        rows = _dicts(scope["paired"]) or []
        planned = len(rows)
        scope_roles = {
            r["id"]: r["role"]
            for r in rows
            if isinstance(r.get("id"), str) and isinstance(r.get("role"), str)
        }

    summary_raw = _load_json_file(ctx, "summary", required=True)
    summary = summary_raw if isinstance(summary_raw, dict) else None

    def file_hash(logical: str) -> str | Missing:
        relative = spec.files.get(logical)
        if relative is None:
            return UNAVAILABLE
        # A declared binding file (dataset freeze, rubric, scoring spec) is required.
        ctx.files.append(ctx.check(logical, relative, required=True))
        try:
            digest = file_sha256(ctx.path(relative))
        except UnjoinableReference:
            return UNAVAILABLE
        return digest if digest is not None else UNAVAILABLE

    dataset_sha = file_hash("dataset_freeze")
    prompts: dict[str, bytes] = {}
    for candidate in spec.prompt_candidates:
        ctx.files.append(ctx.check("prompt", candidate, required=True))
        try:
            prompts[candidate] = ctx.path(candidate).read_bytes()
        except (OSError, UnjoinableReference):
            continue
    receipts = _load_receipts(ctx)
    traces = _parse_traces(ctx, spec.files.get("traces"))
    return NativeInputs(
        observations=observations,
        scores=scores,
        assessments=assessments,
        receipts=receipts,
        not_run=not_run,
        scope_roles=scope_roles,
        planned=planned,
        traces=traces,
        summary=summary,
        rubric_sha=file_hash("rubric"),
        dataset_sha=dataset_sha,
        scoring_sha=file_hash("scoring_spec"),
        prompts=prompts,
    )


def _load_receipts(ctx: Context) -> dict[str, dict[str, Any]]:
    relative = ctx.spec.files.get("requests_dir")
    receipts: dict[str, dict[str, Any]] = {}
    if relative is None:
        return receipts
    try:
        base = ctx.path(relative)
        entries = sorted(p for p in base.iterdir() if p.is_dir())
    except (OSError, UnjoinableReference):
        ctx.add("ERROR", "RECEIPTS_UNAVAILABLE", detail=relative)
        return receipts
    for entry in entries:
        if not is_safe_id(entry.name):
            ctx.add("ERROR", "UNJOINABLE_RECEIPT_DIR")
            continue
        value, error = read_json(entry / "receipt.json")
        if error is not None or not isinstance(value, dict):
            ctx.add("ERROR", "RECEIPT_UNREADABLE", detail=entry.name)
            continue
        if value.get("request_id") != entry.name:
            ctx.add("ERROR", "RECEIPT_ID_MISMATCH", detail=entry.name)
            continue
        receipts[entry.name] = value
    return receipts


def _verify_dataset_freeze(ctx: Context) -> Crosscheck:
    relative = ctx.spec.files.get("dataset_freeze")
    if relative is None:
        return Crosscheck(
            name="dataset_freeze_files", indexed=NA, reported=NA, status="UNAVAILABLE"
        )
    try:
        value, error = read_json(ctx.path(relative))
    except UnjoinableReference:
        value, error = None, "UNJOINABLE"
    files = value.get("files") if isinstance(value, dict) else None
    if error is not None or not isinstance(files, dict):
        if error != "MISSING_FILE":  # a missing file was already reported by check()
            ctx.add("ERROR", "DATASET_FREEZE_UNREADABLE", detail=error or "no files map")
        return Crosscheck(
            name="dataset_freeze_files",
            indexed=UNAVAILABLE,
            reported=UNAVAILABLE,
            status="UNAVAILABLE",
        )
    folder = relative.rsplit("/", 1)[0] if "/" in relative else ""
    verified = 0
    for name, expected in sorted(files.items()):
        try:
            actual = file_sha256(ctx.path(f"{folder}/{name}" if folder else str(name)))
        except UnjoinableReference:
            actual = None
        if actual == expected:
            verified += 1
        else:
            ctx.add("ERROR", "DATASET_FREEZE_MISMATCH", detail=str(name))
    return Crosscheck(
        name="dataset_freeze_files",
        indexed=str(verified),
        reported=str(len(files)),
        status="MATCH" if verified == len(files) else "MISMATCH",
    )


def _prompt_binding(
    ctx: Context, prompts: dict[str, bytes], request: dict[str, Any] | None
) -> tuple[str | Missing, str | Missing, Any]:
    """Prompt files were hashed and pin-checked once at load; match them here."""
    if not ctx.spec.prompt_candidates or request is None:
        return UNAVAILABLE, UNAVAILABLE, UNAVAILABLE
    messages = request.get("messages")
    text = "\n".join(
        m["content"]
        for m in messages or []
        if isinstance(m, dict) and isinstance(m.get("content"), str)
    )
    matches: list[tuple[int, str, str]] = []
    for candidate, raw in sorted(prompts.items()):
        # Checked-out prompt files may carry CRLF while request payloads use LF; compare
        # normalised text but report the hash of the file bytes as they exist.
        body = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()
        if body and body in text:
            matches.append((len(body), candidate, sha256_bytes(raw)))
    if not matches:
        return UNAVAILABLE, UNAVAILABLE, "NOT_FOUND"
    matches.sort(reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0] and matches[0][2] != matches[1][2]:
        return UNAVAILABLE, UNAVAILABLE, "AMBIGUOUS"
    return ctx.rel(matches[0][1]), matches[0][2], "EMBEDDED_IN_REQUEST"


def _native_records(ctx: Context, data: NativeInputs) -> list[IndexRecord]:
    spec = ctx.spec
    summary = data.summary
    fields = spec.summary_fields
    campaign_id: str | Missing = spec.campaign_id or _s(summary, fields.get("campaign", "campaign"))
    fingerprint = _s(summary, fields.get("source_fingerprint", "source_fingerprint"))
    case_counts = Counter(
        o["case_id"] for o in data.observations if isinstance(o.get("case_id"), str)
    )
    request_counts = Counter(
        o["request_id"] for o in data.observations if isinstance(o.get("request_id"), str)
    )
    used_receipts: set[str] = set()
    seen_ids: Counter[str] = Counter()
    records: list[IndexRecord] = []
    requests_dir = spec.files.get("requests_dir", "requests")

    for idx, row in enumerate(data.observations):
        issues: list[str] = []
        case_id = row.get("case_id")
        safe_case = is_safe_id(case_id) and not privacy.is_sensitive(str(case_id))
        base_id = f"{spec.source_id}/{case_id}" if safe_case else f"{spec.source_id}/row-{idx}"
        seen_ids[base_id] += 1
        record_id = base_id if seen_ids[base_id] == 1 else f"{base_id}#{seen_ids[base_id]}"
        if not isinstance(case_id, str):
            issues.append("MISSING_CASE_ID")
        elif case_counts[case_id] > 1:
            issues.append("DUPLICATE_CASE_ID")

        request_id = row.get("request_id")
        receipt: dict[str, Any] | None = None
        request_doc: dict[str, Any] | None = None
        artifacts: list[ArtifactRef] = [
            ArtifactRef(
                kind="observation_row",
                ref=ctx.rel(f"{spec.files['observations']}#row={idx}"),
                sha256=canonical_sha256(row),
                source_manifest=NA,
                pin=NA,
            )
        ]
        evidence: EvidenceClass
        if request_id is None:
            if isinstance(row.get("error_code"), str):
                evidence = "NON_NATIVE_PREFLIGHT"
            else:
                evidence = spec.declared_evidence_class
                issues.append("MISSING_REQUEST_ID")
        else:
            evidence = spec.declared_evidence_class
            if not is_safe_id(request_id):
                issues.append("UNJOINABLE_REQUEST_ID")
                request_id = None
            else:
                if request_counts[request_id] > 1:
                    issues.append("DUPLICATE_REQUEST_ID")
                receipt = data.receipts.get(request_id)
                if receipt is None:
                    issues.append("RECEIPT_MISSING")
                else:
                    used_receipts.add(request_id)
                    if any(
                        receipt.get(k) is not None and receipt.get(k) != row.get(k)
                        for k in ("case_id", "role", "stage")
                    ):
                        issues.append("RECEIPT_KEY_MISMATCH")
                for name in ("receipt.json", "request.json", "public-output.txt"):
                    ref = ctx.check(name, f"{requests_dir}/{request_id}/{name}", record_id)
                    if ref.source_manifest == "MISMATCH" or ref.pin == "STALE":
                        issues.append("ARTIFACT_HASH_MISMATCH")
                    if receipt is not None and ref.sha256 == UNAVAILABLE:
                        issues.append("ARTIFACT_MISSING")
                    if ref.source_manifest == "NOT_LISTED":
                        issues.append("ARTIFACT_NOT_LISTED")
                    if ctx.listed is None and ref.pin == NA and ref.sha256 != UNAVAILABLE:
                        # No campaign manifest and no pin: bytes are hashed but unanchored.
                        issues.append("ARTIFACT_UNANCHORED")
                    if ref.sha256 != UNAVAILABLE or receipt is not None:
                        artifacts.append(ref)
                if receipt is not None:
                    req_ref = next((a for a in artifacts if a.kind == "request.json"), None)
                    out_ref = next((a for a in artifacts if a.kind == "public-output.txt"), None)
                    value, _ = read_json(ctx.path(f"{requests_dir}/{request_id}/request.json"))
                    request_doc = value if isinstance(value, dict) else None
                    if req_ref is not None and req_ref.sha256 != receipt.get("request_sha256"):
                        issues.append("REQUEST_HASH_MISMATCH")
                    if out_ref is not None and out_ref.sha256 != receipt.get(
                        "public_output_sha256"
                    ):
                        issues.append("PUBLIC_OUTPUT_HASH_MISMATCH")

        native_like = evidence in ("NATIVE", "SYNTHETIC_FIXTURE")
        trace = _trace_link(data.traces, row, request_id, receipt, evidence, issues)
        for span_id, status in (
            (trace.agent_span_id, trace.agent_span_status),
            (trace.llm_span_id, trace.llm_span_status),
        ):
            if span_id not in (NA, UNAVAILABLE) and status == UNAVAILABLE:
                issues.append("TRACE_SPAN_STATUS_UNAVAILABLE")  # no END, or END without status
        if isinstance(case_id, str) and case_id in data.scores:
            score_rows = data.scores[case_id]
        else:
            score_rows = []
        if len(score_rows) > 1:
            issues.append("DUPLICATE_SCORE")
        score_row = score_rows[0] if len(score_rows) == 1 else None
        if score_row is None and not score_rows:
            issues.append("MISSING_SCORE")
        if score_row is not None and any(
            score_row.get(k) != row.get(k) for k in ("arm", "turn_index", "conversation_id", "role")
        ):
            issues.append("SCORE_KEY_MISMATCH")

        assessment = data.assessments.get(case_id) if isinstance(case_id, str) else None
        if assessment is None and native_like:
            issues.append("ASSESSMENT_UNAVAILABLE")
        binding: Any = NA if assessment is None else UNAVAILABLE
        if assessment is not None and isinstance(assessment.get("observation_sha256"), str):
            binding = (
                "VERIFIED"
                if assessment["observation_sha256"] == canonical_sha256(row)
                else "MISMATCH"
            )
            if binding == "MISMATCH":
                issues.append("ASSESSMENT_OBSERVATION_MISMATCH")
        assess_rubric = _s(assessment, "rubric_sha256") if assessment is not None else NA
        if (
            assess_rubric not in (NA, UNAVAILABLE)
            and data.rubric_sha != UNAVAILABLE
            and assess_rubric != data.rubric_sha
        ):
            issues.append("RUBRIC_HASH_MISMATCH")
        fp_match: bool | Missing = NA
        if assessment is not None:
            afp = _s(assessment, "source_fingerprint")
            fp_match = (
                UNAVAILABLE
                if afp == UNAVAILABLE or fingerprint == UNAVAILABLE
                else afp == fingerprint
            )

        prompt_ref, prompt_sha, prompt_binding = (
            _prompt_binding(ctx, data.prompts, request_doc) if native_like else (NA, NA, NA)
        )
        if native_like and spec.prompt_candidates and prompt_binding != "EMBEDDED_IN_REQUEST":
            issues.append("PROMPT_NOT_BOUND")
        response_format = request_doc.get("response_format") if request_doc else None
        schema_name: str | Missing = UNAVAILABLE if native_like else NA
        rf_sha: str | Missing = UNAVAILABLE if native_like else NA
        if isinstance(response_format, dict):
            rf_sha = canonical_sha256(response_format)
            js = response_format.get("json_schema")
            schema_name = _s(js, "name") if isinstance(js, dict) else UNAVAILABLE

        usage = _usage(receipt, native_like, issues)
        status = _s(row, "status")
        rejection: str | Missing = NA if status == "ACCEPTED" else UNAVAILABLE
        if status != "ACCEPTED":
            for candidate in (row.get("error_code"), (score_row or {}).get("projection_error")):
                if isinstance(candidate, str) and CODE.match(candidate):
                    rejection = candidate
                    break
        after = row.get("after") if isinstance(row.get("after"), dict) else None
        role = _s(row, "role")
        dispatch = _b(row, "specialist_dispatch")

        records.append(
            IndexRecord(
                record_id=record_id,
                source_id=spec.source_id,
                campaign_id=campaign_id,
                evaluation_id=spec.evaluation_id,
                evidence_class=evidence,
                model_performance_evidence=False,  # set after issues are final
                agent=role,
                arm=_s(row, "arm"),
                case_id=case_id if safe_case else UNAVAILABLE,
                dataset_case_id=_s(row, "dataset_case_id"),
                conversation_id=_s(row, "conversation_id"),
                turn_index=_i(row, "turn_index"),
                stage=_s(row, "stage"),
                test_node_id=NA,
                test_outcome=NA,
                trace=trace,
                versions=Versions(
                    source_fingerprint=fingerprint,
                    prompt_ref=prompt_ref,
                    prompt_sha256=prompt_sha,
                    prompt_binding=prompt_binding,
                    response_schema_name=schema_name,
                    response_format_sha256=rf_sha,
                    dataset_freeze_sha256=data.dataset_sha,
                    rubric_sha256=data.rubric_sha,
                    scoring_spec_sha256=data.scoring_sha,
                ),
                model_call=ModelCall(
                    model_requested=_native_only(native_like, _s(receipt, "model_requested")),
                    model_returned=_native_only(native_like, _s(receipt, "returned_model")),
                    provider_requested=_native_only(native_like, _s(receipt, "upstream_requested")),
                    provider_returned=_native_only(native_like, _s(receipt, "returned_provider")),
                    http_status=_native_only(native_like, _i(receipt, "http_status")),
                    finish_reason=_native_only(native_like, _s(receipt, "finish_reason")),
                    retries=_native_only(native_like, _i(receipt, "retries")),
                    fallback=_native_only(native_like, _b(receipt, "fallback")),
                    send_claimed=_native_only(native_like, _b(receipt, "send_claimed")),
                ),
                validation=Validation(
                    native_schema_status=_native_only(
                        native_like,
                        _first_s(receipt, "native_json_schema_status", "native_schema_status"),
                    ),
                    observation_status=status,
                    rejection_reason=rejection,
                    canonical_accepted=_b(row, "canonical_accepted"),
                    canonical_readiness=_s(after, "readiness"),
                ),
                score=Score(
                    agent_success=_b(score_row, "agent_success"),
                    canonical_state_success=_b(score_row, "canonical_state_success"),
                    schema_status=_first_s(score_row, "schema_status", "native_json_schema_status"),
                    raw_prose_status=_s(score_row, "raw_prose_status"),
                    independent_assessment_status=_s(assessment, "status")
                    if assessment is not None
                    else NA,
                    evaluator_identity=_s(assessment, "reviewer_identity")
                    if assessment is not None
                    else NA,
                    evaluator_independent=_b(assessment, "independent_of_implementation")
                    if assessment is not None
                    else NA,
                    assessment_rubric_sha256=assess_rubric,
                    assessment_observation_binding=binding,
                    assessment_source_fingerprint_match=fp_match,
                    deterministic_display_is_model_credit=_b(
                        score_row, "deterministic_display_is_model_credit"
                    ),
                ),
                effect=Effect(
                    action_kind=spec.action_kinds.get(role, UNAVAILABLE)
                    if isinstance(role, str)
                    else UNAVAILABLE,
                    specialist_dispatch=dispatch,
                    effect_classification=UNAVAILABLE
                    if dispatch == UNAVAILABLE
                    else ("SPECIALIST_DISPATCH_RECORDED" if dispatch else "NO_EXTERNAL_EFFECT"),
                ),
                usage=usage,
                artifacts=artifacts,
                join_status="JOINED",
                issues=sorted(set(issues)),
            )
        )

    observed_cases = set(case_counts)
    for request_id in sorted(set(data.receipts) - used_receipts):
        ctx.add("ERROR", "ORPHAN_RECEIPT", detail=request_id)
    for request_id in sorted(set(data.traces.llm_by_request) - set(request_counts)):
        ctx.add("ERROR", "ORPHAN_LLM_SPAN", detail=request_id)
    for case_id in sorted(set(data.scores) - observed_cases):
        ctx.add("WARNING", "ORPHAN_SCORE", detail=case_id)

    not_run_counts = Counter(
        r["case_id"] for r in data.not_run if isinstance(r.get("case_id"), str)
    )
    for idx, row in enumerate(data.not_run):
        raw_case = row.get("case_id")
        case_id = raw_case if isinstance(raw_case, str) else None
        safe_case = is_safe_id(case_id) and not privacy.is_sensitive(str(case_id))
        base_id = f"{spec.source_id}/{case_id}" if safe_case else f"{spec.source_id}/not-run-{idx}"
        seen_ids[base_id] += 1
        record_id = base_id if seen_ids[base_id] == 1 else f"{base_id}#{seen_ids[base_id]}"
        issues = []
        if case_id is None:
            issues.append("MISSING_CASE_ID")
        elif not_run_counts[case_id] > 1:
            issues.append("DUPLICATE_CASE_ID")
        if case_id is not None and case_id in observed_cases:
            issues.append("NOT_RUN_CONFLICT")
        role = (
            data.scope_roles.get(case_id, UNAVAILABLE) if isinstance(case_id, str) else UNAVAILABLE
        )
        case_value: str | Missing = (
            case_id if isinstance(case_id, str) and safe_case else UNAVAILABLE
        )
        records.append(
            _not_run_record(ctx, row, record_id, case_value, role, campaign_id, issues, idx)
        )
    return records


def _trace_link(
    traces: Traces,
    row: dict[str, Any],
    request_id: str | None,
    receipt: dict[str, Any] | None,
    evidence: EvidenceClass,
    issues: list[str],
) -> TraceLink:
    if not traces.available:
        issues.append("TRACE_UNAVAILABLE")
        u = UNAVAILABLE
        return TraceLink(
            trace_id=u,
            agent_span_id=u,
            llm_span_id=u,
            request_id=request_id
            if request_id
            else (NA if evidence == "NON_NATIVE_PREFLIGHT" else u),
            span_relationship=u,
            agent_span_status=u,
            llm_span_status=u,
            request_hash_match=u,
        )
    case_id = row.get("case_id")
    if evidence == "NON_NATIVE_PREFLIGHT":
        agents = traces.agents_by_case.get(case_id, []) if isinstance(case_id, str) else []
        if isinstance(case_id, str) and traces.llm_by_case.get(case_id):
            issues.append("PREFLIGHT_HAS_LLM_SPAN")
        if len(agents) > 1:
            issues.append("DUPLICATE_AGENT_SPAN")
        agent = agents[0] if len(agents) == 1 else None
        root = traces.root_of(agent) if agent else None
        if agent is None:
            issues.append("TRACE_SPAN_MISSING")
        return TraceLink(
            trace_id=root.span_id if root else UNAVAILABLE,
            agent_span_id=agent.span_id if agent else UNAVAILABLE,
            llm_span_id=NA,
            request_id=NA,
            span_relationship=(
                "VERIFIED" if root is not None and root.kind == "SESSION" else "PARENT_MISMATCH"
            )
            if agent
            else "SPAN_NOT_FOUND",
            agent_span_status=(agent.end_status or UNAVAILABLE) if agent else UNAVAILABLE,
            llm_span_status=NA,
            request_hash_match=NA,
        )
    if request_id is None:
        u = UNAVAILABLE
        return TraceLink(
            trace_id=u,
            agent_span_id=u,
            llm_span_id=u,
            request_id=u,
            span_relationship=u,
            agent_span_status=u,
            llm_span_status=u,
            request_hash_match=u,
        )
    spans = traces.llm_by_request.get(request_id, [])
    if not spans:
        issues.append("TRACE_SPAN_MISSING")
        u = UNAVAILABLE
        return TraceLink(
            trace_id=u,
            agent_span_id=u,
            llm_span_id=u,
            request_id=request_id,
            span_relationship="SPAN_NOT_FOUND",
            agent_span_status=u,
            llm_span_status=u,
            request_hash_match=u,
        )
    if len(spans) > 1:
        issues.append("DUPLICATE_REQUEST_ID")
    llm = spans[0]
    agent = traces.spans.get(llm.parent) if llm.parent else None
    root = traces.root_of(llm)
    relationship_ok = (
        agent is not None
        and agent.kind == "AGENT"
        and agent.case_id == case_id
        and llm.case_id == case_id
        and root is not None
        and root.kind == "SESSION"
        and root is not agent
    )
    if not relationship_ok:
        issues.append("SPAN_PARENT_MISMATCH")
    if receipt is not None and receipt.get("llm_span_id") != llm.span_id:
        issues.append("RECEIPT_SPAN_MISMATCH")
    hash_match: bool | Missing = UNAVAILABLE
    if receipt is not None and isinstance(receipt.get("request_sha256"), str):
        hash_match = llm.request_sha256 == receipt["request_sha256"]
        if not hash_match:
            issues.append("TRACE_REQUEST_HASH_MISMATCH")
    return TraceLink(
        trace_id=root.span_id if root else UNAVAILABLE,
        agent_span_id=agent.span_id if agent else UNAVAILABLE,
        llm_span_id=llm.span_id,
        request_id=request_id,
        span_relationship="VERIFIED" if relationship_ok else "PARENT_MISMATCH",
        agent_span_status=(agent.end_status or UNAVAILABLE) if agent else UNAVAILABLE,
        llm_span_status=llm.end_status or UNAVAILABLE,
        request_hash_match=hash_match,
    )


def _usage(receipt: dict[str, Any] | None, native_like: bool, issues: list[str]) -> Usage:
    if not native_like:
        return Usage(
            input_tokens=NA,
            output_tokens=NA,
            reasoning_tokens=NA,
            token_usage_verified=NA,
            native_latency_ms=NA,
            attempt_wall_latency_ms=NA,
            reported_cost_usd=NA,
            billing_status=NA,
            billing_verified=NA,
            cost_scope=NA,
        )
    verified_tokens = _b(receipt, "token_usage_verified")
    tokens_ok = verified_tokens is True
    if not tokens_ok:
        issues.append("TOKEN_USAGE_UNAVAILABLE")
    cost: str | Missing = UNAVAILABLE
    raw_cost = None if receipt is None else receipt.get("reported_cost_usd_exact")
    if _b(receipt, "billing_verified") is True and isinstance(raw_cost, str):
        try:
            if Decimal(raw_cost).is_finite():
                cost = raw_cost
        except InvalidOperation:
            pass
    if cost == UNAVAILABLE:
        issues.append("COST_UNAVAILABLE")
    return Usage(
        input_tokens=_i(receipt, "input_tokens") if tokens_ok else UNAVAILABLE,
        output_tokens=_i(receipt, "output_tokens") if tokens_ok else UNAVAILABLE,
        reasoning_tokens=_i(receipt, "reasoning_tokens") if tokens_ok else UNAVAILABLE,
        token_usage_verified=verified_tokens,
        native_latency_ms=_f(receipt, "native_latency_ms"),
        attempt_wall_latency_ms=_f(receipt, "attempt_wall_latency_ms"),
        reported_cost_usd=cost,
        billing_status=_s(receipt, "billing_status"),
        billing_verified=_b(receipt, "billing_verified"),
        cost_scope="PROVIDER_RESPONSE_REPORTED" if cost != UNAVAILABLE else UNAVAILABLE,
    )


def _not_run_record(
    ctx: Context,
    row: dict[str, Any],
    record_id: str,
    case_id: str | Missing,
    role: str | Missing,
    campaign_id: str | Missing,
    issues: list[str],
    idx: int,
) -> IndexRecord:
    trace = TraceLink(
        trace_id=NA,
        agent_span_id=NA,
        llm_span_id=NA,
        request_id=NA,
        span_relationship=NA,
        agent_span_status=NA,
        llm_span_status=NA,
        request_hash_match=NA,
    )
    return IndexRecord(
        record_id=record_id,
        source_id=ctx.spec.source_id,
        campaign_id=campaign_id,
        evaluation_id=ctx.spec.evaluation_id,
        evidence_class="NOT_RUN",
        model_performance_evidence=False,
        agent=role,
        arm=_s(row, "arm"),
        case_id=case_id,
        dataset_case_id=_s(row, "dataset_case_id"),
        conversation_id=NA,
        turn_index=NA,
        stage=NA,
        test_node_id=NA,
        test_outcome=NA,
        trace=trace,
        versions=Versions(
            source_fingerprint=NA,
            prompt_ref=NA,
            prompt_sha256=NA,
            prompt_binding=NA,
            response_schema_name=NA,
            response_format_sha256=NA,
            dataset_freeze_sha256=NA,
            rubric_sha256=NA,
            scoring_spec_sha256=NA,
        ),
        model_call=_na_model_call(),
        validation=Validation(
            native_schema_status=NA,
            observation_status="NOT_RUN",
            rejection_reason=NA,
            canonical_accepted=NA,
            canonical_readiness=NA,
        ),
        score=_na_score(),
        effect=Effect(action_kind=NA, specialist_dispatch=NA, effect_classification=NA),
        usage=_usage(None, False, []),
        artifacts=[
            ArtifactRef(
                kind="not_run_row",
                ref=ctx.rel(f"{ctx.spec.files['not_run']}#row={idx}"),
                sha256=canonical_sha256(row),
                source_manifest=NA,
                pin=NA,
            )
        ],
        join_status="NOT_APPLICABLE",
        issues=sorted(set(issues)),
    )


def _na_model_call() -> ModelCall:
    return ModelCall(
        model_requested=NA,
        model_returned=NA,
        provider_requested=NA,
        provider_returned=NA,
        http_status=NA,
        finish_reason=NA,
        retries=NA,
        fallback=NA,
        send_claimed=NA,
    )


def _na_score() -> Score:
    return Score(
        agent_success=NA,
        canonical_state_success=NA,
        schema_status=NA,
        raw_prose_status=NA,
        independent_assessment_status=NA,
        evaluator_identity=NA,
        evaluator_independent=NA,
        assessment_rubric_sha256=NA,
        assessment_observation_binding=NA,
        assessment_source_fingerprint_match=NA,
        deterministic_display_is_model_credit=NA,
    )


def _native_summary(
    ctx: Context, data: NativeInputs | None, records: list[IndexRecord]
) -> SourceSummary:
    spec = ctx.spec
    summary = data.summary if data else None
    fields = spec.summary_fields
    status = _s(summary, fields.get("status", "status"))
    completeness: Completeness = "UNAVAILABLE"
    if status != UNAVAILABLE:
        completeness = spec.completeness_map.get(status, "UNAVAILABLE")
        if status not in spec.completeness_map:
            ctx.add("WARNING", "CAMPAIGN_STATUS_UNMAPPED", detail=status)
    counts = Counter(r.evidence_class for r in records)
    if completeness == "COMPLETE" and counts.get("NOT_RUN"):
        ctx.add("ERROR", "CAMPAIGN_STATUS_INCONSISTENT", detail="complete with NOT_RUN rows")
    if completeness == "PARTIAL_STOPPED":
        ctx.add("INFO", "CAMPAIGN_PARTIAL", detail=status)

    checks: list[Crosscheck] = []
    native = [r for r in records if r.evidence_class in ("NATIVE", "SYNTHETIC_FIXTURE")]
    reported_attempts = (
        _i(summary, fields["native_attempts"]) if "native_attempts" in fields else NA
    )
    checks.append(_cross("native_attempts", str(len(native)), reported_attempts))
    costs = [r.usage.reported_cost_usd for r in native]
    indexed_cost: str | Missing = (
        UNAVAILABLE
        if not costs or any(c in (NA, UNAVAILABLE) for c in costs)
        else str(sum((Decimal(str(c)) for c in costs), Decimal(0)))
    )
    reported_cost = (
        _s(summary, fields["reported_cost_usd"]) if "reported_cost_usd" in fields else NA
    )
    checks.append(_cross("reported_cost_usd", indexed_cost, reported_cost, decimal=True))
    if data is not None and data.planned is not None:
        checks.append(_cross("planned_rows", str(len(records)), data.planned))
    if data is not None:
        checks.append(_verify_dataset_freeze(ctx))
    for check in checks:
        if check.status == "MISMATCH":
            ctx.add("ERROR", "CROSSCHECK_MISMATCH", detail=check.name)
    campaign_id: str | Missing = spec.campaign_id or _s(summary, fields.get("campaign", "campaign"))
    return SourceSummary(
        source_id=spec.source_id,
        kind=spec.kind,
        declared_evidence_class=spec.declared_evidence_class,
        campaign_id=campaign_id,
        campaign_status=status,
        completeness=completeness,
        record_counts=dict(sorted(counts.items())),
        crosschecks=checks,
        files=_dedupe_refs(ctx.files),
    )


def _cross(
    name: str, indexed: str | Missing, reported: object, *, decimal: bool = False
) -> Crosscheck:
    rep: str | Missing
    if reported in (NA, UNAVAILABLE) or reported is None:
        rep = UNAVAILABLE if reported != NA else NA
    else:
        rep = str(reported)
    if indexed in (NA, UNAVAILABLE) or rep in (NA, UNAVAILABLE):
        return Crosscheck(name=name, indexed=indexed, reported=rep, status="UNAVAILABLE")
    if decimal:
        try:
            same = Decimal(indexed) == Decimal(rep)
        except InvalidOperation:
            same = False
    else:
        same = indexed == rep
    return Crosscheck(
        name=name, indexed=indexed, reported=rep, status="MATCH" if same else "MISMATCH"
    )


def _dedupe_refs(refs: Iterable[ArtifactRef]) -> list[ArtifactRef]:
    unique = {(r.kind, r.ref): r for r in refs}
    return [unique[k] for k in sorted(unique)]


# ---------------------------------------------------------------- offline junit


def _junit(ctx: Context) -> tuple[list[IndexRecord], SourceSummary]:
    spec = ctx.spec
    relative = spec.files.get("junit")
    records: list[IndexRecord] = []
    checks: list[Crosscheck] = []
    if relative is None:
        ctx.add("ERROR", "SOURCE_FILE_UNDECLARED", detail="junit")
    else:
        ctx.files.append(ctx.check("junit", relative))
        root: ET.Element | None = None
        try:
            raw = ctx.path(relative).read_bytes()
            # pytest JUnit reports never declare a DTD; refusing one rules out entity
            # expansion and external entities without an extra parser dependency.
            if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
                ctx.add("ERROR", "SOURCE_UNREADABLE", detail="junit: DTD refused")
            else:
                root = ET.fromstring(raw)  # noqa: S314 - DTD-free, manifest-pinned local report
        except (OSError, ET.ParseError, UnjoinableReference):
            ctx.add("ERROR", "SOURCE_UNREADABLE", detail="junit")
        if root is not None:
            suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
            nodes: Counter[str] = Counter()
            reported_tests: int | None = 0
            for suite in suites:
                count = suite.get("tests")
                if reported_tests is not None and count is not None and count.isdigit():
                    reported_tests += int(count)
                else:
                    reported_tests = None
                for case in suite.findall("testcase"):
                    node = f"{case.get('classname', '')}::{case.get('name', '')}"
                    nodes[node] += 1
                    outcome: Any = "PASSED"
                    if case.find("failure") is not None:
                        outcome = "FAILED"
                    elif case.find("error") is not None:
                        outcome = "ERROR"
                    elif case.find("skipped") is not None:
                        outcome = "SKIPPED"
                    issues = ["DUPLICATE_TEST_NODE"] if nodes[node] > 1 else []
                    rid = f"{spec.source_id}/{node}"
                    if nodes[node] > 1:
                        rid += f"#{nodes[node]}"
                    records.append(_offline_record(ctx, rid, node, outcome, relative, issues))
            dup = {n for n, c in nodes.items() if c > 1}
            records = [
                r.model_copy(update={"issues": sorted({*r.issues, "DUPLICATE_TEST_NODE"})})
                if r.test_node_id in dup
                else r
                for r in records
            ]
            checks.append(
                _cross(
                    "junit_tests",
                    str(len(records)),
                    UNAVAILABLE if reported_tests is None else reported_tests,
                )
            )
    for check in checks:
        if check.status == "MISMATCH":
            ctx.add("ERROR", "CROSSCHECK_MISMATCH", detail=check.name)
    counts = Counter(r.evidence_class for r in records)
    summary = SourceSummary(
        source_id=spec.source_id,
        kind=spec.kind,
        declared_evidence_class=spec.declared_evidence_class,
        campaign_id=spec.campaign_id or NA,
        campaign_status=NA,
        completeness=NA,
        record_counts=dict(sorted(counts.items())),
        crosschecks=checks,
        files=_dedupe_refs(ctx.files),
    )
    return records, summary


def _offline_record(
    ctx: Context, record_id: str, node: str, outcome: Any, relative: str, issues: list[str]
) -> IndexRecord:
    na_trace = TraceLink(
        trace_id=NA,
        agent_span_id=NA,
        llm_span_id=NA,
        request_id=NA,
        span_relationship=NA,
        agent_span_status=NA,
        llm_span_status=NA,
        request_hash_match=NA,
    )
    return IndexRecord(
        record_id=record_id,
        source_id=ctx.spec.source_id,
        campaign_id=ctx.spec.campaign_id or NA,
        evaluation_id=ctx.spec.evaluation_id,
        evidence_class="OFFLINE_TEST",
        model_performance_evidence=False,
        agent=NA,
        arm=NA,
        case_id=NA,
        dataset_case_id=NA,
        conversation_id=NA,
        turn_index=NA,
        stage=NA,
        test_node_id=node,
        test_outcome=outcome,
        trace=na_trace,
        versions=Versions(
            source_fingerprint=NA,
            prompt_ref=NA,
            prompt_sha256=NA,
            prompt_binding=NA,
            response_schema_name=NA,
            response_format_sha256=NA,
            dataset_freeze_sha256=NA,
            rubric_sha256=NA,
            scoring_spec_sha256=NA,
        ),
        model_call=_na_model_call(),
        validation=Validation(
            native_schema_status=NA,
            observation_status=NA,
            rejection_reason=NA,
            canonical_accepted=NA,
            canonical_readiness=NA,
        ),
        score=_na_score(),
        effect=Effect(action_kind=NA, specialist_dispatch=NA, effect_classification=NA),
        usage=_usage(None, False, []),
        artifacts=[
            next(f for f in ctx.files if f.kind == "junit").model_copy(
                update={"kind": "junit_testcase", "ref": f"{ctx.rel(relative)}#{node}"}
            )
        ],
        join_status="JOINED",
        issues=sorted(set(issues)),
    )


# ---------------------------------------------------------------- assembly


def _finalise(ctx: Context, record: IndexRecord) -> IndexRecord:
    """Raise record issues as findings, derive join status, then privacy-filter."""
    for issue in record.issues:
        ctx.add("ERROR" if issue in ERROR_CODES else "WARNING", issue, record.record_id)
    join: JoinStatus = record.join_status
    if join != "NOT_APPLICABLE":
        if any(i in ERROR_CODES for i in record.issues):
            join = "UNJOINABLE"
        elif record.issues:
            join = "PARTIAL"
        else:
            join = "JOINED"
    elif any(i in ERROR_CODES for i in record.issues):
        join = "UNJOINABLE"
    # V3 has no independently supported span/prompt verification contract. Its
    # eligibility must not depend solely on the presence of warning strings.
    if ctx.spec.kind == "orchestrator_eval_v3" and join == "JOINED":
        join = "PARTIAL"
    performance = record.evidence_class == "NATIVE" and join == "JOINED"
    dumped = record.model_copy(
        update={"join_status": join, "model_performance_evidence": performance}
    ).model_dump(mode="json")
    redacted: list[str] = []
    clean = privacy.scrub(dumped, redacted.append)
    if redacted:
        clean["issues"] = sorted({*clean["issues"], "PRIVACY_REDACTED"})
        for field_path in redacted:
            ctx.add("WARNING", "PRIVACY_REDACTED", record.record_id, field_path)
    return IndexRecord.model_validate(clean)


def build_source(
    spec: SourceSpec, resolver: Resolver
) -> tuple[list[IndexRecord], SourceSummary, list[Finding]]:
    ctx = Context(spec, resolver)
    try:
        base = resolver.resolve(spec.root, spec.path)
    except UnjoinableReference as exc:
        ctx.add("ERROR", "SOURCE_UNJOINABLE", detail=str(exc))
        base = None
    if base is None or not base.is_dir():
        if base is not None:
            ctx.add("ERROR", "SOURCE_UNAVAILABLE", detail=ref_text(spec.root, spec.path))
        summary = SourceSummary(
            source_id=spec.source_id,
            kind=spec.kind,
            declared_evidence_class=spec.declared_evidence_class,
            campaign_id=spec.campaign_id or UNAVAILABLE,
            campaign_status=UNAVAILABLE,
            completeness="UNAVAILABLE",
            record_counts={},
            crosschecks=[],
            files=[],
        )
        return [], summary, ctx.findings
    _load_evidence_manifest(ctx)
    if spec.evidence_manifest is None and not spec.pins:
        ctx.add("WARNING", "SOURCE_UNPINNED", detail="no campaign manifest and no pins")
    if spec.kind == "orchestrator_eval_v3":
        from trace_eval_correlation.orchestrator_v3 import build_v3

        records, summary = build_v3(ctx)
    elif spec.kind == "offline_junit":
        records, summary = _junit(ctx)
    else:
        data = _load_native(ctx)
        records = _native_records(ctx, data) if data else []
        summary = _native_summary(ctx, data, records)
    gap = any(
        f.record_id is None and (f.severity == "ERROR" or f.code in SOURCE_GAP_WARNINGS)
        for f in ctx.findings
    )
    if gap:
        records = [
            r
            if r.evidence_class == "NOT_RUN"
            else r.model_copy(update={"issues": sorted({*r.issues, "SOURCE_INTEGRITY_GAP"})})
            for r in records
        ]
    records = [_finalise(ctx, r) for r in records]
    return records, _scrub_summary(ctx, summary), ctx.findings


def _scrub_summary(ctx: Context, summary: SourceSummary) -> SourceSummary:
    redacted: list[str] = []
    clean = privacy.scrub(summary.model_dump(mode="json"), redacted.append)
    for field_path in redacted:
        ctx.add("WARNING", "PRIVACY_REDACTED", None, f"source.{field_path}")
    return SourceSummary.model_validate(clean)


def build_index(manifest: Manifest, resolver: Resolver, manifest_sha256: str) -> TraceEvalIndex:
    findings: list[Finding] = []
    references: list[ReferenceSummary] = []
    for ref in manifest.references:
        try:
            target = resolver.resolve(ref.root, ref.path)
            actual = file_sha256(target)
        except UnjoinableReference:
            actual = None
        status: Any = (
            "MISSING_FILE"
            if actual is None
            else (
                "NOT_PINNED"
                if ref.sha256 is None
                else ("VERIFIED" if actual == ref.sha256 else "STALE")
            )
        )
        if status != "VERIFIED":
            findings.append(
                Finding(
                    severity="ERROR",
                    code=f"REFERENCE_{status}",
                    source_id="manifest",
                    detail=ref.ref_id,
                )
            )
        references.append(
            ReferenceSummary(
                ref_id=ref.ref_id,
                artifact=ArtifactRef(
                    kind="reference",
                    ref=ref_text(ref.root, ref.path),
                    sha256=actual if actual is not None else UNAVAILABLE,
                    source_manifest=NA,
                    pin=status,
                ),
            )
        )
    records: list[IndexRecord] = []
    sources: list[SourceSummary] = []
    ids = Counter(s.source_id for s in manifest.sources)
    for spec in manifest.sources:
        if ids[spec.source_id] > 1:
            findings.append(
                Finding(severity="ERROR", code="DUPLICATE_SOURCE_ID", source_id=spec.source_id)
            )
        recs, summary, found = build_source(spec, resolver)
        records.extend(recs)
        sources.append(summary)
        findings.extend(found)
    for record_id, count in sorted(Counter(r.record_id for r in records).items()):
        if count > 1:
            findings.append(
                Finding(
                    severity="ERROR",
                    code="DUPLICATE_RECORD_ID",
                    source_id="index",
                    record_id=record_id,
                )
            )
    clean_findings: list[Finding] = []
    for f in findings:
        rid = f.record_id
        detail = privacy.REDACTED if privacy.is_sensitive(f.detail) else f.detail
        if rid is not None and privacy.is_sensitive(rid):
            rid = privacy.REDACTED
        clean_findings.append(f.model_copy(update={"record_id": rid, "detail": detail}))
    unique = {
        (f.source_id, f.record_id or "", f.code, f.detail, f.severity): f for f in clean_findings
    }
    ordered = [unique[k] for k in sorted(unique)]
    return TraceEvalIndex(
        manifest_sha256=manifest_sha256,
        index_status="INCOMPLETE" if any(f.severity == "ERROR" for f in ordered) else "COMPLETE",
        references=references,
        sources=sources,
        records=sorted(records, key=lambda r: r.record_id),
        findings=ordered,
    )
