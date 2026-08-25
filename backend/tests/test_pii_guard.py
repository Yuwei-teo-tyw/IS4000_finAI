"""
PII redaction: the regex/Luhn matching in `redact_pii`, and the `PIIGuard`
node's state-level behavior (which message it rewrites, when it leaves
state untouched).
"""
from langchain_core.messages import HumanMessage
from langgraph.graph.message import RemoveMessage

from app.agents.nodes.pii_guard import PIIGuard, redact_pii

from conftest import run_async

VALID_VISA = "4532015112830366"   # passes Luhn
INVALID_VISA = "4532015112830367"  # fails Luhn by one digit


def test_redacts_ssn():
    text, found = redact_pii("My SSN is 123-45-6789, please update it.")
    assert found == ["SSN"]
    assert "123-45-6789" not in text
    assert "[REDACTED-SSN]" in text


def test_redacts_email():
    text, found = redact_pii("Reach me at jane.doe@example.com anytime.")
    assert found == ["EMAIL"]
    assert "jane.doe@example.com" not in text
    assert "[REDACTED-EMAIL]" in text


def test_redacts_bank_account_when_keyword_gated():
    text, found = redact_pii("please debit account 123456789 today")
    assert found == ["BANK_ACCOUNT"]
    assert "123456789" not in text
    assert "[REDACTED-ACCOUNT]" in text


def test_large_number_without_keyword_is_not_flagged_as_bank_account():
    text, found = redact_pii("if I invest 100000000 dollars, what happens?")
    assert found == []
    assert text == "if I invest 100000000 dollars, what happens?"


def test_redacts_valid_luhn_credit_card():
    text, found = redact_pii(f"my card number is {VALID_VISA}")
    assert found == ["CREDIT_CARD"]
    assert VALID_VISA not in text
    assert "[REDACTED-CREDIT_CARD]" in text


def test_does_not_redact_invalid_luhn_number():
    text, found = redact_pii(f"order number {INVALID_VISA}")
    assert found == []
    assert INVALID_VISA in text


def test_redacts_multiple_pii_types_in_one_message():
    text, found = redact_pii(
        f"SSN 123-45-6789, email a@b.com, card {VALID_VISA}"
    )
    assert set(found) == {"SSN", "EMAIL", "CREDIT_CARD"}
    assert "123-45-6789" not in text
    assert "a@b.com" not in text
    assert VALID_VISA not in text


def test_clean_text_is_unchanged():
    text, found = redact_pii("What's a good ETF for retirement savings?")
    assert found == []
    assert text == "What's a good ETF for retirement savings?"


def test_pii_guard_rewrites_latest_human_message_and_flags_state():
    guard = PIIGuard()
    original = HumanMessage(content="my SSN is 123-45-6789", id="human-1")
    state = {"messages": [original]}

    result = run_async(guard.run(state))

    assert result["pii_redacted"] is True
    ops = result["messages"]
    removal = next(m for m in ops if isinstance(m, RemoveMessage))
    assert removal.id == "human-1"
    replacement = next(m for m in ops if isinstance(m, HumanMessage))
    assert "123-45-6789" not in replacement.content
    assert "[REDACTED-SSN]" in replacement.content


def test_pii_guard_leaves_clean_message_alone():
    guard = PIIGuard()
    state = {"messages": [HumanMessage(content="what's a good ETF?", id="human-1")]}

    result = run_async(guard.run(state))

    assert result == {"pii_redacted": False}


def test_pii_guard_noop_with_no_human_messages():
    guard = PIIGuard()
    result = run_async(guard.run({"messages": []}))
    assert result == {}
