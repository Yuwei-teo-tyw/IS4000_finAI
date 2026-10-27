# Trace–Eval Correlation Adapter (offline, metadata-only)

A sidecar index that links existing Clarifier/Orchestrator evaluation rows to the execution
evidence they came from: case → agent span → LLM span → request receipt → score →
independent assessment → artifact hashes. It reads historical evidence read-only. It does
not score, admit, replay, upload or own any state.

## Commands

Run from this directory with the repository's Python 3.12 interpreter
(`backend/.venv` of the main checkout supplies `pydantic`). Nothing is installed.

```bash
PYTHONPATH=src python -m trace_eval_correlation pin    --manifest manifests/representative.unpinned.json --out manifests/representative.json
PYTHONPATH=src python -m trace_eval_correlation build  --manifest manifests/representative.json --index index/representative-index.json
PYTHONPATH=src python -m trace_eval_correlation verify --manifest manifests/representative.json --index index/representative-index.json
PYTHONPATH=src python -m trace_eval_correlation schema --out schema/trace-eval-index-1.0.schema.json
```

- `--root NAME=PATH` rebinds a manifest root (evidence moved, another machine). Relative
  root paths resolve against the manifest's directory; the representative manifest uses
  relative roots from this worktree. The index stores only root-relative references
  (`main_dev_candidates:v9.3-readiness/...`), never absolute paths.
- `build` exits 0 when `index_status` is `COMPLETE`, 2 when `INCOMPLETE` (index still
  written; integrity loss is evidence), 64 on usage errors. It refuses to write inside any
  bound evidence root.
- `verify` rebuilds in memory and requires byte equality with the index and its `.sha256`.
- `pin` records the current sha256 of every consumed file; a later difference is `STALE`.

## Contract (`trace-eval-index/1.0`)

Schema: [schema/trace-eval-index-1.0.schema.json](schema/trace-eval-index-1.0.schema.json);
models in [src/trace_eval_correlation/schema.py](src/trace_eval_correlation/schema.py).

| Value | Meaning |
|---|---|
| `NOT_APPLICABLE` | The concept does not exist for this record (tokens of an offline test, request of a preflight row). |
| `UNAVAILABLE` | It should exist but the evidence does not provide or verify it. Never replaced by 0. |

Evidence classes: `NATIVE` (real request with receipt), `NON_NATIVE_PREFLIGHT` (stopped
before any send), `NOT_RUN`, `OFFLINE_TEST` (JUnit node), `SYNTHETIC_FIXTURE` (native-shaped
evidence the manifest declares synthetic). `model_performance_evidence` is true only for
`NATIVE` records whose every join verified; it is eligibility, not a quality verdict.

Verified joins per native record: receipt directory ↔ `request_id`; receipt
`request_sha256` ↔ request.json bytes ↔ LLM span `request_sha256`; receipt `llm_span_id`
↔ LLM span; LLM span parent = AGENT span of the same case, whose root is the SESSION span
(`trace_id`); `public_output_sha256` ↔ public-output.txt; assessment `observation_sha256`
↔ compact-sorted JSON of the observation row; assessment `rubric_sha256` ↔ rubric file;
prompt file text (CRLF-normalised) embedded in the request messages. Every consumed file
(including every prompt candidate) is checked against the campaign's own evidence manifest
and this manifest's pins; a missing declared file is `SOURCE_FILE_MISSING`. Any source-level
integrity error, an unlisted or missing file, or a source with neither campaign manifest nor
pins adds `SOURCE_INTEGRITY_GAP` to that source's records, so none of them counts as model
performance evidence. Per-request files (receipt, request, public output) are anchored only
by the campaign manifest; `pin` does not pin them. Without a campaign manifest a native
record is therefore `ARTIFACT_UNANCHORED` and never counts as model performance evidence. Source-level
cross-checks: native attempts, summed provider-reported cost (exact decimals), planned rows,
frozen-dataset file hashes, JUnit test counts.

Copied fields are an explicit allowlist of scalars. Human text, model output, displays,
rationales, request messages and provider account metadata are never copied (JUnit
test-node IDs are copied verbatim and may contain parametrised test text); a pattern
filter redacts credential- or identifier-shaped strings that survive and reports only the
field path.

## External evidence dependency

The historical evidence named by `manifests/representative.json` (V9.3, V9.4.2/V9.3 B
paired and V9.4.3 directories under the main checkout's untracked `development-candidates/`,
and the Codex audit report in a separate worktree) is **not tracked in Git and is not
packaged by this commit**. A clone without those directories cannot rebuild or `verify`
the representative index: `build` reports the sources UNAVAILABLE and
`tests/test_historical_evidence.py` skips with an `UNAVAILABLE` reason. The committed
index remains a record of what that evidence contained when pinned on 2026-10-27. All other
tests use synthetic fixtures written to a temporary directory and run without the
historical evidence. JUnit XML gate outputs are kept locally only (they embed the machine
hostname); `reports/gate*.txt` carry the results.

## Not in scope

No second ledger or scorer, no admission or policy change, no LangSmith/cloud upload, no
provider calls, no import of another checkout's runtime modules. Base
`assurance/traces/events.jsonl` telemetry and orchestrator-eval-v3 local runs are not yet
adapted (see [FINAL_REPORT.md](FINAL_REPORT.md)).
