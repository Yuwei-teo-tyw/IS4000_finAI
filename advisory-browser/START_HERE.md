# finAI Advisory Browser MVP

This local demonstration depends on the existing project Python 3.12 virtual
environment and its verified isolated frozen v5 runtime. **It is not standalone.**
No installation, Docker, model download, real credentials or cloud account is needed.

1. Extract the ZIP into a normal writable local folder (or use this worktree folder).
2. Check `demo-config.json`: `project_root` must point to the existing IS4000_finAI
   project containing `demo-readiness/session.json` and `backend/.venv`.
3. Close old manually started demo services with Ctrl+C in their own terminals.
4. Double-click **START_ADVISORY_DEMO.cmd**. Wait for READY and the browser window.
5. When finished, double-click **STOP_ADVISORY_DEMO.cmd**. Use
   **CHECK_ADVISORY_DEMO.cmd** to inspect source identity and readiness.

The launcher opens http://127.0.0.1:8820. It starts the maintained Clarifier (8811),
Orchestrator (8812), synthetic mock specialists (8890), and browser adapter (8820).
All bind to 127.0.0.1. An occupied unowned port is a HOLD, never killed or adopted.
Do not change ports or add credentials. All Python children use the existing
outbound guard. The CMD files invoke PowerShell command mode to locate Python;
no execution-policy change, installation or organization-policy bypass occurs.

## Your first synthetic goal

Click **New objective**. Paste into the chat:

> I want to reach SGD 200000 from SGD 50000 with SGD 1000 monthly in 10 years.

Send. The brief should show goal, SGD, target 200000, current 50000, contribution
1000/month and 120 months; readiness READY. Review it, then click **Confirm this
objective**. Only a backend CONFIRMED result enables **Generate Advisory Plan**.
Inspect the returned Goal task and the Risk task that depends on Goal. Planning
alone dispatches nothing. Click **Execute Mock Workflow** once. Inspect actual run
status, two MOCK result cards and execution events. SUCCEEDED must come from the
backend. Neither HTTP 200 nor a green connection badge certifies a successful run.

Open Execution evidence to inspect identities, bindings and structured output.
It is synthetic routing/contract evidence, not a financial recommendation.

## Corrections and other supported scenarios

Start a new objective with `I want to reach SGD 200000.` to see missing fields.
Supply the missing fields in chat, or use **Correct a supported field**. All
corrections go through the existing Clarifier message API; any new revision
invalidates old confirmation and plan selection. Scripted correction supports
amounts, SGD/USD/EUR/GBP currency, horizon in months, and comparison text. Family
changes use natural messages recognized by the backend, for example `Review my
portfolio` or `Compare investing alternatives`. Constraints are shown read-only:
the scripted parser has no accepted constraint-update operation. No field editor
bypasses that limitation. Review actual returned fields after every change.

Other returned plans are rendered from actual tasks/dependencies, including
independent prerequisites. Array order alone does not imply task execution order.

## Refresh, history and uncertain outcomes

Browser storage retains only synthetic presentation/selection data, never the
internal token. **Refresh state** rereads the current objective, attempt, run and
events. Page reload never resends a message, plan or execution. An execution is
marked submitted before sending; on timeout its outcome remains unknown until
inspection. Do not repeat the execution in another browser tab. This MVP is a
single-operator, single-browser-tab demonstration, not a multi-user application.

A new session retains prior backend evidence. **Reset browser presentation only**
clears this browser's selection; it does not delete any backend state. Prior
session/run identifiers remain in backend evidence but this MVP does not provide
a cross-session history catalog. Before resetting, note IDs if needed.

## Startup, shutdown and failures

Each launcher instance keeps `.runtime/<instance>/lifecycle.jsonl` and source
identity. Service data, checkpoints, attempts and network audit stay in the
existing isolated demo runtime under the project. Neither is erased on restart.
The stop command creates an instance-specific shutdown request; owned Python
wrappers request uvicorn graceful exit. There is no process-name, port or recycled
PID termination. If shutdown cannot be verified, the status remains HOLD and the
launcher does not force-kill a process. Keep the evidence and inspect locally.

If start says PORT_OCCUPIED_UNOWNED, stop the previously started demo in its own
terminal. If CHECK says unavailable, do not execute; inspect startup status, stop
the owned demo and restart once the problem is understood. A stale launch lock
requires local inspection, not automatic deletion. No non-idempotent request is
automatically retried. Authentication/validation errors show bounded safe codes.

Manual diagnostic fallback from this folder, using the project Python executable:

```
<project>/backend/.venv/Scripts/python.exe -B launcher.py start --no-browser
<project>/backend/.venv/Scripts/python.exe -B launcher.py check
<project>/backend/.venv/Scripts/python.exe -B launcher.py stop
```

## Scope and limits

- Scripted Clarifier is deterministic parsing, not an LLM evaluation.
- POLICY_ONLY is deterministic; browsers cannot override trusted mode.
- Specialists are MOCK; no financial analysis or recommendations are produced.
- Real Market Researcher is not connected; Product Specialist is NOT_IMPLEMENTED.
- Historical C2.2 Gate B/C findings remain open and outside this MVP's verdict.
- Legacy React/WebSocket frontend is preserved and is not used by this package.
- Loopback synthetic authentication is a personal demo boundary, not production
  identity, authorization or a protection against a malicious local OS user.

See `evidence/` and `RELEASE_NOTES.md` for the actual tested/reviewed release status.
A visual preview is not a READY verdict; unresolved P0-P2 keeps the package on HOLD.
