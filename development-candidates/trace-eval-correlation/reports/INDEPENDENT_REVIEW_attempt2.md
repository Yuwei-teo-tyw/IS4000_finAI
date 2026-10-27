# Independent review: Trace–Eval Correlation Adapter (attempt 2, focused re-review)

Reviewer: the same independent agent as attempt 1. I did not author the fixes. Date: 2026-10-27.
Mode: read-only. This file is the only file I wrote in the worktree; attempt1.md is unchanged.
I ran the probes on fresh synthetic temp copies in my scratchpad and never on real evidence.

## Scope

- Re-read `correlate.py` (full) and `cli.py` (full) after the fixes.
- Read the list of new tests (`tests/test_review_regressions.py`, 15 tests).
- Read the updated README and GUARDRAIL_COVERAGE.md row 18, and the relative-root manifests.
- Checked the regenerated index `index/representative-index.json`.

## Commands and results

| Check | Result |
|---|---|
| `pytest -q -p no:cacheprovider` | **82 passed** |
| `ruff check src tests`; `ruff format --check` | All checks passed; 15 files already formatted |
| `mypy --strict src/trace_eval_correlation` | Success, 7 source files |
| `verify --manifest manifests/representative.json --index index/representative-index.json` | **REPRODUCED** `185013d0…2afc`, exit 0; the sidecar matches |
| `build` to scratchpad + `cmp` with the committed index; `schema` + `cmp` | byte-identical; schema identical |
| Independent cross-check script from attempt 1, rerun on the new index | **0 discrepancies.** 36 native (24 + 12), 1 preflight, 35 NOT_RUN, 87 JUnit; costs 0.01210965 / 0.00873900 |
| Main checkout | branch `feat/agent-lab-c22-hybrid-orchestrator` @ `a2fdd55`; `git diff \| sha256sum` = `8b9b6920…c8f`; `git status --porcelain \| sha256sum` = `c17cf354…2ec429`. **Both match preflight.** |
| Relative roots in the manifest | Correct from `manifests/`: 4 levels up gives `Proj/`, 9 levels up gives `C:/Users/shane`. No username or absolute path in either manifest or the index. |

## Regression and degradation check on the real index

I diffed every record field of the attempt-1 index against the attempt-2 index.
- **Records:** identical in all 159 records. The record ids, join status and eligibility are
  unchanged.
- **Status:** 36/36 NATIVE are still JOINED and model evidence. Records carry zero issues, and the
  only finding is the INFO `CAMPAIGN_PARTIAL`.
- **What changed:** only `sources[].files`, which gained the prompt candidates (V9.3 +5, PAIR +7).
  All of them are `VERIFIED` against both the campaign manifest and the pin.
- **Conclusion:** nothing in the representative index lost JOINED status.

## Attempt-1 probes re-run (synthetic)

| Attempt-1 finding / probe | Now | Status |
|---|---|---|
| P1-1 b2: pinned dataset freeze deleted | INCOMPLETE, `SOURCE_FILE_MISSING` ERROR, records PARTIAL, not model evidence | **Fixed** |
| P1-1 b: pinned rubric deleted | `SOURCE_FILE_MISSING` ERROR; records not model evidence | **Fixed** |
| P2-1 a / a2: unused or bound prompt edited after pinning | `SOURCE_PIN_STALE` + `SOURCE_HASH_MISMATCH`, INCOMPLETE, records not model evidence | **Fixed** |
| P2-2 c2: stale trace pin | INCOMPLETE, `SOURCE_INTEGRITY_GAP` on every record, not model evidence | **Fixed** |
| P2-2 f: per-request files missing from the campaign manifest | record `ARTIFACT_NOT_LISTED`, PARTIAL, not model evidence | **Fixed** (see the P2 residual below) |
| P2-2 n: LLM span with no END | record `TRACE_SPAN_UNTERMINATED`, PARTIAL | **Fixed** |
| P2-3 d / e: duplicate NOT_RUN rows; NOT_RUN row colliding with an observed case | ids unique (`#2`); `DUPLICATE_CASE_ID` / `NOT_RUN_CONFLICT`; list case_id gets `MISSING_CASE_ID` with no crash | **Fixed** |
| P2-4 l: email or secret in summary status or campaign | not present in the rendered index | **Fixed** |
| P3 g / r10: receipt case_id or role differs | `RECEIPT_KEY_MISMATCH` ERROR, UNJOINABLE | **Fixed** |
| P3 h: dataset_freeze path escape | `UNJOINABLE_REFERENCE`, no crash | **Fixed** |
| P3 j: non-integer JUnit `tests` | crosscheck UNAVAILABLE, no crash | **Fixed** |
| P3 k: verify with the sidecar deleted | `NOT_REPRODUCED`, exit 1 | **Fixed** |
| P3 q: missing or invalid manifest | exit 64, no traceback, no path in stderr | **Fixed** |
| P3 p: no campaign manifest and no pins | `SOURCE_UNPINNED` + `SOURCE_INTEGRITY_GAP`; records not model evidence | **Fixed** |
| P3-10: GUARDRAIL wording | Row 18 now says "IMPLEMENTED (structural)". It cites `clarifier/app.py:1-15` and `graph.py:1-8`, which I verified import no specialist client or registry. It labels the 37-row data as observation. | **Fixed** |
| P3 m: preflight row in a SYNTHETIC_FIXTURE source | unchanged (deliberate) | **Accepted.** Never eligible either way. |

## Findings

### P0: none. P1: none.

### P2-1 (residual of attempt-1 P2-2): A source with pins but no campaign manifest leaves per-request evidence unanchored, yet its records stay eligible.
- **Where:** `correlate.py:602-611` raises `ARTIFACT_NOT_LISTED` only when `ctx.listed is not None`.
  `cli.py:72-82` (`pin_manifest`) excludes `requests_dir`. `correlate.py:1356` raises
  `SOURCE_UNPINNED` only when there are *neither* a manifest nor pins.
- **Probe r5:** pin all source-level files, set `evidence_manifest=None`, then edit
  `receipt.json` to `input_tokens=999999`.
- **Result:** `COMPLETE`, A:case-1 `JOINED`, `model_performance_evidence=true`, and the index
  reports 999999.
- **Why receipts escape detection:**
  - Request bytes are still cross-anchored by the trace span hash, but `receipt.json` (tokens,
    latency, model, provider, retries) is anchored by nothing.
  - The cost cross-check against the pinned summary would catch only cost edits.
- **Shipped index not affected:** all three representative sources declare a campaign manifest.
  The configuration is still supported and documented (pin, then build), so the README's "every
  join verified" eligibility is too strong for it.
- **Fix:** either
  - when `ctx.listed is None`, add a record warning (e.g. `ARTIFACT_UNANCHORED`) for per-request
    artifacts whose `pin` is NA; or
  - let `pin` hash `requests/<id>/{receipt,request,public-output}` and have `check()` compare them.

### P3-1: A declared freeze manifest that is unreadable or has the wrong shape gives a silent UNAVAILABLE cross-check.
- **Where:** `correlate.py:478-489`.
- **r1:** unparseable JSON in an unanchored source gives no ERROR, and the cross-check is
  UNAVAILABLE. The records are degraded only by `SOURCE_UNPINNED`.
- **r2:** valid JSON without a `files` map, consistent with the campaign manifest, gives
  `COMPLETE`, JOINED, eligible, with the cross-check silently UNAVAILABLE.
- **Fix:** add an ERROR such as `DATASET_FREEZE_UNREADABLE` when `dataset_freeze` is declared but
  cannot be parsed into a `files` map.

### P3-2: Remaining CLI tracebacks.
- `pin` with a candidate path that escapes the root raises an uncaught `UnjoinableReference`
  (probe r6a). It comes from `cli.py:80`, `resolver.resolve` inside `pin_manifest`.
- An empty `.sha256` sidecar raises `IndexError` at `cli.py:151`, from `.split()[0]` (probe r6b).
- Cosmetic: a JSON syntax error prints `manifest invalid at: ` with an empty location.
- **Fix:** map `UnjoinableReference` to `UsageError` in `pin_manifest`, and treat an empty sidecar
  as `recorded=None`.

### P3-3: `TRACE_SPAN_UNTERMINATED` is also raised for spans that do have an END but a null or non-string status.
- **Where:** `correlate.py:290-292` and `:626-631`.
- **Probe r3:** an END event with `"status": null` is reported as unterminated.
- The conservative outcome (PARTIAL) is fine, but the code name is misleading. Consider
  `TRACE_SPAN_STATUS_UNAVAILABLE`, or tracking END presence separately from status.

### P3-4: `NOT_RUN_CONFLICT` compares a case id with request-id keys.
- **Where:** `correlate.py:809`, `case_id in data.receipts`. `receipts` is keyed by `request_id`,
  so this half of the condition is effectively dead.
- It is harmless. Drop it, or compare against the receipts' `case_id` values.

### Design note (not a defect): degradation is intentionally broad.
- Any source-level ERROR demotes every non-NOT_RUN record of that source to PARTIAL (probe r4: a
  single orphan receipt directory demotes all records).
- This is conservative, documented in the README, and correct for an eligibility flag. It is not
  over-broad on the real evidence (zero demotions).

### Deliberately unchanged P3s
- **Accepted:**
  - Synthetic-source preflight class: never eligible.
  - Undeclared rubric or scoring spec left `UNAVAILABLE`: conservative, and visible.
  - No guard on `schema`: it takes no roots, the target is user-chosen, and nothing is read from
    evidence.
- **Accepted with residual risk:** the pattern-based redaction. It is defence in depth behind
  the allowlist. Absolute paths, Slack/Google keys, local phone numbers and names are still not
  matched, and `evaluator_identity` is copied verbatim (`/root/...`).
  - **Recommendation:** state this limitation explicitly in FINAL_REPORT.md.
  - **Optional hardening:** validate `evaluator_identity` against `SAFE_ID`.
- **README:** still links `FINAL_REPORT.md`. The coordinator says that file will be written after
  this verdict, and it must exist before acceptance.

## Verdict

**PASS_WITH_FINDINGS**

Every attempt-1 P1, P2 and fixed P3 is resolved and covered by regression tests. The shipped
index still reproduces byte for byte. It is independently verified and shows no degradation. The
main checkout is unchanged. One P2 residual remains: per-request receipts are unanchored when a
source has pins but no campaign manifest. It does not affect the representative index but should
be closed or documented in scope. The remaining P3s are minor.
