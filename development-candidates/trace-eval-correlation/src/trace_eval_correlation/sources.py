"""Manifest-bound, read-only source resolution and hashing.

Reusable logic never embeds local absolute paths: a manifest names roots, and the
caller may rebind each root. Every reference must stay inside its root.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TypeGuard

from trace_eval_correlation.schema import NA, UNAVAILABLE, ArtifactRef, HashStatus, Missing

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class UnjoinableReference(ValueError):
    """A reference that cannot be resolved inside its declared root."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: object) -> str:
    """Compact sorted JSON; the canonicalization the historical campaigns used."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(text.encode("utf-8"))


def is_safe_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(SAFE_ID.match(value)) and ".." not in value


class Resolver:
    """Resolves "<root>:<relative>" references against bound root directories."""

    def __init__(self, roots: dict[str, Path]) -> None:
        self._roots = {name: path.resolve() for name, path in roots.items()}

    @property
    def roots(self) -> dict[str, Path]:
        return dict(self._roots)

    def resolve(self, root: str, relative: str) -> Path:
        if root not in self._roots:
            raise UnjoinableReference("ROOT_UNBOUND")
        rel = Path(relative)
        if rel.is_absolute() or rel.drive or any(part == ".." for part in rel.parts):
            raise UnjoinableReference("REFERENCE_ESCAPES_ROOT")
        base = self._roots[root]
        target = (base / rel).resolve()
        if target != base and base not in target.parents:
            raise UnjoinableReference("REFERENCE_ESCAPES_ROOT")
        return target


def ref_text(root: str, *parts: str) -> str:
    return f"{root}:" + "/".join(p.strip("/") for p in parts if p)


def file_sha256(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def hash_status(actual: str | None, expected: str | None, *, stale: bool) -> HashStatus:
    if actual is None:
        return "MISSING_FILE"
    if expected is None:
        return "NOT_PINNED" if stale else "NOT_LISTED"
    if actual == expected:
        return "VERIFIED"
    return "STALE" if stale else "MISMATCH"


def artifact(
    kind: str,
    ref: str,
    path: Path,
    *,
    listed: dict[str, str] | None,
    listed_key: str,
    pins: dict[str, str],
    pin_key: str,
) -> ArtifactRef:
    """Hash one file and compare it with the campaign manifest and this manifest's pin."""
    actual = file_sha256(path)
    source_manifest: HashStatus | Missing = (
        NA if listed is None else hash_status(actual, listed.get(listed_key), stale=False)
    )
    pin: HashStatus | Missing = (
        hash_status(actual, pins[pin_key], stale=True) if pin_key in pins else NA
    )
    return ArtifactRef(
        kind=kind,
        ref=ref,
        sha256=actual if actual is not None else UNAVAILABLE,
        source_manifest=source_manifest,
        pin=pin,
    )


def read_json(path: Path) -> tuple[object | None, str | None]:
    """Return (value, error_code). Error codes never include file content."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "MISSING_FILE"
    except OSError:
        return None, "UNREADABLE_FILE"
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "MALFORMED_JSON"
