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
import time
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


def auth_headers(url: str) -> dict:
    """Content-Type plus a Bearer token when a key is configured (hosted APIs such as Groq need one; LM Studio does not)."""
    h = {"Content-Type": "application/json"}
    key = os.getenv("CLIENT_PROFILING_LLM_API_KEY") or (os.getenv("GROQ_API_KEY") if "groq.com" in url else None)
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


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
                     headers=auth_headers(url))
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


class ModelUnavailable(ConnectionError):
    """Circuit breaker open: a recent call failed (connection / auth / quota / server error), so no new call is attempted."""


_brk = {"until": 0.0, "reason": ""}  # process-wide circuit breaker: monotonic time until which model calls are skipped
_brk_lock = threading.Lock()
_probe = {"ok_until": 0.0, "bad_until": 0.0}
_probe_lock = threading.Lock()


def cooldown_s() -> float:
    return float(os.getenv("CLIENT_PROFILING_LLM_COOLDOWN_S", "60"))


def breaker_open() -> bool:
    return time.monotonic() < _brk["until"]


def trip_breaker(e: BaseException) -> None:
    with _brk_lock:
        _brk["until"], _brk["reason"] = time.monotonic() + cooldown_s(), f"{type(e).__name__}: {e}"[:200]
        _probe["ok_until"] = 0.0
    log.warning("model circuit breaker open for %.0fs (%s)", cooldown_s(), _brk["reason"])


def _trips_breaker(e: BaseException) -> bool:
    """Model is down for every caller: connection failure, read/connect timeout, auth / quota / not found / server error.
    A 400 (bad request) or a bad reply says nothing about availability and never trips it."""
    if isinstance(e, LLMHTTPError):
        return e.status in (401, 402, 403, 404, 429) or e.status >= 500
    return isinstance(e, (OSError, http.client.HTTPException))


def model_available(response_format: Optional[dict] = None) -> bool:
    """False while the breaker is open. Otherwise (at most once per cooldown, single-flight) a tiny probe call confirms the model
    accepts our kind of request (pass the real `response_format` so a schema the provider rejects is caught too). Any probe failure
    marks the model unavailable for the cooldown (a connection/auth/quota failure also opens the global breaker). Used to
    short-circuit to synthetic text before any real work."""
    now = time.monotonic()
    if breaker_open() or now < _probe["bad_until"]:
        return False
    with _probe_lock:
        now = time.monotonic()
        if breaker_open() or now < _probe["bad_until"]:
            return False
        if now < _probe["ok_until"]:
            return True
        body = {"model": model_name(), "temperature": 0, "max_tokens": 512,
                "messages": [{"role": "user", "content": "Reply with an empty JSON object."}]}
        if response_format:
            body["response_format"] = response_format
        try:
            post_chat(body, float(os.getenv("CLIENT_PROFILING_PROBE_TIMEOUT_S", "15")))
        except Exception as e:  # noqa: BLE001
            _probe["bad_until"] = time.monotonic() + cooldown_s()
            log.warning("model probe failed, using synthetic text for %.0fs (%s: %s)", cooldown_s(), type(e).__name__, str(e)[:200])
            return False
        _probe["ok_until"] = time.monotonic() + cooldown_s()
        return True


def _strictify(node):
    """Strict structured output (Groq, OpenAI) needs `additionalProperties: false` and every property in `required` on each object; add both."""
    if isinstance(node, dict):
        out = {k: _strictify(v) for k, v in node.items()}
        if isinstance(out.get("properties"), dict) and out.get("type") == "object":
            out["additionalProperties"] = False
            out["required"] = list(dict.fromkeys([*(out.get("required") or []), *out["properties"]]))
        return out
    return [_strictify(v) for v in node] if isinstance(node, list) else node


def post_chat(body: dict, timeout: float) -> dict:
    """Circuit-breaker wrapper around `_post_chat`: while the breaker is open raise ModelUnavailable at once; a connection /
    auth / quota / server / timeout failure opens it for CLIENT_PROFILING_LLM_COOLDOWN_S (default 60)."""
    _record(None, False)
    js = (body.get("response_format") or {}).get("json_schema")
    if js and js.get("strict") and isinstance(js.get("schema"), dict):
        body = {**body, "response_format": {**body["response_format"], "json_schema": {**js, "schema": _strictify(js["schema"])}}}
    if breaker_open():
        raise ModelUnavailable(f"model skipped (circuit breaker open: {_brk['reason']})")
    try:
        return _post_chat(body, timeout)
    except Exception as e:  # noqa: BLE001
        if _trips_breaker(e):
            trip_breaker(e)
        raise


def _post_chat(body: dict, timeout: float) -> dict:
    """POST an OpenAI chat-completions body to the primary model and return the OpenAI-shaped reply dict.
    If the primary is unreachable / not loaded (see is_unavailable) retry ONCE on LM Studio's native chat endpoint with the
    fallback model; the returned dict then carries fallback=True and the fallback model name. Never falls back for a
    reachable-but-bad reply. Records which model answered (last_model / fallback_active)."""
    _record(None, False)
    connect = float(os.getenv("CLIENT_PROFILING_CONNECT_TIMEOUT_S", "2"))
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
