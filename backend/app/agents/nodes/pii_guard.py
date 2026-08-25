"""
PII Guard subagent (placeholder) - scans the latest user message for common
PII patterns and redacts them before anything downstream (context
compaction, the LLM calls, logs) ever sees the raw value.

This is a lightweight regex-based first pass, not a production PII
detector. Swap in something like Microsoft Presidio, AWS Comprehend PII, or
a hosted DLP API before relying on this for real compliance guarantees -
free-text regex matching over financial content has real failure modes:
it will miss anything that doesn't match these exact shapes, and the bank
account pattern in particular is a coarse, keyword-gated heuristic that can
both over- and under-match.
"""
import re
from typing import Dict, Any, List, Tuple
from langchain_core.messages import HumanMessage
from langgraph.graph.message import RemoveMessage
from app.agents.state import AgentState

SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Keyword-gated so ordinary large numbers (e.g. "if I invest 1000000 dollars")
# aren't misflagged - only digit runs immediately following an account/routing
# keyword are treated as PII.
BANK_ACCOUNT_PATTERN = re.compile(
    r"\b(?:account|acct|routing)\b[^\d]{0,20}(\d{6,17})\b", re.IGNORECASE
)

# Candidate digit runs (with optional spaces/dashes) that *might* be a card
# number - validated against the Luhn checksum before being flagged, which
# cuts down false positives on order numbers, phone numbers, etc.
CREDIT_CARD_CANDIDATE_PATTERN = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact_pii(text: str) -> Tuple[str, List[str]]:
    """Returns (redacted_text, list of PII types found)."""
    found: List[str] = []

    if SSN_PATTERN.search(text):
        found.append("SSN")
        text = SSN_PATTERN.sub("[REDACTED-SSN]", text)

    if EMAIL_PATTERN.search(text):
        found.append("EMAIL")
        text = EMAIL_PATTERN.sub("[REDACTED-EMAIL]", text)

    if BANK_ACCOUNT_PATTERN.search(text):
        found.append("BANK_ACCOUNT")
        text = BANK_ACCOUNT_PATTERN.sub(
            lambda m: m.group(0).replace(m.group(1), "[REDACTED-ACCOUNT]"), text
        )

    cc_found = False

    def _cc_repl(m: "re.Match") -> str:
        nonlocal cc_found
        digits = re.sub(r"[ -]", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            cc_found = True
            return "[REDACTED-CREDIT_CARD]"
        return m.group()

    text = CREDIT_CARD_CANDIDATE_PATTERN.sub(_cc_repl, text)
    if cc_found:
        found.append("CREDIT_CARD")

    return text, found


class PIIGuard:
    """Redacts likely PII from the latest user message before it enters the graph."""

    async def run(self, state: AgentState) -> Dict[str, Any]:
        messages = state["messages"]
        human_messages = [m for m in messages if m.type == "human"]
        if not human_messages:
            return {}

        latest = human_messages[-1]
        if not isinstance(latest.content, str):
            return {}

        redacted_content, found = redact_pii(latest.content)
        if not found:
            return {"pii_redacted": False}

        print(f"PII GUARD: redacted {found} from latest message")

        removals = [RemoveMessage(id=latest.id)] if latest.id else []
        return {
            "messages": removals + [HumanMessage(content=redacted_content)],
            "pii_redacted": True,
        }
