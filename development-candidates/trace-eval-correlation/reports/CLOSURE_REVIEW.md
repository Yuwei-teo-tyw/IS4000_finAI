# Closure review: Trace–Eval Correlation Adapter

Reviewer: a fresh, independent closure reviewer. I authored none of the adapter, its fixes or
the earlier reviews. Date: 2026-10-27.

Mode: read-only. This file is the only file I wrote deliberately in the worktree. One side
effect is disclosed under P3-4: my gate run created ignored bytecode in `src/`.
- Probes ran on copies of the evidence in my session scratchpad.
- The independent cross-check script reads the real evidence and never writes to it.
- I made no git state changes and used no network, provider or model.

## Scope

1. Code changed after attempt 2. I read the final `correlate.py` and `cli.py` in full, plus
   `sources.py`, `privacy.py` and the `test_attempt2_*` tests in
   `tests/test_review_regressions.py`. The changes:
   - `ARTIFACT_UNANCHORED`
   - `DATASET_FREEZE_UNREADABLE`
   - the rename to `TRACE_SPAN_STATUS_UNAVAILABLE`
   - the simplified `NOT_RUN_CONFLICT` condition
   - a `pin` path escape now raises a usage error
   - empty-sidecar handling
   - README "External evidence dependency", FINAL_REPORT §8 and `.gitignore`
2. Whether attempt-2's P2 is closed (pins but no campaign manifest).
3. Whether the attempt-1 P1/P2 fixes still hold.
4. Integrity of all 159 records and the 36 native joins. I checked them with my own script,
   which does not import the adapter.
5. Reproducibility, plus pin drift for all 34 pins and the reference.
6. Redaction and accidental inclusion across every commit candidate.
7. Honest documentation of the unpackaged evidence, and an isolated test run.
8. That the adapter gains no new authority and imports no network or provider code.

## Commands and results

Interpreter: main checkout `backend/.venv` (Python 3.12.10), run from this directory with
`PYTHONPATH=src` and `PYTHONDONTWRITEBYTECODE=1`.

| Check | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider` | **85 passed** |
| `ruff check src tests` | All checks passed |
| `ruff format --check src tests` | 15 files already formatted |
| `mypy --strict src/trace_eval_correlation` | Success, no issues in 7 source files |
| `python -m trace_eval_correlation verify --manifest manifests/representative.json --index index/representative-index.json` | **REPRODUCED** `185013d018ca892a6a2b9f1cc1032315aaf8634189ccc944035f6d45ef7c2afc`, exit 0. The sidecar matches, and `sha256sum` of the index equals the sidecar. This is the same sha that attempt 2 reviewed. |
| `schema --out <scratch>` then `cmp` with `schema/trace-eval-index-1.0.schema.json` | identical |
| `build` with `--root` set to a scratch copy of the evidence, then `cmp` with the committed index | **byte-identical** (COMPLETE, 159 records, 1 INFO finding), so no absolute path enters the output |
| Independent cross-check `xcheck.py` (my own script, reading the real evidence) | **0 real discrepancies**; details below |
| Isolated copy of `src/ tests/ manifests/ index/ pyproject.toml`, where the relative roots do not resolve: `pytest -rs` | **83 passed, 2 skipped**. Skip reason: `UNAVAILABLE: historical evidence roots not present` |
| Same isolated copy: `verify` / `build` | `NOT_REPRODUCED`, exit 1 / `INCOMPLETE`, exit 2. Findings: `REFERENCE_MISSING_FILE` and three `SOURCE_UNAVAILABLE` (root-relative text only). No absolute path in the output. |
| Main checkout at start and end | branch `feat/agent-lab-c22-hybrid-orchestrator` @ `a2fdd55`; `git diff \| sha256sum` = `8b9b6920…c8f`; `git status --porcelain \| sha256sum` = `c17cf354…2ec429`. **Both match preflight at start and end.** |
| Worktree `git status --porcelain` | `?? development-candidates/` only, so no tracked file changed |
| Codex audit sha256 | `bc590650…e2ea9`, equal to the manifest reference |

### Independent cross-check

The script re-derives each value from the raw files.

**Native records:**
- **Counts:** 159 records: 87 OFFLINE_TEST, 36 NATIVE (24 V9.3 + 12 PAIR), 1
  NON_NATIVE_PREFLIGHT and 35 NOT_RUN. Exactly 36 records have
  `model_performance_evidence=true`.
- **Observation row:** each native record's row hash (compact sorted JSON) and `#row=` index
  match.
- **Copied fields:** arm, conversation, turn, stage, role, status and dispatch match the row.
- **Receipt:** each native record has a receipt directory with
  `request_id`/`case_id`/`role`/`stage` equal to the row.
- **Hashes:** `sha256(request.json)` equals the receipt's `request_sha256`, which equals the
  LLM START span's `request_sha256`. `sha256(public-output.txt)` equals the receipt's
  `public_output_sha256`.
- **Campaign manifest:** all three per-request files are listed with the same hash.
- **Spans:** the LLM span is unique per request and `llm_span_id` equals the receipt's. Its
  parent is the AGENT span of the same case, and the root is a SESSION span. The span ids and
  END statuses equal the index values.
- **Copied values:** usage, cost and `model_call` fields equal the receipt.
- **Score:** exactly one score row, with keys equal to the observation.
- **Assessment:** `observation_sha256` matches the canonical row hash. Status, reviewer and
  independence match, and the fingerprint flag agrees with the summary.
- **Prompts:**
  - The prompt is the longest embedded candidate in each request: V9.3 A = clarifier-v92 /
    orchestrator-v91; V9.3 B = v93 / v93; PAIR A = clarifier-v93; PAIR B = clarifier-v942;
    6 each.
  - `response_format` hashes match.
- **Freeze:** the freeze-manifest hash matches, and 8/8 frozen dataset files verify in both
  campaigns.

**Source-level and other records:**
- **Cross-checks:** cost sums are exact: 0.01210965 and 0.00873900. Native attempts are 24 and
  12. Planned rows are 24 and 48, which equals observations plus NOT_RUN rows.
- **Receipts:** no orphan receipts.
- **NOT_RUN:** the 35 rows match `not-run.json` in order: case, arm, dataset case, row hash,
  and the role from `scope.json`.
- **Preflight:** one AGENT span and no LLM span.
- **JUnit:** 87 testcases, all PASSED, equal to the suite `tests` count. Every node is
  present, and `tests-final.xml` is listed under `A/` in the campaign manifest.
- **Pins:** all 34 pins (15 + 17 + 2) equal the current bytes, so there is no drift. Every
  pinned file other than the campaign manifest itself is also listed, with the same hash, in
  the campaign's own evidence manifest.
- **The one flagged item is an error in my own script.** PAIR preflight `B:fresh04-t1` has
  raw `agent_success: null`, and the index correctly reports `UNAVAILABLE`, not an invented
  false.

### Probes (scratch copies of the real evidence; manifests rewritten only in scratch)

| # | Probe | Result |
|---|---|---|
| A2-P2 | V9.3 with `evidence_manifest=None` and its pin dropped (the other 14 pins kept). Edit one `receipt.json` so `input_tokens` = 999999 (was 964). | `COMPLETE` (warnings only). The edited record is `PARTIAL`, `model_performance_evidence=false`, issues `["ARTIFACT_UNANCHORED"]`. All 24 V9.3 natives are unanchored and none is eligible. **Closed.** |
| A2-P2 control | Same, without the edit | The same 24 PARTIAL. The demotion is structural, not caused by the edit. |
| Variant | Campaign manifest declared but **no pins**. Edit the receipt **and** rewrite its entry in the campaign manifest. | `COMPLETE`, record `JOINED`, `model_performance_evidence=true`, with 999999 reported. See P3-1. |
| A1 P1 | Delete the pinned freeze manifest; separately, delete the rubric | `SOURCE_FILE_MISSING` ERROR, INCOMPLETE, `SOURCE_INTEGRITY_GAP` on every V9.3 record, 0 eligible. Deleting the rubric also gives `DATASET_FREEZE_MISMATCH` and `CROSSCHECK_MISMATCH`, because the rubric is a frozen file. **Holds.** |
| A1 P2-1 | Edit an unused prompt candidate; separately, a stale pin on the bound prompt | `SOURCE_HASH_MISMATCH` + `SOURCE_PIN_STALE`, or `SOURCE_PIN_STALE` alone. INCOMPLETE, 0 eligible. **Holds.** |
| A1 P2-2 | Stale trace pin on PAIR | `SOURCE_INTEGRITY_GAP` on every non-NOT_RUN PAIR record, 0 eligible. **Holds.** |
| A1 P2-3 | Append a duplicate NOT_RUN row, a NOT_RUN row for observed `A:fresh01-t1`, and a row with a `null` case | Record ids unique, no `DUPLICATE_RECORD_ID`, 2× `DUPLICATE_CASE_ID`. `…/A:fresh01-t1#2` has `NOT_RUN_CONFLICT`; `…/not-run-37` has `MISSING_CASE_ID`. **Holds** with the simplified condition. |
| A1 P2-4 | Summary `status` = an email, `campaign` = `Bearer sk-…`, fingerprint = `ghp_…` | No sentinel appears in the rendered index. `campaign_status` = `REDACTED`, and a `PRIVACY_REDACTED` WARNING is raised. **Holds.** |
| A2 P3-1 | PAIR freeze manifest is malformed JSON | `DATASET_FREEZE_UNREADABLE` ERROR (plus hash and pin errors), 0 eligible. **Closed.** |
| A2 P3-3 | END event for a bound LLM span with `"status": null` | Record issue `TRACE_SPAN_STATUS_UNAVAILABLE`, PARTIAL, not eligible. **Closed** (name is now accurate). |
| A2 P3-2 | `pin` with candidate `../../escape.txt` | exit 64, `usage error: cannot pin v93-paired-1:../../escape.txt: REFERENCE_ESCAPES_ROOT`, no traceback. **Closed.** |
| A2 P3-2 | `verify` with an empty sidecar | `NOT_REPRODUCED recorded=UNAVAILABLE`, exit 1. **Closed.** |
| CLI | `verify` when the sidecar is non-UTF-8, or is a directory | **Uncaught `UnicodeDecodeError` / `PermissionError`.** See P3-3. |
| CLI | `build` or `pin` with output inside a bound root | exit 64 `refusing to write inside a bound evidence root`. Nothing written. |
| CLI | Manifest with a JSON syntax error | exit 64 `manifest invalid at:` (empty location, already accepted as cosmetic) |

## Findings

### P0: none. P1: none. P2: none.

### P3-1: An unpinned campaign manifest leaves its anchor unverified, with no warning
- **Where:** `src/trace_eval_correlation/correlate.py:1361-1362`. `SOURCE_UNPINNED` fires only
  when there is *neither* a campaign manifest *nor* pins. `ARTIFACT_UNANCHORED`
  (`correlate.py:612`) fires only when `ctx.listed is None`.
- **Scenario:** a source declares `evidence_manifest` but has `pins: {}`. Editing
  `receipt.json` and the matching line of the campaign manifest yields `COMPLETE`, `JOINED`
  and `model_performance_evidence=true`, with the edited token count (probe "Variant").
- **Not affected:** the shipped index. All three campaign manifests are pinned and verified.
- **Already disclosed in part:** the trust model is stated in general terms in FINAL_REPORT §6
  ("campaign manifests themselves are trusted as of pinning").
- **Severity:** I rate this P3 because it is a consistent two-file tamper against an
  explicitly trusted anchor. The owner may weigh it higher. It is the same family as the
  closed attempt-2 P2.
- **Fix:** add a WARNING, such as `CAMPAIGN_MANIFEST_UNPINNED`, to `SOURCE_GAP_WARNINGS` when
  `evidence_manifest` is declared but absent from `pins`. Or state in the README that an
  unpinned campaign manifest is trusted as-is.

### P3-2: The README does not describe the new `ARTIFACT_UNANCHORED` rule
- **Where:** `README.md:50-57`.
- **What is stated:** only the "neither campaign manifest nor pins" case.
- **What is missing:** a pinned source without a campaign manifest now makes every native
  record PARTIAL. It therefore *never* yields model-performance evidence, because `pin`
  excludes `requests_dir` (`cli.py:84`).
- **Where it is mentioned:** only in QUALITY_GATE.md.
- **Fix:** add one sentence to the README contract paragraph.

### P3-3: `verify` still crashes on an unreadable sidecar
- **Where:** `cli.py:158`. `sidecar.read_text(encoding="utf-8")` is unguarded.
- **Scenario:**
  - a sidecar with non-UTF-8 bytes raises `UnicodeDecodeError`;
  - a sidecar path that is a directory raises `PermissionError` on Windows (`IsADirectoryError`
    on POSIX).
  - Both print a traceback instead of `NOT_REPRODUCED`.
- **Partly closed already:** the attempt-2 P3-2 empty-sidecar case is fixed. This is the
  remainder.
- **Fix:** wrap the read in `except (OSError, UnicodeDecodeError)` and treat it as
  `recorded=None`.

### P3-4: The test suite writes bytecode into `src/` despite `PYTHONDONTWRITEBYTECODE`
- **Where:** `tests/test_reproducibility.py:117-118`. The subprocess runs `sys.executable -I`,
  and `-I` ignores `PYTHON*` variables, so it writes
  `src/trace_eval_correlation/__pycache__/*.pyc`.
- **Confirmed** in the isolated copy.
- **Disclosure:** my gate run created six `.pyc` files in that directory (timestamp
  11:53:50). They are covered by `.gitignore` and appear in the ignored listing, not the
  commit listing. I left them in place; the owner may delete them.
- **Fix:** pass `-B` as well as `-I`.

### P3-5: Free text enters the index through JUnit node ids
- **Where:** `correlate.py:1198`, through `test_node_id`, `record_id` and the artifact `ref`.
- **Scenario:** 7 of the 87 V9.4.3 node ids carry parametrised sentences. Two of them are
  canned assistant-style replies, e.g. in
  `test_truthful_outside_scope_continuation_without_state_mutation[...]`.
- **Risk:** these are synthetic test parameters from the historical test source, not human
  input or model output, and are not sensitive. No credential or identifier pattern matched.
- **Why it matters:** CHECKPOINT.md:37 ("Never copy free text") and README.md:59-60 overstate
  the guarantee.
- **Fix:** either qualify the docs ("pytest node ids, including parametrisation text, are
  copied verbatim"), or replace the bracketed parameter suffix with a short hash.

### P3-6: Local path metadata in the committed docs
**Harmless local instructions** (functional, relative, no username):
- `manifests/representative.json:4-5` and `representative.unpinned.json:4-5` hold the relative
  roots.
  - The `codex_audit` root climbs 9 levels to the home directory and names
    `.codex-clean2/worktrees/profile-a-synthetic-isolation/...`.
  - This reveals the machine's directory layout, but `--root` exists to rebind it.
- `CHECKPOINT.md:22-23` uses relative `../../../IS4000_finAI/backend/.venv` paths.

**Unnecessary but low-risk private metadata:**
- `FINAL_REPORT.md:13` gives the full absolute worktree path, with the Windows username and
  personal folder hierarchy (`C:\Users\shane\Desktop\SMU\Y4S1\…`). The author says the
  assignment required it.
- `reports/INDEPENDENT_REVIEW_attempt2.md:25` says "9 levels up gives `C:/Users/shane`".
- `reports/INDEPENDENT_REVIEW_attempt1.md:70,231` uses `Users/shane` as a negative claim and
  as a redaction-probe input.
- None of these is a credential or an email address. The git author name already discloses a
  similar handle.
- **Fix (optional):** replace them with `<home>/…/IS4000_finAI-trace-eval`. The review
  reports are verbatim records, so leaving them is acceptable.

### P3-7: The docs say no third review took place
- **Where:** `QUALITY_GATE.md:62`, `FINAL_REPORT.md:134-135` and `CHECKPOINT.md:31` say the
  attempt-2 fixes were not given a third review.
- **Fix:** after this closure review, reference this file instead.

### Carried forward, still accepted
- `manifest invalid at:` with an empty location for JSON syntax errors.
- Pattern-based redaction. It does not detect absolute paths or names, and
  `evaluator_identity` (`/root/…`) is copied verbatim. Both are disclosed in FINAL_REPORT §6.
- A preflight row in a synthetic source keeps its class.
- An undeclared rubric or scoring spec is reported as `UNAVAILABLE`.

### Checked and found clean
- **Codes:** `NOT_RUN_CONFLICT` now compares only against observed case ids (`correlate.py:814`).
  `DATASET_FREEZE_UNREADABLE` does not double-report a missing file
  (`correlate.py:484`, already `SOURCE_FILE_MISSING`).
- **Source errors reach records:** source-level errors raised in `_native_summary` are recorded
  before the gap computation (`correlate.py:1368-1372`), so they do reach the records.
- **No authority:**
  - imports are stdlib plus pydantic only, with no network, provider, LangSmith or
    `advisory_agents` import;
  - writes are limited to the CLI output paths, which are refused inside bound roots;
  - there is no scoring, admission, replay or upload path, and scores and assessments are
    copied, never computed.
- **Socket and subprocess in tests:** `socket` is used only to *block* network calls, and the
  one subprocess is a fixed-argument import probe.
- **Redaction sweep** over all 41 commit candidates:
  - **Emails:** only `pat@example.com` and `a@b.co` sentinels, in tests and review text.
  - **Credential shapes:** only synthetic sentinels in tests and reviews. The `ghs_correction`
    hits in the index are substrings of a pytest node id, not tokens.
  - **Machine details:** no machine hostname, no user email and no `.env` reference.
  - **Index contents:** no provider account metadata. The receipt `metadata` key is not copied.
  - **Index paths:** the index contains no absolute path.

## Files: commit versus exclude

**Safe to commit**: the 41 files `git ls-files --others --exclude-standard` lists under this
directory, subject to the optional P3 edits:
- `.gitignore`, `README.md`, `FINAL_REPORT.md` (see P3-6), `CHECKPOINT.md`, `QUALITY_GATE.md`,
  `GUARDRAIL_COVERAGE.md`, `pyproject.toml`
- `src/trace_eval_correlation/{__init__,__main__,cli,correlate,privacy,schema,sources}.py`
- `tests/{conftest,test_campaign_states,test_correlation,test_historical_evidence,test_integrity,test_privacy_classes,test_reproducibility,test_review_regressions}.py`
- `schema/trace-eval-index-1.0.schema.json`
- `manifests/representative.json` and `manifests/representative.unpinned.json`
- `index/representative-index.json` and `index/representative-index.json.sha256`
- `reports/INDEPENDENT_REVIEW_attempt1.md`, `reports/INDEPENDENT_REVIEW_attempt2.md`,
  `reports/gate{1,2,3}-{mypy,pytest,ruff,verify}.txt`
- `reports/CLOSURE_REVIEW.md` (this file)

**Exclude** (`.gitignore` already does this, as verified with
`git ls-files --others --ignored --exclude-standard`):
- `reports/*.xml`: 7 JUnit files that embed the hostname
- `src/trace_eval_correlation/__pycache__/` and any `.pytest_cache/`, `.ruff_cache/` or
  `.mypy_cache/`

## Verdict

**PASS.** No P0, P1 or P2 findings are open.
- **Attempt-2 P2:** closed. I reproduced the probe on a copy of the real V9.3 evidence: an
  edited receipt in a pinned source without a campaign manifest now yields `PARTIAL`, flagged
  `ARTIFACT_UNANCHORED`, and is no longer model-performance evidence.
- **Earlier fixes:** every attempt-1 P1/P2 fix and every fixed attempt-2 P3 holds.
- **Index:** the shipped index reproduces byte for byte. It matches the raw evidence on all
  159 records and 36 native joins, and no pin has drifted.
- **Main checkout:** unchanged.
- **Remaining:** seven P3 items. They are minor, none affects the shipped index, and they can
  be fixed after commit at the owner's discretion.
