> Historical local rehearsal from the original MVP assignment. The current optional latest-main publication is assessed in PUBLICATION.md and evidence/publication-*.

# Frontend-only integration assessment

Target A verdict: **SAFE TO INTEGRATE FRONTEND-ONLY** into an independently
preserved representation of current C2.2. Do not cherry-pick into the active dirty
checkout without separately preserving its state and an explicit integration action.
Target B verdict: **CONDITIONAL** for latest fetched upstream main. Textual
integration is clean; this package requires the existing v5 runtime/Python setup.
This is not approval or compatibility evidence for merging the entire C2.2 branch.

## Exact identities and isolated candidates

- Frontend branch: feat/advisory-browser-mvp.
- Verified base: `a2fdd558f7c8de3a634375f041f5af9eb84cc675`.
- Reviewed frontend implementation commit: `0f38f72225f90c79e7f4bbc1e16511399877af9c`.
- C2.2 branch: feat/agent-lab-c22-hybrid-orchestrator, same base HEAD,
  with pre-existing seven tracked backend modifications and untracked v5/evidence.
- Exact current C2.2 snapshot tree: `32ee00a2fe4118e157418c0ce8f370e27fa1feef`;
  954 non-private tracked/untracked source/evidence files.
- C2.2 plus frontend candidate tree: `980e715215f7e2a2e49d4778fca112eba83e4d6a`.
- Previously fetched main: e6916146aba689539211fd77f2f5ddae52cffe44.
- Latest fetched origin/main: `cae7c8e16d466baa3ab514bcd2939d8675aa08d5` (two newer commits).
- Main plus frontend candidate tree: `81265a521c4a65c576c291e4464ccfdfc4d6b71f`.
- Common ancestor: `285cb74551525704ea173633fb44c698be2cd4a7`; ten upstream commits, 81 changed paths,
  29 paths already present at the original common-ancestor baseline.

Candidate identities above are Git **trees**, not merged commits. No merge or
cherry-pick was performed on either target, and no C2.2 snapshot commit was made.
Original active index/worktree and original/sync assessment refs remain preserved.
The sync assessment remains detached at a2fdd558f7c8de3a634375f041f5af9eb84cc675
with its pre-existing rehearsal modifications; this task did not change it.

## Rehearsal method and measured result

Temporary GIT_INDEX_FILE indexes read the baseline/snapshot. The exact reviewed
frontend commit delta (`git diff --binary --full-index BASE COMMIT -- advisory-browser`)
was checked and applied with `git apply --cached --check` and `git apply --cached`.
The source snapshot uses exact raw blobs, with no .env, private database, virtualenv
or ignored runtime copied. Archive-backed historical source records remain intact.
The first tooling attempt failed on Windows long paths; it is preserved separately.
The successful attempt used process-local core.longpaths=true and git cat-file.

| Candidate | Textual conflicts | Changed paths | v5 pins | Focused tests |
|---|---:|---:|---:|---|
| Current C2.2 snapshot + frontend | 0 | 51 additive frontend paths | 559 exact | 30 passed |
| Fetched main + frontend | 0 | 51 additive frontend paths | External v5 runtime required | 30 passed |

Frontend/upstream path overlaps: **0**. No existing frontend,
backend/app, backend/tests, dependency, Docker, authority, policy or contract path
is part of the frontend commit. Both candidate test runs used the existing Python
3.12 environment and verified external frozen runtime, not standalone main services.
This proves the sidecar transport/presentation compatibility boundary only.

A final release metadata follow-up adds scoped byte-preserving .gitattributes,
manifest/report/evidence updates and the packaging allowlist entry. It remains
inside advisory-browser and changes no runtime/API behavior. Final Git receipt
identifies the follow-up commit; it does not claim these tree objects are commits.

## API and semantic compatibility

Actual HTTP operations are maintained v5 /v1/sessions, objective/messages/confirm,
/v2/plans, /v2/planning-attempts, /v1/runs, run/events/cancel, plus /ready. Source tree
is 1a196f3645d26cfaaeddf4952bf79a1a0175c7d398fb6a1277cfb856b4de8995; frozen manifest
20d3c77640a9a0e973246acae346d5bdb0865b1fb2a79394e02fc59a86e6d33c.
The backend owns revision/context/digest confirmation, admission, canonical bindings
and execution status. The adapter injects authentication server-side and never
imports legacy app/database startup. Frontend state grants no execution authority.

Upstream's existing React frontend uses /agents/langgraph WebSocket and /sessions.
It is preserved. Upstream adds Market Researcher routing, Postgres cache/tables/run
registry, interrupted-run recovery and shutdown behavior. Requirements add httpx,
yfinance/trafilatura (dev: ruff); docker comments describe persistent market outputs.
None of those changes are imported or run by this browser package. Their database,
provider, dependency and application compatibility remains unverified here.
The latest fetched main's organizational approval status was not established.
Zero textual conflicts therefore does not establish full-application compatibility.

## Recommended integration and remaining owner decisions

1. Retain the reviewed frontend commit(s); never merge all C2.2 history for this UI.
2. Use an isolated, independently verified current C2.2 snapshot/candidate for any
   later frontend-only integration. Preserve active uncommitted work first.
3. For main, accept the explicit external v5 sidecar dependency or separately
   authorize a reviewed runtime distribution. Do not copy frozen backend pins
   into this ZIP or overwrite teammate Market Researcher code.
4. Legacy database/startup/dependency acceptance and historical Gate B/C are separate
   work. Do not interpret this frontend READY as their closure.
5. Publication, PR, push and target-branch integration require a separate decision.

No remote publication occurred. No target ref, active index or source was changed
by the rehearsal. Only temporary tree/blob objects and task-private candidates were
created. Original credentials/evidence remain byte-preserved.
