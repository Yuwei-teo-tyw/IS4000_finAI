"""LM Studio fallback: Gemma unreachable/not loaded -> ONE retry on /api/v1/chat with the fallback model (faked transport)."""
import json

import pytest

from app.agents.client_profiling import llm
from app.agents.client_profiling.ips_reasoning import finish_section
from app.agents.client_profiling.llm import LLMHTTPError, ModelRouter, model_used, post_chat

NATIVE = {"model_instance_id": "nvidia/nemotron-3-nano-4b",
          "output": [{"type": "reasoning", "content": "thinking..."},
                     {"type": "message", "content": "```json\n{\"answer\": \"hi\"}\n```"}],
          "stats": {"input_tokens": 30, "total_output_tokens": 274, "reasoning_output_tokens": 253}}
OPENAI = {"model": "google/gemma-4-e4b", "choices": [{"message": {"content": "{\"answer\": \"primary\"}"}, "finish_reason": "stop"}]}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in ("CLIENT_PROFILING_FALLBACK_URL", "CLIENT_PROFILING_FALLBACK_MODEL", "CLIENT_PROFILING_FALLBACK_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLIENT_PROFILING_LLM_URL", "http://host.docker.internal:1234/v1")
    monkeypatch.setenv("CLIENT_PROFILING_LLM_MODEL", "google/gemma-4-e4b")
    llm.reset_last()


def fake(monkeypatch, primary, fallback=NATIVE):
    calls = []

    def post(url, payload, timeout, connect_timeout):
        calls.append((url, payload, connect_timeout))
        r = fallback if url.endswith("/api/v1/chat") else primary
        if isinstance(r, BaseException):
            raise r
        return r
    monkeypatch.setattr(llm, "_http_post_json", post)
    return calls


def test_primary_refused_uses_fallback_and_reports_model(monkeypatch):
    calls = fake(monkeypatch, ConnectionRefusedError("refused"))
    out = llm.local_chat_json("sys", "usr")
    assert json.loads(out) == {"answer": "hi"}  # fence stripped, message text only (reasoning ignored)
    assert [c[0] for c in calls] == ["http://host.docker.internal:1234/v1/chat/completions",
                                     "http://host.docker.internal:1234/api/v1/chat"]
    p = calls[1][1]
    assert p["model"] == "nvidia/nemotron-3-nano-4b" and p["input"] == "usr" and p["system_prompt"].startswith("sys")
    assert llm.last_model() == "nvidia/nemotron-3-nano-4b" and llm.fallback_active()
    assert calls[0][2] <= 5  # short connect timeout


@pytest.mark.parametrize("err", [LLMHTTPError(404, "model not found"), LLMHTTPError(503), ConnectionError("connect timeout")])
def test_http_errors_and_connect_timeout_fall_back(monkeypatch, err):
    calls = fake(monkeypatch, err)
    assert post_chat({"model": "google/gemma-4-e4b", "messages": [{"role": "user", "content": "x"}]}, 5)["fallback"] is True
    assert len(calls) == 2


def test_primary_ok_never_calls_fallback(monkeypatch):
    calls = fake(monkeypatch, OPENAI)
    assert json.loads(llm.local_chat_json("s", "u")) == {"answer": "primary"}
    assert len(calls) == 1 and not llm.fallback_active() and llm.last_model() == "google/gemma-4-e4b"


def test_bad_answer_or_slow_read_does_not_fall_back(monkeypatch):
    calls = fake(monkeypatch, TimeoutError("read timed out"))
    with pytest.raises(TimeoutError):
        llm.local_chat_json("s", "u")
    assert len(calls) == 1
    calls = fake(monkeypatch, ValueError("bad json"))
    with pytest.raises(ValueError):
        llm.local_chat_json("s", "u")
    assert len(calls) == 1


def test_both_down_raises_so_callers_say_unavailable(monkeypatch):
    fake(monkeypatch, ConnectionRefusedError("a"), ConnectionRefusedError("b"))
    with pytest.raises(ConnectionRefusedError):
        llm.local_chat_json("s", "u")
    from app.agents.client_profiling.answer import answer_question  # noqa: F401  (callers treat the raise as unavailable)


def test_fallback_disabled_and_url_override(monkeypatch):
    monkeypatch.setenv("CLIENT_PROFILING_FALLBACK_ENABLED", "false")
    calls = fake(monkeypatch, ConnectionRefusedError("x"))
    with pytest.raises(ConnectionRefusedError):
        llm.local_chat_json("s", "u")
    assert len(calls) == 1
    monkeypatch.delenv("CLIENT_PROFILING_FALLBACK_ENABLED")
    monkeypatch.setenv("CLIENT_PROFILING_FALLBACK_URL", "http://other:9999/")
    monkeypatch.setenv("CLIENT_PROFILING_FALLBACK_MODEL", "m2")
    assert llm.fallback_url() == "http://other:9999/api/v1/chat" and llm.fallback_model_name() == "m2"


def test_parse_fallback_reply_shape_and_no_message():
    d = llm.parse_fallback_reply(NATIVE, json_mode=True)
    assert d["model"] == "nvidia/nemotron-3-nano-4b" and d["choices"][0]["message"]["content"] == '{"answer": "hi"}'
    assert d["usage"]["completion_tokens"] == 274 and d["usage"]["reasoning_tokens"] == 253
    with pytest.raises(ValueError):
        llm.parse_fallback_reply({"output": [{"type": "reasoning", "content": "only thinking"}]})


def test_schema_is_put_in_system_prompt_for_fallback():
    body = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], "max_tokens": 99,
            "response_format": {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}}
    p = llm._fallback_payload(body)
    assert "JSON schema" in p["system_prompt"] and p["input"] == "U" and p["max_output_tokens"] == 99


def test_router_reports_fallback_model_for_a_real_chat_fn(monkeypatch):
    fake(monkeypatch, LLMHTTPError(404, "no model"))

    def make(name):
        return lambda s, u: post_chat({"model": name, "messages": [{"role": "user", "content": u}]}, 5)["choices"][0]["message"]["content"]
    r = ModelRouter(make, primary="google/gemma-4-e4b", backup=None)
    r("s", "u")
    assert model_used(r) == "nvidia/nemotron-3-nano-4b"


def test_generation_reasoning_says_fallback_used():
    res = {"model": "nvidia/nemotron-3-nano-4b", "status": "ok", "fields": {}, "bullets": [], "sources": [], "evidence": [], "notIncluded": []}
    out = finish_section(None, "c", "risk", res, notes=[])
    assert out["modelFallback"] is True and "fallback model nvidia/nemotron-3-nano-4b" in out["reasoning"][-1]
    ok = finish_section(None, "c", "risk", {"model": "google/gemma-4-e4b", "fields": {}, "bullets": [], "sources": [], "evidence": [], "notIncluded": []}, notes=[])
    assert "modelFallback" not in ok
