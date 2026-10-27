# V3 Remediation Independent Quality Gate: Orchestrator V3 P3-1 to P3-6

**Verdict: `V3_REMEDIATION_QG_PASS_READY_FOR_OWNER_REVIEW`**

There are no P0, P1 or P2 findings. All six approved P3 remediations (P3-1 to P3-6) are
independently verified. The remediation introduced two new P3 advisories (§8).

This gate covers evidence integrity and remediation correctness only. It does not accept the
engineering, approve integration or make any model-performance claim. The reviewer did not implement
these changes. The author's handoff and logs were treated as claims to test, not as proof.

Review date: 2026-10-27. Environment: Windows 11, Python 3.12.10 (main checkout `backend/.venv`),
pytest 9.1.1, Ruff 0.17.0, mypy 1.20.2, pydantic 2.14.1. No inference, provider, LangSmith, cloud or
network call was made. No Windows process-control experiment was run.

---

## 1. Reviewed source identity

| Item | Value |
|---|---|
| Repository | `IS4000_finAI` |
| Author worktree | `C:\Users\shane\.codex-clean2\worktrees\trace-eval-orchestrator-v3\IS4000_finAI` (read-only) |
| Branch | `codex/trace-eval-orchestrator-v3` ✅ |
| HEAD | `af78ad3944576c7eaec40295b64a0161a1d0047e` ✅ (unchanged before and after the review) |
| Delta under review | **uncommitted** working tree vs HEAD: 8 modified + 11 untracked files |
| `git diff --binary HEAD` SHA-256 | `fe5fd30c30140272bdbff74522c722a75fff08fce0d8611eb123f963cdfd8011` (same before and after) |
| Aggregate of the 19 per-file hashes below | `c1972feeb768f74476cc613bc0ad641103a016162109999aae97ca6c32afc63f` |
| `git diff --check HEAD` | clean |
| Changes outside `development-candidates/trace-eval-correlation/` | **none** (tracked or untracked) |

### Isolated reviewer workspace
`C:\Users\shane\AppData\Local\Temp\claude\C--Users-shane-Desktop-SMU-Y4S1-IS4000---App-of-AI-in-Financial-Services-Proj-IS4000-finAI\d9ffc361-e946-466f-a76e-8045ef5b1895\scratchpad\qg\`

- `baseline/`: `git archive af78ad3` of the adapter directory (51 files)
- `candidate/`: byte copy of the author's working-tree adapter directory, including untracked files and excluding caches (62 files)
- `evidence/`: `git archive HEAD` (`a2fdd55`) of the main checkout, limited to `assurance/evals/reports/orchestrator-eval-v3` and `assurance/evals/datasets/synthetic-v3` (81 files)
- `work/`: the reviewer's scripts and outputs (`reconstruct.py`, `mutate.py`, `srcmut.py`, `preserve.py`, `*.out`)
- `mut/`, `srcmut/`: temporary mutation copies

The author worktree was never written to, and every test, build and mutation ran in the copies.
The worktree's pre-existing ignored caches were left alone.

### Changed-file inventory (SHA-256 of the exact bytes reviewed)
Paths are relative to `development-candidates/trace-eval-correlation/`.

| Status | File | SHA-256 |
|---|---|---|
| M | `README.md` | `c006c59a7289b4e77b42d15f9484736af0f015385dd12a1139c26a812bdb82b9` |
| M | `V3_HANDOFF.md` | `ed77712a59215ea4fd5b7f3e092f91e2b1eadec61e14ef50f26d1fbc94c6de20` |
| M | `index/orchestrator-v3-index.json` | `2cf95c0685b314c0ed1122fd4d37ca652046a4b3c2a69156eca42c2b52190fd1` |
| M | `index/orchestrator-v3-index.json.sha256` | `6e3e19e34bc888118c5d5bb639908773c98b0d5e8747c980cd119b374d7bce58` |
| M | `manifests/orchestrator-v3.json` | `d919c084a70cf06751549e36dcc3819089f7d1a9ed6d0aab6a84cf4ecb620ea3` |
| M | `src/trace_eval_correlation/correlate.py` | `a4d9f58c6e5484267ca44fefe2e84963e5fa6beb744ae659861d9fae3d54e614` |
| M | `src/trace_eval_correlation/orchestrator_v3.py` | `d189b5ab3a962203594f79d25f46214bf8975c6f2062d3ef7a7d4f3051af5f85` |
| M | `tests/test_orchestrator_v3.py` | `00a56deb5adf50139ee6bf047e2f297e5102be58fd9635993aaedaef2f153977` |
| ?? | `reports/V3_INDEPENDENT_QUALITY_GATE.md` | `b5b52a1bb975cbd44bf5f8e701293b520ed24a22842e940c0c83548617eb5080` |
| ?? | `reports/V3_REMEDIATION_REPORT.md` | `91d2d69736b40159a3e75a5f7291fd927b13ccf36d5a3e7d2003ecb22a62d980` |
| ?? | `reports/v3-remediation-focused-tests.txt` | `a75abb3e9bf86aecdc7bcdbca3fdffb4741b4f809016b6944335817817c3acca` |
| ?? | `reports/v3-remediation-mypy.txt` | `63da153bcdac04b2cc982479df4378f21b20029f9acb87ad908fb4d5befe6a43` |
| ?? | `reports/v3-remediation-preservation-before.json` | `a79e444e5a0b6cf07fc261778c4e99fabc3acd7229ee07dabf5a05016682ec2c` |
| ?? | `reports/v3-remediation-preservation.txt` | `9c5e2302e1c48d9a619f9854357e500d7a816a01b204c134bba99f53c82543ca` |
| ?? | `reports/v3-remediation-regression-tests.txt` | `4cc576863d6034bceb288065e538cff7aa50ec467ce416fbbfab14fe94e13f5b` |
| ?? | `reports/v3-remediation-ruff-check.txt` | `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` |
| ?? | `reports/v3-remediation-ruff-format.txt` | `fa97e49c1676702abe414bbd31c59b9b77762b16f15c942859eac40336e91bac` |
| ?? | `reports/v3-remediation-verify-representative.txt` | `55fd0b10e88b7d5f92eb4e8e716ebd6e9a6bffc39bc0d2690cf1f8357578e8a8` |
| ?? | `reports/v3-remediation-verify-v3.txt` | `954cd36bd89865f04d7e9586ab2511c900a4a06c3b328c288508824603fd7f20` |

Unchanged against `af78ad3` (byte compare): `schema.py`, `schema/trace-eval-index-1.0.schema.json`,
`manifests/representative.json`, `representative.unpinned.json`, `index/representative-index.json` and its
`.sha256`. All prior gate reports and the prior review reports are also unchanged: `CLOSURE_REVIEW`,
`INDEPENDENT_REVIEW_attempt1/2`, `PRE_PR_REVIEW`, `gate{1,2,3}-*.txt`, `CHECKPOINT`, `FINAL_REPORT`,
`GUARDRAIL_COVERAGE`, `INTEGRATION_REPORT` and `QUALITY_GATE`.

The preserved copy of the original gate, `reports/V3_INDEPENDENT_QUALITY_GATE.md` (`b5b52a1b…`), is
byte-identical to the original in the first reviewer's scratchpad
(`…spare-2GengR\90dd547d-…\scratchpad\qg-v3\V3_INDEPENDENT_QUALITY_GATE.md`, also `b5b52a1b…`).

### Code delta (substantive lines only; the rest is the P3-6 Ruff reformat)
- `orchestrator_v3.py`: `_read(..., *, parse=True)` gains a keyword `parse=False` path, so a file is hashed and pin-checked but never parsed.
  Every non-`evidence.json` archive entry now goes through `_read(ctx, "archive_file", path, digest, parse=False)`.
  `SCORE_KEY_MISMATCH` now also compares `admission_code`. `rejection_reason` is `NOT_APPLICABLE` when `admitted is True`.
- `correlate.py` `_finalise`: when `ctx.spec.kind == "orchestrator_eval_v3"` and the computed join is `JOINED`, it is forced to `PARTIAL`
  before `performance = NATIVE ∧ JOINED` is computed. This adds a guard; nothing is weakened.
- `manifests/orchestrator-v3.json`: adds `http_receipt_00/01` to `files` and `pins` (62 files and 62 pins).
- Index delta vs `af78ad3` (`diff`): `manifest_sha256`, 3 × `rejection_reason` `UNAVAILABLE→NOT_APPLICABLE`, and
  2 new `archive_file` source refs (pin and source_manifest `VERIFIED`). Nothing else changed.

---

## 2. P3-1 to P3-6 verification

| Finding | Result | Independent basis |
|---|---|---|
| **P3-1** admission-code join | ✅ **VERIFIED** | §3 mutations 1–5: a change to `admission_code` alone in the evidence, in `cases.json`, in an HTTP row, in an admitted row, or a deleted score key, each with archive hash and pins re-anchored, always gives `INCOMPLETE` + `SCORE_KEY_MISMATCH`, exit 2, and the row is `UNJOINABLE`. No false `COMPLETE`. Source mutant M1 (revert) is killed by 3 focused tests. |
| **P3-2** archive validation | ✅ **VERIFIED** | 62/62 declared files exist and match their pins. 30/30 archive-listed hashes match. Every archive entry is declared and pinned. Both receipts were deleted, altered, given a wrong listed hash and unpinned (each detected). Unsafe paths (`../`, deep `../`, backslash `..\`, POSIX-absolute, drive-absolute, `a/../../x`) give `UNJOINABLE_REFERENCE` with all 28 records retained. An extra undeclared in-root entry gives `V3_ARTIFACT_UNPINNED_OR_STALE`. A receipt replaced by a directory is detected. An NTFS junction escape gives `UNJOINABLE_REFERENCE`. Receipt content (including a `sk-test…` marker) never appears in the index. Source mutants M2, M3 and M8 are killed. |
| **P3-3** rejection semantics | ✅ **VERIFIED** | `reconstruct.py` does not import the adapter and rebuilds all 28 rows from the raw evidence plus `cases.json`: 3 admitted → `NOT_APPLICABLE`; 23 `ADMISSION_REJECTED` → concrete joined codes (16 `MISSING_COVERAGE`, 6 `FORBIDDEN_CAPABILITY`, 1 `MISSING_PREREQUISITE`); 2 HTTP → `UNAVAILABLE` with outcome `HTTP_PLAN_REJECTED_OR_UNAVAILABLE`. Score and evidence agree on `admitted`, `outcome` and `admission_code` in 28/28 rows. The index rebuild is byte-identical and SHA-256 recomputes to `2cf95c06…`. See new advisory N-1. |
| **P3-4** synthetic trace IDs | ✅ **VERIFIED (documentation only)** | The README "Orchestrator V3 archive" section and handoff "Partial" bullet both say the labels are synthetic correlation labels, not verified trace IDs, establish no spans, and must not be auto-joined to LangSmith. The reviewer checked the README's claim about historical records against code and data: native `trace_id` is `root.span_id if root else UNAVAILABLE` (`correlate.py:865/928`), and all 37 historical rows with a UUID `trace_id` are `JOINED` with a verified span relationship. The claim is accurate. In-index, every V3 row also carries `V3_SPANS_UNAVAILABLE`, with all span fields `UNAVAILABLE`. A schema-level `trace_id_kind` field remains deferred (§9). |
| **P3-5** eligibility | ✅ **VERIFIED** | On the real archive declared `NATIVE`: 28/28 `PARTIAL`, 0 eligible. Source mutants: removing the warnings only (M6) still gives 0 eligible because the safeguard holds; removing the safeguard only (M5) is killed by 1 test; removing both (M7) is killed by 8 tests. The new NATIVE fixture test removes each warning and both, in-process. The eligibility logic and its tests are strictly stronger than at `af78ad3`. |
| **P3-6** formatting | ✅ **VERIFIED** | `ruff format --check src tests`: 17 files already formatted. `ruff check`: all checks passed. The changed files `orchestrator_v3.py`, `correlate.py` and `test_orchestrator_v3.py` are clean on both checks. |

---

## 3. Independent mutation evidence

### 3a. Black-box CLI runs on temporary evidence copies (`work/mutate.py`, output `work/mutate.out`)
Each scenario copies the 62 declared files into a fresh directory, mutates them, optionally
re-anchors the archive-listed hash and/or the adapter pins, then runs `python -m trace_eval_correlation build`.
Every scenario also asserts that the evidence copy is byte-unchanged after the build, that there are 0
performance-eligible records, and that no absolute temp path appears in the output.

| # | Scenario | Exit | Status | ERROR codes |
|---|---|---|---|---|
| 0 | baseline copy | 0 | COMPLETE | none; 28 PARTIAL |
| 1 | evidence `admission_code` only (`MISSING_COVERAGE→FORBIDDEN_CAPABILITY`), archive hash + pins re-anchored | 2 | INCOMPLETE | `SCORE_KEY_MISMATCH` (row UNJOINABLE) |
| 2 | `cases.json` `admission_code` only, re-pinned | 2 | INCOMPLETE | `SCORE_KEY_MISMATCH` |
| 3 | HTTP row evidence code `null→MISSING_COVERAGE`, re-anchored | 2 | INCOMPLETE | `SCORE_KEY_MISMATCH` |
| 4 | admitted row evidence code `null→FORBIDDEN_CAPABILITY`, re-anchored | 2 | INCOMPLETE | `SCORE_KEY_MISMATCH` |
| 5 | `cases.json` `admission_code` key deleted, re-pinned | 2 | INCOMPLETE | `SCORE_KEY_MISMATCH` |
| 6 | *trust-anchor limit*: evidence and score changed consistently, re-anchored | 0 | COMPLETE | none (expected; consistent forgery is out of scope) |
| 7 | **probe**: admitted=True **and** non-null code in both evidence and score | 0 | COMPLETE | none; `rejection_reason=NOT_APPLICABLE` (**N-1**) |
| 8 | probe: `admitted="true"` (string) in both sources | 0 | COMPLETE | none; `canonical_accepted=UNAVAILABLE`, reason `UNAVAILABLE` (conservative; pre-existing) |
| 9–10 | each receipt deleted | 2 | INCOMPLETE | `SOURCE_FILE_MISSING`, `V3_ARTIFACT_UNPINNED_OR_STALE`, `V3_DECLARED_HASH_MISMATCH` |
| 11–12 | each receipt +1 byte | 2 | INCOMPLETE | `SOURCE_PIN_STALE`, `V3_ARTIFACT_UNPINNED_OR_STALE`, `V3_DECLARED_HASH_MISMATCH` |
| 13–14 | each receipt replaced with secret-marker JSON, pins re-anchored | 2 | INCOMPLETE | `V3_DECLARED_HASH_MISMATCH`; marker absent from index |
| 15–16 | each archive-listed receipt hash set to zeros, re-pinned | 2 | INCOMPLETE | `V3_DECLARED_HASH_MISMATCH` |
| 17–18 | each receipt pin removed | 2 | INCOMPLETE | `V3_ARTIFACT_UNPINNED_OR_STALE` |
| 19 | *trust-anchor limit*: receipt, archive hash and pins all re-anchored | 0 | COMPLETE | none (expected) |
| 20–24, 26 | receipt archive path → `../outside.txt`, `../../../../outside.txt`, `..\..\outside.txt`, POSIX-absolute, `C:\…` absolute, `assurance/../../outside.txt` | 2 | INCOMPLETE | `UNJOINABLE_REFERENCE`; 28 records retained; no outside content or path in output |
| 25 | receipt archive path → `//host/share/x.txt` | 2 | INCOMPLETE | `V3_ARTIFACT_UNPINNED_OR_STALE` (informational, see below) |
| 27 | extra in-root archive entry not declared by the adapter | 2 | INCOMPLETE | `V3_ARTIFACT_UNPINNED_OR_STALE`; content absent |
| 28 | receipt path replaced by a directory | 2 | INCOMPLETE | `SOURCE_FILE_MISSING`, `…UNPINNED_OR_STALE`, `V3_DECLARED_HASH_MISMATCH` |
| 29 | `http-v3-01-4b/` replaced by an NTFS junction outside the root | 2 | INCOMPLETE | `UNJOINABLE_REFERENCE`, `V3_EVIDENCE_INVALID`, `V3_JOIN_KEYS_MISMATCH`, `V3_RECORD_COUNT_MISMATCH` |
| 30 | real archive declared NATIVE | 0 | COMPLETE | none; 28 NATIVE PARTIAL, 0 eligible |

Result: 30/31 scenarios matched the reviewer's prior expectation. The one exception, #25, is
**not a defect**. `Context.path` prefixes `spec.path` (`.`), so `//host/share/x.txt` becomes `.///host/share/x.txt`. That resolves
to an in-root relative path, which `Resolver.resolve` contains. No UNC or network access is attempted, and
the entry fails closed as unpinned. The reviewer's expectation of `UNJOINABLE_REFERENCE` was too strict.

### 3b. Source-mutation kill test (`work/srcmut.py`, output `work/srcmut.out`)
Each mutant is one edit to a copy of the candidate. The focused suite ran with `TRACE_EVAL_V3_ROOT` bound to the extracted evidence.

| Mutant | Focused result | Killed? |
|---|---|---|
| M1 drop `admission_code` from the score join (revert P3-1) | 3 failed / 42 passed | ✅ |
| M2 skip non-evidence entries (revert P3-2) | 13 failed | ✅ |
| M3 parse non-evidence content (`parse=True`) | 12 failed | ✅ |
| M4 copy `rejection_reason` verbatim for admitted rows (revert P3-3) | 2 failed | ✅ |
| M5 remove the V3 source-kind safeguard | 1 failed | ✅ |
| M6 remove seeded span/prompt warnings only | 1 failed (committed-index reproduction); **0 eligible**, so the safeguard holds | ✅ |
| M7 remove warnings **and** the safeguard | 8 failed | ✅ |
| M8 drop the listed-hash check for `archive_file` (pin-only) | 9 failed | ✅ |

---

## 4. Index and preservation hashes

| Artifact | Expected | Recomputed (`hashlib`/`sha256sum`) | Sidecar | Rebuild |
|---|---|---|---|---|
| `index/orchestrator-v3-index.json` | `2cf95c0685b314c0ed1122fd4d37ca652046a4b3c2a69156eca42c2b52190fd1` | ✅ identical | ✅ | `build --root evidence=<main checkout>` and `=<extracted copy>` → `COMPLETE records=28 findings=56`, **byte-identical** (`cmp`). `verify` → `REPRODUCED`, exit 0 |
| `index/representative-index.json` | `185013d018ca892a6a2b9f1cc1032315aaf8634189ccc944035f6d45ef7c2afc` | ✅ identical; also byte-identical to `af78ad3` | ✅ | `build` with explicit `main_dev_candidates=<main>/development-candidates` and `codex_audit=<profile-a-synthetic-isolation>/…/guardrails-traces-evals-coverage` → `COMPLETE records=159 findings=1`, **byte-identical**. `verify` → `REPRODUCED`, exit 0 |
| `schema/trace-eval-index-1.0.schema.json` | unchanged | `schema --out` regenerates **byte-identical** | n/a | n/a |

**Preservation of 251 scoped files** (`work/preserve.py`, output `work/preserve.out`). The reviewer re-hashed every entry of
`v3-remediation-preservation-before.json` against the live roots:

| Scope | Entries | Live vs snapshot | Independent anchor |
|---|---|---|---|
| `candidate:` | 22 | 22/22 match | 21/22 equal the `af78ad3` blobs. The remaining one is `reports/V3_INDEPENDENT_QUALITY_GATE.md` (untracked, `b5b52a1b…`), which equals the original reviewer's copy. |
| `evidence:` | 86 | 86/86 match | **86/86 equal the `git show HEAD:` blobs of the main checkout `a2fdd55`** |
| `main_dev_candidates:` | 142 | 142/142 match | No Git anchor (untracked in the main checkout). Indirectly supported by the byte-identical representative rebuild. |
| `codex_audit:` | 1 | 1/1 match | n/a |
| **Total** | **251** | **251/251** | |

The main checkout's V3 evidence paths are clean: `git diff --quiet HEAD` passed, and there are 0 tracked or untracked changes.
`IS4000_finAI-trace-eval` (`7a03599`) and `IS4000_finAI-trace-eval-integration` (`6a0b66e`) are clean and untouched.

---

## 5. Tests, lint and typing

All of these ran from the isolated `candidate/` copy with `PYTHONPATH=src`.

| Command | Result | Matches author claim |
|---|---|---|
| `pytest tests/test_orchestrator_v3.py` with `TRACE_EVAL_V3_ROOT=<main checkout>` | **45 PASS** | ✅ 45 |
| same with `TRACE_EVAL_V3_ROOT=<extracted copy>` | **45 PASS** | ✅ |
| `pytest tests -rs` with the root bound (main checkout / extracted copy) | **128 PASS, 2 SKIP** | ✅ 128/2 |
| `pytest tests -rs` with **no** `TRACE_EVAL_V3_ROOT` | **123 PASS, 5 FAIL, 2 SKIP** | n/a (documented behaviour; see N-2) |
| `ruff check --no-cache src tests` | PASS | ✅ |
| `ruff format --check src tests` | PASS (17 files) | ✅ |
| `mypy --no-incremental src tests` (strict + pydantic plugin) | PASS (17 files); `src` alone PASS (8) | ✅ |

**PASS vs SKIP vs UNAVAILABLE.** The 2 SKIPs are `test_historical_evidence.py:45` and `:74`
(`UNAVAILABLE: historical evidence roots not present`). They are **not counted as passes**. The equivalent assertion was
covered by the explicit-root CLI `verify … REPRODUCED 185013…` (a CLI run, not a pytest pass). The 5 no-env
FAILs are the env-gated real-archive tests: `test_actual_28_record_archive`, `test_committed_v3_index_reproduces`
and 3 × `test_actual_archive_corruption_in_temporary_copy`. Each one fails with `UNAVAILABLE: required verification needs explicit TRACE_EVAL_V3_ROOT`.

The author's recorded logs (`v3-remediation-*.txt`) agree with every reproduced figure.

---

## 6. Boundaries

| Requirement | Status |
|---|---|
| P3-7 (historical pytest portability) explicitly deferred | ✅ README, handoff and remediation report. `test_historical_evidence.py` and the representative manifests are unchanged. |
| P3-8 (adapter version, record-ID format) explicitly deferred | ✅ `ADAPTER_VERSION`/pyproject stay `1.0.0`. Record-ID construction is unchanged. Consumers are told to use the identity fields. |
| No schema or contract change | ✅ `schema.py` is byte-unchanged and the JSON Schema regenerates identical. `schema_version` is still `trace-eval-index/1.0`. The only manifest-side change is additional `files`/`pins` entries. |
| No application or execution contract change | ✅ nothing outside the adapter directory changed |
| No new evaluator, scoring authority or performance claim | ✅ copy-only. `rejection_reason` maps the admitted case to `NOT_APPLICABLE` and does not rescore. No admission or scoring code is imported. Eligibility is only tightened. |
| No historical evidence modified | ✅ §4 |
| No provider inference, cloud call or upload | ✅ none were needed or made. `src/` has no `socket`/`urllib`/`httpx`/`requests`/`langsmith`/`langchain`/`openai`/`subprocess` imports (`requests_dir` is a manifest key). |
| Privacy | ✅ non-evidence content is never parsed. Secret and outside-content markers were absent from every index produced. No absolute paths in output. No credentials in the new reports, README or handoff (grep). |

---

## 7. Residual original findings

| Finding | Status |
|---|---|
| P3-1 to P3-6 | Closed (§2) |
| P3-7 historical test portability | **Open, deferred by owner decision.** The tests still SKIP outside the original location. |
| P3-8 version and record-ID grammar | **Open, deferred by owner decision.** |
| Original §8 risks (remote freshness, file-symlink escape, self-reported usage, time-of-check gap, trust anchor) | Unchanged. Not re-certified by the author. The reviewer re-verified the junction escape only (§3a #29). |

## 8. New findings from this gate

No new **P0**, **P1** or **P2** findings.

### N-1 (P3): an admitted row's contradictory `admission_code` is masked as `NOT_APPLICABLE` with no finding
- **Ref:** `orchestrator_v3.py:335` (`rejection_reason=NA if row.get("admitted") is True else …`). There is no consistency check between `admitted` and `admission_code`.
- **Repro:** §3a #7. Set `admitted=true` and `admission_code="FORBIDDEN_CAPABILITY"` consistently in both the evidence and `cases.json`, then re-anchor. The result is `COMPLETE`, exit 0, `rejection_reason=NOT_APPLICABLE` and no issue.
- **Impact:** a regression introduced by P3-3. Before the remediation, the contradictory code was at least visible in the index. Now an internally contradictory archive is reported as a clean admission. **The real archive is unaffected**: all 3 admitted rows have `admission_code=null` (reconstruction). Exploiting this needs a consistent forgery of two files plus pins, which is already outside the trust model. Hence P3.
- **Test gap:** `test_rejection_reason_semantics` covers `(True, None)` but not `(True, <code>)`.
- **Suggested remedy (not applied):** when `admitted is True` and `admission_code` is not `None`, add a record issue (for example `V3_ADMITTED_WITH_REJECTION_CODE`, ERROR or WARNING by owner choice). Also add the `(True, "FORBIDDEN_CAPABILITY")` test case. On the real archive this would not change the index bytes.

### N-2 (P3): the default suite is now red without `TRACE_EVAL_V3_ROOT`
- **Ref:** `tests/test_orchestrator_v3.py:337-341` (`pytest.fail("UNAVAILABLE: …")`).
- **Observed:** with no environment variable, the result is 123 PASS, 5 FAIL, 2 SKIP. At `af78ad3` it was 104 PASS, 3 SKIP.
- **Impact:** this is deliberate and documented (README and handoff: missing access fails as `UNAVAILABLE` and is not counted as success). It does give the suite two different policies for missing evidence: V3 tests FAIL, while historical tests SKIP. Any fresh clone, or any future CI job that runs the adapter suite, will be red unless the root is bound. The repository currently has no CI workflow that runs this suite, so nothing breaks today.
- **Remedy:** an owner decision, made together with P3-7. Either keep fail-closed and document the required environment in any CI job, or make both kinds of evidence-gated test behave the same way.

### Informational (no finding)
- §3a #25: a `//host/share` style archive path resolves inside the root and fails closed as unpinned. Safe.
- §3a #8: a non-boolean `admitted` yields `UNAVAILABLE` fields with no finding. This is conservative and pre-existing (not introduced by the remediation).
- P3-4 is closed by documentation only. A consumer that reads the index without the README must rely on `source.kind == orchestrator_eval_v3` and the `V3_SPANS_UNAVAILABLE` issue to tell a label from a trace ID. This was the remedy the original gate accepted. A `trace_id_kind` field stays a candidate for the next schema revision.

---

## 9. Integration readiness

- **Correctness:** the six approved remediations are correct and tested, and each one is mutation-killed. Eligibility is strictly tighter.
  The committed V3 index (`2cf95c06…`) reproduces byte-for-byte from two independent evidence roots. The representative index
  (`185013d0…`) is unchanged and still reproduces.
- **Before commit (owner's choice):** consider fixing N-1. It is small and local, and it does not change the real-archive index bytes.
  Decide N-2 together with P3-7. Decide whether to commit the untracked `reports/` evidence files alongside the code.
- **Route (unchanged from the original gate):** commit and integrate only from a fresh, clean worktree cut from freshly fetched
  `origin/main`. After any rebase, re-run `build`/`verify` and confirm `2cf95c06…`. Any change that alters the index bytes needs another independent recheck.
- **Not authorized here:** commit, push, PR, merge or integration. Owner review is still required. This gate does not accept engineering.

## 10. Limitations and unavailable checks

| Item | Status |
|---|---|
| Remote freshness of `origin/main` | **UNVERIFIED** (no fetch, by restriction) |
| File-symlink escape | **UNVERIFIED** by execution (not attempted; junction escape verified instead) |
| Historical-source pytest tests | **SKIP / UNAVAILABLE**; covered only by CLI `verify` |
| 142 `main_dev_candidates` preservation entries | Checked only against the author's snapshot and indirectly by the representative rebuild. There is no independent Git anchor because the directory is untracked in the main checkout. |
| Timing of the "before" preservation snapshot | Cannot be proven independently. Its candidate and evidence entries do equal the committed Git blobs. |
| Toolchain independence | The reviewer used the same `backend/.venv` interpreter and tool versions as the author |
| Token, latency and usage values | Still self-reported by the harness (`token_usage_verified=UNAVAILABLE`). Not re-audited. |
| Main checkout | On the C2.2 branch with unrelated uncommitted work. Read only through `git archive`/`git show`/hashing. Not modified. |

---

**Return: `V3_REMEDIATION_QG_PASS_READY_FOR_OWNER_REVIEW`**
