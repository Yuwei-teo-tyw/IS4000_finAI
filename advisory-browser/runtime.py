"""Trusted synthetic runtime configuration and exact source checks, no inference."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
TREE = "1a196f3645d26cfaaeddf4952bf79a1a0175c7d398fb6a1277cfb856b4de8995"
MANIFEST = "20d3c77640a9a0e973246acae346d5bdb0865b1fb2a79394e02fc59a86e6d33c"
GUARD = "e684bfb948f150445b818a13178de72447d2cdf93f302aada2908b7fa9ee63a1"
PORTS = (8811, 8812, 8890, 8820)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configuration() -> tuple[Path, Path, Path]:
    local = PACKAGE / "demo-config.local.json"
    if not local.is_file():
        raise ValueError("LOCAL_CONFIG_REQUIRED_COPY_DEMO_CONFIG_EXAMPLE")
    try:
        raw = local.read_bytes()
        if len(raw) > 4096:
            raise ValueError
        config = json.loads(raw)
        if not isinstance(config, dict) or set(config) != {"project_root"}:
            raise ValueError
        project_root = config["project_root"]
        if not isinstance(project_root, str) or not project_root.strip():
            raise ValueError
    except (OSError, ValueError, TypeError):
        raise ValueError("LOCAL_CONFIG_INVALID_SET_PROJECT_ROOT") from None
    if not Path(project_root).is_absolute():
        raise ValueError("LOCAL_CONFIG_PROJECT_ROOT_MUST_BE_ABSOLUTE")
    try:
        project = Path(project_root).resolve(strict=True)
    except OSError:
        raise ValueError("V5_PROJECT_UNAVAILABLE_CHECK_LOCAL_CONFIG") from None
    if not (project / "demo-readiness/session.json").is_file():
        raise ValueError("PROJECT_NOT_DEMO_READY_EXTERNAL_V5_REQUIRED")
    session = json.loads((project / "demo-readiness/session.json").read_text())
    root = Path(session["runtime_root"]).resolve(strict=True)
    expected = (project / "backend/.lab-data/demo-readiness").resolve(strict=True)
    if root.parent != expected or (root / "backend/.env").exists():
        raise ValueError("RUNTIME_ISOLATION_INVALID")
    if session["source_tree"] != TREE or session["source_files"] != 562:
        raise ValueError("RUNTIME_IDENTITY_INVALID")
    python = project / "backend/.venv/Scripts/python.exe"
    if not python.is_file():
        raise ValueError("PYTHON_ENVIRONMENT_UNAVAILABLE")
    return project, root, python


def verify() -> dict[str, object]:
    project, root, _ = configuration()
    for base in (project, root):
        path = base / "assurance/evals/authorities/engineering-authority-v5.json"
        if sha(path) != MANIFEST:
            raise ValueError("FROZEN_MANIFEST_MISMATCH")
        manifest = json.loads(path.read_text())
        if len(manifest["files"]) != 559 or manifest["tree_fingerprint"] != TREE:
            raise ValueError("FROZEN_IDENTITY_MISMATCH")
        for name, entry in manifest["files"].items():
            target = (base / name).resolve(strict=True)
            if not target.is_relative_to(base) or sha(target) != entry["sha256"]:
                raise ValueError("FROZEN_SOURCE_MISMATCH")
    if sha(project / "demo-readiness/guard/sitecustomize.py") != GUARD:
        raise ValueError("DEMO_GUARD_MISMATCH")
    if sys.version_info[:2] != (3, 12):
        raise ValueError("PYTHON_312_REQUIRED")
    for package in ("fastapi", "httpx", "pydantic", "uvicorn", "langgraph"):
        __import__(package)
    return {
        "authority": "engineering-authority-v5",
        "pins": 559,
        "source_tree": TREE,
        "manifest_sha256": MANIFEST,
        "mode": "POLICY_ONLY",
        "provider": "scripted",
        "specialists": "MOCK_HTTP",
    }


def environment() -> dict[str, str]:
    project, root, _ = configuration()
    # Keep OS essentials, remove all inherited provider, trace and secret settings.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(
            ("LAB_", "LANGSMITH_", "LANGCHAIN_", "OTEL_", "FINAI_DEMO_")
        )
        and not key.upper().endswith(
            ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PROXY")
        )
    }
    env.update(
        {
            "FINAI_DEMO_ROOT": str(root),
            "PYTHONPATH": os.pathsep.join(
                (
                    str(project / "demo-readiness/guard"),
                    str(root / "backend/src"),
                    str(root / "backend/foundation/src"),
                )
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONSAFEPATH": "1",
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
            "LANGSMITH_PROJECT": "IS4000",
            "LANGSMITH_API_KEY": "",
            "LAB_INTERNAL_API_TOKEN": (root / "demo-token.private.txt").read_text(),
            "LAB_PROVIDER": "scripted",
            "LAB_CLARIFIER_PROVIDER": "scripted",
            "LAB_ORCHESTRATOR_PROVIDER": "scripted",
            "LAB_ORCHESTRATION_MODE": "POLICY_ONLY",
            "LAB_RUNTIME_AUTHORITY": "engineering-authority-v5",
            "LAB_SPECIALIST_MODE": "MOCK_HTTP",
            "LAB_ALLOW_EXTERNAL_MODEL_CALLS": "false",
            "LAB_ALLOW_MODEL_DOWNLOADS": "false",
            "LAB_ALLOW_PAID_CALLS": "false",
            "LAB_ENABLE_FALLBACK": "false",
            "LAB_ALLOW_LIVE_SPECIALISTS": "false",
            "LAB_TAVILY_ENABLED": "false",
            "LAB_SYNTHETIC_DATA_ONLY": "true",
            "LAB_CONFIRMED_FREE_PROVIDERS": "",
        }
    )
    return env
