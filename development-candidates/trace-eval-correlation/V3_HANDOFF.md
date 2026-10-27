# Orchestrator V3 offline reader handoff

## Current reviewed integration state

V3 and the P3 remediation are committed and locally integrated at reviewed HEAD
`94b73581f25d555825553186bff5d26cbf4771e0` on `codex/trace-eval-v3-latest-main`,
based on fetched main `6a34a69e70b89aed93065e2d8a9e236fc2e1071f`.
The independent pre-PR gate returned
`V3_PREPR_QG_PASS_READY_FOR_OWNER_PUBLICATION_REVIEW`, with QG-1 documenting stale
README/handoff wording. This QG-1 documentation correction is uncommitted and awaits
independent delta review. No publication or merge into main has occurred or is authorized.
This is offline correlation readiness, not verified end-to-end agent capability.

The original reviewed baseline `af78ad3944576c7eaec40295b64a0161a1d0047e` and its
historical results below remain preserved. The previous uncommitted-remediation status
described in the preserved remediation report is historical; it is not the state of
reviewed HEAD `94b7358`.

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
All 62/62 required V3 source files are absent from fetched main at the base identified
above, and this candidate does not add historical evidence. A fresh clone alone cannot
reproduce the archived index. Provision an external root containing the pinned archive
and prepared inputs. From this adapter directory, set `$Python` to that interpreter and
`$EvidenceRoot` to the provisioned repository's absolute path, then run in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
& $Python -m trace_eval_correlation build --manifest manifests/orchestrator-v3.json --index index/orchestrator-v3-index.json --root "evidence=$EvidenceRoot"
& $Python -m trace_eval_correlation verify --manifest manifests/orchestrator-v3.json --index index/orchestrator-v3-index.json --root "evidence=$EvidenceRoot"
$env:TRACE_EVAL_V3_ROOT = $EvidenceRoot
& $Python -m pytest tests -q
& $Python -m ruff check src tests
& $Python -m mypy src
```

## Verification at reviewed HEAD 94b7358

The independent pre-PR gate reproduced the following results; these are recorded
review results, not new test runs for this documentation correction:

| Full adapter suite configuration | Result |
|---|---|
| Explicit `TRACE_EVAL_V3_ROOT` containing all 62 pinned files | 128 passed, 2 historical-source skips; exit 0. |
| `TRACE_EVAL_V3_ROOT` unset | 123 passed, 5 failed, 2 historical-source skips; exit 1. |

The five failures are deliberate fail-closed `UNAVAILABLE` results for required V3
archive/reproduction checks. They do not count as success or optional skips. The two
historical-source skips are also `UNAVAILABLE` and are not passes. Explicit-root CLI
verification separately reproduced the representative index; it does not turn those
skipped pytest checks into passes. Ruff lint/format and strict mypy passed at reviewed HEAD.

Current index SHA-256 values, independently rebuilt and verified at that gate:

- V3: `2cf95c0685b314c0ed1122fd4d37ca652046a4b3c2a69156eca42c2b52190fd1`.
- Representative: `185013d018ca892a6a2b9f1cc1032315aaf8634189ccc944035f6d45ef7c2afc`.

All 28 V3 records remain `PARTIAL` and performance-ineligible. Synthetic correlation
labels are not verified execution traces; missing spans/prompt binding and unverified
usage prevent end-to-end performance claims. `COMPLETE` describes source/index integrity.

## Historical baseline at af78ad3

Original reviewed-baseline evidence (preserved in Git): 105 tests passed, two existing
historical-source tests skipped (`UNAVAILABLE`).
The actual V3 archive test passed. Ruff and strict mypy passed. Build returned `COMPLETE`
with 28 partial records and 56 gap warnings; verify returned `REPRODUCED`.
`COMPLETE` describes index/source integrity, not complete trace coverage or model acceptance.
Reviewed-baseline SHA256: `078075018cc8eb894c6810578336d19c2da6e03074e83dadfe4a6a7ad84078e7`.
Historical remediation results/hash and exact independent recheck instructions are in
[reports/V3_REMEDIATION_REPORT.md](reports/V3_REMEDIATION_REPORT.md).

## Remaining constraints and owner decisions

V3 archive and committed-index reproduction tests require `TRACE_EVAL_V3_ROOT` explicitly;
missing access fails those required checks with `UNAVAILABLE`, rather than counting a skip
as successful verification. Historical-source pytest portability (P3-7) remains deferred;
use the explicit-root representative CLI verification in the remediation report.

P3-7 historical-test portability and P3-8 adapter version/record-ID redesign are accepted
residual findings requiring separate owner decisions. No version bump or record-ID change
is included. Consumers must use the separate identity fields rather than splitting record IDs.

This documentation correction leaves the representative index, historical evidence and
main unchanged. Retain the isolated worktree and local
branch for independent documentation-delta review and owner publication review. External
evidence-root delivery, public disclosure of workstation metadata in preserved review
reports, and any future publication require separate owner decisions. The six uncommitted
integration reports/logs remain local evidence and must stay out of staging. No commit,
push, PR creation, merge or publication is authorized by this handoff.
