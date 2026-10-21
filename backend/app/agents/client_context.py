"""
Workspace context for a chat turn sent by the Geneva frontend: who is asking
(RM / IC / PS) and which client is in focus.

The frontend sends `{"message": ..., "context": {...}}` over the WebSocket;
this turns the context into one system note for the specialists. Only known
fields are read, each is cleaned and length-capped, so the payload can't
smuggle arbitrary instructions into the prompt beyond those short values.
The backend has no client data of its own (IPS, holdings, notes stay in the
Geneva workspace), so the note tells the model not to guess them.
"""
import re
from typing import Any, Optional

from app.prompts.prompt_builder import get_prompt

ROLE_LABELS = {"rm": "Relationship Manager", "ic": "Investment Counsellor", "ps": "Product Specialist"}
MAX_FIELD_CHARS = 80


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text[:MAX_FIELD_CHARS] or None


def context_details(context: Any) -> Optional[str]:
    """The cleaned details ("the user is a ...; the client in focus is ..."), or None."""
    if not isinstance(context, dict):
        return None
    details = []
    role = ROLE_LABELS.get(str(context.get("role", "")).lower())
    if role:
        details.append(f"the user is a {role}")
    name, client_id = _clean(context.get("client_name")), _clean(context.get("client_id"))
    if name:
        details.append(f"the client in focus is {name}" + (f" (id {client_id})" if client_id else ""))
        risk = _clean(context.get("risk_category"))
        if risk:
            details.append(f"risk category {risk}")
        ips = context.get("ips_version")
        if isinstance(ips, int) and not isinstance(ips, bool) and ips > 0:
            details.append(f"active IPS v{ips}")
        elif ips is None and "ips_version" in context:
            details.append("no active IPS yet")
    return "; ".join(details) or None


def format_client_context(context: Any) -> Optional[str]:
    """System note for this turn, or None when there is no usable context."""
    details = context_details(context)
    return get_prompt("shared.client_context", details=details) if details else None
