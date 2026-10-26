"""Local LLM access for the Client Profiling Agent (meeting-notes only).

ONE call per question: the model returns {in_scope, broad, summary_request, summary_format, answerable, answer, groups, cites, explanation, inference} as
constrained JSON (no reasoning tokens). Talks to a local OpenAI-compatible server (LM Studio by default) over
plain HTTP, no new dependency.

Config (env): CLIENT_PROFILING_LLM_ENABLED (default true), CLIENT_PROFILING_LLM_MODEL (default
"google/gemma-4-e4b"), CLIENT_PROFILING_LLM_URL (default http://localhost:1234/v1),
CLIENT_PROFILING_ANSWER_TIMEOUT_S (default 60), CLIENT_PROFILING_ANSWER_MAX_TOKENS (default 450).
"""
import json
import os
import urllib.request
from typing import Callable

ChatFn = Callable[[str, str], str]  # (system, user) -> raw JSON string


def enabled() -> bool:
    return os.getenv("CLIENT_PROFILING_LLM_ENABLED", "true").lower() not in ("0", "false", "no")


def model_name() -> str:
    return os.getenv("CLIENT_PROFILING_LLM_MODEL", "google/gemma-4-e4b")


_STR_LIST = {"type": "array", "items": {"type": "string"}}
_BULLET = {"type": "object", "properties": {"text": {"type": "string"}, "cites": _STR_LIST}, "required": ["text", "cites"]}
_EXPLANATION = {"type": "object", "properties": {
    "risk_category": {"type": "string"}, "text": {"type": "string"},
    "recommended_asset_classes": _STR_LIST, "cites": _STR_LIST},
    "required": ["risk_category", "text", "recommended_asset_classes", "cites"]}
_ANSWER_SCHEMA = {"type": "object", "properties": {
    "in_scope": {"type": "boolean"},
    "broad": {"type": "boolean"},
    "answerable": {"type": "boolean"},
    "answer": {"type": "string"},
    "groups": {"type": "array", "items": {"type": "object", "properties": {
        "heading": {"type": "string"}, "bullets": {"type": "array", "items": _BULLET}}, "required": ["heading", "bullets"]}},
    "cites": _STR_LIST,
    "explanation": _EXPLANATION,
    "summary_request": {"type": "boolean"},
    "summary_format": {"type": "string"},
    "inference": {"type": "string"}},
    "required": ["in_scope", "broad", "summary_request", "summary_format", "answerable", "answer", "groups", "cites", "explanation", "inference"]}


def local_chat_json(system: str, user: str) -> str:
    """The single local-model call (constrained JSON, temperature 0). Raises on any connection/HTTP problem."""
    base = os.getenv("CLIENT_PROFILING_LLM_URL", "http://localhost:1234/v1").rstrip("/")
    body = json.dumps({
        "model": model_name(), "temperature": 0, "max_tokens": int(os.getenv("CLIENT_PROFILING_ANSWER_MAX_TOKENS", "450")),
        "response_format": {"type": "json_schema", "json_schema": {"name": "grounded_answer", "strict": True, "schema": _ANSWER_SCHEMA}},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=float(os.getenv("CLIENT_PROFILING_ANSWER_TIMEOUT_S", "60"))) as r:
        return json.load(r)["choices"][0]["message"]["content"]
