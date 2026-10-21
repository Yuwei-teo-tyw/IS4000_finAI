"""
Prompt Builder - central loader for app/prompts/prompts.yaml.

Every agent prompt in this project lives in that YAML file, versioned, so
changing a prompt is a reviewable YAML diff rather than a code diff.

Usage:
    from app.prompts.prompt_builder import get_prompt

    system_text = get_prompt("general.system")
    note = get_prompt("shared.regenerate_note", feedback="too vague")

Version pinning: each key's YAML entry has a `latest` pointer used by
default. Override a specific key's version via the PROMPT_VERSION_OVERRIDES
env var (a JSON object mapping key -> version) for a rollback or an A/B
test without touching code:

    PROMPT_VERSION_OVERRIDES='{"general.system": "v1"}'

get_prompt_version(key) returns which version was actually resolved, so
callers can attach it to trace metadata (e.g. Langfuse) for prompt-level
analysis of which version produced which outcome.
"""
import os
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import yaml

_PROMPTS_PATH = Path(__file__).parent / "prompts.yaml"


class PromptNotFoundError(KeyError):
    pass


class PromptBuilder:
    """Loads prompts.yaml once and resolves versioned prompt templates."""

    def __init__(self, path: Path = _PROMPTS_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self._overrides: Dict[str, str] = self._load_overrides()
        self.reload()

    @staticmethod
    def _load_overrides() -> Dict[str, str]:
        raw = os.getenv("PROMPT_VERSION_OVERRIDES", "")
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print(f"PROMPT BUILDER: could not parse PROMPT_VERSION_OVERRIDES, ignoring: {raw!r}")
            return {}

    def reload(self) -> None:
        """Re-read prompts.yaml from disk. Useful for tests, or for
        hot-reloading prompt changes without restarting the process."""
        with self._lock:
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

    def _resolve(self, key: str) -> Tuple[Dict[str, Any], str]:
        try:
            agent, name = key.split(".", 1)
            entry = self._data[agent][name]
        except (ValueError, KeyError) as e:
            raise PromptNotFoundError(f"Unknown prompt key: {key!r}") from e

        version = self._overrides.get(key) or entry.get("latest")
        versions = entry.get("versions", {})
        if version not in versions:
            raise PromptNotFoundError(f"Prompt {key!r} has no version {version!r}")
        return versions[version], version

    def get(self, key: str, **format_kwargs) -> str:
        version_entry, _ = self._resolve(key)
        template = version_entry["template"].strip()
        if format_kwargs:
            return template.format(**format_kwargs)
        return template

    def get_version(self, key: str) -> str:
        _, version = self._resolve(key)
        return version


_builder: Optional[PromptBuilder] = None


def _get_builder() -> PromptBuilder:
    global _builder
    if _builder is None:
        _builder = PromptBuilder()
    return _builder


def get_prompt(key: str, **format_kwargs) -> str:
    return _get_builder().get(key, **format_kwargs)


def get_prompt_version(key: str) -> str:
    return _get_builder().get_version(key)
