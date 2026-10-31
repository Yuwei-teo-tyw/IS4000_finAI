"""Hybrid retrieval: RRF fusion and lexical query builder (pure, fake rankings)."""
from app.agents.client_profiling.hybrid import or_query, rrf_fuse


def test_rrf_scores_and_order():
    out = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]], k=60)
    d = dict(out)
    assert d["a"] == d["b"] == 1 / 61 + 1 / 62
    assert [k for k, _ in out][:2] == ["a", "b"]          # tie keeps first-seen order
    assert d["c"] == 1 / 63 and d["d"] == 1 / 63 and len(out) == 4


def test_rrf_item_in_both_beats_item_top_in_one():
    out = rrf_fuse([["x", "shared"], ["y", "shared"]])
    assert out[0][0] == "shared"


def test_rrf_top_empty_and_single_leg():
    assert rrf_fuse([]) == [] and rrf_fuse([[], []]) == []
    assert [k for k, _ in rrf_fuse([["a", "b", "c"], []], top=2)] == ["a", "b"]   # lexical-only degrades to its own order
    assert [k for k, _ in rrf_fuse([["a", "a", "b"]])] == ["a", "b"]              # duplicates counted once


def test_or_query():
    assert or_query("What is Jane's risk appetite?!") == "what or is or jane or risk or appetite"
    assert or_query("  ") == ""
