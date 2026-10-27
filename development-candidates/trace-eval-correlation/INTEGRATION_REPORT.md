# Integration report — Trace–Eval Correlation Adapter onto `main`

**Disposition: `READY_FOR_TRACE_EVAL_PR_AUTHORIZATION`** (local only; nothing pushed, no PR, no merge)

## Commits

| | SHA | Notes |
|---|---|---|
| Source commit (reviewed, preserved) | `7a035992e51b3e18693c6c97eda1fe409f0c3818` | Branch `feat/trace-eval-correlation-offline`; parent `a2fdd55` (local agent-lab lineage, not on `main`) |
| Integration base (`origin/main`, fetched 2026-10-27) | `3665abb0e6b11e72c76eefbedac47260196f9423` | Merge of PR #20; shared default branch |
| Integration commit 1 (cherry-pick `-x`) | `5055506e5d28b72ffc70170a17cd64038356f39e` | Clean; adapter tree `416dc0f2…` equals the source commit's |
| Integration commit 2 (remediation) | `579288cfaa351a46dcbe957afe9ec3e919102dce` | Adds `.gitattributes` (LF) and doc-only edits |
| Integration commit 3 | the commit adding this file | Docs only: this report and `reports/PRE_PR_REVIEW.md` |

Branch: `integration/trace-eval-correlation-prepr`. Worktree: `IS4000_finAI-trace-eval-integration`, a sibling of the main checkout.

**Why `origin/main`:** it is the shared default branch. The adapter imports only the standard library and pydantic, and it has no runtime dependency on the unpushed agent-lab lineage. The only coupling to that lineage is documentation, which commit 2 now discloses.

## Integration blocker and remediation

**Problem:** with `core.autocrlf=true`, a fresh Windows checkout converted LF to CRLF. That changed the manifest bytes, and with them the `manifest_sha256` embedded in the index.
- `verify` reported NOT_REPRODUCED.
- `test_committed_representative_index_reproduces` failed.

The baseline run on commit 1 gave 84 passed, 1 failed. The source worktree never showed the defect because its files were written as LF and never re-checked-out.

**Fix (commit 2):** an adapter-local `.gitattributes` with `* text eol=lf`. Source, test, manifest, index and schema content are unchanged.

**Doc edits in the same commit:**
- The guardrail mapping now says its citations come from `a2fdd55`, which is not on `main`.
- The README now documents the tooling a fresh clone needs and what it can reproduce.
- A machine-specific path was removed from FINAL_REPORT.

The reviewer independently reproduced the defect on commit 1 and confirmed the fix on commit 2.

## File inventory (`3665abb..HEAD`)

45 files are added, all under `development-candidates/trace-eval-correlation/`. Nothing outside that directory changes.

| Group | Files |
|---|---|
| Config | `.gitattributes`, `.gitignore`, `pyproject.toml` |
| Docs | `README.md`, `FINAL_REPORT.md`, `QUALITY_GATE.md`, `CHECKPOINT.md`, `GUARDRAIL_COVERAGE.md`, `INTEGRATION_REPORT.md` |
| Source | `src/trace_eval_correlation/{__init__,__main__,cli,correlate,privacy,schema,sources}.py` |
| Tests | `tests/{conftest,test_campaign_states,test_correlation,test_historical_evidence,test_integrity,test_privacy_classes,test_reproducibility,test_review_regressions}.py` |
| Data | `index/representative-index.json` (+`.sha256`), `manifests/representative{,.unpinned}.json`, `schema/trace-eval-index-1.0.schema.json` |
| Gate records | `reports/{INDEPENDENT_REVIEW_attempt1,INDEPENDENT_REVIEW_attempt2,CLOSURE_REVIEW,PRE_PR_REVIEW}.md`, `reports/gate{1,2,3}-{mypy,pytest,ruff,verify}.txt` |

## Verification

| Scope | Result |
|---|---|
| Original source machine (integration worktree) | pytest **85 passed**; ruff and format clean; `mypy --strict` clean (7 files); `verify` **REPRODUCED** `185013d0…2afc`; schema byte-identical; 159 records; 36/36 native JOINED and model-evidence eligible; all pins VERIFIED |
| Fresh local clone, `autocrlf=true`, no evidence roots | **83 passed, 2 skipped** (UNAVAILABLE); ruff and mypy clean; schema identical; committed index bytes identical; `build` INCOMPLETE (SOURCE_UNAVAILABLE, REFERENCE_MISSING_FILE), exit 2; `verify` **NOT_REPRODUCED**, exit 1 |
| Unavailable externally | The historical V9 evidence and the Codex audit are untracked and not packaged. They cannot be re-verified from a clone, and no result from a clone is presented as newly reproduced. |

**Independent pre-PR gate: PASS**, with no P0–P2 findings ([reports/PRE_PR_REVIEW.md](reports/PRE_PR_REVIEW.md)). The reviewer was fresh and independent. It re-derived all 36 native joins and the 34 pins with its own scripts, reproduced the CRLF defect and its fix, and confirmed that source, provenance and scope were preserved.

## What a fresh clone can and cannot do

- **Can:** run the 83 portable tests, ruff and mypy; regenerate and compare the schema; read the committed index as a historical snapshot; and use the adapter on any evidence the user supplies through a manifest.
- **Cannot:** rebuild or `verify` the representative index, or re-check its pins and guardrail citations, without the untracked evidence roots and the unpublished `a2fdd55` lineage.

## Remaining P3 limitations (accepted, not material)

1. **Merge strategy.** `.gitattributes` does not rewrite an existing CRLF checkout; re-checkout the adapter directory after updating. Merge with **squash or a merge commit, not rebase**: a rebase would land commit 1, which does not reproduce on its own.
2. `* text eol=lf` would mangle binary files added to the directory later. `text=auto eol=lf` is safer if binaries are ever added.
3. Some lines describe the source-branch state and are now stale:
   - `FINAL_REPORT.md` §1, §8 and `QUALITY_GATE.md` mention the worktree path that commit 2 removed.
   - `FINAL_REPORT.md` says "uncommitted".
   - `FINAL_REPORT.md` and `CHECKPOINT.md` describe the old run environment.
4. `QUALITY_GATE.md` cites JUnit XML gate files. They are gitignored and stay local, so those links dangle on `main`; the `gate*.txt` summaries carry the results.
5. The manifests' relative `codex_audit` root and `FINAL_REPORT.md` reveal the home-directory layout and a worktree name, but not the absolute path.
6. A malformed `.sha256` (non-UTF-8, or a directory) makes `verify` exit with a traceback (exit 1). That fails closed and never gives a false REPRODUCED. A campaign manifest without pins is not flagged; this is documented in the README, and every committed source is pinned.
7. `pytest` must run from the adapter directory. Collecting from the repository root fails at import, and `main` has no CI that does so.

Also carried over:
- The redaction filter is pattern-based.
- JUnit test-node IDs may contain test text.
- Cost is provider-reported only.
- `events.jsonl`, eval-v3 and LangSmith correlation are out of scope.

## Preservation

- **Main checkout:** unchanged — branch `feat/agent-lab-c22-hybrid-orchestrator` at `a2fdd55`, diff hash `8b9b6920…8cc8f`, status hash `c17cf354…2ec429`, 52 dirty entries untouched.
- **Other worktrees:** all 11 pre-existing worktrees have unchanged HEAD, status and diff hashes, as do all pre-existing local branches. `feat/trace-eval-correlation-offline` is still at `7a035992`.
- **Remote:** `git fetch` updated remote-tracking refs only.
- **Not done:** no push, PR, merge, deployment, inference, cloud upload, or C2.2, G-1, Profile A or Orchestrator change.

## PR readiness

Technically ready for a PR from `integration/trace-eval-correlation-prepr` into `main`. The branch is 3 commits ahead of `origin/main` and 0 behind. Opening the PR, and pushing the branch, require separate owner authorization.
