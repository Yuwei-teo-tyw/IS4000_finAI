# Final report — Local Trace–Eval Correlation Adapter

**Disposition: `READY_FOR_TRACE_EVAL_OWNER_REVIEW`. The closure review passed and the
adapter was committed locally on this branch.**

The adapter, schema, CLI, representative index, tests, guardrail mapping and independent
gate are complete. No historical evidence was modified, and the main checkout matches its
preflight state. Nothing was pushed, and no network or provider call was made.

> **Integration note:** this report describes the source branch, built on the local agent-lab
> commit `a2fdd55`. For the integration onto `main`, see [INTEGRATION_REPORT.md](INTEGRATION_REPORT.md).

## 1. Worktree and branch

| | |
|---|---|
| Worktree | `IS4000_finAI-trace-eval`, a sibling of the main checkout (the local machine path is omitted for publication) |
| Branch | `feat/trace-eval-correlation-offline` (new; uncommitted, as instructed) |
| Base commit | `a2fdd558f7c8de3a634375f041f5af9eb84cc675` |
| Created with | `git worktree add -b feat/trace-eval-correlation-offline <path> a2fdd55` |

**Why this base:** a2fdd55 was HEAD of both the main checkout and Codex's
`profile-a-synthetic-isolation` worktree, where the audit lives. The historical V9 evidence is
untracked in the main checkout, so no branch contains it. It is read in place, read-only,
through manifest roots and is not copied.

**Preflight:**
- The proposed path and branch were unused.
- Eleven existing worktrees were found and left untouched.
- The main checkout was on `feat/agent-lab-c22-hybrid-orchestrator` at a2fdd55, with 52
  porcelain entries.
- Main checkout hashes: tracked diff sha256 `8b9b6920…8cc8f`; `status --porcelain` sha256
  `c17cf354…2ec429`.

## 2. Source and evidence references (all read-only)

The roots are relative to `manifests/`. Every consumed file is pinned in
[manifests/representative.json](manifests/representative.json): 15 pins for V9.3, 17 for
PAIR and 2 for V9.4.3. Each file is also verified against the campaign's own evidence
manifest.

**Requirements origin:** the Codex audit `…/.codex-clean2/worktrees/profile-a-synthetic-isolation/IS4000_finAI/development-candidates/guardrails-traces-evals-coverage/GUARDRAILS_TRACES_EVALS_COVERAGE.md`, sha256 `bc59065042b271e0c8e58f22cea54734cb0bca74040e92a63e328719177e2ea9`. It is verified as a manifest reference.

| Source | Directory (main checkout, `development-candidates/`) | Key pins (sha256 prefix) | Indexed |
|---|---|---|---|
| `v93-paired-1` (V9.3 native, COMPLETE) | `v9.3-readiness` | evidence manifest `fb01f1ec…`, observations `69b6dd46…`, summary `a021497a…`, traces `01168127…` | 24 NATIVE (12 Clarifier, 12 Orchestrator) |
| `pair-v942-v93b-1` (V9.4.2 vs V9.3 B, STOPPED) | `v9.4.2-v9.3b-paired-readiness` | evidence manifest `0160bcd0…`, observations `e191f4aa…`, summary `8dde256e…`, traces `5cb0345e…` | 12 NATIVE, 1 NON_NATIVE_PREFLIGHT, 35 NOT_RUN |
| `v943-offline-tests` | `v9.4.3-offline` | evidence manifest `14f45ba6…` (prefix `A/`), `tests-final.xml` `19f987f0…` | 87 OFFLINE_TEST |

**Evidence chain reused per native record:**
- `reports/observations.json`, `scores.json`, `independent-prose-assessments.json` and
  `local-traces.jsonl`.
- `reports/requests/<id>/{receipt,request,public-output}`.
- `campaign/scope.json` and `not-run.json`.
- Frozen dataset `freeze-manifest.json`: 8/8 files verified in each campaign.
- Rubric (V9.3) or shared scoring spec (PAIR).
- Versioned `prompts/*.txt`.

**Telemetry contracts:**
- *Mapped but not adapted:* canonical `backend/src/advisory_agents/telemetry.py`
  (`SAFE_FIELDS`, `SAFE_EVENTS`, `record()`), at a2fdd55 in this worktree.
- *Adapted:* the V9 native span contract, SESSION → AGENT → LLM START/END records with
  `request_sha256`.

**LangSmith:** the historical run and experiment IDs listed in the audit are not re-queried.
Cloud fields are out of scope for this offline index.

## 3. Files created (all under `development-candidates/trace-eval-correlation/`)

| Path | Purpose |
|---|---|
| `src/trace_eval_correlation/schema.py` | Versioned Pydantic contracts `trace-eval-index/1.0` and `trace-eval-manifest/1.0` |
| `src/trace_eval_correlation/sources.py` | Manifest-bound root resolution, containment, hashing |
| `src/trace_eval_correlation/privacy.py` | Allowlist-backed redaction pass |
| `src/trace_eval_correlation/correlate.py` | Join, integrity and cross-check logic (no scoring) |
| `src/trace_eval_correlation/cli.py`, `__main__.py`, `__init__.py` | `pin` / `build` / `verify` / `schema` commands |
| `schema/trace-eval-index-1.0.schema.json` | Generated JSON Schema |
| `manifests/representative.unpinned.json`, `manifests/representative.json` | Source manifest, before and after pinning |
| `index/representative-index.json` (+ `.sha256`) | Representative offline index: 159 records, COMPLETE, sha `185013d018ca892a6a2b9f1cc1032315aaf8634189ccc944035f6d45ef7c2afc` |
| `tests/` (8 files, 85 tests) | Deterministic synthetic fixtures plus read-only historical checks |
| `GUARDRAIL_COVERAGE.md` | Course-aligned Clarifier/Orchestrator guardrail mapping |
| `QUALITY_GATE.md`, `reports/` | Independent gate report and all gate and attempt outputs |
| `README.md`, `pyproject.toml`, `FINAL_REPORT.md`, `CHECKPOINT.md` | Docs and tool configuration |

**Files modified:** none. Nothing outside this directory changed, and the worktree's
tracked files equal a2fdd55.

**Reproduce:** run from this directory with the main checkout's `backend/.venv` Python 3.12:

```bash
PYTHONPATH=src python -m trace_eval_correlation verify --manifest manifests/representative.json --index index/representative-index.json
```

## 4. Test, lint and type-check results

Final gate 3 results:

| Check | Result |
|---|---|
| `pytest` | **85 passed** |
| `ruff check` + `ruff format --check` | clean |
| `mypy --strict src/trace_eval_correlation` | clean (7 files) |
| `verify` | REPRODUCED |
| Historical evidence | Consumed-file hashes unchanged across builds (asserted in `test_historical_evidence.py`), and all pins VERIFIED |

All 12 required test categories are covered. See `tests/test_correlation.py`,
`test_integrity.py`, `test_campaign_states.py`, `test_privacy_classes.py`,
`test_reproducibility.py` and `test_review_regressions.py`.

**What the representative index shows:**
- **Joins:** every one of the 36 native records joins on all of:
  - case
  - agent span
  - LLM span
  - SESSION trace root
  - receipt
  - request hash, both file and span
  - public-output hash
  - score
  - independent assessment, bound to the observation hash
  - the exact prompt file embedded in the request: V9.3 A = clarifier-v92 / orchestrator-v91;
    V9.3 B = v93 / v93; PAIR A = clarifier-v93; PAIR B = clarifier-v942
- **Cross-checks:** all match the campaigns' own summaries — attempts, exact reported cost
  (0.01210965 / 0.00873900), planned rows (24 / 48) and JUnit count (87).

**Test evidence versus model performance:**
- Synthetic test fixtures exercise join rules only. They are never model evidence.
- `model_performance_evidence = true` marks only fully verified NATIVE records. It means the
  record is eligible to count as evidence; it is not a quality verdict.
- The 36 native records are small, single-provider historical samples (GPT-OSS-120B via Groq).
  No statistical or superiority claim follows.

## 5. Independent gate

The gate **PASSED**; see [QUALITY_GATE.md](QUALITY_GATE.md).
- **Attempt 1:** PASS_WITH_FINDINGS (P1 ×1, P2 ×4). All of them are fixed.
- **Attempt 2:** PASS_WITH_FINDINGS (P2 ×1, P3 ×4). The P2 and all four P3s are fixed.
- **After attempt 2:** the fixes were verified by gate 3 and dedicated tests.
- **Closure review:** a fresh reviewer returned **PASS** with zero open P0–P2 and seven
  accepted P3s ([reports/CLOSURE_REVIEW.md](reports/CLOSURE_REVIEW.md)). It confirmed that
  the unanchored-evidence P2 is closed. The index is byte-identical throughout
  (`185013d0…2afc`).

## 6. Limitations and future instrumentation gaps

- **Coverage:** only the V9 native span format and JUnit reports are adapted.
  - Not adapted: canonical `assurance/traces/events.jsonl` telemetry, orchestrator-eval-v3 local
    (Ollama) evidence, V9.1/V9.2/V9.4 campaigns and Profile A synthetic receipts. Each needs a
    small reader; the schema already accommodates them.
  - Base telemetry events lack case, prompt and source hashes, so they cannot be joined at
    record level without new instrumentation.
- **LangSmith:** cloud run IDs are not correlated. The historical IDs in the audit are not
  re-queried, and no upload path exists by design.
- **Cost:** cost is the provider-response-reported charge only. There is no invoice
  reconciliation, reservation accounting or failed-call usage; missing values stay UNAVAILABLE.
- **Latency:** only `native_latency_ms` and `attempt_wall_latency_ms` from the receipts are
  available. TTFT and per-span durations are not computed.
- **Hash trust:** the campaign manifests themselves are trusted as of pinning on 2026-10-27.
  Pins detect later drift; they do not prove the original campaign's honesty.
- **Assessment binding:** the `proposal_sha256` canonicalization reproduced for only 21/24 and
  11/13 rows, so it is not used. The observation-hash binding is used instead (36/36 VERIFIED).
- **Rubric/scoring spec:** for campaigns that never had one (V9.3 scoring spec, PAIR rubric
  file), the field is reported as UNAVAILABLE. This is conservative and could arguably be
  NOT_APPLICABLE.
- **Redaction:** the filter is pattern-based defence in depth over a strict field allowlist.
  - It does not detect personal names, Slack or Google keys, local 8-digit phone numbers or
    absolute paths.
  - `evaluator_identity` values such as `/root/v93_paired_final_audit` are copied verbatim.
    These are reviewer labels.
  - Identifier-like fields (case and conversation IDs) remain potentially identifying with
    real data.
- **Integrity degradation:** any source-level error demotes every record in that source. This
  is conservative by design.
- **Scenarios not covered:** injection, rejected-predecessor recovery and real-data privacy
  scenarios remain unexecuted, per the audit. They are registered here as gaps; this
  assignment did not create a new campaign for them.
- **Runtime:** the adapter runs on the main checkout's `backend/.venv` interpreter (pydantic
  2.14.1). It imports none of the main checkout's runtime modules, but has no venv of its own.

## 7. Main checkout preservation

At completion the main checkout is identical to preflight:
- Branch `feat/agent-lab-c22-hybrid-orchestrator`, HEAD `a2fdd55`.
- Tracked diff sha256 `8b9b69203bdac1834bd5e0e64452aab4323781babaadcdc6208ab3c52568cc8f`.
- `status --porcelain` sha256 `c17cf3544e36754e45d0d0377708dd6b0b51bfe8bdce6613c49d6774ff2ec429`.

The reviewer independently confirmed these hashes at the start and end of both reviews.

**Not touched:**
- `IS4000_finAI-orchestrator`
- the Codex worktrees
- the C2.2 lifecycle-remediation candidate
- historical evaluations and Profile A candidates

No stash, reset, clean, branch switch, commit, push, PR, merge, upload, provider call or
specialist execution occurred. The worktree is retained.

## 8. Publication notes (closure, 2026-10-27)

- **External dependency:** the historical evidence roots are untracked directories outside
  this repository's history (main checkout `development-candidates/v9.*`, Codex worktree
  audit). The commit does not package or reproduce them. Without them `build`/`verify`
  report the sources UNAVAILABLE and the two historical tests skip; the 83 synthetic tests
  run independently (verified in an isolated copy: 83 passed, 2 skipped).
- **Excluded from Git:** `reports/*.xml` JUnit outputs (they embed the machine hostname),
  caches and bytecode, via `.gitignore` in this directory. The XML files remain on disk as
  preserved local evidence; `reports/gate*.txt` carry the same results.
- **Paths kept deliberately:** section 1 records the worktree path, as the assignment
  required. The review reports quote local paths only as file locations and as one
  redaction-probe input. The manifests and index contain no absolute paths or usernames.
