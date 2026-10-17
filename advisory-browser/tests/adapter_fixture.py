"""Explicit adapter-only live QA fixture; never adopts or stops backend services."""

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import PACKAGE, configuration, environment, verify

identity = verify()
_, root, python = configuration()
stop = PACKAGE / (".runtime/adapter-qa-" + str(uuid.uuid4()) + ".stop")
if stop.exists():
    raise SystemExit("QA_STOP_SENTINEL_ALREADY_EXISTS")
env = environment()
env["FINAI_BROWSER_INSTANCE"] = "adapter-only-qa"
process = subprocess.Popen(
    [str(python), "-B", str(PACKAGE / "service.py"), "browser", str(stop)],
    cwd=root,
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(
    json.dumps(
        {
            "fixture": "adapter-only",
            "pid": process.pid,
            "stop_file": str(stop),
            "source": identity,
        }
    ),
    flush=True,
)
try:
    while process.poll() is None and not stop.exists():
        time.sleep(0.2)
finally:
    stop.touch()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        print("HOLD: OWNED_ADAPTER_SHUTDOWN_UNVERIFIED", flush=True)
        raise SystemExit(1) from None
    print("OWNED_ADAPTER_EXIT " + str(process.returncode), flush=True)
