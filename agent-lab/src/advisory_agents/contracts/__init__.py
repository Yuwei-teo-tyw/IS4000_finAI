"""Canonical lab v1 JSON contracts. Extra fields always fail closed."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def uid() -> str:
    return str(uuid4())


def utc() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: dict[str, object]) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)


Family = Literal["goal", "investment", "portfolio", "scenario", "unknown"]
Money = str


class Fields(Wire):
    family: Family = "unknown"
    target_amount: str | None = Field(default=None, pattern=r"^\d+(\.\d{1,2})?$")
    current_amount: str | None = Field(default=None, pattern=r"^\d+(\.\d{1,2})?$")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    horizon_months: int | None = Field(default=None, gt=0, le=1200)
    monthly_contribution: str | None = Field(default=None, pattern=r"^\d+(\.\d{1,2})?$")
    comparison: str | None = Field(default=None, max_length=500)
    constraints: str | None = Field(default=None, max_length=500)


class ObjectiveUpdate(Wire):
    """A proposal only. Confirmation is deliberately absent."""

    fields: Fields
    changed_fields: list[str] = Field(max_length=8)
    switch_objective: bool
    ambiguous_fields: list[str] = Field(max_length=8)
    response: str = Field(max_length=1000)


class Objective(Wire):
    schema_version: Literal["1.0"] = "1.0"
    session_id: str
    owner_id: str
    objective_id: str = Field(default_factory=uid)
    revision: int = 0
    context_revision: int = 0
    fields: Fields = Field(default_factory=Fields)
    provenance: dict[str, str] = Field(default_factory=dict)
    turn_ids: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=lambda: ["family"])
    contradictions: list[str] = Field(default_factory=list)
    readiness: Literal["NEEDS_INPUT", "READY", "CONFIRMED", "BUDGET_EXHAUSTED"] = "NEEDS_INPUT"
    content_digest: str = ""
    confirmed_digest: str | None = None
    confirmed_revision: int | None = None
    response: str = "What would you like to explore?"


class SessionRequest(Wire):
    owner_id: str = Field(min_length=1, max_length=100)


class MessageRequest(Wire):
    owner_id: str
    expected_revision: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=3000)
    request_id: str = Field(default_factory=uid)
    trace_id: str = Field(default_factory=uid)


class ConfirmRequest(Wire):
    owner_id: str
    revision: int
    content_digest: str
    request_id: str = Field(default_factory=uid)
    trace_id: str = Field(default_factory=uid)


class Task(Wire):
    task_id: str = Field(min_length=1, max_length=60, pattern=r"^[a-zA-Z0-9_-]+$")
    capability: str
    depends_on: list[str] = Field(max_length=8)
    required: bool


class PlanProposal(Wire):
    tasks: list[Task] = Field(min_length=1, max_length=8)
    reason: str = Field(max_length=500)


class PlanRequest(Wire):
    owner_id: str
    session_id: str
    revision: int
    content_digest: str
    request_id: str = Field(default_factory=uid)
    trace_id: str = Field(default_factory=uid)


class Plan(Wire):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(default_factory=uid)
    binding: PlanRequest
    objective_id: str
    context_revision: int
    proposal: PlanProposal
    accepted: bool
    created_at: str = Field(default_factory=utc)


class RunRequest(Wire):
    owner_id: str
    plan_id: str
    idempotency_key: str = Field(min_length=1, max_length=100)
    mode: Literal["DRY_RUN", "MOCK_HTTP"] = "DRY_RUN"


class SpecialistRequest(Wire):
    schema_version: Literal["1.0"]
    request_id: str
    trace_id: str
    run_id: str
    task_id: str
    objective_id: str
    revision: int
    context_revision: int
    capability: str
    currency: str | None
    units: Literal["synthetic"]


class SpecialistResult(SpecialistRequest):
    label: Literal["MOCK"]
    status: Literal["SUCCEEDED"]
    timestamp: str = Field(min_length=20, max_length=40)

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        try:
            instant = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("UTC_ISO_TIMESTAMP_REQUIRED") from None
        if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
            raise ValueError("UTC_ISO_TIMESTAMP_REQUIRED")
        return value


class FaultRequest(Wire):
    mode: Literal[
        "none",
        "unavailable",
        "timeout",
        "rate_limit",
        "malformed",
        "wrong_binding",
        "stale",
        "duplicate",
        "optional_failure",
    ]


class Event(Wire):
    timestamp: str = Field(default_factory=utc)
    capability: str | None = None
    task_id: str | None = None
    status: str
    method: str | None = None
    path: str | None = None
    duration_ms: float | None = None


class Run(Wire):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(default_factory=uid)
    owner_id: str
    plan_id: str
    mode: Literal["DRY_RUN", "MOCK_HTTP"]
    status: str = "PENDING"
    events: list[Event] = Field(default_factory=list)
    results: dict[str, SpecialistResult] = Field(default_factory=dict)
