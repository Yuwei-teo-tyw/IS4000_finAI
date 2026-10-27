# V3 Independent Quality Gate — Orchestrator V3 Evidence Correlation

**Verdict: `QG_PASS_READY_FOR_OWNER_REVIEW`**. No P0, P1 or P2 findings. There are 8 P3 advisories (§7).

This is an independent evidence-integrity and evaluation-quality review. It does **not** accept the
engineering, approve integration or say anything about model performance. The reviewer did not
implement the candidate and did not use the author's handoff as proof of any claim.

Review date: 2026-10-27. Reviewer environment: Windows 11, Python 3.12.10 from the main checkout's
`backend/.venv`, pytest 9.1.1, Ruff 0.17.0, mypy 1.20.2, pydantic 2.14.1.

---

## 1. Reviewed candidate

| Item | Value |
|---|---|
| Repository | `IS4000_finAI` |
| Author worktree | `C:\Users\shane\.codex-clean2\worktrees\trace-eval-orchestrator-v3\IS4000_finAI` (read only) |
| Branch | `codex/trace-eval-orchestrator-v3` |
| **Reviewed commit** | `af78ad3944576c7eaec40295b64a0161a1d0047e` |
| Parent | `6a34a69e70b89aed93065e2d8a9e236fc2e1071f`, "feat(evals): add offline trace-eval evidence correlation (#21)" |
| Parent vs `origin/main` | Parent equals the **local** `origin/main` ref. No fetch was run, so whether the remote has moved since is **UNVERIFIED**. |
| Author worktree state | Clean: 0 tracked or untracked changes; only ignored caches (`.mypy_cache`, `.ruff_cache`, `__pycache__`). HEAD unchanged after the review. |

### Isolated review workspace
`C:\Users\shane\AppData\Local\Temp\claude\C--Users-shane--claude-spares-spare-2GengR\90dd547d-e63f-4050-8616-7d069ba0773d\scratchpad\qg-v3\`

- `candidate/`: `git archive af78ad3` (exact commit tree; no git metadata and no branch or worktree created)
- `evidence/`: `git archive HEAD` of the main checkout (`a2fdd55`), limited to
  `assurance/evals/reports/orchestrator-eval-v3` and `assurance/evals/datasets/synthetic-v3` (81 files)
- `work/`: the reviewer's own scripts, outputs and mutation copies (`reconstruct.py`, `mutate.py`, `mutate2.py`, `*.out`)

### Changed-file inventory (`6a34a69..af78ad3`): 8 files, +5425/−2
All changes are under `development-candidates/trace-eval-correlation/`. **Nothing outside it changed**
(verified with `git diff --name-only | grep -v`).

| File | Change |
|---|---|
| `V3_HANDOFF.md` | new |
| `index/orchestrator-v3-index.json` | new (4626 lines) |
| `index/orchestrator-v3-index.json.sha256` | new |
| `manifests/orchestrator-v3.json` | new: 60 files, 60 pins |
| `src/trace_eval_correlation/orchestrator_v3.py` | new: 324 lines |
| `src/trace_eval_correlation/correlate.py` | +7/−1 (2 error codes plus a dispatch branch) |
| `src/trace_eval_correlation/schema.py` | 1 line (`SourceSpec.kind` Literal adds `orchestrator_eval_v3`) |
| `tests/test_orchestrator_v3.py` | new: 272 lines |

### Files actually inspected
- Candidate source, read in full: `orchestrator_v3.py`, `sources.py`, `cli.py`, `privacy.py`; the `schema.py` contracts;
  `correlate.py` (helpers `_s/_i/_f/_b/_dicts/_na_score`, `Context`, `ERROR_CODES`, `_finalise`,
  `build_source`, `build_index`); `tests/test_orchestrator_v3.py`; `tests/test_historical_evidence.py`;
  `pyproject.toml`; `V3_HANDOFF.md`; `manifests/orchestrator-v3.json`; `manifests/representative.json` (roots).
- Archived evidence (main checkout `a2fdd55`, tracked since `200cf9e`): the archive `manifest.json`, `cases.json`,
  `datasets/synthetic-v3/inputs.json`, `datasets/synthetic-v3/manifest.json` (freeze), 28 `evidence.json`,
  2 `http-receipt.json` (hash only) and 28 prepared input files (hash and size only). All 53 freeze-listed files were
  hashed against the main checkout.
- Only the shape and metadata of evidence content were read. Prompts and model output were not printed.

---

## 2. Independent record and hash verification

**Method.** `work/reconstruct.py` (it does **not** import `trace_eval_correlation`) rebuilds the
expected record set straight from the archived files. It then compares the committed index field by field.
It ran against both the extracted copy and the live main checkout.

| Check | Result |
|---|---|
| Adapter manifest: 60 `files` entries, 60 distinct paths, `files` set == `pins` set | ✅ |
| 60/60 pins match actual file SHA-256 | ✅ (both roots) |
| Archive manifest: 30 listed files (28 `evidence.json`, 2 `http-receipt.json`), all 30 hashes match | ✅ |
| Archive-listed evidence set == manifest `evidence_00..27` set | ✅ |
| Dataset freeze `status == FROZEN`; all 53 freeze-listed files hash-match (main checkout) | ✅ 53/53 |
| `inputs.json` hash == freeze listing | ✅ |
| 28 evidence keys `(phase, case_id, model)`, unique; 28 score keys, 28 input keys, all three sets equal, no duplicates | ✅ |
| 28 receipt `request_id`s, unique, none missing; `reservation_id == request_id` for all 28 | ✅ |
| Prepared input file hash == `inputs.json` sha == freeze sha == pin == evidence `expected_input_sha256` == evidence `actual_input_sha256`; byte length == `inputs.json.bytes` | ✅ 28/28 |
| `requested_model == returned_model == key.model`; `role == orchestrator`; `provider == ollama` | ✅ 28/28 |
| `evaluation_tree` == archive `evaluation_tree`; `evidence_status == COMPLETE`; `outbound_count == 1` | ✅ 28/28 |
| `cases.json` vs evidence: `admitted`, `outcome`, `admission_code`, `provider_status`, `input_tokens`, `output_tokens`, `latency_ms`, `graph_duration_ms`, `actual_schema_valid` | ✅ 28/28 all equal |
| `archive.actual_attempts == outbound_posts == 28 == records` | ✅ |
| **Committed index vs reconstruction**: 31 fields per record plus evidence and prepared-input artifact refs | ✅ **0 mismatches** |
| Duplicate record IDs in index | none |

Note on the byte-for-byte claim: the archive holds hashes of the prepared inputs, not copies of the request bodies.
So "archived inputs match prepared inputs byte-for-byte" holds in this sense: the evidence's
`expected/actual_input_sha256` equal the SHA-256 of the prepared file bytes. The smoke and primary
`dev-v3-01` inputs share identical bytes and hashes (`4091b5a5…`, `bee108d9…`), as the pins declare.

### Outcome distribution (from the original evidence)

| Phase | n | Admitted | Outcome | Admission code |
|---|---|---|---|---|
| primary | 24 | 3 (`dev-v3-02` 4b and 9b, `held-v3-02` 9b) | 3 `ADMITTED`, 21 `ADMISSION_REJECTED` | 15 `MISSING_COVERAGE`, 5 `FORBIDDEN_CAPABILITY`, 1 `MISSING_PREREQUISITE`, 3 null |
| smoke | 2 | 0 | 2 `ADMISSION_REJECTED` | 1 `FORBIDDEN_CAPABILITY`, 1 `MISSING_COVERAGE` |
| http | 2 | 0 | 2 `HTTP_PLAN_REJECTED_OR_UNAVAILABLE` | null, null |

**Claim confirmed: 3 admissions, 23 admission rejections, 2 HTTP rejected-or-unavailable.** The
index copies these exactly (`validation.canonical_accepted`, `observation_status`, `rejection_reason`).
Models are `qwen3.5:4b` ×14 and `qwen3.5:9b` ×14. All 28 receipts have `status=PASS`, `schema_valid=true`,
`reasoning_tokens=null` and `backend_provider=null`. The 2 HTTP rows have `graph_duration_ms=null`.

### Index hashes (recomputed independently)

| Artifact | Required | Recomputed | Sidecar |
|---|---|---|---|
| `index/orchestrator-v3-index.json` | `078075018cc8eb894c6810578336d19c2da6e03074e83dadfe4a6a7ad84078e7` | ✅ identical | ✅ identical |
| `index/representative-index.json` | `185013d018ca892a6a2b9f1cc1032315aaf8634189ccc944035f6d45ef7c2afc` | ✅ identical | ✅ identical |

### Determinism and rebuild
- `build` with `evidence=<main checkout>` and `evidence=<extracted copy>` → `COMPLETE records=28 findings=56 sha256=078075…`.
  Both outputs are **byte-identical** to the committed index. No absolute paths are embedded (refs are `evidence:./…`).
- `verify` against the committed index → `REPRODUCED`, exit 0.
- **Historical baseline under the candidate adapter**: `verify --manifest manifests/representative.json` with
  explicit `--root main_dev_candidates=…/Proj/IS4000_finAI/development-candidates --root codex_audit=…/profile-a-synthetic-isolation/…`
  → `REPRODUCED sha256=185013…`. The `correlate.py` and `schema.py` edits do not change the historical output.
- `schema` regenerated: byte-identical to `schema/trace-eval-index-1.0.schema.json` (index contract unchanged).

---

## 3. Reproduced tests, lint and typing

| Command (run from the isolated copy) | Result |
|---|---|
| `pytest tests -q -rs` with **no** `TRACE_EVAL_V3_ROOT` | **104 passed, 3 skipped** (2 historical UNAVAILABLE + the V3 real-archive test UNAVAILABLE) |
| `TRACE_EVAL_V3_ROOT=<main checkout> pytest tests -q -rs` | **105 passed, 2 skipped** (2 historical UNAVAILABLE) |
| `TRACE_EVAL_V3_ROOT=<extracted copy> pytest tests -q -rs` | **105 passed, 2 skipped** |
| `ruff check --no-cache src tests` | All checks passed |
| `ruff format --check src tests` | 2 files would be reformatted: `orchestrator_v3.py`, `tests/test_orchestrator_v3.py` (P3-6). All pre-existing files are formatted. |
| `mypy` (strict, pydantic plugin) `src` | Success: no issues in 8 source files |
| `mypy src tests` | Success: no issues in 17 source files |

The author's "105 passed, 2 skipped" **reproduces only when `TRACE_EVAL_V3_ROOT` is bound**. The two
historical-source tests (`test_historical_evidence.py:45`, `:74`) **did not run** in any configuration and
are **not counted as passes**. They skip because `manifests/representative.json` binds roots with
relative paths that only resolve from the original `IS4000_finAI-trace-eval` location (P3-7). Their
assertions are covered separately by the `verify … REPRODUCED 185013…` run above. It was a CLI run, not a pytest pass.

---

## 4. Synthetic-corruption results (temporary copies only)

Each scenario ran the candidate CLI on a fresh copy of the evidence. "repinned" means the reviewer also
rewrote the archive-manifest hash and the adapter pins, so the adapter's *semantic* checks are tested
rather than just the hash gate. In every scenario the evidence root was byte-unchanged after the build,
no record became `model_performance_evidence=true`, and no secret or absolute path appeared in the output.

| Scenario | Exit | Index status | Detection |
|---|---|---|---|
| baseline | 0 | COMPLETE | 28 PARTIAL |
| evidence file deleted | 2 | INCOMPLETE | `SOURCE_FILE_MISSING`, `V3_JOIN_KEYS_MISMATCH`, `V3_RECORD_COUNT_MISMATCH`, 27 records |
| evidence +1 byte | 2 | INCOMPLETE | `SOURCE_PIN_STALE`, `V3_DECLARED_HASH_MISMATCH` |
| prepared input +1 byte | 2 | INCOMPLETE | `SOURCE_PIN_STALE`, `REQUEST_HASH_MISMATCH` (record UNJOINABLE) |
| …adapter pins only | 2 | INCOMPLETE | `V3_DECLARED_HASH_MISMATCH` (freeze), `REQUEST_HASH_MISMATCH` |
| …inputs.json, freeze and pins all re-anchored (evidence hash differs) | 2 | INCOMPLETE | `REQUEST_HASH_MISMATCH` |
| archive manifest invalid JSON (unpinned / repinned) | 2 | INCOMPLETE | `V3_OBJECT_REQUIRED`, `V3_RECORD_COUNT_MISMATCH`, 0 records |
| `cases.json` invalid JSON, repinned | 2 | INCOMPLETE | `MISSING_SCORE` ×28 UNJOINABLE |
| duplicate request ID, repinned | 2 | INCOMPLETE | `DUPLICATE_REQUEST_ID` on both rows |
| duplicate case key, repinned | 2 | INCOMPLETE | `DUPLICATE_CASE_ID`, `V3_DUPLICATE_JOIN`, `V3_JOIN_KEYS_MISMATCH`; both rows retained |
| rejected→admitted flip, repinned | 2 | INCOMPLETE | `SCORE_KEY_MISMATCH` |
| admitted→rejected flip, repinned | 2 | INCOMPLETE | `SCORE_KEY_MISMATCH` |
| **`admission_code` only changed, repinned** | 0 | **COMPLETE** | **not detected** (P3-1) |
| returned model ≠ key, repinned | 2 | INCOMPLETE | `RECEIPT_KEY_MISMATCH` |
| `actual_input_sha256` altered, repinned | 2 | INCOMPLETE | `REQUEST_HASH_MISMATCH` |
| receipt tokens absent / null | 0 | COMPLETE | tokens → `UNAVAILABLE` (never 0), `token_usage_verified=UNAVAILABLE` |
| secret, email and NRIC-shaped text in non-allowlisted fields | 0 | COMPLETE | not copied (allowlist) |
| credential text in an allowlisted field (`finish_reason`) | 0 | COMPLETE | `PRIVACY_REDACTED`, value `REDACTED` |
| freeze `status=DRAFT`, repinned | 2 | INCOMPLETE | `V3_DATASET_NOT_FROZEN` |
| `actual_attempts=29`, repinned | 2 | INCOMPLETE | `V3_RECORD_COUNT_MISMATCH` |
| archive entry dropped and count lowered to 27, repinned | 2 | INCOMPLETE | `V3_JOIN_KEYS_MISMATCH` |
| duplicate archive path, repinned | 2 | INCOMPLETE | `V3_DUPLICATE_ARCHIVE_PATH` |
| archive entry → `../outside.json` (+pin) | 2 | INCOMPLETE | caught only indirectly via `V3_JOIN_KEYS_MISMATCH` and count; **no `UNJOINABLE_REFERENCE`** (P3-2) |
| archive entry → `../../../../outside.txt`, repinned | 2 | INCOMPLETE | same, indirect only (P3-2) |
| evidence directory replaced by an NTFS **junction** to outside the root | 2 | INCOMPLETE | `UNJOINABLE_REFERENCE` (containment holds after `resolve()`) |
| evidence **file symlink** to outside the root | — | — | **UNVERIFIED**: the OS refused symlink creation (no privilege). The code path is the same `Path.resolve()` containment check that the junction case exercised. |
| `http-receipt.json` tampered (unpinned / repinned) | 0 | **COMPLETE** | **not detected** (P3-2) |
| prepared-input pin removed | 2 | INCOMPLETE | `V3_ARTIFACT_UNPINNED_OR_STALE`, `REQUEST_HASH_MISMATCH` |
| `declared_evidence_class=OFFLINE_TEST` | 2 | INCOMPLETE | `V3_EVIDENCE_CLASS_INVALID` |
| output path inside the evidence root | 64 | — | refused; nothing written |

**Eligibility-guard mutation.** A copy of `orchestrator_v3.py` with the seeded
`V3_SPANS_UNAVAILABLE` and `V3_PROMPT_BINDING_UNAVAILABLE` issues removed (line 175) gave
`COMPLETE`, 28 × `JOINED`, 28 × `model_performance_evidence=true` on the real archive. In the default (no-env) suite this mutation is caught **only** by the
`join_status == "PARTIAL"` assertion in `test_all_28_records_and_phase_sensitive_identity`.
With the env var bound, `test_actual_28_record_archive` also catches it. The guard is protected, but by a single
fixture assertion (see P3-5).

---

## 5. Evidence truthfulness: verified vs PARTIAL vs UNAVAILABLE

| Requirement | Status | Basis |
|---|---|---|
| All 28 records `join_status=PARTIAL` | ✅ VERIFIED | committed index and rebuild |
| No V3 row `model_performance_evidence=true` | ✅ VERIFIED | 0/28; structurally depends on seeded issues (line 175) plus `_finalise` (NATIVE ∧ JOINED) |
| Spans `agent_span_id`, `llm_span_id`, `span_relationship`, span statuses | UNAVAILABLE (correctly) | 28/28 |
| Prompt `prompt_ref`, `prompt_sha256`, `prompt_binding` | UNAVAILABLE (correctly) | 28/28 |
| Synthetic correlation IDs not presented as verified spans | ✅ with caveat | `trace_id` holds a label such as `v3-primary-dev-v3-01-4b` in the same field where the historical index holds real UUID trace IDs; no span is claimed (P3-4) |
| `NATIVE` = archived model-inference attempt | ✅ | manifest-declared; every row has a receipt with `status=PASS`, `outbound_count=1`, tokens and latency. `send_claimed=true` comes from `outbound_count`. Nothing implies Windows-native execution. |
| `COMPLETE` = source/index completeness only | ✅ | `index_status` = no ERROR findings; `completeness` = record count == `actual_attempts`. Campaign status copied as `MEASURED_NOT_MODEL_ACCEPTANCE`. |
| Schema validity not presented as quality success | ✅ | `score.schema_status=VALID` sits beside `agent_success`, `canonical_state_success` and `independent_assessment_status` = UNAVAILABLE |
| Missing tokens and billing never become 0 | ✅ VERIFIED (mutation) | absent or null → `UNAVAILABLE`; `reasoning_tokens` UNAVAILABLE ×28; cost, billing and `cost_scope` UNAVAILABLE |
| Numeric usage explicitly unverified | ✅ | `token_usage_verified=UNAVAILABLE` ×28. Copied receipt tokens and latency match `cases.json` in all 28 rows (internally consistent, still self-reported). |
| No invented independent evaluation or reviewer provenance | ✅ | `evaluator_identity`, `evaluator_independent`, `assessment_*` = UNAVAILABLE |
| Admission and rejection outcomes copied, not recomputed | ✅ | no admission or scoring code imported or executed |
| `http_status`, `provider_returned`, HTTP `attempt_wall_latency_ms` | UNAVAILABLE (correctly) | source fields null or absent |

---

## 6. Privacy and boundary controls

| Control | Status |
|---|---|
| Strict metadata allowlist (only named scalar fields copied; `observation`, `proposal`, `reason` and free text never read into records) | ✅ code review plus mutation (no leak) |
| No raw prompt, model output or PFI in the committed index | ✅ prepared-input content is never parsed (`_read` result discarded at line 220); 77 leaf fields per record, all metadata |
| Defence-in-depth redaction (`privacy.scrub`) on records, summaries and findings | ✅ mutation |
| Root containment: absolute, drive, `..` and resolved-path containment | ✅ via `Resolver.resolve`; junction escape refused |
| No writes inside evidence roots | ✅ CLI refuses (exit 64); every mutation root byte-unchanged; main-checkout evidence paths clean (`git diff --quiet HEAD -- assurance/evals`) |
| No second scorer, canonical ledger or policy authority | ✅ copy-only; no score contract or interpretation added |
| No LangSmith, provider or network imports | ✅ none in `src/` (grep for socket, urllib, http, requests, httpx, langsmith, langchain, openai, ollama, subprocess) |
| No application execution or admission behaviour change | ✅ zero files changed outside the candidate directory; `backend/` does not reference the adapter |

---

## 7. Findings inventory

No **P0**, **P1** or **P2** findings.

### P3-1: `admission_code` (index `rejection_reason`) is not joined against the saved score
- **Ref:** `orchestrator_v3.py:210` compares only `("admitted", "outcome")`; `:299` copies `rejection_reason` from the evidence row alone.
- **Repro:** `work/mutate2.py` → `admission_code_only_changed_repinned` gives `COMPLETE` with no finding.
- **Impact:** the handoff's "saved outcome joins" claim covers acceptance and outcome but not the rejection reason. On the real archive they agree 28/28 (reviewer cross-check), so the committed index is correct. This is a detection gap for internally inconsistent archives only.
- **Remedy:** add `admission_code` to the `SCORE_KEY_MISMATCH` comparison, plus one parametrised test case.

### P3-2: Non-`evidence.json` archive entries are skipped with no hash or path validation
- **Ref:** `orchestrator_v3.py:148-149` (`if not path.endswith("/evidence.json"): continue`).
- **Repro:** tampering `http-receipt.json` still gives `COMPLETE`. Archive entries rewritten to `../outside.json` or `../../../../outside.txt` are skipped silently; they are caught only by the join and count checks, never as `UNJOINABLE_REFERENCE`.
- **Impact:** 2 of the 30 archive-listed hashes are never verified by the adapter (the reviewer verified both independently: they match). An unsafe path in a non-evidence entry would not be reported as unsafe. No content is read, so this does not affect privacy.
- **Remedy:** validate every archive entry's path with `ctx.path()`, hash-verify it against the archive listing even when it is not consumed, then skip its content. Alternatively, state in the handoff that only 28/30 archive hashes are adapter-verified.

### P3-3: `rejection_reason="UNAVAILABLE"` on admitted rows
- **Ref:** `orchestrator_v3.py:299`; 3 admitted records.
- **Impact:** by the schema's own convention (`schema.py` module docstring), a rejection reason for an admitted plan is `NOT_APPLICABLE`, not `UNAVAILABLE`. This is a semantic inaccuracy only.
- **Remedy:** emit `NOT_APPLICABLE` when `admitted is True`. HTTP rows (unknown) correctly stay `UNAVAILABLE`.

### P3-4: Synthetic correlation label stored in `trace.trace_id`
- **Ref:** `orchestrator_v3.py:276`.
- **Impact:** the historical index holds real UUID trace IDs in this field, while V3 holds labels such as `v3-primary-dev-v3-01-4b`. Only the record-level `V3_SPANS_UNAVAILABLE` issue tells them apart. A downstream join on `trace_id` against LangSmith would silently find nothing.
- **Remedy (no schema change):** document the field semantics per source kind in the README and handoff. If the schema is next revised, add a `trace_id_kind` field (`VERIFIED_TRACE` / `CORRELATION_LABEL`).

### P3-5: The eligibility guard has thin test protection; fixture assertions about `model_performance_evidence` are vacuous
- **Ref:** `tests/test_orchestrator_v3.py:47` uses `declared_evidence_class="SYNTHETIC_FIXTURE"`, under which `model_performance_evidence` is always false. The NATIVE path runs only in the env-gated `:262` test.
- **Repro:** the eligibility mutation in §4 is caught by a single `join_status == "PARTIAL"` assertion.
- **Remedy:** add one fixture test with `declared_evidence_class="NATIVE"` asserting PARTIAL and `model_performance_evidence is False` for every row. Also add a byte-reproduction test for the committed `orchestrator-v3-index.json`, matching `test_committed_representative_index_reproduces`. Today that reproduction is checked only by the manual CLI `verify`.

### P3-6: New files not `ruff format`-clean
- **Ref:** `orchestrator_v3.py`, `tests/test_orchestrator_v3.py`. All pre-existing files are formatted. `ruff check` passes.
- **Remedy:** run `ruff format` on both files. This changes no behaviour, and the index hash is unaffected.

### P3-7: Historical-source pytest tests cannot run from any worktree except the original location
- **Ref:** `manifests/representative.json:4-5` (relative roots); `tests/test_historical_evidence.py:22-29`.
- **Impact:** in the author worktree and the reviewer copy they always skip (UNAVAILABLE). The evidence actually exists and reproduces through CLI `--root` overrides. This is an inherited (PR #21) gap, not V3-specific.
- **Remedy (follow-up, not blocking):** let the tests accept root overrides through env vars, as the V3 test does.

### P3-8: Record-ID encoding is not injective, and versions were not bumped
- **Ref:** `orchestrator_v3.py:179` joins `phase:case_id:model` with `:`, while model IDs contain `:` (`qwen3.5:4b`), so naive `split(":")` consumers break. The reviewer's own script hit this. Collisions are still caught by `DUPLICATE_RECORD_ID`. `ADAPTER_VERSION` and `pyproject` stay `1.0.0` although the adapter gained a source kind, so built indexes cannot be told apart by adapter capability. The pre-V3 adapter on `main` rejects the V3 manifest (`sources.0.kind`).
- **Remedy:** document the record-ID grammar (the model is the suffix after the third `:`) and bump the adapter minor version at integration. Bumping would change the index bytes, so re-pin and re-hash under a separate review.

---

## 8. Unresolved risks
1. **Remote freshness of `main` is UNVERIFIED** (no fetch). The parent equals the local `origin/main` ref only.
2. **File-symlink escape is UNVERIFIED by execution** (no privilege). The junction escape was verified, and the same containment path applies.
3. **The historical pytest tests did not run** (UNAVAILABLE). Equivalent CLI reproduction passed (`185013…`).
4. **Usage numbers are self-reported by the evaluation harness** (receipt plus `cases.json` agree). They have no external provider or billing corroboration and are correctly flagged `token_usage_verified=UNAVAILABLE`.
5. **Inherited time-of-check gap:** each file is hashed and then re-read for parsing (`orchestrator_v3.py:54` vs `:64`, same pattern as `correlate.py:342/344`). This is negligible offline over git-tracked, read-only evidence.
6. The pins and archive manifest are the trust anchor. Anyone who can rewrite both can forge consistent evidence. This is inherent to the design and outside the adapter's scope.

## 9. Preservation status
| Item | Status |
|---|---|
| Author worktree / commit `af78ad3` | unchanged, clean (HEAD and status re-checked after review) |
| `representative-index.json` and `.sha256`, `representative.json`, `representative.unpinned.json`, `schema/trace-eval-index-1.0.schema.json` | byte-identical to parent `6a34a69` |
| Historical evidence (main checkout `assurance/evals/...orchestrator-eval-v3`, `synthetic-v3`) | clean vs `HEAD a2fdd55`; read only |
| Main checkout (C2.2 branch `feat/agent-lab-c22-hybrid-orchestrator`) | not modified by the reviewer; pre-existing uncommitted changes untouched |
| `IS4000_finAI-trace-eval` (`7a03599`), `IS4000_finAI-trace-eval-integration` (`6a0b66e`) | clean, untouched |
| Git operations by the reviewer | read-only only (`rev-parse`, `log`, `diff`, `status`, `show`, `archive`). No commit, branch, worktree, fetch, push, PR or merge. |
| Inference, provider, LangSmith or network calls | none |

## 10. Integration recommendation
- **Schema compatibility:** compatible. The index JSON Schema regenerates byte-identical (`SourceSummary.kind` is `str`). `schema_version` is unchanged at `trace-eval-index/1.0`. The only contract widening is the manifest-side `SourceSpec.kind` Literal. The historical index reproduces unchanged under the candidate adapter.
- **Route:** integrate from a **fresh, clean worktree cut from freshly fetched `origin/main`**. Do not use the
  author worktree, the main checkout (C2.2 branch with unrelated uncommitted work) or the older
  `IS4000_finAI-trace-eval-integration` tree. While `origin/main` still equals `6a34a69`, this is a fast-forward of one commit.
  After any rebase, re-run `build`/`verify` and confirm the V3 hash. It changes only if the adapter code or manifest changes.
- **Remediation:** none is required to pass this gate. Bounded optional remediation for Codex, best done before integration:
  P3-1, P3-3, P3-5 and P3-6 (small, local, no change to the committed index hash, except P3-3, which changes 3 field values and therefore the hash).
  P3-2 and P3-4 are documentation or validation hardening. P3-7 and P3-8 can be follow-ups. Any remediation that changes the index bytes
  needs a **separate independent recheck** of the new hash.
- Owner review is still required. This gate does not accept engineering or integration.

---

**Return: `QG_PASS_READY_FOR_OWNER_REVIEW`**
