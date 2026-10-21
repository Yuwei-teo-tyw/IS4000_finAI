"""
Runtime configuration, read from environment variables only. Risk
thresholds are not configured here: they live in the versioned policy file
(data/policy.json) so every finding can cite the policy version it used.

    RISK_POLICY_PATH                  Use a different policy file (default: data/policy.json).
    PRODUCT_DATA_STALE_AFTER_DAYS     Passed to the shared suitability gate for its stale-data notes (default 90, shared with the PM).
    RECOMMENDER_LIQUIDITY_NEED_MONTHS A dated withdrawal within this many months makes the liquidity-need check apply (default 12, shared with the Product Recommender).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_path(name: str) -> Optional[Path]:
    raw = os.getenv(name)
    return Path(raw) if raw and raw.strip() else None


@dataclass(frozen=True)
class Settings:
    policy_path: Optional[Path] = field(default_factory=lambda: _env_path("RISK_POLICY_PATH"))
    product_stale_after_days: int = field(default_factory=lambda: _env_int("PRODUCT_DATA_STALE_AFTER_DAYS", 90))
    liquidity_need_months: int = field(default_factory=lambda: _env_int("RECOMMENDER_LIQUIDITY_NEED_MONTHS", 12))


def get_settings() -> Settings:
    return Settings()
