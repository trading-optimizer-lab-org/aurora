"""Strategy degradation forecaster (R142).

Train a regression model on the strategy archive: features = early
realised metrics, regime tags, parameter shape; label = months until
the strategy degraded below SLA. Use to forecast remaining lifetime
of new candidates and rank.

Scope: scaffold + closed-form reference model (logistic regression on
a fixed feature vector). The full version trains a richer model
(XGBoost / RF) on a larger archive, but the surface is the same so
operators can swap the regressor without touching consumers.

Why a scaffold rather than a full ML pipeline now: the historical
archive is too small in this workspace to fit a non-trivial model,
and the surface (StrategySnapshot -> survival fraction) is the part
that consumers depend on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

import numpy as np


@dataclass(frozen=True)
class StrategySnapshot:
    """One historical strategy at the moment of forecasting.

    Attributes:
        strategy_id: identifier (used only in reports).
        early_sharpe: Sharpe over the first 60 trading days post-promote.
        early_calmar: Calmar over the same window.
        early_max_drawdown: max drawdown over the same window
            (negative number).
        regime_tag: e.g. "low_vol", "trending", "rangebound".
        n_params: complexity proxy for the parameter vector.
        months_until_degradation: target label, months between promote
            and SLA breach. Use ``None`` at forecast time.
    """

    strategy_id: str
    early_sharpe: float
    early_calmar: float
    early_max_drawdown: float
    regime_tag: str = "unknown"
    n_params: int = 0
    months_until_degradation: float | None = None


_REGIME_INDEX = {
    "unknown": 0,
    "low_vol": 1,
    "trending": 2,
    "rangebound": 3,
    "high_vol": 4,
}


def _featurise(snap: StrategySnapshot) -> np.ndarray:
    return np.asarray([
        snap.early_sharpe,
        snap.early_calmar,
        snap.early_max_drawdown,
        float(_REGIME_INDEX.get(snap.regime_tag, 0)),
        float(snap.n_params),
        1.0,  # bias term
    ], dtype=float)


@dataclass
class DegradationForecaster:
    """Linear regression model: features -> months_until_degradation.

    Fit with closed-form OLS via ``np.linalg.lstsq``. No external ML
    dependency. Operators can subclass and override ``fit`` / ``predict``
    to plug a richer model.
    """

    weights: np.ndarray | None = None

    def fit(self, snapshots: Sequence[StrategySnapshot]) -> None:
        labelled = [s for s in snapshots if s.months_until_degradation is not None]
        if len(labelled) < 5:
            raise ValueError(
                "need at least 5 labelled snapshots; got "
                f"{len(labelled)}"
            )
        X = np.vstack([_featurise(s) for s in labelled])
        y = np.asarray(
            [s.months_until_degradation for s in labelled], dtype=float
        )
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        self.weights = coef

    def predict(self, snapshot: StrategySnapshot) -> float:
        if self.weights is None:
            raise RuntimeError("forecaster has not been fit yet")
        x = _featurise(snapshot)
        return float(x @ self.weights)

    def rank(self, snapshots: Sequence[StrategySnapshot]) -> List[StrategySnapshot]:
        if self.weights is None:
            raise RuntimeError("forecaster has not been fit yet")
        return sorted(
            snapshots,
            key=lambda s: self.predict(s),
            reverse=True,
        )


__all__ = [
    "StrategySnapshot",
    "DegradationForecaster",
]
