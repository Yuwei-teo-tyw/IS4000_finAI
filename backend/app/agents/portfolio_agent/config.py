"""
Runtime configuration, read from environment variables only - no API keys
or endpoints are hard-coded anywhere in this service.

    PORTFOLIO_GROQ_API_KEY            The Portfolio Agent's own Groq key. If this variable is present at all
                                      (even empty), the PM never uses the shared GROQ_API_KEY, so it cannot bill
                                      someone else's account by accident; empty -> deterministic text only.
    GROQ_API_KEY                      Shared key, used only when PORTFOLIO_GROQ_API_KEY is absent.
    PORTFOLIO_LLM_ENABLED             "false" disables LLM explanations even if a key is present (default "true").
    PORTFOLIO_LLM_MODEL               Groq model id (default: the main app's CURRENT_MODEL).
    PORTFOLIO_LLM_TIMEOUT_SECONDS     Per-call timeout before falling back (default 30).
    PORTFOLIO_LLM_MAX_TOKENS          Max output tokens for the explanation call (default 2500).
    PORTFOLIO_STORE_MAX_ITEMS         In-memory proposal store capacity (default 500).
    MARKET_DATA_STALE_AFTER_DAYS      Market analysis older than this is flagged stale (default 30).
    PRODUCT_DATA_STALE_AFTER_DAYS     Product data older than this is flagged stale (default 90).
"""
import os
from dataclasses import dataclass, field

from app.core.constants import CURRENT_MODEL

OWN_KEY_VAR = "PORTFOLIO_GROQ_API_KEY"


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
    llm_enabled: bool = field(default_factory=lambda: _env_bool("PORTFOLIO_LLM_ENABLED", True))
    llm_model: str = field(default_factory=lambda: os.getenv("PORTFOLIO_LLM_MODEL") or CURRENT_MODEL)
    llm_timeout_seconds: int = field(default_factory=lambda: _env_int("PORTFOLIO_LLM_TIMEOUT_SECONDS", 30))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("PORTFOLIO_LLM_MAX_TOKENS", 2500))
    store_max_items: int = field(default_factory=lambda: _env_int("PORTFOLIO_STORE_MAX_ITEMS", 500))
    market_stale_after_days: int = field(default_factory=lambda: _env_int("MARKET_DATA_STALE_AFTER_DAYS", 30))
    product_stale_after_days: int = field(default_factory=lambda: _env_int("PRODUCT_DATA_STALE_AFTER_DAYS", 90))

    @property
    def groq_api_key(self) -> str | None:
        # Read on access rather than cached, so the key never ends up in a
        # repr()/log line of the settings object.
        if OWN_KEY_VAR in os.environ:
            return os.environ[OWN_KEY_VAR].strip() or None
        return os.getenv("GROQ_API_KEY") or None

    @property
    def llm_key_source(self) -> str:
        """Which variable the key comes from (never the key itself), for /health."""
        if OWN_KEY_VAR in os.environ:
            return OWN_KEY_VAR if os.environ[OWN_KEY_VAR].strip() else f"{OWN_KEY_VAR} (empty)"
        return "GROQ_API_KEY (shared)" if os.getenv("GROQ_API_KEY") else "none"


def get_settings() -> Settings:
    return Settings()
