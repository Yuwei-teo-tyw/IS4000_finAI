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

    async def ainvoke(self, messages):
        self._fake.calls.append(list(messages))
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
