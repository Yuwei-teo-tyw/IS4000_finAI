# Orchestrator V3 offline reader handoff

The reviewed baseline is preserved at `af78ad3944576c7eaec40295b64a0161a1d0047e`.
P3 remediation is uncommitted and requires a fresh independent Quality Gate.
This is offline correlation readiness, not verified end-to-end agent capability.

## Scope and evidence

- Added `orchestrator_eval_v3` alongside the two existing source kinds. No runtime imports,
  instrumentation, scorer execution, admission execution, provider calls or telemetry joins.
- The pinned manifest validates 62 files: archive manifest, saved scores, input manifest,
  dataset freeze, 28 evidence files, 28 prepared input files and two HTTP receipt files.
  Archive paths are resolved
  relative to the bound repository, never against the current working directory.
- All 28 records use `(phase, case_id, model)` identity: 2 smoke, 24 primary, 2 HTTP.
  Rejections remain copied outcomes; they do not imply failed evidence verification.
- Verified: artifact pins, archive evidence hashes, frozen input hashes and matching saved
  expected/actual input hashes, request/reservation identity, saved outcome joins.
- Partial: all 28 records. V3 `trace.trace_id` values are synthetic correlation labels,
  not verified execution trace IDs. They establish no real agent/LLM spans and must not
  be automatically joined to LangSmith runs. Receipt request IDs are retained, but there is
  no agent/LLM span tree or verified prompt binding. `model_performance_evidence=false`.
- Unavailable: spans/relationships, prompt binding, independent assessment, billing/cost,
  and absent usage values. Receipt usage is copied, not independently certified.
- Every archive-listed path and hash is checked. HTTP transcripts are hash-validated only;
  their content is not parsed/copied, and their session/dispatch facts are not inferred.
  Arbitrary evaluation metric columns remain in the referenced saved score artifact; no new
  score contract or interpretation is introduced. No match to `events.jsonl` is attempted.
- Missing or ambiguous joins and changed/unpinned/unsafe sources produce integrity findings.
  Duplicate evidence rows are retained individually rather than selecting a winner.

## Reproduce

Use Python 3.12 from the original repository's `backend/.venv/Scripts/python.exe`.
From this adapter directory, bind the original repository containing the archived V3
evidence (it may be absent in a fresh clone). Set `$Python` to that interpreter and
`$EvidenceRoot` to that repository's absolute path, then run in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
& $Python -m trace_eval_correlation build --manifest manifests/orchestrator-v3.json --index index/orchestrator-v3-index.json --root "evidence=$EvidenceRoot"
& $Python -m trace_eval_correlation verify --manifest manifests/orchestrator-v3.json --index index/orchestrator-v3-index.json --root "evidence=$EvidenceRoot"
$env:TRACE_EVAL_V3_ROOT = $EvidenceRoot
& $Python -m pytest tests -q
& $Python -m ruff check src tests
& $Python -m mypy src
```

Reviewed-baseline evidence (preserved in Git): 105 tests passed, two existing
historical-source tests skipped (`UNAVAILABLE`).
The actual V3 archive test passed. Ruff and strict mypy passed. Build returned `COMPLETE`
with 28 partial records and 56 gap warnings; verify returned `REPRODUCED`.
`COMPLETE` describes index/source integrity, not complete trace coverage or model acceptance.
Reviewed-baseline SHA256: `078075018cc8eb894c6810578336d19c2da6e03074e83dadfe4a6a7ad84078e7`.
Current remediation results/hash and exact independent recheck instructions are in
[reports/V3_REMEDIATION_REPORT.md](reports/V3_REMEDIATION_REPORT.md).

V3 archive and committed-index reproduction tests require `TRACE_EVAL_V3_ROOT` explicitly;
missing access fails those required checks with `UNAVAILABLE`, rather than counting a skip
as successful verification. Historical-source pytest portability (P3-7) remains deferred;
use the explicit-root representative CLI verification in the remediation report.

P3-7 historical-test portability and P3-8 adapter version/record-ID redesign are accepted
residual findings requiring separate owner decisions. No version bump or record-ID change
is included. Consumers must use the separate identity fields rather than splitting record IDs.

The existing representative index, evidence and main are unchanged. Extra files beyond
the requested implementation list are this review/reproduction handoff, the requested
separate index and its CLI-required SHA256 sidecar. Retain the isolated worktree and local
feature branch for fresh independent Quality Gate review; no integration is authorized.
