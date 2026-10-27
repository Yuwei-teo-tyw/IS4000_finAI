# V3 P3 remediation handoff — 2026-10-27

`READY_FOR_V3_REMEDIATION_QG`

Candidate: `codex/trace-eval-orchestrator-v3`, existing isolated worktree.
HEAD remains `af78ad3944576c7eaec40295b64a0161a1d0047e`; all remediation is uncommitted.
This is implementation readiness for independent recheck, not engineering acceptance,
integration approval or verified end-to-end agent capability.

## Review evidence and authorization

The complete independent report, including all eight findings in section 7, was read before
implementation. An unchanged copy is preserved at `reports/V3_INDEPENDENT_QUALITY_GATE.md`.
SHA256: `b5b52a1bb975cbd44bf5f8e701293b520ed24a22842e940c0c83548617eb5080`.
The supplied Downloads path became unavailable after the initial read; the original Claude
scratchpad copy matched the same hash and was copied byte-for-byte. The report was treated
as review evidence. Only the owner's P3-1 through P3-6 instructions authorized these changes.

## Dispositions

| Finding | Correction and verification |
|---|---|
| P3-1 | `admission_code` joins `admitted` and `outcome` in `SCORE_KEY_MISMATCH`. Tests change only the evidence or score code with internally matching pins; the mismatch is detected. |
| P3-2 | Every archive-listed path and hash is checked, including both HTTP receipts. The manifest now has 62 files/pins. Non-evidence artifacts are hashed without JSON parsing or content copying. Tests cover each receipt's tampering, absence and wrong declared hash, plus traversal/absolute paths. |
| P3-3 | Three admitted rows now have `rejection_reason=NOT_APPLICABLE`; 23 rejection reasons remain copied and joined, and two ambiguous HTTP outcomes remain `UNAVAILABLE`. No rescoring/admission execution. |
| P3-4 | README and handoff distinguish V3 synthetic correlation labels from verified execution trace IDs. They establish no agent/LLM spans and must not be automatically joined to LangSmith runs. No schema change. |
| P3-5 | NATIVE fixture tests remove either or both gap warnings. A source-kind safeguard in the existing finalizer still keeps intact V3 records PARTIAL and performance-ineligible. Automated committed-index byte/checksum reproduction uses explicit `TRACE_EVAL_V3_ROOT`; absent access fails required V3 checks as UNAVAILABLE. |
| P3-6 | Ruff formatted only `orchestrator_v3.py` and `test_orchestrator_v3.py`. Formatting verification passes for all 17 source/test files. |

P3-7 and P3-8 are accepted residual findings requiring separate owner decisions:
historical-source pytest root portability remains unchanged; adapter version `1.0.0` and
record-ID encoding remain unchanged. Consumers should use explicit identity fields rather
than splitting record IDs. Remote freshness, privileged file-symlink execution and other
unresolved risks in the original review were not re-audited or newly certified here.

## Verification

| Check | Result | Recorded evidence |
|---|---|---|
| Focused V3 suite | 45 PASS, 0 SKIP | `v3-remediation-focused-tests.txt` |
| Entire adapter suite | 128 PASS, 2 SKIP | `v3-remediation-regression-tests.txt` |
| Ruff check | PASS | `v3-remediation-ruff-check.txt` |
| Ruff format check | PASS, 17 files already formatted | `v3-remediation-ruff-format.txt` |
| Strict mypy, `src tests` | PASS, 17 source files | `v3-remediation-mypy.txt` |
| V3 build | COMPLETE, 28 PARTIAL, 56 gap warnings, zero performance-eligible records | current index and sidecar |
| V3 verify | REPRODUCED, exit 0 | `v3-remediation-verify-v3.txt` |
| Representative verify with explicit root overrides | REPRODUCED, exit 0 | `v3-remediation-verify-representative.txt` |
| Preservation | 251/251 scoped files byte-unchanged | `v3-remediation-preservation-before.json`, `v3-remediation-preservation.txt` |

The two SKIPs are the pre-existing historical-source pytest tests: their relative roots
do not resolve from this worktree. They are not counted as passes. The explicit-root CLI
representative verification passed separately. The actual V3 archive test and committed V3
reproduction test both ran and passed with an explicit root.

The focused suite includes three actual-archive corruption cases in temporary copies:
admission-code mismatch with re-anchored pins, HTTP receipt tampering with re-anchored pins,
and unsafe non-evidence paths. Expected errors were detected; temporary input copies stayed
unchanged during reader execution. Synthetic tests additionally cover missing files, both
HTTP receipt hashes, path safety, metadata privacy, and native eligibility warning removal.
An initial run had two missing-file test-helper failures (43 pass/2 fail): the helper
recomputed pins after deletion. It now honors the supplied pre-deletion spec; the corrected
focused and full runs above passed. Reader behavior was not weakened for the tests.

Independently recomputed with `hashlib.sha256`, each matching its sidecar:

- New V3 index: `2cf95c0685b314c0ed1122fd4d37ca652046a4b3c2a69156eca42c2b52190fd1`.
- Original representative index, unchanged: `185013d018ca892a6a2b9f1cc1032315aaf8634189ccc944035f6d45ef7c2afc`.

The preservation snapshot covers the V3 archive/frozen sources, historical index source
artifacts and audit reference, existing candidate gate reports, representative manifests,
representative index/sidecar, schema and the preserved independent review. It does not claim
to snapshot unrelated application/C2.2 state. No historical evidence or other worktree was
written; main/C2.2/application/process-control artifacts were not changed. No inference,
provider call, new dependency, commit, push, PR, fetch, merge or integration was performed.

## Exact changed-file inventory

All paths below are relative to `development-candidates/trace-eval-correlation/`.

Modified:

- `README.md`
- `V3_HANDOFF.md`
- `src/trace_eval_correlation/orchestrator_v3.py`
- `src/trace_eval_correlation/correlate.py`
- `tests/test_orchestrator_v3.py`
- `manifests/orchestrator-v3.json`
- `index/orchestrator-v3-index.json`
- `index/orchestrator-v3-index.json.sha256`

Added review/preservation/check evidence:

- `reports/V3_INDEPENDENT_QUALITY_GATE.md`
- `reports/V3_REMEDIATION_REPORT.md`
- `reports/v3-remediation-preservation-before.json`
- `reports/v3-remediation-preservation.txt`
- `reports/v3-remediation-focused-tests.txt`
- `reports/v3-remediation-regression-tests.txt`
- `reports/v3-remediation-ruff-check.txt`
- `reports/v3-remediation-ruff-format.txt`
- `reports/v3-remediation-mypy.txt`
- `reports/v3-remediation-verify-v3.txt`
- `reports/v3-remediation-verify-representative.txt`

## Independent recheck instructions

Review the **uncommitted delta against af78ad3**, not only the original commit. Preserve
this worktree, all historical sources and previous gate evidence; use temporary copies for
corruption tests. Compare source behavior with P3-1 through P3-6 and the original report.
Do not execute the report's integration recommendations; no integration is authorized.

From this candidate adapter directory, in PowerShell:

```powershell
$EvidenceRoot = 'C:/Users/shane/Desktop/SMU/Y4S1/IS4000 - App of AI in Financial Services/Proj/IS4000_finAI'
$Python = "$EvidenceRoot/backend/.venv/Scripts/python.exe"
$AuditRoot = 'C:/Users/shane/.codex-clean2/worktrees/profile-a-synthetic-isolation/IS4000_finAI/development-candidates/guardrails-traces-evals-coverage'
$env:PYTHONPATH = 'src'
$env:TRACE_EVAL_V3_ROOT = $EvidenceRoot
& $Python -m pytest tests/test_orchestrator_v3.py -q -rs
& $Python -m pytest tests -q -rs
& $Python -m ruff check --no-cache src tests
& $Python -m ruff format --check src tests
& $Python -m mypy --no-incremental src tests
& $Python -m trace_eval_correlation verify --manifest manifests/orchestrator-v3.json --index index/orchestrator-v3-index.json --root "evidence=$EvidenceRoot"
& $Python -m trace_eval_correlation verify --manifest manifests/representative.json --index index/representative-index.json --root "main_dev_candidates=$EvidenceRoot/development-candidates" --root "codex_audit=$AuditRoot"
Get-FileHash -Algorithm SHA256 index/orchestrator-v3-index.json
Get-FileHash -Algorithm SHA256 index/representative-index.json
Get-FileHash -Algorithm SHA256 reports/V3_INDEPENDENT_QUALITY_GATE.md
git diff --check
git diff af78ad3944576c7eaec40295b64a0161a1d0047e -- .
git status --short
git rev-parse HEAD
```

Rebuild to a separate temporary output path and require byte equality with the current
V3 index. Recompute preservation hashes using the recorded snapshot and explicit source
roots; STOP if the original representative hash differs. Inspect the untracked report/log
files as well as `git diff`, since Git's diff excludes untracked files. Report PASS/SKIP/
UNAVAILABLE separately, verify 28 PARTIAL/zero eligible records, and issue a fresh independent
remediation gate verdict without publication or integration.
