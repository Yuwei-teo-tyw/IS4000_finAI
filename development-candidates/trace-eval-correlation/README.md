# Trace–Eval Correlation Adapter (offline, metadata-only)

A sidecar index that links existing Clarifier/Orchestrator evaluation rows to the execution
evidence they came from: case → agent span → LLM span → request receipt → score →
independent assessment → artifact hashes. It reads historical evidence read-only. It does
not score, admit, replay, upload or own any state.

## Reviewed V3 integration state

V3 and its remediation are committed and locally integrated on
`codex/trace-eval-v3-latest-main` at reviewed HEAD
`94b73581f25d555825553186bff5d26cbf4771e0`, based on fetched main
`6a34a69e70b89aed93065e2d8a9e236fc2e1071f`. The independent pre-PR gate returned
`V3_PREPR_QG_PASS_READY_FOR_OWNER_PUBLICATION_REVIEW`. This local integration has
not been published or merged into main. The QG-1 documentation correction is
uncommitted and awaits independent delta review; no publication is authorized.

## Commands

Run from this directory with any Python 3.12 environment that has `pydantic>=2.7`; tests
also need `pytest`, and the quality checks need `ruff` and `mypy`. On `main`,
`backend/requirements.txt` and `backend/requirements-dev.txt` provide pydantic, pytest and
ruff, but not mypy. The adapter is not installed and imports nothing from `backend/`.

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
index remains a record of what that evidence contained when pinned on 2026-10-27.
Separately, five V3 archive checks require `TRACE_EVAL_V3_ROOT`; missing access deliberately
fails them with an `UNAVAILABLE` reason. Synthetic fixture tests run in temporary directories.
JUnit XML gate outputs are kept locally only (they embed the machine hostname);
`reports/gate*.txt` carry the results.

All **62/62 V3 source files are absent** from the fetched main tree identified above;
this candidate does not add those archives or prepared inputs. Reproducing the archived
V3 index requires external evidence-root provisioning: bind a root containing all pinned
files with `--root evidence=<repository-with-archived-V3-evidence>` for CLI commands and
set `TRACE_EVAL_V3_ROOT` to that root for the required tests. A fresh clone alone cannot
rebuild either historical index. Evidence delivery or publication needs a separate owner
decision; local reproduction does not make the sources available to teammates.

## Fresh clone: what reproduces

The independent pre-PR gate recorded these full-adapter results at reviewed HEAD;
the two historical-source tests remain unavailable from the isolated review location:

| Scope | Needs | Observed result |
|---|---|---|
| Full adapter tests without V3 root | This directory and test dependencies; `TRACE_EVAL_V3_ROOT` unset | 123 passed, 5 failed, 2 historical-source skips (`UNAVAILABLE`); exit 1. |
| Full adapter tests with explicit V3 root | All 62 pinned V3 files and `TRACE_EVAL_V3_ROOT` set | 128 passed, 2 historical-source skips (`UNAVAILABLE`); exit 0. |
| V3 index reproduction | External V3 evidence root bound with CLI `--root evidence=...` | `build` and `verify` reproduce the committed V3 index byte for byte. |
| Representative index reproduction | External historical campaign and audit roots bound with CLI `--root` overrides | `build` and `verify` reproduce the committed representative index byte for byte; this is separate from the skipped pytest checks. |
| Portable static checks | This directory and Python/tool dependencies | `schema` regeneration, Ruff lint/format and strict mypy pass without historical evidence. |

The five V3 failures without access are deliberate fail-closed required-verification
failures, not successful checks or optional skips. The two historical-source skips are
not passes. Their relative-root portability remains deferred (P3-7); provision explicit
CLI roots for representative reproduction. See [V3_HANDOFF.md](V3_HANDOFF.md) for commands.

The committed indexes are historical, source-dependent snapshots. The adapter-local
`.gitattributes` forces LF line endings. Without it, `core.autocrlf=true` checkouts change
the manifest bytes, and so the embedded `manifest_sha256`, which breaks byte verification.

Trust anchors: per-request files are anchored only by each campaign's own evidence
manifest. That manifest is pinned in `manifests/representative.json`. A new manifest that
lists a campaign manifest but omits its pin gets no warning, so pin it with `pin`.

## Orchestrator V3 archive

`manifests/orchestrator-v3.json` declares the `orchestrator_eval_v3` source kind.
Bind `--root evidence=<repository-with-archived-V3-evidence>` when building or verifying
`index/orchestrator-v3-index.json`. See [V3_HANDOFF.md](V3_HANDOFF.md) for commands.
Every archive-listed path and hash is validated, including the two HTTP receipts;
non-evidence content is neither parsed nor copied into the index.

For this source kind, `trace.trace_id` contains a **synthetic correlation label**, such as
`v3-primary-dev-v3-01-4b`, not a verified execution trace ID. Historical native campaign
records use this field for verified trace identity only when their span joins verify.
V3 labels establish no real agent/LLM spans and must not be automatically joined to
LangSmith runs. All intact V3 records remain `PARTIAL` and performance-ineligible,
including when declared `NATIVE`; complete artifact verification does not prove
end-to-end agent capability. No schema version change is introduced.

## Not in scope

No second ledger or scorer, no admission or policy change, no LangSmith/cloud upload, no
provider calls, no import of another checkout's runtime modules. Base
`assurance/traces/events.jsonl` telemetry remains unadapted. V3 support is limited to the
offline archive reader described above; it adds no runtime integration.
