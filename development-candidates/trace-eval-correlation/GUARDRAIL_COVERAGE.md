# Clarifier / Orchestrator guardrail coverage (course-aligned)

Mapping only; no guardrail was added or changed in this assignment. Source references are
to the locally developed agent-lab lineage at commit `a2fdd55` (`backend/src/advisory_agents`)
unless marked otherwise.

**That lineage is not part of `main`.** When this adapter was integrated, `main` contained no
`backend/src/advisory_agents`, so the cited files and line numbers cannot be checked from a
clone of `main`. Read this table as a dated record of that lineage, not of `main`.
"Audit" = Codex `GUARDRAILS_TRACES_EVALS_COVERAGE.md` (sha256 `bc590650…e2ea9`), read-only.

Status: **IMPLEMENTED** — enforced in code and cited; **IMPLEMENTED (isolated)** — exists
only in V9/Profile A candidate trees, not the canonical lab; **GUIDANCE** — prompt text,
not enforcement; **PARTIAL** — exists with material gaps; **NOT IMPLEMENTED**; **UNVERIFIED**
— claimed elsewhere, not re-checked here.

| Category | Clarifier | Orchestrator | Gap / evidence limit |
|---|---|---|---|
| Prompt-level behavioural guardrails | GUIDANCE — versioned prompts (`prompts/clarifier-v91…v943.txt` in V9 candidate trees). This index verifies which file each native request embedded. | GUIDANCE — `orchestrator-v91/v93.txt`; same verification. | Prompts instruct; they do not enforce. Schema validity is not injection resistance (Audit). |
| Explainability / uncertainty | IMPLEMENTED — `Objective.missing`, `contradictions`, `readiness` (`backend/src/advisory_agents/contracts/__init__.py:63-65`). | IMPLEMENTED — `PlanProposal.reason`, max 500 chars (`contracts/__init__.py:99-101`). | Rationale quality is judged only by independent prose assessment (copied into the index as `independent_assessment_status`), not by code. |
| Reflection / critique | NOT IMPLEMENTED — no self-critique or reflection step found in `backend/src/advisory_agents`. | NOT IMPLEMENTED. | Independent human/agent review of outputs is evaluation, not a runtime reflection loop. |
| Structured output and deterministic validation | IMPLEMENTED — `Wire` models `extra="forbid"`, `strict=True` (`contracts/__init__.py:25`); typed mutation in `clarifier/graph.py:58-99` (Audit). Native strict JSON schema per request (`response_format_sha256` in index). | IMPLEMENTED — `orchestrator/admission.py:5` `validate_plan` (unconfirmed, duplicate, forbidden, dependency, cycle). | Canonical admission still allows optional→required promotion (Audit). Hardened R1/R2 is IMPLEMENTED (isolated). |
| Tool / action access controls | IMPLEMENTED (structural) — the Clarifier service has no dispatch path: `clarifier/app.py:1-15` and `graph.py:1-8` import no specialist client or registry, and model output is applied only through `ObjectiveUpdate`. Observed data agrees: `effect_classification` is `NO_EXTERNAL_EFFECT` for all 37 observed rows (both agents); that is observation, not the control. | IMPLEMENTED — `registry.py:20-22` owns endpoints ("model output never supplies this endpoint authority"); executor dispatches only admitted plans (`orchestrator/graph.py:123-238`). | Real specialists NOT_ASSESSED; mock HTTP only. |
| Human confirmation / approval | IMPLEMENTED — `clarifier/app.py:124-149` confirm requires matching `revision` and `content_digest`. | IMPLEMENTED — admission rejects unconfirmed objectives (Audit). | PARTIAL overall: no authenticated real confirmer or review receipt at the application seam (Audit, G-1). |
| Trace observability | IMPLEMENTED — `telemetry.py:29,66` allowlists (`SAFE_FIELDS`, `SAFE_EVENTS`); `record()` returns False with a safe warning on outage (`telemetry.py:177-184`). Native campaigns keep SESSION/AGENT/LLM spans. | Same. | PARTIAL: base telemetry lacks case/prompt/source hashes; this adapter correlates only V9 native span files. LangSmith cloud correlation not established. |
| Model-quality and safety evaluations | IMPLEMENTED (isolated) — V9.3 (12 Clarifier attempts) and PAIR (12 attempts, stopped) native evaluations with frozen datasets and independent prose review; indexed here. | IMPLEMENTED (isolated) — V9.3 12 Orchestrator attempts; eval-v3 local runs incl. 4 injection cases, all ADMISSION_REJECTED (Audit). | Small samples, single provider, no statistical claim. Injection, recovery and real-data privacy scenarios remain unexecuted (Audit). |

Offline tests (V9.4.3, 87 JUnit nodes) are indexed as `OFFLINE_TEST` and carry no model
fields; they are regression evidence, not model performance.
