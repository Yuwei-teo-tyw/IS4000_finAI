"""Local LLM access for the Client Profiling Agent (meeting-notes only).

ONE call per question: the model returns {in_scope, broad, summary_request, summary_format, answerable, answer, groups, cites, explanation, inference} as
constrained JSON (no reasoning tokens). Talks to a local OpenAI-compatible server (LM Studio by default) over
plain HTTP, no new dependency.

Config (env): CLIENT_PROFILING_LLM_ENABLED (default true), CLIENT_PROFILING_LLM_MODEL (default
"google/gemma-4-e4b"), CLIENT_PROFILING_LLM_URL (default http://localhost:1234/v1),
CLIENT_PROFILING_ANSWER_TIMEOUT_S (default 120), CLIENT_PROFILING_ANSWER_MAX_TOKENS (default 2500: Gemma 4 reasoning tokens count against it).

Fallback (LM Studio only): when the primary model is NOT reachable or not loaded (connection refused / connect timeout /
HTTP 4xx-5xx) `post_chat` retries the same prompt ONCE against LM Studio's native `POST {server}/api/v1/chat` with
CLIENT_PROFILING_FALLBACK_MODEL (default "nvidia/nemotron-3-nano-4b"). CLIENT_PROFILING_FALLBACK_URL optionally overrides the
server (default: the primary URL without "/v1"); CLIENT_PROFILING_FALLBACK_ENABLED=false turns it off;
CLIENT_PROFILING_CONNECT_TIMEOUT_S (default 3) bounds how long a dead primary can delay the fallback. A reachable-but-bad
reply (empty / truncated / invalid JSON) never falls back: that stays with the caller's own retry logic. The model that really
answered is reported by `last_model()` / `model_used(chat)`, and `fallback_active()` says whether it was the fallback.
"""
import http.client
import json
import logging
import os
import re
import threading
import urllib.parse
from typing import Callable, Optional

log = logging.getLogger(__name__)

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


# --------------------------------------------------------------------------- transport + LM Studio fallback
class LLMHTTPError(OSError):
    """The server answered with HTTP status >= 400 (model not found / not loaded, server error ...)."""

    def __init__(self, status: int, detail: str = ""):
        super().__init__(f"HTTP {status}: {detail[:200]}")
        self.status = status


_tls = threading.local()  # per-thread: what the last post_chat call on this thread used
_last: dict = {"model": None, "fallback": False}  # process-wide copy (for callers whose work ran on a pool thread)


def _primary_base() -> str:
    return os.getenv("CLIENT_PROFILING_LLM_URL", "http://localhost:1234/v1").rstrip("/")


def fallback_enabled() -> bool:
    return os.getenv("CLIENT_PROFILING_FALLBACK_ENABLED", "true").lower() not in ("0", "false", "no")


def fallback_model_name() -> str:
    return os.getenv("CLIENT_PROFILING_FALLBACK_MODEL", "").strip() or "nvidia/nemotron-3-nano-4b"


def fallback_url() -> str:
    """LM Studio native chat endpoint. Override CLIENT_PROFILING_FALLBACK_URL = server root (or the full .../chat URL);
    default = the primary base URL without its trailing /v1 (so docker's host.docker.internal carries over)."""
    root = os.getenv("CLIENT_PROFILING_FALLBACK_URL", "").strip().rstrip("/") or re.sub(r"/v1$", "", _primary_base())
    return root if root.endswith("/api/v1/chat") else f"{root}/api/v1/chat"


def _record(model: Optional[str], fallback: bool) -> None:
    _tls.model, _tls.fallback = model, fallback
    _last["model"], _last["fallback"] = model, fallback


def last_model() -> Optional[str]:
    """Model that answered the last post_chat on this thread (None when none ran)."""
    return getattr(_tls, "model", None)


def fallback_active() -> bool:
    return bool(getattr(_tls, "fallback", False))


def last_model_any_thread() -> Optional[str]:
    return _last["model"]


def reset_last() -> None:
    _record(None, False)


def _http_post_json(url: str, payload: dict, timeout: float, connect_timeout: float) -> dict:
    """The only network call: POST JSON, short connect timeout then the full read timeout. Raises OSError on any problem."""
    u = urllib.parse.urlsplit(url)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = cls(u.hostname, u.port, timeout=connect_timeout)
    try:
        try:
            conn.connect()
        except TimeoutError as e:  # connect timeout = host dead; distinct from a slow read
            raise ConnectionError(f"connect timeout to {u.hostname}:{u.port}") from e
        conn.sock.settimeout(timeout)
        conn.request("POST", u.path + (f"?{u.query}" if u.query else ""), body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        raw = r.read()
        if r.status >= 400:
            raise LLMHTTPError(r.status, raw.decode("utf-8", "replace"))
        return json.loads(raw)
    finally:
        conn.close()


def is_unavailable(e: BaseException) -> bool:
    """Gemma is not reachable / not loaded: refused or unreachable connection, connect timeout, HTTP 4xx-5xx.
    A slow reply (read timeout after a good connect) or a bad answer is NOT 'unavailable'."""
    if isinstance(e, LLMHTTPError):
        return True
    if isinstance(e, (ConnectionError, http.client.RemoteDisconnected)):
        return True
    return isinstance(e, OSError) and not isinstance(e, TimeoutError)  # (a connect timeout is re-raised as ConnectionError)


def _fence_stripped(t: str) -> str:
    t = t.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S | re.I)
    return m.group(1).strip() if m else t


def _fallback_payload(body: dict) -> dict:
    msgs = body.get("messages") or []
    system = "\n\n".join(m["content"] for m in msgs if m.get("role") == "system")
    user = "\n\n".join(m["content"] for m in msgs if m.get("role") == "user")
    schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("schema")
    if schema:  # the native endpoint has no constrained decoding: ask for the same shape in words
        system += ("\n\nReply with ONLY one minified JSON object that matches this JSON schema. No markdown, no code fence, "
                   "no commentary:\n" + json.dumps(schema))
    payload = {"model": fallback_model_name(), "system_prompt": system, "input": user, "temperature": 0}
    if body.get("max_tokens"):
        payload["max_output_tokens"] = int(body["max_tokens"])
    return payload


def parse_fallback_reply(d: dict, json_mode: bool = False) -> dict:
    """LM Studio /api/v1/chat reply -> OpenAI-shaped dict {'model','choices':[{'message':{'content'},'finish_reason'}],'usage','fallback'}.
    Reply shape: {'model_instance_id', 'output': [{'type': 'reasoning'|'message', 'content': str}, ...], 'stats': {...}}.
    Raises ValueError when there is no message text (reasoning only / empty)."""
    out = d.get("output")
    if not isinstance(out, list):
        raise ValueError("fallback reply has no output")
    text = "".join(str(o.get("content") or "") for o in out if isinstance(o, dict) and o.get("type") == "message").strip()
    if not text:
        raise ValueError("fallback model returned no message text")
    st = d.get("stats") or {}
    return {"model": d.get("model_instance_id") or fallback_model_name(), "fallback": True,
            "choices": [{"message": {"content": _fence_stripped(text) if json_mode else text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": st.get("input_tokens"), "completion_tokens": st.get("total_output_tokens"),
                      "reasoning_tokens": st.get("reasoning_output_tokens")}}


def post_chat(body: dict, timeout: float) -> dict:
    """POST an OpenAI chat-completions body to the primary model and return the OpenAI-shaped reply dict.
    If the primary is unreachable / not loaded (see is_unavailable) retry ONCE on LM Studio's native chat endpoint with the
    fallback model; the returned dict then carries fallback=True and the fallback model name. Never falls back for a
    reachable-but-bad reply. Records which model answered (last_model / fallback_active)."""
    _record(None, False)
    connect = float(os.getenv("CLIENT_PROFILING_CONNECT_TIMEOUT_S", "3"))
    try:
        d = _http_post_json(f"{_primary_base()}/chat/completions", body, timeout, connect)
    except Exception as e:  # noqa: BLE001
        if not (fallback_enabled() and is_unavailable(e)) or body.get("model") == fallback_model_name():
            raise
        log.warning("primary model %r unavailable (%s: %s); retrying once on fallback %r",
                    body.get("model"), type(e).__name__, e, fallback_model_name())
        json_mode = bool((body.get("response_format") or {}).get("json_schema"))
        raw = _http_post_json(fallback_url(), _fallback_payload(body), timeout, connect)
        d = parse_fallback_reply(raw, json_mode)
        _record(d["model"], True)
        return d
    _record(d.get("model") or body.get("model"), False)
    return d


def local_chat_json(system: str, user: str) -> str:
    """The single local-model call (constrained JSON, temperature 0). Raises on any connection/HTTP problem
    (after the one LM Studio fallback attempt when the primary model is unavailable)."""
    body = {
        "model": model_name(), "temperature": 0, "max_tokens": int(os.getenv("CLIENT_PROFILING_ANSWER_MAX_TOKENS", "2500")),
        "response_format": {"type": "json_schema", "json_schema": {"name": "grounded_answer", "strict": True, "schema": _ANSWER_SCHEMA}},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    return post_chat(body, float(os.getenv("CLIENT_PROFILING_ANSWER_TIMEOUT_S", "120")))["choices"][0]["message"]["content"]


def backup_model_name():
    """Optional fallback model (env CLIENT_PROFILING_LLM_BACKUP_MODEL); None when not configured."""
    v = os.getenv("CLIENT_PROFILING_LLM_BACKUP_MODEL", "").strip()
    return v or None


class ModelRouter:
    """ChatFn that tries the primary model, then the backup model. `model_used` = the model that produced the last good
    reply (the backup's name after a fallback); None until a call succeeds. Raises when no model answers."""

    def __init__(self, make, primary=None, backup=None):
        self.make, self.primary, self.backup = make, primary or model_name(), backup if backup is not None else backup_model_name()
        self.model_used = None

    def __call__(self, system: str, user: str) -> str:
        names = [self.primary] + ([self.backup] if self.backup and self.backup != self.primary else [])
        err = None
        for name in names:
            try:
                reset_last()
                out = self.make(name)(system, user)
                self.model_used = last_model() or name  # post_chat reports the fallback model when it answered instead
                return out
            except Exception as e:  # noqa: BLE001 - any connection/HTTP problem moves on to the backup
                err = e
        raise err


def model_used(chat) -> str:
    """Name of the model behind `chat` (a ModelRouter reports what it really used; an injected fn counts as the primary)."""
    return getattr(chat, "model_used", None) or (last_model() if chat is local_chat_json else None) or model_name()
