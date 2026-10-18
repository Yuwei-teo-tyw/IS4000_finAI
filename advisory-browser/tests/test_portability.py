"""Machine-local setup is explicit, bounded, private and actionable."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime


def test_missing_local_configuration_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "PACKAGE", tmp_path)
    with pytest.raises(
        ValueError, match="LOCAL_CONFIG_REQUIRED_COPY_DEMO_CONFIG_EXAMPLE"
    ):
        runtime.configuration()


@pytest.mark.parametrize(
    "value",
    [
        {"project_root": ""},
        {"project_root": True},
        {"project_root": "x", "token": "SENTINEL"},
        [],
        "bad-json",
    ],
)
def test_local_configuration_invalid_is_safe(monkeypatch, tmp_path, value):
    monkeypatch.setattr(runtime, "PACKAGE", tmp_path)
    text = value if value == "bad-json" else json.dumps(value)
    (tmp_path / "demo-config.local.json").write_text(text, encoding="utf-8")
    with pytest.raises(
        ValueError, match="LOCAL_CONFIG_INVALID_SET_PROJECT_ROOT"
    ) as failure:
        runtime.configuration()
    assert "SENTINEL" not in str(failure.value)


def test_relative_project_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "PACKAGE", tmp_path)
    (tmp_path / "demo-config.local.json").write_text(
        '{"project_root":"../other"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="LOCAL_CONFIG_PROJECT_ROOT_MUST_BE_ABSOLUTE"):
        runtime.configuration()


def test_oversized_local_configuration_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "PACKAGE", tmp_path)
    (tmp_path / "demo-config.local.json").write_text(" " * 4097, encoding="utf-8")
    with pytest.raises(ValueError, match="LOCAL_CONFIG_INVALID_SET_PROJECT_ROOT"):
        runtime.configuration()


def test_example_is_portable_and_local_config_not_packaged():
    import package as release

    example = json.loads((runtime.PACKAGE / "demo-config.example.json").read_text())
    assert example == {"project_root": ""}
    assert "demo-config.local.json" not in release.TOP
    assert "demo-config.example.json" in release.REQUIRED
    assert (
        "demo-config.local.json"
        in (runtime.PACKAGE / ".gitignore").read_text().splitlines()
    )
