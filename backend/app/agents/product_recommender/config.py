"""
Runtime configuration, read from environment variables only.

    PRODUCT_DATA_STALE_AFTER_DAYS     Product data older than this is flagged stale (default 90, shared with the PM).
    RECOMMENDER_LIQUIDITY_NEED_MONTHS A dated withdrawal within this many months makes the liquidity-need check apply (default 12).
    RECOMMENDER_DRAWDOWN_HARD_LIMIT   "true" turns the single-product drawdown check from a note into an exclusion (default "false").
"""
import os
from dataclasses import dataclass, field


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


def get_settings() -> Settings:
    return Settings()
