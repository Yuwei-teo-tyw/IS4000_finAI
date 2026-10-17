"""Owned lifecycle and exact-source checks without changing live processes."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher
from runtime import TREE, verify


def test_frozen_identity():
    assert verify()["pins"] == 559


def test_health_rejects_another_instance(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "READY",
                "instance": "other",
                "source_tree": TREE,
                "mode": "POLICY_ONLY",
                "clarifier": "scripted",
                "specialists": "MOCK_HTTP",
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        launcher.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler)),
    )
    assert not launcher.health(8820, "owned")
    assert launcher.health(8820, "other")


def test_reuse_still_verifies_source(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "STATE", tmp_path)
    monkeypatch.setattr(
        launcher, "read_status", lambda: {"status": "READY", "instance": "old"}
    )

    def changed():
        raise ValueError("FROZEN_SOURCE_MISMATCH")

    monkeypatch.setattr(launcher, "verify", changed)
    with pytest.raises(ValueError, match="FROZEN_SOURCE_MISMATCH"):
        launcher.start(False)


def test_reuse_requires_owned_reservation(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "STATE", tmp_path)
    monkeypatch.setattr(
        launcher, "read_status", lambda: {"status": "READY", "instance": "old"}
    )
    monkeypatch.setattr(launcher, "verify", dict)
    monkeypatch.setattr(launcher, "health", lambda *args: True)
    with pytest.raises(ValueError, match="OWNED_INSTANCE_UNHEALTHY"):
        launcher.start(False)
