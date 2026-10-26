"""IS-92: generation responses expose the model that actually produced the content."""
import pytest

from app.agents.client_profiling import ips_generate
from app.agents.client_profiling.ips_generate import generate_ips_section
from app.agents.client_profiling.llm import ModelRouter, model_used
from ips_helpers import Chat, FakeStore, note

N = note(1, "2026-10-20", "Jane: I am very risk averse.")
GOOD = {"fields": [], "bullets": [{"text": "I am very risk averse", "cite": "N1", "quote": ""}]}


def make_router(ok_models, payload=GOOD):
    def make(name):
        def call(s, u):
            if name not in ok_models:
                raise ConnectionError(name)
            import json
            return json.dumps(payload)
        return call
    return lambda: ModelRouter(make, primary="primary-m", backup="backup-m")


def test_primary_model_name(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_LLM_MODEL", "primary-m")
    r = generate_ips_section(FakeStore([N]), "x", "risk", make_router({"primary-m"})())
    assert r["status"] == "ok" and r["model"] == "primary-m"


def test_backup_model_name_on_fallback():
    r = generate_ips_section(FakeStore([N]), "x", "risk", make_router({"backup-m"})())
    assert r["status"] == "ok" and r["model"] == "backup-m"


def test_no_model_available_exposes_no_name(monkeypatch):
    monkeypatch.setattr(ips_generate, "enabled", lambda: False)
    r = generate_ips_section(FakeStore([N]), "x", "risk")
    assert r["status"] == "unavailable" and r["model"] is None and "No model" in r["modelMessage"]


def test_all_models_failing_is_unavailable():
    r = generate_ips_section(FakeStore([N]), "x", "risk", make_router(set())())
    assert r["status"] == "unavailable" and r["model"] is None


def test_router_reports_last_used_and_raises():
    rt = ModelRouter(lambda n: (lambda s, u: "{}"), primary="p", backup="b")
    rt("s", "u")
    assert model_used(rt) == "p"
    with pytest.raises(ConnectionError):
        ModelRouter(lambda n: (_ for _ in ()).throw(ConnectionError()), primary="p", backup="b")("s", "u")


def test_allocation_exposes_model():
    from ips_helpers import alloc_payload
    r = generate_ips_section(FakeStore([N], risk_cap=2), "x", "allocation", make_router({"backup-m"}, alloc_payload())())
    assert r["model"] == "backup-m"
