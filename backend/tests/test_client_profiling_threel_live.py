"""Opt-in: 3L allocation generation + discussion against the REAL local model.

    RUN_LIVE_PROFILING_TESTS=1 pytest -m live tests/test_client_profiling_threel_live.py
"""
import os
import re
import time

import pytest

from app.agents.client_profiling.ips_generate import generate_ips_section
from app.agents.client_profiling.store import DocumentStore
from app.agents.client_profiling.threel import discuss_allocation

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("RUN_LIVE_PROFILING_TESTS"), reason="set RUN_LIVE_PROFILING_TESTS=1 (needs the local model)"),
]
FIRST_PERSON = re.compile(r"\b(I|I'm|my|we|our)\b")


def _retry(fn, ok):
    for i in range(3):
        r = fn()
        if ok(r):
            return r
        time.sleep(10)
    return r


def test_live_jane_fraser_allocation_and_discuss():
    s = DocumentStore()
    r = _retry(lambda: generate_ips_section(s, "jft", "allocation"), lambda r: r["status"] != "unavailable")
    assert r["status"] == "ok" and r["model"], r
    a = r["allocation"]
    assert [b["id"] for b in a["buckets"]] == ["liquidity", "longevity", "legacy"]
    assert a["buckets"][0]["strategy"] in ("A", "B")
    for b in a["buckets"]:
        assert b["strategy"] in "ABCDEF" and len(b["justification"]) > 40 and not FIRST_PERSON.search(b["justification"])
    notes = " ".join(n.text for n in s.get_notes("jft"))
    for e in r["evidence"]:
        assert e["passage"] in notes

    msg = "for Liquidity I am sure she wants more growth than pure fixed income. Justify."
    d = _retry(lambda: discuss_allocation(s, "jft", msg, [], {"buckets": [{"id": b["id"], "strategy": b["strategy"]} for b in a["buckets"]]}),
               lambda d: d.get("status") != "unavailable")
    assert d["allocation"]["buckets"][0]["strategy"] in ("A", "B")
    assert re.search(r"A\s*(-|to|or|and)\s*B|Strategy A or B|A \(Fixed Income\) or B", d["answer"]), d["answer"]
    assert len(d["answer"]) > 120 and d["stance"] in ("disagree", "partial")
    print(d["answer"])
