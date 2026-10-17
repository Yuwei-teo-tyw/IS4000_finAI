# Browser MVP implementation plan
Goal: fulfill the complete user browser MVP specification supplied 17 October 2026.
Architecture: additive offline assets, fixed-operation same-origin HTTP adapter,
small process-owning launcher. Existing backend owns all business state/admission.
Tech stack: HTML/CSS/vanilla JS; existing Python 3.12/FastAPI/Pydantic/httpx/uvicorn.
Baseline/authority: a2fdd558f7c8de3a634375f041f5af9eb84cc675; root/backend AGENTS;
docs/agent-lab/implementation.md; C2.0 contract specification and C2.1 policy design;
maintained Clarifier, Orchestrator, Console, v1/v2 contracts; demo-readiness guide,
configuration/check/guard; local/upstream React frontend. Required sources read.
Compatibility: all frozen v5 pins, original frontend and active dirty C2.2 preserved.
TDD route: off/skipped; behavioral regressions, real HTTP and observed browser QA.
Verification: pytest, ruff, real journey, source preservation, start/check/stop,
ZIP hash/member verification, fresh independent source/security and journey reviews.

Requirement readiness: ready; user specification explicitly authorizes frontend,
new local branch/worktree, reviewed local commits and independent reviews.
Change necessity: legacy frontend targets separate WebSocket/database API; a
working browser needs presentation and authenticated transport. Minimum boundary
is advisory-browser only. No canonical backend operation is reimplemented.
Existence check: lightweight separate package justified by incompatible legacy API
and offline/no-install requirement. Retire adapter after accepted unified frontend
adopts v5 HTTP contracts and server-side authentication. No fallback owner.
Architecture integrity: canonical API owns objective/revision/digest, admission,
policy and execution. Adapter only validates bounded transport. No model calls.
Complexity budget: separate runtime identity/config, transport, lifecycle, browser
state/rendering/styles and tests. One responsibility per file. No large framework.
Plan pressure test: user scenarios and source freeze define verification; proceed.

Tasks:
1. Preserve initial inventory and verify byte-exact runtime/source/dependencies.
2. Implement fixed-schema transport and synthetic process-owning local launcher.
3. Implement responsive Clarifier, confirmation, dynamic plan, run/event/results.
4. Test A-D, refresh/duplicate protection, keyboard/layouts, lifecycle and archive.
5. Fresh independent security and journey review; resolve all P0-P2 before READY.
6. Reviewed frontend-only local commit; isolated C2.2/upstream integration assessment.

Execution readiness: intent locked to supplied MVP; scope advisory-browser only;
baseline above; no frozen/backend/legacy changes; no inference/tracing/providers;
no historical campaign/ledger use. All confirmation/admission backend-owned.
Execution route: inline; fresh independent review agents explicitly user-requested.
Checkpoint in CHECKPOINT.md. Preserve failed attempts. Stop on user mandatory gates.
TaskStartSnapshot: active feature branch at baseline with seven tracked dirty paths
and untracked C2.2 evidence. Existing original/sync assessment untouched. Native
create_worktree attached isolated checkout under Codex worktrees; suggested sibling
was optional. New feat/advisory-browser-mvp starts at verified baseline, clean.
Default cwd remains original; every write explicitly targets attached worktree.
Coordinator retains isolated worktree for user testing; no automatic cleanup.
