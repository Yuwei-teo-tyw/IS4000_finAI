# Independent quality gate — Trace–Eval Correlation Adapter

The reviewer was a fresh general-purpose agent with no authorship role. It worked read-only,
wrote only its own review files and ran probes on synthetic temp copies. The two review
reports are kept verbatim:

- [reports/INDEPENDENT_REVIEW_attempt1.md](reports/INDEPENDENT_REVIEW_attempt1.md):
  **PASS_WITH_FINDINGS**, with no P0, one P1, four P2 and several P3 findings.
- [reports/INDEPENDENT_REVIEW_attempt2.md](reports/INDEPENDENT_REVIEW_attempt2.md):
  **PASS_WITH_FINDINGS**, with no P0, no P1, one residual P2 and four P3 findings.

## What the reviewer verified independently

- **Joins:** the reviewer wrote its own join script, separate from the adapter, and checked
  all 159 records against the raw evidence. It found 0 discrepancies. The 36 native records
  join receipt ↔ request ↔ public output ↔ campaign manifest ↔ LLM span ↔ AGENT parent ↔
  SESSION root ↔ score ↔ assessment observation hash.
- **Counts and costs:** 24 + 12 native records, 1 PAIR preflight, 35 NOT_RUN and 87 JUnit
  nodes. Costs are US$0.01210965 for V9.3 and US$0.00873900 for PAIR.
- **Pins:** all 34 attempt-1 pins and the Codex audit reference hash match.
- **Reproduction:** the index rebuilds byte for byte.
- **Main checkout:** its preflight hashes matched at the start and end of both reviews.
- **No authority:** the adapter introduces no new scorer, admission or ledger authority.
- **No external calls:** no network or provider imports. There are no invented zeros and no
  free text, account metadata or absolute paths in the index.
- **Guardrail mapping:** the line citations in GUARDRAIL_COVERAGE.md are accurate at a2fdd55.

## Resolution of findings

| Finding | Resolution | Regression test (`tests/test_review_regressions.py`) |
|---|---|---|
| A1 P1-1: a missing consumed file raised no finding | `SOURCE_FILE_MISSING` is now raised. It is an ERROR when the file is required, listed or pinned. | `test_p1_*` |
| A1 P2-1: prompt pins were never checked | Prompt candidates now go through `check()` at load time. | `test_p2_1_*` |
| A1 P2-2: source-level failures never reached the records | Affected records now get `SOURCE_INTEGRITY_GAP`, `ARTIFACT_NOT_LISTED` and a span-status issue. | `test_p2_2_*` |
| A1 P2-3: NOT_RUN rows could produce duplicate ids | NOT_RUN rows now share the id counter, get `DUPLICATE_CASE_ID`, and a global `DUPLICATE_RECORD_ID` check catches the rest. | `test_p2_3_*` |
| A1 P2-4: source summaries skipped the privacy filter | Summaries now go through `_scrub_summary`. | `test_p2_4_*` |
| A1 P3: receipt keys, crashes, sidecar, bad manifest, unpinned sources, roots, wording | All fixed. | `test_p3_*` |
| A2 P2-1: a source with pins but no campaign manifest left receipts unanchored | Per-record `ARTIFACT_UNANCHORED` added; such records lose model-evidence eligibility. | `test_attempt2_p2_*` |
| A2 P3-1: an unreadable freeze manifest raised no finding | `DATASET_FREEZE_UNREADABLE` is now raised. | `test_attempt2_p3_unreadable_*` |
| A2 P3-2: `pin` path escape and an empty sidecar crashed with tracebacks | Both now exit 64 or fail cleanly. | `test_attempt2_p3_empty_sidecar_*` |
| A2 P3-3: misleading span code | The record-level code is renamed `TRACE_SPAN_STATUS_UNAVAILABLE`. | `test_p2_2_unterminated_*` |
| A2 P3-4: dead NOT_RUN condition | The condition is removed. | — |

These P3 items are accepted and left unchanged:

- A preflight row in a synthetic source keeps the NON_NATIVE_PREFLIGHT class.
- An undeclared rubric or scoring spec stays UNAVAILABLE.
- The `schema` command has no evidence-root guard.
- The redaction filter is pattern-based (see FINAL_REPORT limitations).
- A JSON syntax error in the manifest reports no field location (cosmetic).

## Final focused gate (gate 3, after attempt-2 fixes)

| Check | Result | Evidence |
|---|---|---|
| pytest | 85 passed | `reports/gate3-pytest.txt`, `reports/pytest-gate3.xml` |
| ruff check + format | clean | `reports/gate3-ruff.txt` |
| mypy --strict | clean, 7 files | `reports/gate3-mypy.txt` |
| verify (offline reproduction) | REPRODUCED, sha `185013d0…2afc` | `reports/gate3-verify.txt` |

The attempt-2 fixes are small and each one has a dedicated regression test. They were
verified by gate 3 and then by a separate closure review (below). The index is
byte-identical to the one checked in attempt 2: the attempt-2 fixes changed behaviour only
on synthetic failure paths, and none of those occur in the real evidence.

Failed attempts are preserved. `reports/pytest-attempt3-postreview.xml` is a failed run
caused by a wrong test expectation. Gates 1 and 2 and the attempt-1 and attempt-2
outputs are kept alongside it.

## Closure review (fresh reviewer, before the local commit)

[reports/CLOSURE_REVIEW.md](reports/CLOSURE_REVIEW.md): **PASS**, zero open P0–P2, seven
P3s. This reviewer did not write the code or any fix. It independently re-checked all 159
records and the 36 native joins against the raw evidence with its own script. It
reproduced and confirmed the closure of the attempt-2 P2 (`ARTIFACT_UNANCHORED`) and
re-probed the attempt-1 fixes. It also verified the 34 pins, byte-identical reproduction,
the redaction of every file proposed for commit, and that the synthetic tests run without
the historical evidence (83 passed, 2 skipped as UNAVAILABLE).

Open P3s, accepted as limitations. Code was not changed after the closure review.

1. A source with a campaign manifest but no pins gets no warning. The campaign manifest is
   then the only trust anchor: a receipt edited together with its manifest entry stays
   JOINED. The representative manifest pins all of its sources.
2. Documentation gap, now corrected in README: `pin` never pins per-request files, so a
   source without a campaign manifest can never count as model evidence.
3. `verify` crashes with a traceback when the sidecar is non-UTF-8 or a directory.
4. The import-probe test runs Python with `-I`, which ignores `PYTHONDONTWRITEBYTECODE`, so
   it writes `src/**/__pycache__`. That directory is gitignored.
5. JUnit test-node IDs may contain parametrised test text. Docs now say this.
6. FINAL_REPORT section 1 contains the local worktree path, which the assignment required.
7. Stale "no third review" wording, now corrected.

**Gate status: PASSED.** No P0–P2 findings remain open.
