# Optional frontend publication gates
Goal: publish only advisory-browser from reviewed source onto latest main, then
squash merge only after independent PASS and all GitHub requirements are satisfied.
Baseline: source 8e8116affbdf021c024bf59d5086f3b945952432 (implementation 0f38f72225f90c79e7f4bbc1e16511399877af9c),
main cae7c8e16d466baa3ab514bcd2939d8675aa08d5, frozen v5 tree unchanged.
TaskStartSnapshot: original frontend clean, C2.2 and sync inventories saved privately;
no active Git operation; local rollback codex/rollback-advisory-browser-mvp-20261017.
New attached native integration worktree, branch feat/advisory-browser-mvp-main,
starts at freshly fetched main. Only the two verified frontend commits cherry-picked.
Scoped attributes caused six checkout-only JSON newline differences; exact committed
bytes restored in this new task-owned checkout before portability edits.

Change necessity: tracked developer-specific config prevents actionable teammate
setup. Minimal boundary: ignored local config + blank tracked example, consumers,
package manifest, setup docs and focused tests; remove developer tool paths from
browser-test defaults. No fallback project selection or duplicate state owner.
Architecture: optional sidecar to separately approved v5 runtime. Main legacy React,
Market Researcher, backend/database startup/dependencies remain byte-identical.
TDD route off; focused behavioral tests, actual HTTP/browser and lifecycle checks.
Tasks: recover/inventory; portable setup; fresh tests/reviews; rebuild ZIP/manifest;
publish only this branch and draft PR; re-fetch refs/CI/approvals; fresh independent
pre-merge verdict; squash only through normal GitHub enforcement if all gates pass.
Stop at open PR if any material required gate is unsatisfied. No bypass/force-push,
main direct push, real inference/cloud/provider calls or backend migration.

## Fresh local candidate evidence
- Latest fetched main still cae7c8e16d466baa3ab514bcd2939d8675aa08d5; no upstream
  delta since prior assessment. Main source/dependency/database/React/Market blobs
  unchanged; new code stays only under advisory-browser.
- 39 focused tests passed locally and independently; lint/format pass.
- Actual browser Goal -> Risk SUCCEEDED, exactly two correctly bound MOCK results;
  explicit confirmation/admission, lost-plan-response recovery, page-refresh no replay.
- Deliberate duplicate plan-bound idempotency request returned the same existing run
  with exactly two specialist POST events; no extra dispatch or automatic retry.
- Candidate START/CHECK/STOP passed, all four owned service exit codes zero.
  Real unavailable-backend UI and cancellation/partial/failure response fixtures pass.
- Internal token absent from browser responses; configuration example is blank,
  local config ignored, no real credentials/model/cloud services used.
- Original cached demo ownership was stale (zero cached owned PIDs alive). Its STOP
  correctly returned SHUTDOWN_UNVERIFIED instead of terminating by name/port/PID.
  This failed old-instance observation is separate from the clean new-candidate
  lifecycle and has not been rewritten as a passing shutdown.
- Original tracked source/config, frozen v5 and historical evidence remain preserved.
  Fresh synthetic service-owned state and lifecycle/audit records are additive.
- Independent source reviewer found no source defects and independently passed 39
  tests. Overall source verdict was CONDITIONAL pending fresh release proof; final
  archive/extracted-copy review follows below. No historical receipt is treated as
  proof for changed candidate bytes.

## GitHub gate status before publication
Authenticated collaborator has push permission, not admin/maintain. Squash merging
is enabled. Main reports protected=true; summary lists non-admin required status
contexts/checks empty, while detailed REST protection is unavailable (404), GraphQL
classic protection rule is null/zero rules, and visible branch rules/rulesets are
empty. No open main PR and no repository .github CI workflow was found at preflight.
These partial protection readbacks do not constitute required-team approval.
Final PR/CI/approval state and a fresh independent pre-merge verdict must be checked.
If a required gate cannot be established, leave an open draft PR; no bypass,
admin/force merge, direct main push or merge-until-green is authorized.

## Portable ZIP and preservation proof
The rebuilt portable candidate archive contains the blank example and no local
configuration. An extracted copy rejected startup with actionable instructions
until its own ignored local config was explicitly provisioned. START/CHECK/STOP
then passed; all four owned services exited zero. Final executable/runtime/config
example members are byte-identical to that extracted smoke. Archive/source-manifest
members/hashes are rebuilt and re-read after release metadata changes.
Original frontend, C2.2 and sync source/evidence inventories, HEAD and Git status
remain unchanged, including hashed credential-file preservation. Approved tests
append fresh synthetic service-owned session/audit/lifecycle records; no historical
records were reset, deleted or committed. No frozen backend is included in this PR.

## Independent local gate verdict
Fresh read-only reviewer /root/publication_source_review returned
**PASS — OPTIONAL FRONTEND-ONLY INTEGRATION**, no unresolved P0-P2, after inspecting
current source, fresh browser/lifecycle/preservation receipts and independently
reading every member/hash of the portable ZIP. Its independent 39-test run passed.
This permits branch/PR publication only. GitHub requirements and a separate fresh
pre-merge verdict remain required before squash. Final commit/PR/merge state is
recorded externally rather than pretending that local readiness is an actual merge.
