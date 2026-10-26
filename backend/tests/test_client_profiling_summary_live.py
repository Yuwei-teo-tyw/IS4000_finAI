"""Opt-in: summary quality + routing against a REAL local model (LM Studio).

    RUN_LIVE_PROFILING_TESTS=1 pytest -m live tests/test_client_profiling_summary_live.py
"""
import os

import pytest

from app.agents.client_profiling.llm import local_chat_json
from app.agents.client_profiling.summary import HEADINGS, summarise_notes
from app.agents.client_profiling.store import MeetingNoteDoc

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("RUN_LIVE_PROFILING_TESTS"), reason="set RUN_LIVE_PROFILING_TESTS=1 (needs the local model)"),
]

TEXT = ("The client expects a bonus of 50000 each March and plans to sell a property for 1200000. "
        "Monthly spending is 8000 and tuition of 30000 is due in September. "
        "Risk tolerance is balanced with a 10 year horizon. Prefers equities and bonds, avoids crypto.")


class Store:
    def get_notes(self, cid):
        return [MeetingNoteDoc(id="note_1", client_id="x", date="2026-01-01", title="Review", text=TEXT)]

    def get_client(self, cid):
        from types import SimpleNamespace
        return SimpleNamespace(id=cid, name="Test Client")


def test_live_summary_shape_and_no_invented_figures():
    from app.agents.client_profiling.summary import _figs
    res = summarise_notes(Store(), "x")
    assert res["status"] == "ok"
    secs = res["meetings"][0]["sections"]
    assert [s["heading"] for s in secs] == [h for _, h in HEADINGS]
    assert any(s["bullets"] for s in secs)
    for s in secs:
        for b in s["bullets"]:
            assert _figs(b["text"]) <= _figs(TEXT)


def test_live_summary_request_flag_is_set():
    import json
    from app.agents.client_profiling.answer import answer_question
    from app.agents.client_profiling.extract import extract_key_facts
    ans = answer_question("Summarise the meeting notes", Store(), extract_key_facts(Store(), "x"), local_chat_json)
    assert ans is not None and ans["summary_request"] is True
