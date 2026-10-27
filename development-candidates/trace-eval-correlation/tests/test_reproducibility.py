"""12: deterministic reproduction, read-only sources and no network access."""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import Campaign, Lab, render_index
from trace_eval_correlation.cli import main


def _tree_hash(base: Path) -> dict[str, str]:
    return {
        p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }


def test_identical_evidence_renders_identical_bytes(lab: Lab, campaign: Campaign) -> None:
    campaign.write(lab.evidence / "camp")
    first = render_index(lab.build(lab.manifest()))
    second = render_index(lab.build(lab.manifest()))
    assert first == second


def test_cli_build_then_verify(
    lab: Lab, campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    campaign.write(lab.evidence / "camp")
    manifest = lab.write_manifest(lab.manifest())
    index = lab.root / "out" / "index.json"
    root = f"evidence={lab.evidence}"
    before = _tree_hash(lab.evidence)
    assert main(["build", "--manifest", str(manifest), "--index", str(index), "--root", root]) == 0
    assert _tree_hash(lab.evidence) == before  # sources untouched
    sidecar = (index.parent / "index.json.sha256").read_text().split()[0]
    assert sidecar == hashlib.sha256(index.read_bytes()).hexdigest()
    assert main(["verify", "--manifest", str(manifest), "--index", str(index), "--root", root]) == 0
    assert "REPRODUCED" in capsys.readouterr().out
    assert str(lab.root) not in index.read_text(encoding="utf-8")

    (lab.evidence / "camp/reports/scores.json").write_text("[]")
    assert main(["verify", "--manifest", str(manifest), "--index", str(index), "--root", root]) == 1


def test_build_reports_incomplete_with_exit_code(lab: Lab, campaign: Campaign) -> None:
    base = campaign.write(lab.evidence / "camp")
    (base / "reports/traces.jsonl").unlink()
    manifest = lab.write_manifest(lab.manifest())
    out = lab.root / "out" / "index.json"
    code = main(
        [
            "build",
            "--manifest",
            str(manifest),
            "--index",
            str(out),
            "--root",
            f"evidence={lab.evidence}",
        ]
    )
    assert code == 2 and json.loads(out.read_text())["index_status"] == "INCOMPLETE"


def test_cli_refuses_to_write_inside_evidence_and_unbound_roots(
    lab: Lab, campaign: Campaign
) -> None:
    campaign.write(lab.evidence / "camp")
    manifest = lab.write_manifest(lab.manifest())
    before = _tree_hash(lab.evidence)
    inside = lab.evidence / "camp" / "reports" / "index.json"
    assert (
        main(
            [
                "build",
                "--manifest",
                str(manifest),
                "--index",
                str(inside),
                "--root",
                f"evidence={lab.evidence}",
            ]
        )
        == 64
    )
    assert _tree_hash(lab.evidence) == before
    assert main(["build", "--manifest", str(manifest), "--index", str(lab.root / "x.json")]) == 64


def test_build_opens_no_network_socket(
    lab: Lab, campaign: Campaign, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign.write(lab.evidence / "camp")

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert lab.build(lab.manifest()).index_status == "COMPLETE"


def test_adapter_imports_no_provider_or_cloud_client() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); import trace_eval_correlation.cli;"
        "bad=[m for m in ('httpx','requests','langsmith','openai','anthropic','urllib.request',"
        "'http.client','advisory_agents') if m in sys.modules]; print(','.join(bad))"
    )
    out = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-I", "-c", probe, str(src)], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == ""


def test_schema_command_writes_versioned_schema(lab: Lab) -> None:
    out = lab.root / "schema.json"
    assert main(["schema", "--out", str(out)]) == 0
    schema = json.loads(out.read_text())
    assert schema["properties"]["schema_version"]["const"] == "trace-eval-index/1.0"
