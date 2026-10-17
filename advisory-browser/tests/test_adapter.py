"""Security/contract tests over real ASGI HTTP, backend transport isolated."""

import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import configuration

_, runtime_root, _ = configuration()
sys.path[:0] = [
    str(runtime_root / "backend/src"),
    str(runtime_root / "backend/foundation/src"),
]
import server

ORIGIN = "http://127.0.0.1:8820"
TOKEN = "synthetic-test-auth-private-value"


@pytest.fixture
def client(monkeypatch):
    for key, value in {
        "LAB_INTERNAL_API_TOKEN": TOKEN,
        "LAB_ORCHESTRATION_MODE": "POLICY_ONLY",
        "LAB_CLARIFIER_PROVIDER": "scripted",
        "LAB_SPECIALIST_MODE": "MOCK_HTTP",
    }.items():
        monkeypatch.setenv(key, value)
    with TestClient(server.app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as browser:
        yield browser


def submit(client, operation="new", payload=None, resource=None, **kwargs):
    return client.post(
        "/api/command",
        json={
            "operation": operation,
            "payload": payload or {"owner_id": "synthetic-test"},
            "resource_id": resource,
        },
        **kwargs,
    )


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost:8820", "null"]
)
def test_cross_origin(client, origin):
    assert submit(client, headers={"Origin": origin}).status_code == 403


def test_origin_required(client):
    with TestClient(server.app, base_url=ORIGIN) as browser:
        assert submit(browser).status_code == 403


def test_host_and_fetch_site(client):
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize(
    "operation,payload,resource",
    [
        ("proxy", {"owner_id": "x", "url": "https://evil.example"}, None),
        ("objective", {"owner_id": "x"}, "../secret"),
        ("objective", {"owner_id": "x"}, "http://127.0.0.1:11434"),
        ("new", {"owner_id": "x", "mode": "HYBRID_SCRIPTED"}, None),
        ("new", {"owner_id": "x", "token": "leak"}, None),
        (
            "execute",
            {
                "owner_id": "x",
                "plan_id": "p",
                "idempotency_key": "k",
                "mode": "DRY_RUN",
            },
            None,
        ),
        ("message", {"owner_id": "x", "expected_revision": 0, "text": ""}, "sid"),
        ("new", {"owner_id": "https://evil.example"}, None),
    ],
)
def test_rejected_before_dispatch(client, operation, payload, resource):
    assert submit(client, operation, payload, resource).status_code == 422


def test_request_size_and_json(client):
    assert (
        client.post(
            "/api/command",
            content="x" * 17000,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/command", content="bad", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/command", content="bad", headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )


def test_real_fixed_route_and_private_auth(client):
    observed = []

    def handler(request):
        observed.append(
            (str(request.url), request.method, request.headers.get("authorization"))
        )
        return httpx.Response(
            200,
            json={"session_id": "s", "response": TOKEN, "headers": {"token": TOKEN}},
        )

    server.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = submit(client)
    assert response.status_code == 200
    assert observed == [
        ("http://127.0.0.1:8811/v1/sessions", "POST", "Bearer " + TOKEN)
    ]
    assert TOKEN not in response.text
    assert "content-security-policy" in response.headers
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (409, {"detail": "STALE_REVISION"}, "STALE_REVISION"),
        (401, {"detail": TOKEN}, "BACKEND_REQUEST_REJECTED"),
        (422, {"detail": [{"input": TOKEN}]}, "BACKEND_REQUEST_REJECTED"),
        (503, {"detail": "MODEL_UNAVAILABLE"}, "MODEL_UNAVAILABLE"),
    ],
)
def test_safe_error_semantics(client, status, body, expected):
    server.app.state.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    )
    response = submit(client)
    assert response.status_code == status
    assert response.json()["error"]["code"] == expected
    assert TOKEN not in response.text


def test_response_bounds_and_malformed(client):
    server.app.state.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"x" * 1048577)
        )
    )
    assert submit(client).json()["error"]["code"] == "BACKEND_RESPONSE_TOO_LARGE"
    server.app.state.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"not json")
        )
    )
    assert submit(client).json()["error"]["code"] == "BACKEND_CONTRACT_ERROR"


def test_unavailable_no_retry(client):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("private raw error", request=request)

    server.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert submit(client).json()["error"]["code"] == "BACKEND_UNAVAILABLE"
    assert len(calls) == 1


def test_assets_offline_and_no_arbitrary_file(client):
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/demo-config.json").status_code == 404
    assert client.get("/assets/../../runtime.py").status_code == 404
