"""
Portfolio Agent house assumptions (capital market assumptions and stress
scenarios). The Market Researcher reports observed data and a cycle call but
no return forecasts, so expected returns and scenario returns come from this
explicit, illustrative assumption set - always labelled basis=ASSUMPTION,
never attributed to the Market Researcher. Replace the JSON with the
investment office's approved CMAs in a real deployment.
"""
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).parent / "capital_market_assumptions.json"


@dataclass(frozen=True)
class ScenarioAssumption:
    name: str
    horizon: str
    narrative: str
    uses_recession_probability: bool
    asset_class_returns: dict


@dataclass(frozen=True)
class CapitalMarketAssumptions:
    label: str
    as_of: str
    long_term_expected_return: dict  # asset class -> % p.a.
    horizon: str
    scenarios: tuple
    volatility: dict = field(default_factory=dict)  # asset class -> % p.a. standard deviation
    correlation_labels: tuple = ()
    correlation_matrix: tuple = ()  # rows in correlation_labels order

    def covariance(self, classes: list[str]):
        """Covariance matrix (in %^2) for `classes`, or None if any class lacks a
        volatility or correlation - never a guessed value."""
        import numpy as np

        idx = {c: i for i, c in enumerate(self.correlation_labels)}
        if any(c not in idx or c not in self.volatility for c in classes):
            return None
        corr = np.array(self.correlation_matrix, dtype=float)[np.ix_([idx[c] for c in classes], [idx[c] for c in classes])]
        vol = np.array([self.volatility[c] for c in classes], dtype=float)
        return corr * np.outer(vol, vol)


@lru_cache(maxsize=1)
def load_assumptions() -> CapitalMarketAssumptions:
    raw = json.loads(_PATH.read_text(encoding="utf-8"))
    lt = dict(raw["long_term_expected_return"])
    horizon = lt.pop("_horizon", "")
    return CapitalMarketAssumptions(
        label=raw["label"],
        as_of=raw["as_of"],
        long_term_expected_return=lt,
        horizon=horizon,
        scenarios=tuple(ScenarioAssumption(**s) for s in raw["scenarios"]),
        volatility={k: v for k, v in raw.get("volatility", {}).items() if not k.startswith("_")},
        correlation_labels=tuple(raw.get("correlation", {}).get("labels", ())),
        correlation_matrix=tuple(tuple(r) for r in raw.get("correlation", {}).get("matrix", ())),
    )
