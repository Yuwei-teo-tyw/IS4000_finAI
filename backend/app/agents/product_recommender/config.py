"""
Runtime configuration, read from environment variables only.

    PRODUCT_DATA_STALE_AFTER_DAYS     Product data older than this is flagged stale (default 90, shared with the PM).
    RECOMMENDER_LIQUIDITY_NEED_MONTHS A dated withdrawal within this many months makes the liquidity-need check apply (default 12).
    RECOMMENDER_DRAWDOWN_HARD_LIMIT   "true" turns the single-product drawdown check from a note into an exclusion (default "false").
    GROQ_API_KEY                      LLM key (shared with the main app). Unset -> deterministic text only.
    RECOMMENDER_LLM_ENABLED           "false" disables LLM-written reasons and narratives even if a key is present (default "true").
    RECOMMENDER_LLM_MODEL             Groq model id (default: the main app's CURRENT_MODEL).
    RECOMMENDER_LLM_TIMEOUT_SECONDS   Per-call timeout before falling back (default 30).
    RECOMMENDER_LLM_MAX_TOKENS        Max output tokens per call, including a reasoning model's hidden reasoning (default 6000).
"""
import os
from dataclasses import dataclass, field

from app.core.constants import CURRENT_MODEL


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    product_stale_after_days: int = field(default_factory=lambda: _env_int("PRODUCT_DATA_STALE_AFTER_DAYS", 90))
    liquidity_need_months: int = field(default_factory=lambda: _env_int("RECOMMENDER_LIQUIDITY_NEED_MONTHS", 12))
    drawdown_hard_limit: bool = field(default_factory=lambda: _env_bool("RECOMMENDER_DRAWDOWN_HARD_LIMIT", False))
    llm_enabled: bool = field(default_factory=lambda: _env_bool("RECOMMENDER_LLM_ENABLED", True))
    llm_model: str = field(default_factory=lambda: os.getenv("RECOMMENDER_LLM_MODEL") or CURRENT_MODEL)
    llm_timeout_seconds: int = field(default_factory=lambda: _env_int("RECOMMENDER_LLM_TIMEOUT_SECONDS", 30))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("RECOMMENDER_LLM_MAX_TOKENS", 6000))

    @property
    def groq_api_key(self) -> str | None:
        # Read on access, so the key never lands in a repr() or log line.
        return os.getenv("GROQ_API_KEY") or None


def get_settings() -> Settings:
    return Settings()
