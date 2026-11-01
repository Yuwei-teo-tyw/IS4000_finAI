"""IPS market environment block from the Market Analysis Agent (used by Generate IPS). No network, no LLM."""
import json
from types import SimpleNamespace

from app.agents.market_researcher.ips_context import IPS_MARKET_REQUEST, ips_market_context
from app.agents.portfolio_agent.upstream.market_analysis import _MOCK_PATH
from conftest import run_async


class FakeRunner:
    def __init__(self, tmp_path, fresh=True, finish="succeeded"):
        p = tmp_path / "run.json"
        p.write_text(_MOCK_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        self.rec = SimpleNamespace(run_id="mr_t", json_path=str(p), status=finish, error=None if finish == "succeeded" else "boom")
        self.fresh, self.submitted = fresh, []
        self.registry = self
        self.service = SimpleNamespace(settings=SimpleNamespace(run_budget_seconds=1))

    async def latest_success(self, region, since):
        return self.rec if self.fresh else None

    async def submit(self, req):
        self.submitted.append(req)
        return SimpleNamespace(run_id="mr_t")

    async def wait(self, run_id, timeout):
        return self.rec


def test_reuses_a_fresh_run_without_starting_one(tmp_path):
    r = FakeRunner(tmp_path)
    m = run_async(ips_market_context(r))
    assert m["status"] == "ok" and m["reusedRun"] and m["runId"].startswith("mr_") and not r.submitted
    assert m["regime"]["phase"] and m["asOf"] and m["indicators"] and m["source"] == "Market Analysis Agent"
    raw = json.loads(_MOCK_PATH.read_text(encoding="utf-8"))
    known = {i["name"] for i in raw["indicators"]}
    assert all(i["name"] in known for i in m["indicators"])  # copied from the run, nothing invented


def test_starts_a_small_run_when_none_is_fresh(tmp_path):
    r = FakeRunner(tmp_path, fresh=False)
    m = run_async(ips_market_context(r))
    assert r.submitted == [IPS_MARKET_REQUEST] and not m["reusedRun"]
    req = r.submitted[0]
    assert req.planning == "off" and req.explain_events is False and req.include_narrative is False


def test_failed_run_or_no_agent_is_unavailable_not_faked(tmp_path):
    m = run_async(ips_market_context(FakeRunner(tmp_path, fresh=False, finish="failed")))
    assert m["status"] == "unavailable" and "did not finish" in m["message"] and "indicators" not in m
    assert run_async(ips_market_context(None))["status"] == "unavailable"
