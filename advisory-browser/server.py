"""Fixed public HTTP operations, same-origin browser transport; no business engine."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from advisory_agents.contracts import (
    ConfirmRequest,
    MessageRequest,
    RunRequest,
    SessionRequest,
)
from advisory_agents.orchestrator.runtime_models import RuntimePlanRequest
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from runtime import PACKAGE, TREE

ORIGIN = "http://127.0.0.1:8820"
ORIGINS = {
    "clarifier": "http://127.0.0.1:8811",
    "orchestrator": "http://127.0.0.1:8812",
    "mocks": "http://127.0.0.1:8890",
}
MAX_BODY = 16384
MAX_RESPONSE = 1048576
ID = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,90}$")


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    owner_id: str
    resource_id: str


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    operation: Literal[
        "new",
        "objective",
        "message",
        "confirm",
        "plan",
        "attempt",
        "execute",
        "run",
        "events",
        "cancel",
    ]
    resource_id: str | None = None
    payload: dict


MODELS = {
    "new": SessionRequest,
    "objective": SessionRequest,
    "message": MessageRequest,
    "confirm": ConfirmRequest,
    "plan": RuntimePlanRequest,
    "attempt": SessionRequest,
    "execute": RunRequest,
    "run": SessionRequest,
    "events": SessionRequest,
    "cancel": SessionRequest,
}


def failure(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)


def sanitized(value, token):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if any(
                w in k.lower()
                for w in (
                    "authorization",
                    "token",
                    "secret",
                    "password",
                    "headers",
                    "api_key",
                )
            )
            else sanitized(v, token)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitized(item, token) for item in value]
    if isinstance(value, str) and token:
        return value.replace(token, "[REDACTED]")
    return value


@asynccontextmanager
async def lifespan(app):
    if not os.environ.get("LAB_INTERNAL_API_TOKEN"):
        raise RuntimeError("SYNTHETIC_AUTH_REQUIRED")
    if (
        os.environ.get("LAB_ORCHESTRATION_MODE") != "POLICY_ONLY"
        or os.environ.get("LAB_CLARIFIER_PROVIDER") != "scripted"
        or os.environ.get("LAB_SPECIALIST_MODE") != "MOCK_HTTP"
    ):
        raise RuntimeError("TRUSTED_MODE_REQUIRED")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15),
        trust_env=False,
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(retries=0),
    ) as client:
        app.state.client = client
        yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def browser_boundary(request: Request, call_next):
    if request.headers.get("host") != "127.0.0.1:8820":
        return failure(403, "HOST_REJECTED")
    if request.headers.get("origin") not in (None, ORIGIN):
        return failure(403, "ORIGIN_REJECTED")
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        return failure(403, "CROSS_SITE_REJECTED")
    if request.method == "POST":
        if request.headers.get("origin") != ORIGIN:
            return failure(403, "ORIGIN_REQUIRED")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return failure(415, "JSON_REQUIRED")
    response = await call_next(request)
    response.headers.update(
        {
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
        }
    )
    return response


async def forward(service, method, path, body=None, params=None):
    token = os.environ.get("LAB_INTERNAL_API_TOKEN", "")
    try:
        async with app.state.client.stream(
            method,
            ORIGINS[service] + path,
            json=body,
            params=params,
            headers={"Authorization": "Bearer " + token},
        ) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_RESPONSE:
                    return failure(502, "BACKEND_RESPONSE_TOO_LARGE")
            try:
                value = json.loads(data)
            except (ValueError, UnicodeError):
                return failure(502, "BACKEND_CONTRACT_ERROR")
            if not response.is_success:
                detail = value.get("detail") if isinstance(value, dict) else None
                if detail is None and isinstance(value, dict):
                    detail = (
                        value.get("error", {}).get("code")
                        if isinstance(value.get("error"), dict)
                        else value.get("code")
                    )
                code = (
                    detail
                    if isinstance(detail, str) and SAFE_CODE.fullmatch(detail)
                    else "BACKEND_REQUEST_REJECTED"
                )
                return failure(response.status_code, code)
            if not isinstance(value, (dict, list)):
                return failure(502, "BACKEND_CONTRACT_ERROR")
            return JSONResponse(sanitized(value, token))
    except httpx.TimeoutException:
        return failure(
            504,
            "BACKEND_TIMEOUT_OUTCOME_UNKNOWN"
            if method == "POST"
            else "BACKEND_TIMEOUT",
        )
    except httpx.HTTPError:
        return failure(503, "BACKEND_UNAVAILABLE")


@app.get("/api/health")
async def health():
    services = {}
    for name in ORIGINS:
        result = await forward(name, "GET", "/ready")
        value = json.loads(result.body)
        services[name] = (
            "READY"
            if result.status_code == 200 and value.get("status") == "READY"
            else "UNAVAILABLE"
        )
    return {
        "instance": os.environ.get("FINAI_BROWSER_INSTANCE"),
        "services": services,
        "mode": "POLICY_ONLY",
        "clarifier": "scripted",
        "specialists": "MOCK_HTTP",
        "source_tree": TREE,
        "status": "READY"
        if all(v == "READY" for v in services.values())
        else "UNAVAILABLE",
    }


@app.post("/api/command")
async def command(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BODY:
            return failure(413, "REQUEST_TOO_LARGE")
    try:
        command = Command.model_validate_json(bytes(raw))
        op = command.operation
        body = MODELS[op].model_validate(command.payload).model_dump(mode="json")
        if not ID.fullmatch(body["owner_id"]):
            raise ValueError
        rid = command.resource_id
        needs_resource = op in {
            "objective",
            "message",
            "confirm",
            "attempt",
            "run",
            "events",
            "cancel",
        }
        if needs_resource and (not rid or not ID.fullmatch(rid)):
            raise ValueError
        if not needs_resource and rid is not None:
            raise ValueError
        if op == "execute" and body["mode"] != "MOCK_HTTP":
            raise ValueError
    except (ValidationError, ValueError, TypeError, KeyError):
        return failure(422, "INVALID_BROWSER_REQUEST")
    owner = {"owner_id": body["owner_id"]}
    # Every destination and path template is trusted code, never an arbitrary URL.
    routes = {
        "new": ("clarifier", "POST", "/v1/sessions"),
        "objective": ("clarifier", "GET", f"/v1/sessions/{rid}/objective"),
        "message": ("clarifier", "POST", f"/v1/sessions/{rid}/messages"),
        "confirm": ("clarifier", "POST", f"/v1/sessions/{rid}/confirm"),
        "plan": ("orchestrator", "POST", "/v2/plans"),
        "attempt": ("orchestrator", "GET", f"/v2/planning-attempts/{rid}"),
        "execute": ("orchestrator", "POST", "/v1/runs"),
        "run": ("orchestrator", "GET", f"/v1/runs/{rid}"),
        "events": ("orchestrator", "GET", f"/v1/runs/{rid}/events"),
        "cancel": ("orchestrator", "POST", f"/v1/runs/{rid}/cancel"),
    }
    service, method, path = routes[op]
    return await forward(
        service,
        method,
        path,
        body if method == "POST" and op != "cancel" else None,
        owner if method == "GET" or op == "cancel" else None,
    )


@app.get("/")
async def index():
    return FileResponse(PACKAGE / "assets/index.html")


@app.get("/assets/{name}")
async def asset(name: str):
    if name not in {"app.js", "style.css"}:
        return failure(404, "ASSET_NOT_FOUND")
    return FileResponse(PACKAGE / "assets" / name)
