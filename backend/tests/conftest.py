"""
Shared fixtures for the agent test suite.

None of these tests hit Groq, Tavily, or Postgres. Every LLM-backed node
gets `get_groq_model` monkeypatched - in that node module's *own*
namespace, since each module does `from app.core import get_groq_model` at
import time and binds its own reference - to return a `FakeLLM` queued
with the exact structured-output / AIMessage responses a test expects, in
call order.

`run_async` exists because the installed pytest (6.2.5) predates native
async test support and pytest-asyncio isn't a project dependency; wrapping
each coroutine in `asyncio.run` avoids adding either.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_async(coro):
    return asyncio.run(coro)


class _StructuredOutput:
    """Stand-in for `llm.with_structured_output(Schema)`."""

    def __init__(self, fake):
        self._fake = fake

    async def ainvoke(self, messages, config=None):
        self._fake.calls.append(list(messages))
        self._fake.configs.append(config)
        return self._fake._pop()


class _BoundTools:
    """Stand-in for `llm.bind_tools([...])`."""

    def __init__(self, fake):
        self._fake = fake

    async def ainvoke(self, messages):
        self._fake.calls.append(list(messages))
        return self._fake._pop()


class FakeLLM:
    """FIFO queue of canned responses, consumed in the order a node calls
    `with_structured_output(...).ainvoke(...)`, `bind_tools(...).ainvoke(...)`,
    or a bare `.ainvoke(...)` - mirrors how each node actually drives ChatGroq.

    Every call's message list is recorded to `self.calls` so tests can
    assert on what a node actually sent the model (e.g. that PII was
    redacted, or financial shorthand was expanded, before the prompt went
    out).
    """

    def __init__(self, *responses):
        self._queue = list(responses)
        self.calls = []
        self.configs = []  # the `config` passed with each structured-output call, if any

    def queue(self, *responses):
        self._queue.extend(responses)
        return self

    def _pop(self):
        if not self._queue:
            raise AssertionError("FakeLLM: ainvoke called with no queued response left")
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def with_structured_output(self, schema):
        return _StructuredOutput(self)

    def bind_tools(self, tools):
        return _BoundTools(self)

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return self._pop()


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture(autouse=True)
def _no_local_llm_for_profiling(request, monkeypatch):
    """Client Profiling tests must be deterministic: never call a local model that may be running."""
    if "client_profiling" in request.node.nodeid and not request.node.get_closest_marker("live"):
        monkeypatch.setenv("CLIENT_PROFILING_LLM_ENABLED", "false")


@pytest.fixture(autouse=True)
def _json_store_for_profiling(request, monkeypatch):
    """Offline client_profiling tests use the JSON store (no DB); the default singleton is reset around each test.
    test_client_profiling_pg.py builds its own PostgresStore in a throwaway schema."""
    if "client_profiling" in request.node.nodeid:
        from app.agents.client_profiling import store as store_mod
        monkeypatch.setenv("CLIENT_PROFILING_STORE", "json")
        store_mod.reset_default_store()
        yield
        store_mod.reset_default_store()
    else:
        yield


def fake_chat_reply(system: str, user: str) -> str:
    """Test stand-in for the single local model call: JSON {in_scope, broad, answerable, ...} (test-side keywords)."""
    import json
    q = user.rsplit("Adviser's question:", 1)[-1].lower()
    base = {"in_scope": True, "broad": False, "answerable": False, "answer": "", "groups": [], "cites": [],
            "explanation": {"risk_category": "", "text": "", "recommended_asset_classes": [], "cites": []}}
    if any(k in q for k in ("weather", "capital of")):
        base["in_scope"] = False
    return json.dumps(base)


@pytest.fixture
def fake_router(monkeypatch):
    """Opt-in: enable the local model with a fake (for HTTP-level tests that cannot pass answer_chat=)."""
    monkeypatch.setenv("CLIENT_PROFILING_LLM_ENABLED", "true")
    from app.agents.client_profiling import answer as answer_mod
    monkeypatch.setattr(answer_mod, "local_chat_json", fake_chat_reply)
    from app.agents.client_profiling import source_router
    monkeypatch.setattr(source_router, "local_router_chat",  # the source router: these legacy tests are all meeting-notes questions
                        lambda system, user: '{"source": "notes", "confidence": 0.95}')
