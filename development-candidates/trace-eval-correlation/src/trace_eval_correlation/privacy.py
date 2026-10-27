"""Metadata-only privacy filter.

The adapter copies an explicit allowlist of scalar fields and never copies free text
(human input, model output, displays, rationales, request messages or provider account
metadata). This pass is defence in depth over that allowlist: any surviving string that
looks like a credential or a direct personal identifier is replaced, and only the field
name is reported.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

REDACTED = "REDACTED"

_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)\b(api[_-]?key|authorization|password|passwd|secret|token)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\blsv2_[A-Za-z0-9_]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\+\d{1,3}[ -]?\d{3,4}[ -]?\d{4}\b"),
    re.compile(r"\b[STFGM]\d{7}[A-Z]\b"),  # Singapore NRIC/FIN shape
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN shape
)


def is_sensitive(value: str) -> bool:
    return any(p.search(value) for p in _PATTERNS)


def scrub(tree: Any, on_redact: Callable[[str], None], path: str = "") -> Any:
    """Return a copy of a JSON-like tree with sensitive strings replaced."""
    if isinstance(tree, dict):
        return {k: scrub(v, on_redact, f"{path}.{k}" if path else str(k)) for k, v in tree.items()}
    if isinstance(tree, list):
        return [scrub(v, on_redact, f"{path}[]") for v in tree]
    if isinstance(tree, str) and is_sensitive(tree):
        on_redact(path)
        return REDACTED
    return tree
