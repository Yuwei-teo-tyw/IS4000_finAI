"""Hybrid retrieval helpers: Reciprocal Rank Fusion of a lexical ranking and a dense ranking, plus the lexical query builder."""
from __future__ import annotations

import re
from typing import Hashable, Optional, Sequence

RRF_K = 60


def rrf_fuse(rankings: Sequence[Sequence[Hashable]], k: int = RRF_K, top: Optional[int] = None) -> list[tuple[Hashable, float]]:
    """Reciprocal Rank Fusion. Each ranking is a best-first list of keys; score(key) = sum over rankings of 1/(k + rank), rank from 1.
    Returns [(key, score)] best first (ties keep first-seen order), cut to `top` when given. Empty rankings are ignored."""
    scores: dict = {}
    for ranking in rankings:
        seen = set()
        for rank, key in enumerate(ranking, start=1):
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    out = sorted(scores.items(), key=lambda kv: -kv[1])  # sorted() is stable: ties keep insertion order
    return out[:top] if top is not None else out


def or_query(text: str) -> str:
    """Free text -> 'w1 or w2 or ...' for websearch_to_tsquery (any-term match; ts_rank_cd then favours chunks matching more terms)."""
    words = dict.fromkeys(w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1)
    return " or ".join(list(words)[:40])
