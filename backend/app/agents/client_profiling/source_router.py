"""Source router for the Client Profiling Agent: which database does a question belong to?

ONE small local-model call that sees ONLY the adviser's question (never client data) and returns
{"source": "notes"|"ips"|"both"|"unclear"|"out_of_scope", "confidence": 0..1}. None when the model is off,
unreachable or returns something invalid: the caller must never guess. Read-only, no side effects.
"""
import json
import os
import urllib.request
from typing import Optional

from .llm import ChatFn, enabled, model_name

MIN_CONFIDENCE = 0.7
SOURCES = ("notes", "ips", "both", "unclear", "out_of_scope")

ROUTER_SYSTEM = """You route a wealth adviser's question to ONE data source. You see only the question.
Sources:
- "notes": what the client said, wants, worries about or discussed in MEETINGS (meeting notes, calls, conversations).
- "ips": the official Investment Policy Statement (IPS): objectives, risk category, constraints, allocation, approved plan.
- "both": ONLY when the adviser explicitly asks to compare or combine the meeting notes with the IPS.
- "unclear": the question could mean either source (e.g. "What did we agree on risk?") or names neither.
- "out_of_scope": unrelated to this client's meeting notes or IPS (weather, general knowledge, markets).
Give "confidence" between 0 and 1: how sure you are of the chosen source. Reply with JSON only."""

_ROUTER_SCHEMA = {"type": "object", "properties": {
    "source": {"type": "string", "enum": list(SOURCES)},
    "confidence": {"type": "number"}},
    "required": ["source", "confidence"]}


def local_router_chat(system: str, user: str) -> str:
    """The router's local-model call (constrained JSON, temperature 0, short). Raises on any connection/HTTP problem."""
    base = os.getenv("CLIENT_PROFILING_LLM_URL", "http://localhost:1234/v1").rstrip("/")
    body = json.dumps({
        "model": model_name(), "temperature": 0, "max_tokens": 40,
        "response_format": {"type": "json_schema", "json_schema": {"name": "source_route", "strict": True, "schema": _ROUTER_SCHEMA}},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=float(os.getenv("CLIENT_PROFILING_ROUTER_TIMEOUT_S", "10"))) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def route_source(message: str, chat: Optional[ChatFn] = None) -> Optional[dict]:
    """{'source', 'confidence'} or None when the model is unavailable/invalid (never guess)."""
    if chat is None:
        if not enabled():
            return None
        chat = local_router_chat
    try:
        out = json.loads(chat(ROUTER_SYSTEM, f"Adviser's question: {(message or '')[:1000]}"))
        src, conf = out.get("source"), out.get("confidence")
        if src not in SOURCES or isinstance(conf, bool) or not isinstance(conf, (int, float)):
            return None
        return {"source": src, "confidence": max(0.0, min(1.0, float(conf)))}
    except Exception:
        return None
