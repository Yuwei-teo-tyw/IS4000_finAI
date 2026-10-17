"""Explicit release allowlist, reproducible ZIP and complete member/hash readback."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOP = {
    ".gitignore",
    "demo-config.json",
    "runtime.py",
    "server.py",
    "service.py",
    "launcher.py",
    "package.py",
    "START_ADVISORY_DEMO.cmd",
    "STOP_ADVISORY_DEMO.cmd",
    "CHECK_ADVISORY_DEMO.cmd",
    "START_HERE.md",
    "RELEASE_NOTES.md",
    "PLAN.md",
    "CHECKPOINT.md",
    "MERGE_IMPACT.md",
}
EXCLUDED_EVIDENCE = {"archive-verification.json", "git-receipt.json"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


REQUIRED = TOP | {
    "assets/index.html",
    "assets/app.js",
    "assets/style.css",
    "tests/test_adapter.py",
    "tests/test_lifecycle.py",
    "tests/adapter_fixture.py",
    "tests/live_browser.cjs",
    "tests/unavailable_browser.cjs",
    "tests/state_browser.cjs",
    "evidence/focused-checks.json",
    "evidence/contract-tests.json",
    "evidence/browser-qa.json",
    "evidence/goal-http-evidence.json",
    "evidence/real-unavailable.json",
    "evidence/state-ui-tests.json",
    "evidence/preservation.json",
    "evidence/independent-review.md",
}


def package() -> dict:
    if any(not (ROOT / name).is_file() for name in REQUIRED):
        raise ValueError("PACKAGE_REQUIRED_MEMBER_MISSING")
    files = {
        name: (ROOT / name).read_bytes()
        for name in sorted(TOP)
        if (ROOT / name).is_file()
    }
    for directory, extensions in (
        ("assets", {".html", ".css", ".js"}),
        ("tests", {".py", ".cjs"}),
        ("evidence", {".json", ".jsonl", ".png", ".md"}),
    ):
        for path in sorted((ROOT / directory).iterdir()):
            if (
                path.is_file()
                and path.suffix in extensions
                and path.name not in EXCLUDED_EVIDENCE
            ):
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    # Check actual synthetic auth value never appears; real .env is never opened.
    from runtime import configuration

    _, runtime, _ = configuration()
    token = (runtime / "demo-token.private.txt").read_bytes().strip()
    for name, data in files.items():
        if token and token in data:
            raise ValueError("PACKAGE_SECRET_REJECTED")
        if name.startswith((".runtime/", ".git/")) or name.endswith(
            (".sqlite3", ".env", ".pyc")
        ):
            raise ValueError("PACKAGE_PRIVATE_MEMBER_REJECTED")
    manifest = {
        "version": "browser-mvp.v1",
        "standalone": False,
        "requires": "Existing project Python 3.12 and isolated frozen v5 runtime",
        "files": {
            name: {"sha256": sha(data), "bytes": len(data)}
            for name, data in sorted(files.items())
        },
    }
    source_manifest = json.dumps(manifest, indent=2).encode()
    (ROOT / "source-manifest.json").write_bytes(source_manifest)
    files["source-manifest.json"] = source_manifest
    archive = ROOT / "IS4000_Advisory_Browser_MVP.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(
                "advisory-browser/" + name, date_time=(2026, 10, 17, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data)
    with zipfile.ZipFile(archive) as check:
        expected = {"advisory-browser/" + name for name in files}
        if (
            set(check.namelist()) != expected
            or len(check.namelist()) != len(expected)
            or check.testzip() is not None
        ):
            raise ValueError("ARCHIVE_MEMBER_MISMATCH")
        for name, data in files.items():
            if sha(check.read("advisory-browser/" + name)) != sha(data):
                raise ValueError("ARCHIVE_HASH_MISMATCH")
    receipt = {
        "status": "PASS",
        "path": str(archive),
        "sha256": sha(archive.read_bytes()),
        "members": len(files),
        "bytes": archive.stat().st_size,
        "source_manifest_sha256": sha(source_manifest),
        "credential_scan": "PASS",
        "standalone": False,
    }
    (ROOT / "evidence/archive-verification.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt


if __name__ == "__main__":
    print(json.dumps(package(), indent=2))
