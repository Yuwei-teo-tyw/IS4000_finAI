# Checkpoint — trace-eval-correlation (2026-10-27)

**Status: `LOCALLY_COMMITTED_AWAITING_INTEGRATION_DECISION`.** The adapter is in one local
commit on branch `feat/trace-eval-correlation-offline` (worktree
`…/Proj/IS4000_finAI-trace-eval`, parent a2fdd55). `git log -1` gives the SHA. The fresh
closure review passed (`reports/CLOSURE_REVIEW.md`).

## Done

1. Preflight: main checkout state and hashes recorded, and the worktree created.
2. Evidence recovered read-only: V9.3, PAIR, V9.4.3 and the Codex audit.
3. Adapter, schema 1.0, CLI (`pin` / `build` / `verify` / `schema`) and the representative
   index. The index is COMPLETE, with 159 records and sha `185013d0…2afc`.
4. 85 tests, ruff, strict mypy and offline reproduction: all pass.
5. Guardrail coverage mapping.
6. Independent review in two attempts. All P0–P2 findings are resolved.

## Resume or re-verify

Run from this directory:

```bash
PYTHONPATH=src ../../../IS4000_finAI/backend/.venv/Scripts/python -m pytest -q
PYTHONPATH=src ../../../IS4000_finAI/backend/.venv/Scripts/python -m trace_eval_correlation verify --manifest manifests/representative.json --index index/representative-index.json
```

## Open decisions for the owner

- Whether to add readers for canonical `events.jsonl` telemetry and orchestrator-eval-v3.
  This would need instrumentation that adds case and prompt hashes to base telemetry events.
- Whether to integrate the branch. It is committed locally only: no push, PR or merge.
- Whether to address the accepted closure-review P3s (QUALITY_GATE.md).

## Invariants for anyone continuing

- Never write inside an evidence root.
- Never copy human, model or review free text. JUnit test-node IDs are the one exception: they are
  copied verbatim and may contain parametrised test text.
- Never turn UNAVAILABLE into 0.
- Never compute or alter scores.
- Re-run `pin` only when deliberately rebinding evidence. Pins exist to detect drift.
