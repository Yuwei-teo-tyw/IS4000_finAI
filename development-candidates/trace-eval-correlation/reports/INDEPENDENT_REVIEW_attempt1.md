# Independent review: Trace–Eval Correlation Adapter (attempt 1)

Reviewer: fresh, independent agent (did not author the code). Date: 2026-10-27.
Mode: read-only. The only file written in the worktree is this report. The probes ran on
synthetic copies in the reviewer's scratchpad temp directory and never on real evidence.

## Scope reviewed

- `src/trace_eval_correlation/{schema,sources,privacy,correlate,cli,__main__,__init__}.py`, read in full.
- `tests/` (conftest plus 6 modules, 67 tests), read in full.
- `manifests/representative.json` (+ `.unpinned.json`), `index/representative-index.json` (+ `.sha256`),
  `schema/trace-eval-index-1.0.schema.json`, `README.md`, `GUARDRAIL_COVERAGE.md`, `reports/gate1-*`.
- The raw evidence it consumes, read-only: `IS4000_finAI/development-candidates/{v9.3-readiness,
  v9.4.2-v9.3b-paired-readiness, v9.4.3-offline}`.
- The requirements origin `GUARDRAILS_TRACES_EVALS_COVERAGE.md` (Codex audit), read in full.
- The canonical lab at `a2fdd55` in this worktree (`backend/src/advisory_agents`), read only for the
  lines that GUARDRAIL_COVERAGE.md cites.

## Commands run and results

| Command | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider` (PYTHONPATH=src) | **67 passed** |
| `ruff check src tests --no-cache` | **All checks passed** |
| `mypy --strict src/trace_eval_correlation` | **Success: no issues found in 7 source files** |
| `python -m trace_eval_correlation verify --manifest manifests/representative.json --index index/representative-index.json` | **REPRODUCED** sha256=663dac01…6f42, exit 0 |
| `build` to scratchpad path, then `cmp` with the committed index | byte-identical, `COMPLETE records=159 findings=1` |
| `schema --out <scratchpad>` then `cmp` with the committed schema | identical |
| Main checkout `git diff \| sha256sum` / `git status --porcelain \| sha256sum` (start and end) | `8b9b6920…c8f` / `c17cf354…2ec429`, both match preflight. Branch `feat/agent-lab-c22-hybrid-orchestrator` @ `a2fdd55` |
| Worktree `git status --porcelain`, `git rev-parse HEAD` | only `?? development-candidates/`; HEAD `a2fdd558…`; branch `feat/trace-eval-correlation-offline`; `git diff --stat a2fdd55 -- backend` empty |
| Independent re-hash of all 34 manifest pins against the evidence files | 0 mismatches |
| sha256 of the Codex audit file | `bc590650…e2ea9`, matches the manifest reference |
| Independent cross-check script (my own join logic, not the adapter's) over all observations, receipts, request/public-output bytes, campaign manifests, spans, scores, assessments, NOT_RUN rows, JUnit | **0 discrepancies** (details in section 3) |
| 17 synthetic probes, each on a fresh temp copy of the test fixture | see findings |

I did not run a live test of the CLI write guard against a real evidence root: the environment's
permission classifier blocked that command. The guard is covered by
`test_cli_refuses_to_write_inside_evidence_and_unbound_roots`, and I reviewed its code (`cli.py:83-87`).

## Verification of the requested items

1. **Worktree isolation: verified.** The new code exists only under the new worktree's untracked
   `development-candidates/`. The worktree's `backend/` is identical to `a2fdd55`. The main checkout's
   diff and porcelain hashes match preflight at the start and at the end of the review.
2. **Evidence preservation: verified, with a gap (see P3-5).** The source code writes files only in
   `cli.py` (pin/build/schema). `build` and `pin` refuse output paths inside any bound root (Windows
   path comparison is case-insensitive). `schema` has no such guard. All 34 pins match the current
   files. The evidence roots are untracked in the main checkout, so git cannot detect changes there.
   Integrity rests on the pins and the campaign manifests.
3. **Referential integrity: verified for every record, not only a sample.** The count is 36 NATIVE
   (V9.3 24 = 12 clarifier + 12 orchestrator; PAIR 12). For each of them I checked: receipt dir =
   `request_id` = receipt `request_id`; sha256(request.json) = receipt `request_sha256` = LLM span
   `request_sha256`; sha256(public-output.txt) = receipt `public_output_sha256`; all three files listed
   with a matching hash in the campaign manifest; exactly one LLM span per request, with
   `span_id` = receipt `llm_span_id`; its parent is an AGENT span of the same case, whose parent is
   the SESSION root; `trace_id`, agent and LLM span ids and END statuses equal the index; tokens,
   cost, latency and model/provider/http/retries/fallback copied exactly; exactly one score row with
   `agent_success`/`canonical_state_success` copied; assessment `observation_sha256` = compact-sorted
   hash of the row, and its status copied. All 36 have `model_performance_evidence=true`. The single
   PAIR preflight row `B:fresh04-t1` has no request id, its own AGENT span, no LLM span and NA usage.
   There are 35 NOT_RUN rows and 87 OFFLINE_TEST JUnit nodes (suite `tests="87"`, 0 failed or skipped).
   Receipt directory sets equal the used request ids (no orphans). The cost sums are V9.3
   **0.01210965** and PAIR **0.00873900**, equal to the summaries. PAIR planned rows: 13 + 35 = 48.
4. **Missing values: mostly correct.** No fake zeros: non-string or unverified cost and unverified
   tokens become `UNAVAILABLE`, and preflight, NOT_RUN and offline records get `NOT_APPLICABLE`.
   `trace_id` is the SESSION root span id. That id is derived, not invented, and the README documents
   it. One arguable choice: a hash concept the campaign does not declare is reported as `UNAVAILABLE`
   rather than `NOT_APPLICABLE` (P3-9).
5. **Privacy: verified for the shipped index.** The index has no free text, no `key_remaining` or
   `spendable_credits`, no `C:/` or `Users/shane` paths, and no PRIVACY_REDACTED findings. Some gaps
   remain in the filter (P2-3, P3-8).
6. **No new authority: verified.** Scores, statuses and assessment verdicts are copied. The adapter
   computes only hashes, join verdicts, counts and the cost sum for cross-checks. It has no admission
   or ledger logic and imports nothing from `advisory_agents`.
7. **No network or provider calls: verified.** The only imports are stdlib and pydantic. A test
   confirms that httpx, requests, langsmith, openai, anthropic, urllib.request and http.client are
   absent from the imported modules, and that socket creation is refused during a build.
8. **Test evidence vs model performance: verified.** Only NATIVE + JOINED records are eligible.
   OFFLINE_TEST, NOT_RUN, preflight and SYNTHETIC_FIXTURE are never eligible. The fixtures declare
   `NATIVE` by default, so synthetic records report `model_performance_evidence=true` inside tests.
   This stays in memory and is never shipped. The class depends entirely on what the manifest
   declares (P3-6).
9. **Bugs and test categories:** see the findings below. All 12 categories are exercised. Category 4
   ("missing … hashes") is covered only through files read by `read_json`. A missing hashed-only or
   pinned file is not covered and is in fact silent (P1-1).
10. **GUARDRAIL_COVERAGE.md:** every cited line was checked at `a2fdd55`, and all are accurate:
    `contracts/__init__.py:25` (`Wire` with `extra="forbid", strict=True`), `:63-65`
    (missing/contradictions/readiness), `:99-101` (`PlanProposal.reason` max 500);
    `orchestrator/admission.py:5` `validate_plan`; `registry.py:20-22` (the comment "model output
    never supplies this endpoint authority"); `clarifier/app.py:124-149` (confirm checks revision and
    digest at :137); `telemetry.py:29` SAFE_FIELDS, `:66` SAFE_EVENTS, `:177-184` `record()` returns
    False with a warning; `orchestrator/graph.py:123-238` `dispatch_wave`. A grep found no
    reflection or critique step, which is consistent with NOT IMPLEMENTED. The "37 observed rows,
    NO_EXTERNAL_EFFECT" count is correct (36 native + 1 preflight). One wording issue is P3-10.

## Findings

### P0: none

### P1-1: Missing pinned or listed source files produce no finding. The index can be COMPLETE with records eligible after a consumed file is deleted.
- **Where:** `sources.py:72-74` returns `MISSING_FILE`. `correlate.py:209-214` (`Context.check`)
  raises findings only for `MISMATCH`, `NOT_LISTED` and `STALE`. `correlate.py:389-398` (`file_hash`)
  silently returns `UNAVAILABLE`. `correlate.py:451-459` (`_verify_dataset_freeze`) returns an
  UNAVAILABLE crosscheck with no finding.
- **Scenario (probe b2):** pin every consumed file, then delete `evaluation/freeze-manifest.json`.
  The build returns `index_status=COMPLETE` with no errors and no warnings. Records stay `JOINED`
  with `model_performance_evidence=true`. Only the summary's file entry shows `MISSING_FILE` /
  `MISSING_FILE`, and the `dataset_freeze_files` crosscheck is quietly `UNAVAILABLE`.
- **Scenario (probe b):** deleting a pinned `rubric.json` gives `rubric_sha256=UNAVAILABLE` and
  disables the `RUBRIC_HASH_MISMATCH` check (`correlate.py:619-624`). There is no rubric finding.
  The fixture went INCOMPLETE only because its freeze manifest happens to list the rubric.
- **Why it matters:** the audit's acceptance criteria include "source drift" and missing hashes, and
  the README says a later difference from a pin is STALE. Losing a frozen dataset or rubric is
  integrity loss that must make the index INCOMPLETE.
- **Fix:** in `Context.check`, emit `ERROR SOURCE_FILE_MISSING` when `actual is None`, and treat
  `pin == "MISSING_FILE"` as stale. Make `_verify_dataset_freeze` raise an ERROR when the freeze
  manifest is declared but unreadable. Add tests that delete a pinned hashed-only file.

### P2-1: Prompt-candidate pins are recorded but never verified.
- **Where:** `cli.py:72` adds `prompt_candidates` to the pins. `correlate.py:491-500`
  (`_prompt_binding`) reads the files without `ctx.check`, so the prompts never appear in
  `sources[].files` and their pins are never compared (the committed index lists no prompt files).
- **Scenario (probe a):** modify an unused candidate after pinning. The result is COMPLETE with no
  findings, and `verify` would still say REPRODUCED because that file's hash is not in the index.
  **Probe a2:** append whitespace to the *bound* prompt `p1.txt`. A fresh build is COMPLETE and
  JOINED, and it reports the *new* `prompt_sha256` with no STALE finding. Only the byte comparison
  with a previously committed index would catch it.
- **Why it matters:** README:49-50 says "Every consumed file is checked against the campaign's own
  evidence manifest and this manifest's pins". That is false for prompts, which are a key version
  anchor.
- **Fix:** run `ctx.check("prompt_candidate", candidate)` for each candidate, once per source, and
  append the results to `ctx.files`. Add a stale-prompt test.

### P2-2: `model_performance_evidence` ignores source-level integrity failures and unverified per-request hashes.
- **Where:** `correlate.py:1246-1260` derives eligibility only from the record's own `issues`.
  Source-level findings (`SOURCE_PIN_STALE`, `SOURCE_HASH_MISMATCH` on traces, scores or summary,
  `CAMPAIGN_MANIFEST_UNAVAILABLE`, `CROSSCHECK_MISMATCH`, `ORPHAN_RECEIPT`) and per-artifact
  `NOT_LISTED` warnings are never copied into the record's issues.
- **Scenarios:**
  - Probe c2: the traces file's pin is stale. The index is INCOMPLETE, but A:case-1 is `JOINED`
    with `mpe=true`, even though its span ids come from a file known to have changed.
  - Probe f: receipt.json, request.json and public-output.txt are removed from the campaign
    manifest. The index is COMPLETE (WARNING only) and the record is JOINED with `mpe=true`.
  - Probe n: the LLM span has no END (writer crash). The record is JOINED with `mpe=true` and
    `llm_span_status=UNAVAILABLE`.
- **Why it matters:** the README defines eligibility as "every join verified". A consumer that
  filters on `model_performance_evidence` without also checking `index_status` would count
  records whose evidence chain is stale or unanchored.
- **Fix:**
  - Propagate source-level ERRORs into each record of that source (for example a
    `SOURCE_INTEGRITY_FAILED` issue).
  - Add `ARTIFACT_NOT_LISTED` (and an unterminated-span issue) to the record's issues so the record
    becomes PARTIAL.
  - Alternatively, document and enforce that eligibility is valid only when `index_status=COMPLETE`.

### P2-3: Duplicate NOT_RUN rows, and NOT_RUN rows that collide with observed cases, emit duplicate `record_id`s.
- **Where:** `correlate.py:754-771` does not use the `seen_ids` counter and does not check for
  duplicates among the NOT_RUN rows.
- **Scenario (probe d):** two NOT_RUN rows for `A:case-3` give two records with the same id
  `synthetic-1/A:case-3`, no issue, and `index_status=COMPLETE`. A `planned_rows` mismatch would
  catch this only when `scope.json` is declared and holds unique ids.
- **Scenario (probe e):** a NOT_RUN row for an observed case is flagged `NOT_RUN_CONFLICT`, but its
  `record_id` equals the native record's id.
- **Why it matters:** the record id is the join key of a correlation index, and test category 2
  covers duplicate IDs.
- **Fix:** share `seen_ids` across observations and NOT_RUN rows, add `DUPLICATE_CASE_ID` (ERROR) for
  repeated NOT_RUN case ids, and assert that record ids are unique in `build_index`.

### P2-4: `SourceSummary` (and reference) fields are not privacy-filtered.
- **Where:** `correlate.py:1035-1080` copies `campaign_status`, `campaign_id` and crosscheck values
  verbatim from the summary. `privacy.scrub` runs only on records (`:1265`) and on findings
  (`:1357-1363`).
- **Scenario (probe l):** a summary status `"STOPPED by pat@example.com"` and a campaign
  `"camp Bearer sk-abcdefghijklmnop"` both appear in the rendered index. The finding copy of the
  status is redacted, but the summary copy is not.
- **Why it matters:** the README promises that the pattern filter covers surviving strings. The
  real data is clean, so this is a defence-in-depth gap.
- **Fix:** scrub each `SourceSummary` and `ReferenceSummary` dump, as `_finalise` does for records,
  or validate status and campaign values against `CODE` or `SAFE_ID`.

### P3-1: Malformed inputs crash the build with uncaught exceptions instead of producing findings.
The exceptions print tracebacks that can contain absolute paths.
- `correlate.py:451`: `_verify_dataset_freeze` calls `ctx.path(relative)` outside try/except. A
  `dataset_freeze` path that escapes the root raises `UnjoinableReference` (probe h).
- `correlate.py:760`: a non-string NOT_RUN `case_id` (for example a list) raises `TypeError:
  unhashable` at `case_id in observed_cases` (probe i).
- `correlate.py:1139`: `int(suite.get("tests"))` on a non-numeric value raises `ValueError`
  (probe j).
- `cli.py:37` / `:145`: only `UsageError` is caught. A missing manifest, invalid manifest JSON, or a
  pydantic `ValidationError` produces a raw traceback that includes the local path (probe q).

Fix: guard each of these and map them to `SOURCE_UNREADABLE`/`UNJOINABLE_REFERENCE`. In `main`,
catch `OSError`/`ValueError`, print a path-free message and exit 64.

### P3-2: `verify` accepts a missing `.sha256` sidecar.
`cli.py:139` uses `recorded in (None, digest)`. Probe k deleted the sidecar, and verify still
printed `REPRODUCED … recorded=UNAVAILABLE` with exit 0. README:26 says verify requires equality
with "the index and its `.sha256`". Fix: require the sidecar, or document that it is optional.

### P3-3: Receipt self-identification is not cross-checked.
The receipt has `case_id`, `role`, `stage` and `source_sha256`. None is compared with the
observation or the campaign fingerprint (`correlate.py:565-588`). Probe g set the receipt's
`case_id` to another case: the result was COMPLETE, JOINED and eligible. Span checks catch most
request-id swaps, so the impact is low. Fix: compare these fields when present and add
`RECEIPT_KEY_MISMATCH`.

### P3-4: A preflight row inside a SYNTHETIC_FIXTURE source is classed `NON_NATIVE_PREFLIGHT`.
At `correlate.py:551-553` such a row loses its synthetic marker (probe m). It is never eligible, so
the impact is cosmetic. It does blur the native, synthetic and offline classes. Fix: keep the
declared synthetic class, or add a `declared_synthetic` flag.

### P3-5: The `schema` sub-command has no evidence-root guard.
`cli.py:117-121` writes to any `--out` path, including one inside the evidence roots. The guard
also protects only the roots as bound at run time: a `--root` override moves the protection away
from the real evidence. Fix: apply `_refuse_inside_roots` using the representative manifest's
roots, or document the limitation.

### P3-6: Evidence class depends entirely on the manifest declaration.
- The adapter does not detect synthetic-shaped data. The fixtures declare `NATIVE` with
  `model: synthetic/model`, and they yield `model_performance_evidence=true` in memory.
- With `evidence_manifest=None` and no pins (probe p), the index is COMPLETE and eligible with no
  integrity anchoring at all.
- Fix: emit a WARNING `INTEGRITY_UNANCHORED` when a NATIVE source has neither a campaign manifest
  nor pins, and consider making the fixture default `SYNTHETIC_FIXTURE`.

### P3-7: Broken README link.
README.md:64 links `FINAL_REPORT.md`, which does not exist in the deliverable.

### P3-8: The redaction filter misses some shapes, and one identity field is copied verbatim.
- **False negatives:** `privacy.is_sensitive` returns False for:
  - absolute paths (`C:/Users/shane/x`, `/home/alice/notes`);
  - Slack (`xoxb-…`) and Google (`AIza…`) keys;
  - local 8-digit SG phone numbers (`91234567`);
  - lowercase NRIC (`s1234567d`);
  - personal names.
- **Verbatim copy:** `evaluator_identity` copies values such as `/root/v93_paired_final_audit`
  (an agent path from another system; a test explicitly allowlists it). Any local path in that field
  would leak.
- **False positive:** SSN-shaped substrings in ids (`A:case-123-45-6789`) are flagged. This degrades
  gracefully: the case_id becomes UNAVAILABLE and the record id becomes `row-N`.
- **JUnit record ids:** these are not pre-filtered. If a node name is sensitive, `scrub` would turn
  `record_id` into `REDACTED` and could produce collisions (theoretical; none in the current
  evidence).
- **Fix:** add path and common key prefixes, validate `evaluator_identity` against `SAFE_ID`, and
  build the redacted record id before the scrub.

### P3-9: Undeclared hash concepts are reported as UNAVAILABLE rather than NOT_APPLICABLE.
- V9.3 records have `scoring_spec_sha256=UNAVAILABLE` (V9.3 has no shared scoring spec; it uses a
  rubric). PAIR records have `rubric_sha256=UNAVAILABLE` (PAIR uses a scoring spec).
- Under the README's own definitions, a concept the campaign does not have is NOT_APPLICABLE.
- This is uncertain and debatable: UNAVAILABLE is the conservative choice. Consider a per-source
  declaration of which concepts apply.

### P3-10: GUARDRAIL_COVERAGE.md wording overclaims in one row.
"Tool / action access controls — IMPLEMENTED" for the Clarifier rests on the observed
`effect_classification=NO_EXTERNAL_EFFECT` for 37 rows. That is an observation of no dispatch, not
evidence of an enforced control. Rephrase it as "observed, not enforced by the Clarifier".

### P3-11: Housekeeping and minor notes.
- `src/trace_eval_correlation/__pycache__` exists (possibly from the gate runs; harmless).
- `manifests/representative.json` holds absolute local root paths that include the username. This is
  acceptable for a local manifest, but worth noting before sharing.
- `REQUEST_HASH_MISMATCH` is used for two different failures (file bytes vs receipt at
  `correlate.py:583-584`, and span vs receipt at `:867-871`). Splitting the codes would aid diagnosis.

## Test-category assessment (12 required)

All 12 categories are genuinely exercised. Coverage gaps:
- Category 2 (duplicate IDs) does not include NOT_RUN duplicates (P2-3).
- Category 4 (missing hashes) is covered only through files read by `read_json`. Missing hashed-only
  or pinned files, and stale prompt pins, are untested and broken (P1-1, P2-1).
- Category 9 (writer failure) does not assert eligibility for a native record whose LLM span is
  unterminated (P2-2).
- Category 10 (privacy) does not cover `SourceSummary` (P2-4).
- Category 12 (reproducibility) does not cover a missing sidecar (P3-2).

## Overall verdict

**PASS_WITH_FINDINGS**

The shipped representative index is correct. I reproduced it byte for byte and independently
verified every native, preflight, NOT_RUN and offline record against the raw evidence. Counts and
costs match, and the index is privacy-clean, side-effect-free and adds no new authority. Worktree
isolation and evidence preservation hold. No P0 was found.

P1-1 (a missing pinned or consumed file is silent) should be fixed before engineering acceptance.
P2-1 to P2-4 should be fixed within this scope: the integrity and eligibility guarantees the README
states are currently stronger than the code enforces.
