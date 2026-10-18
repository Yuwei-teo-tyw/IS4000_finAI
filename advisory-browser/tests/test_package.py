"""A release cannot certify a self-consistent but incomplete subset."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package as release


@pytest.mark.parametrize(
    "missing",
    [
        "server.py",
        "START_ADVISORY_DEMO.cmd",
        "assets/app.js",
        "evidence/independent-review.md",
    ],
)
def test_missing_required_member_rejected_before_archive(
    monkeypatch, tmp_path, missing
):
    monkeypatch.setattr(release, "ROOT", tmp_path)
    for name in release.REQUIRED - {missing}:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    with pytest.raises(ValueError, match="PACKAGE_REQUIRED_MEMBER_MISSING"):
        release.package()
    assert not (tmp_path / "IS4000_Advisory_Browser_MVP.zip").exists()
