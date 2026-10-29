"""IPS extras over HTTP: auto-save on generation, structured data round trip, override audit, chat allocation passthrough."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.client_profiling import store as store_mod
from app.agents.client_profiling.ips_generate import generate_ips_section as real_generate
from app.agents.client_profiling.store import DocumentStore
from app.endpoints import client_profiling as ep
from ips_helpers import Chat, alloc_payload

U = "/agents/client-profiling"
app = FastAPI()
app.include_router(ep.router)
PAYLOADS = {"demographics": {"fields": [{"label": "Occupation", "value": "Chief Executive Officer of CityBank", "cite": "N1"}]},
            "philosophy": {"approach": {"value": "", "cite": ""}, "believes": {"value": "", "cite": ""}, "avoids": {"value": "", "cite": ""}},
            "goals": {"bullets": [{"label": "Primary goals", "text": "Keeping capital safe comes first", "cite": "N1", "quote": ""}]},
            "risk": {"fields": [], "bullets": [{"text": "I am very risk averse", "cite": "N1", "quote": ""}]},
            "allocation": alloc_payload()}


@pytest.fixture
def api(monkeypatch):
    st = DocumentStore()
    monkeypatch.setattr(store_mod, "_default", st)
    monkeypatch.setattr(ep, "generate_ips_section", lambda s, c, sec: real_generate(s, c, sec, Chat(PAYLOADS[sec])))
    return TestClient(app)


def test_generation_autosaves_and_returns_version(api):
    r = api.post(f"{U}/ips-generate", json={"client_id": "jft", "section": "goals"}).json()
    assert r["saved"] is True and r["version"] and r["ips"]["version"] == r["version"] and r["saved_ips"] == r["ips"]
    assert r["model"]
    v = r["version"]
    data = r["ips"]["data"]
    assert data["rmSignatureImage"] == "/signature-isabel.png" and data["rmSignedDate"] and data["reviewRules"]
    assert [g["key"] for g in data["goals"]][0] == "returnRequirements" and data["targets"] and "lifeEvents" not in data
    # next section continues the same version
    r2 = api.post(f"{U}/ips-generate", json={"client_id": "jft", "section": "allocation", "version": v}).json()
    assert r2["version"] == v and [b["portfolio"] for b in r2["ips"]["data"]["threeL"]] == ["Liquidity", "Longevity", "Legacy"]
    assert r2["ips"]["data"]["goals"] == data["goals"]  # earlier section kept
    saved = api.get(f"{U}/ips/jft").json()
    assert saved["versions"][0]["version"] == v and saved["versions"][0]["data"]["threeL"]


def test_generate_all_saves_one_version_with_events(api):
    n0 = len(api.get(f"{U}/ips/jft").json()["versions"])
    r = api.post(f"{U}/ips-generate/all", json={"client_id": "jft"}).json()
    assert r["saved"] and [e["section"] for e in r["events"]] == ["demographics", "philosophy", "goals", "risk", "allocation"]
    assert all(e["model"] for e in r["events"]) and r["model"]
    assert len(api.get(f"{U}/ips/jft").json()["versions"]) == n0 + 1
    assert r["ips"]["data"]["risk"]["bullets"] == ["The client is very risk averse"]


def test_nothing_saved_when_no_model(api, monkeypatch):
    monkeypatch.setattr(ep, "generate_ips_section", lambda s, c, sec: real_generate(s, c, sec))
    monkeypatch.setenv("CLIENT_PROFILING_LLM_ENABLED", "false")
    n0 = len(api.get(f"{U}/ips/jft").json()["versions"])
    r = api.post(f"{U}/ips-generate", json={"client_id": "jft", "section": "goals"}).json()
    assert r["saved"] is False and r["model"] is None and r["modelMessage"]
    assert len(api.get(f"{U}/ips/jft").json()["versions"]) == n0


def test_save_load_drops_old_life_events_and_keeps_reason(api):
    data = {"lifeEvents": [{"id": "m1", "year": 2035, "label": "Sabbatical", "detail": "Takes a year off", "manual": True}],
            "threeL": [{"portfolio": "Liquidity", "strategy": "A", "strategyName": "Fixed Income", "reason": "RM wrote this",
                        "source": None, "default": False, "conflict": None}]}
    r = api.post(f"{U}/ips/jft", json={"data": data, "status": "Draft"}).json()
    v = r["ips"]["version"]
    got = api.get(f"{U}/ips/jft").json()["versions"][0]["data"]
    assert "lifeEvents" not in got and got["threeL"][0]["reason"] == "RM wrote this" and len(got["goals"]) == 7
    # RM removes the event and edits the reason
    data["threeL"][0]["reason"] = "edited"
    api.post(f"{U}/ips/jft", json={"version": v, "data": data})
    got = api.get(f"{U}/ips/jft").json()["versions"][0]["data"]
    assert "lifeEvents" not in got and got["threeL"][0]["reason"] == "edited"
    assert api.post(f"{U}/ips/jft", json={}).status_code == 422


def test_old_ips_versions_get_defaults(api):
    v = api.get(f"{U}/ips/ser").json()["versions"][0]
    assert v["data"]["rmSignedDate"] == v["issuedOn"] and len(v["data"]["goals"]) == 7 and v["data"]["reviewRules"]


def test_override_audit_log(api):
    body = {"clientId": "jft", "portfolio": "Longevity", "from": "C", "to": "D", "reason": "Client wants more growth"}
    r = api.post(f"{U}/ips-allocation/override", json=body, headers={"X-RM-Id": "isabel"}).json()
    assert r["ok"] is True and r["ts"]
    log = api.get(f"{U}/ips-allocation/overrides/jft").json()["overrides"]
    assert log[0]["from"] == "C" and log[0]["to"] == "D" and log[0]["rmId"] == "isabel" and log[0]["portfolio"] == "Longevity"
    assert api.post(f"{U}/ips-allocation/override", json={**body, "portfolio": "Liquidity", "to": "E"}).status_code == 422
    assert api.post(f"{U}/ips-allocation/override", json={**body, "clientId": "ser"}).status_code == 403


def test_chat_passes_allocation_history_and_pending(api, monkeypatch):
    seen = {}
    monkeypatch.setattr(ep, "handle_chat", lambda m, c, **kw: seen.update(kw) or ep.ToolResult(tool="x", message="m"))
    api.post(f"{U}/ips/jft", json={"data": {"threeL": [{"portfolio": "Liquidity", "strategy": "A", "reason": "r1"},
                                                       {"portfolio": "Longevity", "strategy": "C", "reason": "r2"}]}})
    api.post(f"{U}/ips-chat/jft", json={"role": "user", "text": "earlier"})
    api.post(f"{U}/chat", json={"message": "why C?", "client_id": "jft", "pending_proposal": {"bucket": "longevity", "strategy": "D"}})
    assert seen["allocation"]["buckets"][1] == {"id": "longevity", "strategy": "C", "justification": "r2"}
    assert seen["history"] == [{"role": "user", "text": "earlier"}] and seen["pending_proposal"]["strategy"] == "D"
    api.post(f"{U}/chat", json={"message": "x", "client_id": "jft", "allocation": {"buckets": []}, "history": [{"role": "user", "text": "h"}]})
    assert seen["allocation"] is None or seen["allocation"] != {} and seen["history"] == [{"role": "user", "text": "h"}]


def _lines(resp):
    import json
    return [json.loads(x) for x in resp.text.splitlines() if x.strip()]


def test_stream_one_autosave_all_sections(api):
    n0 = len(api.get(f"{U}/ips/jft").json()["versions"])
    resp = api.post(f"{U}/ips-generate/stream", json={"client_id": "jft"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/x-ndjson")
    ls = _lines(resp)
    assert ls[0]["type"] == "start" and ls[-1]["type"] == "done"
    secs = [x for x in ls if x["type"] == "section"]
    assert sorted(x["section"] for x in secs) == sorted(["demographics", "philosophy", "goals", "risk", "allocation"])
    assert all(x["status"] == "ok" and x["model"] and "reasoning" in x for x in secs)
    done = ls[-1]
    assert done["saved"] and done["version"] and done["ips"]["version"] == done["version"] and done["model"]
    assert len(api.get(f"{U}/ips/jft").json()["versions"]) == n0 + 1  # exactly one new draft


def test_stream_error_in_one_section_keeps_others(api, monkeypatch):
    def gen(s, c, sec):
        if sec == "risk":
            raise RuntimeError("boom client secret")
        return real_generate(s, c, sec, Chat(PAYLOADS[sec]))
    monkeypatch.setattr(ep, "generate_ips_section", gen)
    resp = api.post(f"{U}/ips-generate/stream", json={"client_id": "jft"})
    ls = _lines(resp)
    by = {x["section"]: x for x in ls if x["type"] == "section"}
    assert by["risk"]["status"] == "error" and "secret" not in by["risk"]["message"]
    assert all(by[s]["status"] == "ok" for s in by if s != "risk") and len(by) == 5
    assert ls[-1]["saved"] is True


def test_stream_book_check_and_no_model(api, monkeypatch):
    assert api.post(f"{U}/ips-generate/stream", json={"client_id": "ser"}).status_code == 403
    monkeypatch.setattr(ep, "generate_ips_section", lambda s, c, sec: real_generate(s, c, sec))
    monkeypatch.setenv("CLIENT_PROFILING_LLM_ENABLED", "false")
    n0 = len(api.get(f"{U}/ips/jft").json()["versions"])
    ls = _lines(api.post(f"{U}/ips-generate/stream", json={"client_id": "jft"}))
    assert ls[-1]["saved"] is False and ls[-1]["modelMessage"]
    assert len(api.get(f"{U}/ips/jft").json()["versions"]) == n0
