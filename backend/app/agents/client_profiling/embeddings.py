"""Optional text embeddings for the Client Profiling Agent (semantic note search).

Calls the local OpenAI-compatible server (CLIENT_PROFILING_LLM_URL, default http://localhost:1234/v1)
POST /embeddings with CLIENT_PROFILING_EMBED_MODEL (default text-embedding-nomic-embed-text-v1.5, 768 dims).
stdlib only; short timeout; every failure returns None so callers fall back to keyword search.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Optional

DIMS = 768
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
CHUNK_CHARS = 400
TIMEOUT_S = 10


def embed_model() -> str:
    return os.getenv("CLIENT_PROFILING_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")


def embed(texts: list[str], prefix: str = "") -> Optional[list[list[float]]]:
    """One vector per text (same order), or None on any failure."""
    if not texts:
        return []
    base = (os.getenv("CLIENT_PROFILING_EMBED_URL") or os.getenv("CLIENT_PROFILING_LLM_URL", "http://localhost:1234/v1")).rstrip("/")
    url = base + "/embeddings"
    payload: dict = {"model": embed_model(), "input": [prefix + t for t in texts]}
    if "api.openai.com" in base and os.getenv("CLIENT_PROFILING_EMBED_DIMS"):
        payload["dimensions"] = int(os.environ["CLIENT_PROFILING_EMBED_DIMS"])  # text-embedding-3 can shrink to the DB's vector size
    headers = {"Content-Type": "application/json"}
    if os.getenv("CLIENT_PROFILING_EMBED_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['CLIENT_PROFILING_EMBED_API_KEY']}"
    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = sorted(json.loads(resp.read())["data"], key=lambda d: d.get("index", 0))
        vecs = [[float(x) for x in d["embedding"]] for d in data]
        return vecs if len(vecs) == len(texts) and all(vecs) else None
    except Exception:
        return None


def embed_documents(texts: list[str]) -> Optional[list[list[float]]]:
    return embed(texts, DOC_PREFIX)


def embed_query(text: str) -> Optional[list[float]]:
    out = embed([text], QUERY_PREFIX)
    return out[0] if out else None


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6g}" for x in v) + "]"


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Paragraph windows of ~max_chars; an over-long paragraph is packed sentence by sentence."""
    chunks: list[str] = []
    cur = ""

    def flush() -> None:
        nonlocal cur
        if cur.strip():
            chunks.append(cur.strip())
        cur = ""

    for para in (p.strip() for p in re.split(r"\n\s*\n", text or "")):
        if not para:
            continue
        if len(para) <= max_chars:
            if cur and len(cur) + 2 + len(para) > max_chars:
                flush()
            cur = f"{cur}\n\n{para}" if cur else para
            continue
        flush()
        for s in re.split(r"(?<=[.!?])\s+", para):
            s = s.strip()
            while len(s) > max_chars:  # unbroken run: hard split
                flush()
                chunks.append(s[:max_chars])
                s = s[max_chars:]
            if cur and len(cur) + 1 + len(s) > max_chars:
                flush()
            cur = f"{cur} {s}" if cur else s
        flush()
    flush()
    return chunks
