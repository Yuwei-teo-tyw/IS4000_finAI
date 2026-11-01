"""
Model SAA library: reference allocations per 3L bucket (Longevity, Legacy), loaded from library.json.

The library is configuration, not client data: the Portfolio Agent evaluates these models against one
client and recommends the best fit (see selection.py). Liquidity has no SAA, so it has no library.
`load_library()` validates the file once (weights add to 100, unique ids, known asset classes and
objectives, each model within the growth cap of its own risk level) and raises LibraryError on any fault,
so a bad edit fails loudly instead of producing silent recommendations.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

LIBRARY_PATH = Path(__file__).parent / "library.json"
SaaBucket = Literal["longevity", "legacy"]
SAA_BUCKETS: tuple[SaaBucket, ...] = ("longevity", "legacy")


class LibraryError(RuntimeError):
    """The model library file is missing or invalid."""


class ModelSaa(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=20)
    name: str
    risk_level: int = Field(ge=1, le=5)
    strategy_code: str = Field(pattern="^[A-F]$")
    objectives: list[str]
    min_horizon_years: float = Field(ge=0)
    purpose: str
    rationale: str
    weights: dict[str, float]


class BucketLibrary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    purpose: str
    models: list[ModelSaa]


class Framework(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    weights: dict[str, float]
    horizon_comfort_years: float
    growth_classes: list[str]
    illiquid_classes: list[str]
    max_illiquid_pct: float
    growth_cap_by_risk_level: dict[str, float]
    max_change_pp_warning: float


class Library(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: str
    asset_classes: list[str]
    objective_vocabulary: list[str]
    framework: Framework
    buckets: dict[SaaBucket, BucketLibrary]

    def bucket(self, b: SaaBucket) -> BucketLibrary:
        return self.buckets[b]

    def model(self, b: SaaBucket, model_id: str) -> Optional[ModelSaa]:
        return next((m for m in self.buckets[b].models if m.id == model_id), None)

    def growth_share(self, weights: dict[str, float]) -> float:
        return round(sum(weights.get(c, 0) for c in self.framework.growth_classes), 2)

    def illiquid_share(self, weights: dict[str, float]) -> float:
        return round(sum(weights.get(c, 0) for c in self.framework.illiquid_classes), 2)

    def growth_cap(self, risk_level: int) -> float:
        return self.framework.growth_cap_by_risk_level[str(max(1, min(5, risk_level)))]


def _check(lib: Library) -> None:
    w = lib.framework.weights
    if abs(sum(w.values()) - 100) > 1e-6:
        raise LibraryError(f"framework weights add to {sum(w.values())}, not 100")
    if set(lib.buckets) != set(SAA_BUCKETS):
        raise LibraryError("the library needs exactly the longevity and legacy buckets")
    ids: set[str] = set()
    for b, bl in lib.buckets.items():
        if not bl.models:
            raise LibraryError(f"{b} has no models")
        for m in bl.models:
            if m.id in ids:
                raise LibraryError(f"duplicate model id {m.id}")
            ids.add(m.id)
            if abs(sum(m.weights.values()) - 100) > 0.01:
                raise LibraryError(f"{m.id} weights add to {sum(m.weights.values())}, not 100")
            unknown = set(m.weights) - set(lib.asset_classes)
            if unknown:
                raise LibraryError(f"{m.id} uses unknown asset classes {sorted(unknown)}")
            if any(v < 0 for v in m.weights.values()):
                raise LibraryError(f"{m.id} has a negative weight")
            bad = set(m.objectives) - set(lib.objective_vocabulary)
            if bad:
                raise LibraryError(f"{m.id} uses unknown objectives {sorted(bad)}")
            if lib.growth_share(m.weights) > lib.growth_cap(m.risk_level) + 1e-9:
                raise LibraryError(f"{m.id} exceeds the growth cap of risk level {m.risk_level}")


def parse_library(raw: dict) -> Library:
    try:
        lib = Library.model_validate(raw)
    except ValidationError as e:
        raise LibraryError(f"model library is invalid ({e.error_count()} errors)") from e
    _check(lib)
    return lib


@lru_cache(maxsize=1)
def load_library(path: Optional[str] = None) -> Library:
    p = Path(path) if path else LIBRARY_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise LibraryError(f"model library could not be read: {type(e).__name__}") from e
    return parse_library(raw)
