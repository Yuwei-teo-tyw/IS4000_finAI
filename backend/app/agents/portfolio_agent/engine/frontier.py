"""
Long-only mean-variance efficient frontier at asset-class level.

Model (all inputs are the Portfolio Agent's labelled house assumptions):
  expected return  mu_i  = long-term expected return of asset class i (% p.a., before product fees)
  covariance       Sigma = diag(vol) . Corr . diag(vol)
  portfolio return       = w . mu
  portfolio variance     = w' Sigma w
Constraints: fully invested (sum w = 1), long-only (w >= 0), and only the
asset classes the client can actually hold.

For each target return the minimum-variance portfolio is found exactly: the
KKT system of the equality-constrained problem is solved on every subset of
asset classes (the candidate active sets) and the lowest-variance solution
with non-negative weights is kept. With at most ~10 classes that is at most
1,024 small linear solves - no optimisation library or approximation needed.
"""
from dataclasses import dataclass
from itertools import combinations
from typing import Optional

import numpy as np

from app.agents.portfolio_agent.assumptions import CapitalMarketAssumptions

MAX_CLASSES = 10  # keeps the exact subset enumeration small
TOL = 1e-9


@dataclass(frozen=True)
class FrontierPoint:
    volatility_pct: float
    expected_return_pct: float
    weights: dict  # asset class -> % of portfolio


@dataclass(frozen=True)
class Frontier:
    asset_classes: list[str]
    points: list[FrontierPoint]


def _model(cma: CapitalMarketAssumptions, classes: list[str]):
    mu = [cma.long_term_expected_return.get(c) for c in classes]
    cov = cma.covariance(classes)
    if cov is None or any(m is None for m in mu):
        return None, None
    return np.array(mu, dtype=float), cov


def _solve_subset(mu: np.ndarray, cov: np.ndarray, subset: tuple[int, ...], target: Optional[float]) -> Optional[np.ndarray]:
    """Min w' cov w on `subset` with sum w = 1 (and mu.w = target if given). None if singular."""
    k = len(subset)
    S = cov[np.ix_(subset, subset)]
    rows = [np.ones(k)] + ([mu[list(subset)]] if target is not None else [])
    A = np.vstack(rows)
    b = np.array([1.0] + ([target] if target is not None else []))
    m = A.shape[0]
    kkt = np.block([[2 * S, A.T], [A, np.zeros((m, m))]])
    rhs = np.concatenate([np.zeros(k), b])
    try:
        sol = np.linalg.solve(kkt, rhs)
    except np.linalg.LinAlgError:
        return None
    w = np.zeros(len(mu))
    w[list(subset)] = sol[:k]
    return w


def min_variance(mu: np.ndarray, cov: np.ndarray, target: Optional[float] = None) -> Optional[np.ndarray]:
    """Exact long-only minimum-variance weights (fractions), optionally at a target return."""
    n = len(mu)
    best, best_var = None, np.inf
    for size in range(1, n + 1):
        for subset in combinations(range(n), size):
            w = _solve_subset(mu, cov, subset, target)
            if w is None or w.min() < -1e-8:
                continue
            if target is not None and abs(w @ mu - target) > 1e-6:
                continue
            var = float(w @ cov @ w)
            if var < best_var - TOL:
                best, best_var = np.clip(w, 0, None), var
    if best is not None:
        best = best / best.sum()
    return best


def efficient_frontier(cma: CapitalMarketAssumptions, classes: list[str], n_points: int = 25) -> Optional[Frontier]:
    """None when the assumptions don't cover every class (no frontier is drawn from guesses)."""
    classes = [c for c in classes]
    if not classes or len(classes) > MAX_CLASSES:
        return None
    mu, cov = _model(cma, classes)
    if mu is None:
        return None
    w_min = min_variance(mu, cov)
    if w_min is None:
        return None
    lo, hi = float(w_min @ mu), float(mu.max())
    targets = [lo] if hi - lo < 1e-9 else list(np.linspace(lo, hi, n_points))
    points = []
    for t in targets:
        w = min_variance(mu, cov, t)
        if w is None:
            continue
        points.append(FrontierPoint(
            volatility_pct=round(float(np.sqrt(w @ cov @ w)), 4),
            expected_return_pct=round(float(w @ mu), 4),
            weights={c: round(float(x) * 100, 2) for c, x in zip(classes, w) if x > 1e-6},
        ))
    return Frontier(asset_classes=classes, points=points)


def model_point(cma: CapitalMarketAssumptions, weights_pct: dict) -> Optional[tuple[float, float]]:
    """(volatility %, expected return %) of a portfolio under the same model, or None."""
    classes = [c for c, w in weights_pct.items() if w > 0]
    if not classes:
        return None
    mu, cov = _model(cma, classes)
    if mu is None:
        return None
    w = np.array([weights_pct[c] for c in classes], dtype=float) / 100
    return round(float(np.sqrt(w @ cov @ w)), 4), round(float(w @ mu), 4)
