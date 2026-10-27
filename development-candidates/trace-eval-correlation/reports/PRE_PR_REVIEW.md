# Pre-PR review: Trace–Eval Correlation Adapter integration onto `main`

Reviewer: a fresh, independent pre-PR reviewer. I did not write the adapter, its fixes, the
earlier reviews or the integration commits. Date: 2026-10-27.

Mode: read-only. This file is the only file I wrote in any existing worktree, and it is left
uncommitted. Probes ran on scratch clones in my session scratchpad (`git clone --no-hardlinks`
of the local repository). The import-probe test wrote `src/trace_eval_correlation/__pycache__/`
in the integration worktree; I deleted it. I made no git state change in any existing
worktree, used no network, provider, model or install, and opened no `.env` or credential file.

**Verdict: PASS** — zero open P0, P1 or P2 findings. Seven P3 findings, none blocking.

## Scope

- Integration worktree `IS4000_finAI-trace-eval-integration`, branch
  `integration/trace-eval-correlation-prepr`, HEAD `579288c`.
- Base `origin/main` = `3665abb0e6b11e72c76eefbedac47260196f9423`.
- Commit 1 `5055506` (cherry-pick of `7a035992`) and commit 2 `579288c` (`.gitattributes` plus
  doc edits).
- Docs read in full: README.md, FINAL_REPORT.md, QUALITY_GATE.md, CHECKPOINT.md,
  GUARDRAIL_COVERAGE.md, `reports/CLOSURE_REVIEW.md`. The two independent-review reports were
  read where they bear on these checks (usernames, paths, accepted P3s).
- Source: `cli.py` in full, the historical, reproducibility and review-regression tests, and
  `conftest.py`.
- Historical evidence (`v9.3-readiness`, `v9.4.2-v9.3b-paired-readiness`, `v9.4.3-offline`
  and the Codex audit) was read only, never written.

## Commands and results

Interpreter: main checkout `backend/.venv` (Python 3.12.10). Run from the adapter directory
with `PYTHONPATH=src` and `PYTHONDONTWRITEBYTECODE=1`.

### 1. Integration base and provenance

| Check | Result |
|---|---|
| `git rev-parse origin/main` | `3665abb0e6b1…` (merge of PR #20, 2026-10-26). The reflog shows a fast-forward fetch of `origin/main` to 3665abb. |
| `git log --format='%H %P'` | `579288c` parent `5055506`; `5055506` parent `3665abb`. Both are ahead of `origin/main` (2), and 0 are behind. |
| `git merge-base --is-ancestor a2fdd55 origin/main` | exit 1, so a2fdd55 is **not** an ancestor, as stated |
| `5055506` message trailer | `(cherry picked from commit 7a035992e51b3e18693c6c97eda1fe409f0c3818)` |
| `git patch-id --stable` for 7a035992 and 5055506 | identical (`b71f2830…`) |
| `git diff --name-status a2fdd55 7a035992` vs `3665abb 5055506` | identical file set (41 added files) |
| `origin/main` contents | no `development-candidates/`, no root `.gitattributes`, no `backend/src/advisory_agents`, no `.github` CI. `backend/pytest.ini` has `testpaths = tests`. |

`3665abb` is a sound target. The change is purely additive under a new directory, so it
cannot conflict with any path on `main`. The adapter imports nothing from `a2fdd55` code.

### 2. Source preservation

| Check | Result |
|---|---|
| `git rev-parse feat/trace-eval-correlation-offline` | `7a035992e51b…` (unchanged) |
| `git rev-parse <c>:development-candidates/trace-eval-correlation` | 7a035992 = `416dc0f2…`; 5055506 = `416dc0f2…` (equal); 579288c = `5d6ab2ba…` (differs only by commit 2) |
| Source worktree `IS4000_finAI-trace-eval` | HEAD 7a03599. `status --porcelain --ignored` lists only the ignored `reports/*.xml`. |

### 3. Remediation scope and the CRLF root cause

`git show 579288c` adds `.gitattributes` (`* text eol=lf`). It changes only these docs:
README.md (+18/−2), FINAL_REPORT.md, GUARDRAIL_COVERAGE.md and CHECKPOINT.md.
`git diff --stat 5055506 579288c -- src tests manifests index schema pyproject.toml .gitignore reports`
is empty, so no source, test, manifest, index, schema or report content changed.
`git ls-files --eol` shows `i/lf` for every tracked file, so no blob needs renormalising.

Reproduction on scratch clones. The system git config has `core.autocrlf=true`, and
`--root` binds both roots to the real evidence, read-only.

| Checkout | Working-tree EOL | `verify` |
|---|---|---|
| 5055506, `core.autocrlf=true` | 42 × `w/crlf` | **NOT_REPRODUCED**, rebuilt sha `e7c2b87c…` ≠ recorded `185013d0…`, exit 1 |
| 5055506, `core.autocrlf=false` (control) | 42 × `w/lf` | **REPRODUCED** `185013d0…2afc`, exit 0 |
| 579288c, fresh clone, `core.autocrlf=true` | 43 × `w/lf`; manifest sha `3ec19873…` equals `manifest_sha256` in the index | **REPRODUCED** `185013d0…2afc`, exit 0 |
| 579288c, after an in-place switch from a CRLF 5055506 checkout | 38 × `w/crlf` (unchanged files are not rewritten); `git status` clean | **NOT_REPRODUCED**, exit 1 (see P3-1) |

The root cause is real. The rebuilt sha changes even though rebuilding does not read the
index file, because the CRLF manifest bytes change the embedded `manifest_sha256`. With the
same commit and LF, verify reproduces. `test_committed_representative_index_reproduces`
compares the same bytes, so it would fail the same way wherever the roots resolve.

The doc edits are accurate:
- `main`'s `backend/requirements.txt` lists `pydantic`.
- `requirements-dev.txt` lists `pytest>=7` and `ruff`, but not mypy.
- `main` has no `backend/src/advisory_agents`.
- The fresh-clone table matches my results in section 5.
- Spot-checked citations at a2fdd55 are correct: `contracts/__init__.py:25,63-65,99-101`,
  `registry.py:20-22`, `orchestrator/admission.py:5` and `telemetry.py:29,66,177-184`.

Adjacent statements made stale by these edits are listed in P3-3.

### 4. Results on the integration worktree (579288c)

| Command | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider` | **85 passed** |
| `ruff check --no-cache src tests` | All checks passed |
| `ruff format --check --no-cache src tests` | 15 files already formatted |
| `mypy --strict --cache-dir <scratch> src/trace_eval_correlation` | Success: no issues found in 7 source files |
| `python -m trace_eval_correlation verify --manifest manifests/representative.json --index index/representative-index.json` | **REPRODUCED** `185013d018ca892a6a2b9f1cc1032315aaf8634189ccc944035f6d45ef7c2afc`, recorded the same, exit 0 |
| `schema --out <scratch>` then `cmp` | identical (sha `dabf6d37…`) |

### 5. Evidence integrity and reproducibility

I checked these with my own scripts, which do not import the adapter. They read the raw
evidence and the committed index.

- **Records:** 159 in total: 87 OFFLINE_TEST, 36 NATIVE, 35 NOT_RUN and 1
  NON_NATIVE_PREFLIGHT. `index_status` is COMPLETE, with one INFO finding
  (`CAMPAIGN_PARTIAL`).
- **Native records:** all 36 are `JOINED` with `model_performance_evidence=true` and no
  issues. No non-native record is eligible.
- **Pins:** I re-hashed all 34 source pins and the Codex reference against the raw files: 0
  mismatches.
  - In the index, the source files are 31 × (`pin` VERIFIED, `source_manifest` VERIFIED) and
    3 × (VERIFIED, NOT_APPLICABLE). The reference is VERIFIED.
  - Every source's `evidence_manifest` is itself pinned (15, 17 and 2 pins).
- **Artifacts:** I re-hashed every hashable artifact (receipt, request, public output and 87
  JUnit nodes): 0 mismatches.
- **Native joins, re-derived independently:** for all 36 records, 0 problems on each of the
  following.
  - The receipt directory equals `request_id`.
  - The receipt `request_sha256` equals the sha of request.json.
  - The receipt `public_output_sha256` equals the sha of public-output.txt.
  - The receipt `case_id` equals the record's.
  - `llm_span_id` is an LLM span, its parent is an AGENT span, and that span's parent is a
    SESSION span.
  - Receipt, request and output each equal their campaign evidence-manifest entry.
  - The index's retries and fallback equal the receipt's.
- **Claims:** no unverifiable result is presented as new.
  - README "Fresh clone: what reproduces" labels the index a historical, source-dependent
    snapshot.
  - It states that a fresh-clone `build`/`verify` failure is "not a new result".
  - The `gate*.txt` files are dated gate records.

**Fresh scratch clone of 579288c** (relative roots do not resolve):

| Command | Result |
|---|---|
| `pytest -q -rs` | **83 passed, 2 skipped**. Both skips at `tests/test_historical_evidence.py` say `UNAVAILABLE: historical evidence roots not present`. |
| `build --index <scratch>/index.json` | **INCOMPLETE** `records=0 findings=4`, exit 2. Findings: `REFERENCE_MISSING_FILE` plus 3 × `SOURCE_UNAVAILABLE`, with root-relative detail only. |
| `verify` (committed index) | **NOT_REPRODUCED** sha `039ddafb…`, recorded `185013d0…`, exit 1 |
| ruff, ruff format, mypy --strict, schema regeneration | all clean or identical |

### 6. Privacy and publication readiness

`git diff --name-only 3665abb..579288c` lists 43 files, all under
`development-candidates/trace-eval-correlation/`. They are source, tests, schema, two
manifests, the index and its sidecar, docs, three review reports and 12 `gate*.txt`. No
receipt, request, output, observation or other raw evidence file is included. No `.xml`
(hostname-bearing) file is tracked: `reports/*.xml` is gitignored.

- **Credentials and emails:** sweeps for `sk-`, `Bearer`, `api_key`, `password`, email, IPv4
  and URL patterns found only synthetic sentinels: `pat@example.com`, `a@b.co`,
  `sk-abcdefghijklmnop` and `sk-or-v1-abc…`. They appear in tests and review prose. There are
  no real credentials, hostnames, IPs or URLs.
- **Index strings:** the only strings with spaces are JUnit `test_node_id` parametrisations
  from the lab's own synthetic test suite. One example is `Current balance is EUR 14300 or
  USD 15800; the client has not chosen.` These are documented and contain no client data.
  - `evaluator_identity` holds `/root/…_final_audit` reviewer labels. They are documented in
    FINAL_REPORT §6.
  - No request messages, model output, rationale or provider account metadata is present.
- **Username mentions:** a case-insensitive `git grep shane|C:/|/Users/|AppData|…` over the
  579288c adapter tree finds exactly 6 lines, all in preserved review records:
  - `reports/CLOSURE_REVIEW.md:197` quotes the folder hierarchy prefix
    `C:\Users\shane\Desktop\SMU\Y4S1\…`. This is a review finding about a path that 579288c
    has since removed.
  - `reports/CLOSURE_REVIEW.md:199-200` are meta-references to the attempt-1 and attempt-2
    lines below.
  - `reports/INDEPENDENT_REVIEW_attempt2.md:25` describes where the relative root resolves
    ("9 levels up gives `C:/Users/shane`").
  - `reports/INDEPENDENT_REVIEW_attempt1.md:70` is a negative claim (no `Users/shane` paths
    in the index).
  - `reports/INDEPENDENT_REVIEW_attempt1.md:231` is a synthetic redaction-probe input
    (`C:/Users/shane/x`).

  All are prose and none is a credential. The coordinator's claim holds for file content.
  The username handle and an email address also appear in the git author metadata of both
  commits (`shaneqwaszx <…@live.com.sg>`), which is ordinary authorship. See P3-5 for
  related path metadata.

### 7. No application runtime changes

- Nothing outside `development-candidates/trace-eval-correlation/` changed.
- Imports in `src/` are stdlib (argparse, json, hashlib, re, decimal, xml.etree, …) plus
  pydantic only. There is no `backend`, `app` or `advisory_agents` import, and no
  httpx/requests/urllib/socket/LangSmith/provider client.
- `socket` appears only in a test that blocks it. `subprocess` appears only in the
  fixed-argument import probe.
- Writes happen only to CLI `--out`/`--index` paths, and `_refuse_inside_roots` refuses
  evidence roots (`cli.py:100-104`).
- There is no upload, inference, scoring, admission or financial-execution path.

### 8. No unrelated worktree modifications

| Check | Start | End |
|---|---|---|
| Main checkout branch / HEAD | `feat/agent-lab-c22-hybrid-orchestrator` / `a2fdd558…` | same |
| `git diff \| sha256sum` | `8b9b6920…8cc8f` (matches) | same |
| `git status --porcelain \| sha256sum` | `c17cf354…2ec429` (matches, 52 entries) | same |
| Integration worktree `status --porcelain --ignored` | only ignored `__pycache__/` (from the import probe; deleted) | only this file, `?? …/reports/PRE_PR_REVIEW.md` |

### 9. Accepted P3s, re-assessed

Neither creates material integration or publication risk; see P3-6.

## Findings

No P0, P1 or P2 findings.

### P3-1: `.gitattributes` does not repair existing CRLF checkouts, and 5055506 alone does not reproduce
- **Where:** `.gitattributes:3` (commit 579288c); README.md:90-92.
- **Scenario:** A clone with `core.autocrlf=true` that already has 5055506 or 7a03599
  checked out switches to 579288c. Git rewrites only the files that changed (docs and
  `.gitattributes`), so the manifest and index stay CRLF. `git status` is clean, and `verify`
  still reports NOT_REPRODUCED (reproduced above: 38 × `w/crlf`, exit 1).
  - If the PR is rebase-merged, `main` also gets an intermediate commit (5055506) that does
    not reproduce under autocrlf. This matters only to bisect.
- **Fix:** In README, add one line: after updating an older checkout, delete the directory
  and run `git checkout -- development-candidates/trace-eval-correlation`. Prefer a squash or
  merge-commit merge.

### P3-2: `* text eol=lf` forces text mode on every future file in the directory
- **Where:** `.gitattributes:3`.
- **Scenario:** Every file in the directory is binary-unsafe. A later binary added here (for
  example a PNG chart or a zipped evidence bundle) would be EOL-normalised on commit and
  corrupted. No binary exists today.
- **Fix:** Use `* text=auto eol=lf`, or scope the rule to `*.json *.sha256 *.md *.py *.toml
  *.txt`.

### P3-3: Doc statements left stale by the integration edits
- **Where:**
  - `FINAL_REPORT.md:208-209` and `QUALITY_GATE.md:91` say §1 contains the local worktree
    path. 579288c removed that path (FINAL_REPORT.md:17).
  - `FINAL_REPORT.md:18` says the branch is "uncommitted", which contradicts lines 3-4.
  - `FINAL_REPORT.md:85-86` says "tracked files equal a2fdd55".
  - `CHECKPOINT.md:5` says "`git log -1` gives the SHA". On `main` that gives a different
    commit.
- **Scenario:** A PR reader is told a path is present that is not, and sees contradictory
  commit status. The integration note at FINAL_REPORT:10-11 mitigates this, but does not
  correct it.
- **Fix:** Correct these lines in the follow-up docs commit, or list them as superseded in
  INTEGRATION_REPORT.md.

### P3-4: QUALITY_GATE cites JUnit XML evidence that is not in Git
- **Where:** `QUALITY_GATE.md:56` (`reports/pytest-gate3.xml`) and `QUALITY_GATE.md:66`
  ("Failed attempts are preserved. `reports/pytest-attempt3-postreview.xml` …").
- **Scenario:** `reports/*.xml` is gitignored, so on `main` these links are dangling. The
  failed attempt-3 and attempt-4 runs exist only as local XML in the source worktree, with
  no committed `.txt` counterpart. A reader of `main` cannot inspect the preserved failure
  that the document cites.
- **Fix:** Reword to "kept locally only (not in Git; embeds hostname)". Optionally commit a
  hostname-free `reports/attempt3-pytest.txt` and `reports/attempt4-pytest.txt` summary.

### P3-5: Machine-layout metadata in committed files
- **Where:**
  - `manifests/representative.json:5` and `manifests/representative.unpinned.json:5`. The
    `codex_audit` root climbs nine levels to the home directory and names
    `.codex-clean2/worktrees/profile-a-synthetic-isolation/…`.
  - `FINAL_REPORT.md:42` contains the same path.
  - The six review-record lines in section 6.
- **Scenario:** Publishing reveals the home-directory depth, a Codex worktree name and the
  Windows username. None of it is a credential, and the username is already public via the
  commit author.
- **Fix (optional):** Keep the review records verbatim, as accepted by the closure review.
  If desired, set `codex_audit` to `null` in the manifests and require `--root` binding. The
  CLI already supports an unbound root with a usage error.

### P3-6: Accepted P3s re-assessed; no material risk
- **Malformed `.sha256`** (`cli.py:157-160`), probed on a scratch copy with the roots bound:

  | Sidecar | Result |
  |---|---|
  | non-UTF-8 | traceback, exit 1 |
  | directory | `PermissionError` traceback, exit 1 |
  | empty | `NOT_REPRODUCED recorded=UNAVAILABLE`, exit 1 |
  | correct digest, wrong filename or extra tokens | REPRODUCED, exit 0 (the name is not checked) |

  No malformed sidecar ever yields REPRODUCED with a wrong digest. The ignored filename is
  harmless because the digest is recomputed from the index bytes. The only cost is a raw
  traceback.
  - **Fix (later):** catch `OSError` and `UnicodeDecodeError` as `UsageError`, and check
    `parts[1]` against the index name.
- **Campaign manifest without pins:** probed with the synthetic fixtures. I edited a
  receipt's `input_tokens` and re-hashed its entry in the campaign evidence manifest, with no
  pins. The record stayed `JOINED`, `model_performance_evidence=true`, COMPLETE, with no
  finding. This confirms the accepted limitation.
  - It does not affect the committed index, because all three evidence manifests are pinned.
  - README.md:94-96 now documents it, and the adapter has no admission or scoring authority.
  - **Fix (later):** emit a WARNING such as `CAMPAIGN_MANIFEST_UNPINNED` when
    `evidence_manifest` is not in `pins`.

### P3-7: Running pytest from the repository root fails collection
- **Where:** `pyproject.toml:8-11`. `pythonpath = ["src"]` applies only when pytest's rootdir
  is the adapter directory.
- **Scenario:** `python -m pytest development-candidates` from the repository root gives
  `ModuleNotFoundError: No module named 'trace_eval_correlation'`, with 1 collection error.
  `main` has no CI and runs backend tests from `backend/` (`backend/pytest.ini`), and README
  says to run from this directory. So nothing breaks today.
- **Fix (optional):** state "run pytest from this directory, not the repository root" next
  to the commands.

### Observation (not a finding)
The main checkout's AGENTS.md (agent-lab lineage) forbids commits, branches, pushes, PRs and
merges for that assignment. This integration branch and its commits exist, so opening or
pushing the PR needs the owner's explicit authorization. I did not verify that authorization.

## What a fresh clone can and cannot reproduce

**Can reproduce anywhere** (a clone of `main` plus Python 3.12 with pydantic ≥ 2.7, pytest,
ruff and mypy):
- 83 synthetic tests pass, and the 2 historical tests skip as `UNAVAILABLE`.
- ruff and `mypy --strict` are clean.
- `schema` regenerates byte-identically.
- With `core.autocrlf=true`, a fresh checkout is now LF and byte-stable.

**Can reproduce only on the source machine**, or wherever the untracked evidence roots
resolve or are bound with `--root`:
- `verify` REPRODUCED `185013d0…2afc`.
- All 34 pins plus the reference VERIFIED.
- The 36 native joins.

**Cannot reproduce elsewhere:**
- Rebuilding the representative index: `build` gives INCOMPLETE/UNAVAILABLE, exit 2, and
  `verify` gives NOT_REPRODUCED, exit 1.
- The GUARDRAIL_COVERAGE line citations, which refer to the a2fdd55 lineage that is absent
  from `main`.

The committed index is a historical snapshot, and the docs say so.

## Verdict

**PASS.** There are zero open P0–P2 findings.
- The base is sound and provenance is intact: the patch-id and the adapter tree equal
  7a035992.
- The CRLF root cause is real and fixed for fresh checkouts.
- Commit 2 changes no code or data.
- All gates pass, and evidence integrity is independently confirmed.
- No runtime or application surface changed, and no unrelated worktree changed.

P3-1 to P3-7 are recommended doc and hardening follow-ups, and none blocks the PR.
