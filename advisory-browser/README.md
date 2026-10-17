# Optional Advisory Browser MVP

**Optional sidecar — not standalone.** This directory does not change the existing
React/WebSocket application, Market Researcher, backend dependencies or Postgres
startup. It calls a separately provisioned, approved `engineering-authority-v5`
synthetic lab over fixed loopback HTTP. A normal checkout of main does **not**
contain that runtime or its Python environment. Missing setup is UNAVAILABLE,
not a working demo or an invitation to copy unreviewed backend source into main.

## Required external setup

Ask the v5 runtime owner to provision an approved local project with:

- Python 3.12 at `backend/.venv/Scripts/python.exe`, with its already approved
  FastAPI/Pydantic/httpx/uvicorn/LangGraph dependencies installed.
- All 559 frozen v5 source pins, manifest and archive/review metadata; source tree
  `1a196f3645d26cfaaeddf4952bf79a1a0175c7d398fb6a1277cfb856b4de8995`.
- `demo-readiness/session.json`, `check.py` and the approved outbound guard.
- The isolated 562-file frozen runtime identified by that session, under the
  external project's `backend/.lab-data/demo-readiness/`, with no backend `.env`.
- Its locally provisioned synthetic internal token and service-owned synthetic
  state. Do not use real provider keys, real customer data or a real `.env`.

This PR does not distribute or migrate that backend. A teammate without it must
obtain an approved runtime distribution from its owner; that is a separate action.
The frontend does not install dependencies, download models or call cloud services.
The existing frontend and real Market Researcher remain available through their
original application; this sidecar does not connect to the real Market Researcher.

## Configure this machine once

1. Copy `demo-config.example.json` to `demo-config.local.json` in this directory.
2. Set its sole `project_root` field to the **absolute local path** of the approved
   external v5 project. The tracked example intentionally contains an empty value.
3. Keep `demo-config.local.json` local: it is ignored by Git and excluded from ZIPs.
   No path is guessed from main, the current directory, the environment or another
   developer's machine. An absent/invalid file gives an actionable HOLD message.
4. Close previous manually started demo services in their own terminals. If another
   sidecar owns the fixed ports, stop it with its own STOP helper before starting
   this copy. This package never kills/adopts an unowned port occupant.
5. Double-click `START_ADVISORY_DEMO.cmd`. The launcher verifies v5 source/config,
   starts only its owned processes and opens http://127.0.0.1:8820 after readiness.
6. `CHECK_ADVISORY_DEMO.cmd` shows source and service status. Finish with
   `STOP_ADVISORY_DEMO.cmd`; synthetic sessions and failed evidence are retained.

See [START_HERE.md](START_HERE.md) for the goal journey, editing and safe recovery.
CMD files use PowerShell command mode; no execution-policy change or automatic
installation occurs. The internal token stays server-side, never in browser JS,
HTML, URLs, storage or the tracked configuration example.

## Verification and release

After provisioning the external runtime and ignored config, use that project's
Python 3.12 to run `-B -m pytest advisory-browser/tests -q -p no:cacheprovider`
from the repository root. The suite needs the external v5 contracts and cannot
certify standalone main. Browser QA requires an already available Playwright
module (`FINAI_PLAYWRIGHT_MODULE`, or normal `playwright` module resolution) and
installed Chrome (`FINAI_CHROME`, or the usual Windows Chrome location). No browser
or Node package download is performed by the suite. Fixture UI states are labeled
separately from actual mock-service journeys in `evidence/`.

Run `-B advisory-browser/package.py` with the same Python to rebuild the ZIP and
manifest. The ZIP contains the blank example, not your local configuration. After
extracting it, perform the same explicit local configuration step. Executable
members and archive hashes are verified; runtime/private state is excluded.
Historical receipts in `evidence/` describe earlier reviewed versions. Fresh
publication evidence identifies this exact latest-main candidate separately.

## Meaning of this demo

Scripted Clarifier is not an LLM evaluation. POLICY_ONLY is deterministic; browser
requests cannot override it. Specialists are MOCK and produce contract/routing
diagnostics, not financial recommendations. Real Market Researcher is disconnected;
Product is NOT_IMPLEMENTED. Historical C2.2 Gate B/C remains HOLD. Independent
frontend acceptance does not close backend engineering or benchmark acceptance.
