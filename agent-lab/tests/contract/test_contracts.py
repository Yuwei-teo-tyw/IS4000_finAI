import json

import pytest
from pydantic import ValidationError

from advisory_agents.contracts import Fields, MessageRequest, ObjectiveUpdate, SpecialistRequest


def test_strict_money_and_wire_types():
    with pytest.raises(ValidationError):
        Fields(target_amount=500000)
    with pytest.raises(ValidationError):
        Fields(target_amount="NaN")
    with pytest.raises(ValidationError):
        Fields(currency="dollars")
    assert (
        Fields.model_validate_json('{"target_amount":"500000","currency":"SGD"}').currency == "SGD"
    )


def test_extra_model_confirmation_and_url_rejected():
    base = dict(
        fields=Fields(),
        changed_fields=[],
        switch_objective=False,
        ambiguous_fields=[],
        response="review",
    )
    with pytest.raises(ValidationError):
        ObjectiveUpdate(**base, confirmed=True)
    with pytest.raises(ValidationError):
        MessageRequest(
            owner_id="a", expected_revision=0, text="hello", executable_url="https://bad.example"
        )


def test_errors_hide_sentinel_input():
    sentinel = "SENTINEL_PRIVATE_TOKEN_VALUE"
    try:
        Fields(target_amount=sentinel)
    except ValidationError as exc:
        assert sentinel not in str(exc)


def test_schema_all_required_boundary():
    schema = SpecialistRequest.model_json_schema()
    assert schema["additionalProperties"] is False
    assert {
        "task_id",
        "run_id",
        "request_id",
        "trace_id",
        "objective_id",
        "revision",
        "context_revision",
    } <= set(schema["required"])
    assert "authorization" not in json.dumps(schema).lower()
