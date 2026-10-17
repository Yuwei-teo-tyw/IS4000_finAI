"""Small local demo launcher. Only its own live Popen handles are ever signalled."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
import webbrowser

import httpx
from runtime import PACKAGE, PORTS, TREE, configuration, environment, verify

STATE = PACKAGE / ".runtime"
URL = "http://127.0.0.1:8820"


def write(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def read_status():
    try:
        return json.loads((STATE / "current.json").read_text())
    except (OSError, ValueError):
        return {}


def record(directory, code, **values):
    event = {"time": time.time(), "code": code, **values}
    with (directory / "lifecycle.jsonl").open("a") as stream:
        stream.write(json.dumps(event) + "\n")


def available():
    for port in PORTS:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise ValueError(f"PORT_{port}_OCCUPIED_UNOWNED") from None


def health(port, instance=None):
    try:
        with httpx.Client(
            timeout=10 if port == 8820 else 2, trust_env=False, follow_redirects=False
        ) as client:
            result = client.get(
                f"http://127.0.0.1:{port}"
                + ("/api/health" if port == 8820 else "/ready")
            )
        value = result.json()
        ready = result.status_code == 200 and value.get("status") == "READY"
        if port == 8820:
            ready = (
                ready
                and instance is not None
                and value.get("instance") == instance
                and value.get("source_tree") == TREE
                and value.get("mode") == "POLICY_ONLY"
                and value.get("clarifier") == "scripted"
                and value.get("specialists") == "MOCK_HTTP"
            )
        return ready
    except (httpx.HTTPError, ValueError):
        return False


def shutdown_request():
    value = read_status()
    instance = value.get("instance", "")
    try:
        uuid.UUID(instance)
    except (ValueError, TypeError):
        raise ValueError("NO_OWNED_INSTANCE") from None
    directory = STATE / instance
    if not directory.is_dir():
        raise ValueError("OWNED_INSTANCE_MISSING")
    (directory / "stop.request").touch()
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        state = read_status()
        if state.get("instance") == instance and state.get("status") in {
            "STOPPED",
            "FAILED",
        }:
            print("Owned demo stopped; evidence retained.")
            return
        time.sleep(0.2)
    raise ValueError("SHUTDOWN_UNVERIFIED_NO_FORCED_TERMINATION")


def supervise(instance):
    directory = STATE / instance
    directory.mkdir(exist_ok=False)
    processes = []
    status = {"instance": instance, "status": "STARTING", "pid": os.getpid()}
    write(STATE / "current.json", status)
    stop = directory / "stop.request"
    failed = False
    try:
        identity = verify()
        available()
        env = environment()
        env["FINAI_BROWSER_INSTANCE"] = instance
        project, root, python = configuration()
        # Existing safe configuration/authority check, no inference or provider discovery.
        checked = subprocess.run(
            [str(python), "-B", str(project / "demo-readiness/check.py")],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=45,
            check=False,
        )
        if checked.returncode:
            raise ValueError("SAFE_CONFIGURATION_CHECK_FAILED")
        write(directory / "source-identity.json", identity)
        write(directory / "safe-check.json", json.loads(checked.stdout))
        record(directory, "SOURCE_AND_SAFE_CHECK_PASSED", pins=559)
        for kind, port in zip(("clarifier", "orchestrator", "mocks", "browser"), PORTS):
            process = subprocess.Popen(
                [str(python), "-B", str(PACKAGE / "service.py"), kind, str(stop)],
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            processes.append((kind, process))
            record(
                directory,
                "OWNED_PROCESS_STARTED",
                service=kind,
                pid=process.pid,
                port=port,
            )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if stop.exists():
                break
            if any(process.poll() is not None for _, process in processes):
                raise ValueError("OWNED_SERVICE_EXITED_BEFORE_READINESS")
            if all(health(port, instance) for port in PORTS):
                status.update(
                    status="READY",
                    services={name: process.pid for name, process in processes},
                )
                write(STATE / "current.json", status)
                record(directory, "READY")
                break
            time.sleep(0.5)
        else:
            raise ValueError("READINESS_TIMEOUT")
        while not stop.exists():
            if any(process.poll() is not None for _, process in processes):
                raise ValueError("OWNED_SERVICE_EXITED")
            time.sleep(0.25)
    except Exception as error:  # noqa: BLE001 - sanitize launcher boundary errors
        failed = True
        code = str(error) if isinstance(error, ValueError) else "LAUNCHER_FAILED"
        record(directory, "FAILED", reason=code)
        status.update(status="STOPPING", reason=code)
        write(STATE / "current.json", status)
    finally:
        stop.touch()
        deadline = time.monotonic() + 20
        for name, process in processes:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
                record(
                    directory,
                    "OWNED_PROCESS_EXITED",
                    service=name,
                    pid=process.pid,
                    exit_code=process.returncode,
                )
            except subprocess.TimeoutExpired:
                failed = True
                record(directory, "SHUTDOWN_UNVERIFIED", service=name, pid=process.pid)
        alive = [name for name, process in processes if process.poll() is None]
        status.update(
            status="SHUTDOWN_UNVERIFIED"
            if alive
            else ("FAILED" if failed else "STOPPED")
        )
        write(STATE / "current.json", status)
        record(directory, status["status"])
        lock = STATE / "launch.lock"
        if not alive and lock.is_file() and lock.read_text() == instance:
            lock.unlink()
        # No PID/name/port based termination, even on failure. Preserve all evidence.


def start(open_browser):
    STATE.mkdir(exist_ok=True)
    current = read_status()
    verify()
    if current.get("status") == "READY":
        lock = STATE / "launch.lock"
        if (
            lock.is_file()
            and lock.read_text() == current.get("instance")
            and health(8820, current.get("instance"))
        ):
            print("Demo already owned and ready: " + URL)
            if open_browser:
                webbrowser.open(URL)
            return
        raise ValueError("OWNED_INSTANCE_UNHEALTHY_USE_STOP_AND_CHECK")
    if current.get("status") in {"STARTING", "STOPPING", "SHUTDOWN_UNVERIFIED"}:
        raise ValueError("INSTANCE_REQUIRES_CHECK")
    verify()
    available()
    instance = str(uuid.uuid4())
    try:
        reservation = os.open(
            STATE / "launch.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY
        )
    except FileExistsError:
        raise ValueError("EXISTING_LAUNCH_RESERVATION_INSPECT_EVIDENCE") from None
    os.write(reservation, instance.encode())
    os.close(reservation)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    subprocess.Popen(
        [
            sys.executable,
            "-B",
            str(PACKAGE / "launcher.py"),
            "supervise",
            "--instance",
            instance,
        ],
        cwd=PACKAGE,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    deadline = time.monotonic() + 160
    while time.monotonic() < deadline:
        current = read_status()
        if current.get("instance") == instance:
            if current.get("status") == "READY":
                print("READY: " + URL + " (scripted / POLICY_ONLY / MOCK_HTTP)")
                if open_browser:
                    webbrowser.open(URL)
                return
            if current.get("status") in {"FAILED", "STOPPED", "SHUTDOWN_UNVERIFIED"}:
                raise ValueError(current.get("reason", "START_FAILED"))
        time.sleep(0.3)
    raise ValueError("START_TIMEOUT_INSPECT_RETAINED_EVIDENCE")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "check", "supervise"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--instance")
    args = parser.parse_args()
    try:
        if args.action == "supervise":
            supervise(args.instance)
        elif args.action == "start":
            start(not args.no_browser)
        elif args.action == "stop":
            shutdown_request()
        else:
            identity = verify()
            value = read_status()
            checks = {str(port): health(port, value.get("instance")) for port in PORTS}
            print(
                json.dumps(
                    {"source": identity, "instance": value, "readiness": checks},
                    indent=2,
                )
            )
            return 0 if value.get("status") == "READY" and all(checks.values()) else 1
        return 0
    except Exception as error:  # noqa: BLE001 - sanitize launcher boundary errors
        code = (
            str(error) if isinstance(error, ValueError) else "LOCAL_DEMO_CHECK_FAILED"
        )
        print(
            "HOLD: "
            + code
            + ". Check .runtime evidence; no unrelated process was changed."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
