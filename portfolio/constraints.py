"""Portfolio constraints.

A frozen dataclass that bundles the hard limits a portfolio must respect:
min/max per-asset weights, long-only flag, gross/net exposure caps, cash
floor, turnover cap, per-strategy capital cap and group exposure caps.

The ``validate`` method returns a list of violation strings; an empty list
means the weight vector is admissible.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class PortfolioConstraints:
    """Hard constraints for a portfolio weight vector.

    Parameters
    ----------
    min_weight, max_weight
        Lower/upper bound on every individual asset weight. Use negative
        ``min_weight`` to allow shorts (only meaningful when
        ``long_only=False``).
    long_only
        If True, every weight must be >= 0. Overrides ``min_weight`` if
        ``min_weight`` was set negative by mistake.
    gross_exposure_max
        Cap on sum(|w|). Defaults to 1.0 (fully invested, no leverage).
    net_exposure_max
        Cap on sum(w). Defaults to 1.0.
    cash_floor
        Minimum cash fraction = 1 - sum(w). Defaults to 0.0.
    turnover_max
        Cap on sum(|w_new - w_prev|). Only enforced when ``previous_weights``
        is provided to ``validate``.
    per_strategy_cap
        Optional dict mapping a single asset/strategy id to its individual
        weight cap (overrides ``max_weight`` when stricter). Indexing uses
        the position in the weight vector unless ``asset_ids`` is supplied.
    group_max
        Optional mapping of group label -> max group exposure. Used together
        with the ``group_labels`` argument to ``validate``.
    """
    min_weight: float = 0.0
    max_weight: float = 1.0
    long_only: bool = True
    gross_exposure_max: float = 1.0
    net_exposure_max: float = 1.0
    cash_floor: float = 0.0
    turnover_max: float | None = None
    per_strategy_cap: dict | None = field(default=None)
    group_max: dict | None = field(default=None)

    def __post_init__(self) -> None:
        if self.max_weight < self.min_weight:
            raise ValueError(
                f"max_weight ({self.max_weight}) must be >= min_weight "
                f"({self.min_weight})"
            )
        if self.gross_exposure_max < 0:
            raise ValueError("gross_exposure_max must be >= 0")
        if self.net_exposure_max < 0:
            raise ValueError("net_exposure_max must be >= 0")
        if not (0.0 <= self.cash_floor <= 1.0):
            raise ValueError("cash_floor must be in [0, 1]")
        if self.turnover_max is not None and self.turnover_max < 0:
            raise ValueError("turnover_max must be >= 0")
        if self.long_only and self.min_weight < 0:
            # Long-only overrides any negative min_weight passed in.
            object.__setattr__(self, "min_weight", 0.0)

    # --------------------------------------------------------------------- #
    # Validation                                                            #
    # --------------------------------------------------------------------- #
    def validate(
        self,
        weights: Sequence[float],
        group_labels: Sequence[str] | None = None,
        previous_weights: Sequence[float] | None = None,
        tol: float = 1e-8,
    ) -> list[str]:
        """Return list of violation strings (empty list => admissible)."""
        w = np.asarray(weights, dtype=float).ravel()
        violations: list[str] = []

        if w.size == 0:
            return ["empty weight vector"]
        if not np.all(np.isfinite(w)):
            violations.append("weights contain non-finite values")
            return violations

        # Per-asset bounds
        if self.long_only and (w < -tol).any():
            violations.append(
                f"long_only violated: min weight {float(w.min()):.6g}"
            )
        if (w < self.min_weight - tol).any():
            violations.append(
                f"min_weight={self.min_weight} violated: actual "
                f"min={float(w.min()):.6g}"
            )
        if (w > self.max_weight + tol).any():
            violations.append(
                f"max_weight={self.max_weight} violated: actual "
                f"max={float(w.max()):.6g}"
            )

        # Gross / net exposure
        gross = float(np.sum(np.abs(w)))
        net = float(np.sum(w))
        if gross > self.gross_exposure_max + tol:
            violations.append(
                f"gross_exposure_max={self.gross_exposure_max} violated: "
                f"gross={gross:.6g}"
            )
        if net > self.net_exposure_max + tol:
            violations.append(
                f"net_exposure_max={self.net_exposure_max} violated: "
                f"net={net:.6g}"
            )

        # Cash floor: 1 - sum(w) >= cash_floor (assuming long-only fully
        # invested; for long-short use net exposure instead).
        cash = 1.0 - net
        if cash < self.cash_floor - tol:
            violations.append(
                f"cash_floor={self.cash_floor} violated: cash={cash:.6g}"
            )

        # Turnover
        if self.turnover_max is not None and previous_weights is not None:
            prev = np.asarray(previous_weights, dtype=float).ravel()
            if prev.shape != w.shape:
                violations.append(
                    f"previous_weights shape {prev.shape} != {w.shape}"
                )
            else:
                turnover = float(np.sum(np.abs(w - prev)))
                if turnover > self.turnover_max + tol:
                    violations.append(
                        f"turnover_max={self.turnover_max} violated: "
                        f"turnover={turnover:.6g}"
                    )

        # Per-strategy cap (positional)
        if self.per_strategy_cap:
            for key, cap in self.per_strategy_cap.items():
                if isinstance(key, int) and 0 <= key < w.size:
                    if w[key] > cap + tol:
                        violations.append(
                            f"per_strategy_cap[{key}]={cap} violated: "
                            f"w={float(w[key]):.6g}"
                        )

        # Group caps
        if self.group_max and group_labels is not None:
            labels = list(group_labels)
            if len(labels) != w.size:
                violations.append(
                    f"group_labels length {len(labels)} != weights {w.size}"
                )
            else:
                for grp, cap in self.group_max.items():
                    idx = [i for i, lab in enumerate(labels) if lab == grp]
                    if not idx:
                        continue
                    grp_sum = float(np.sum(w[idx]))
                    if grp_sum > cap + tol:
                        violations.append(
                            f"group_max[{grp}]={cap} violated: "
                            f"group_sum={grp_sum:.6g}"
                        )
        return violations

    def is_admissible(
        self,
        weights: Sequence[float],
        group_labels: Sequence[str] | None = None,
        previous_weights: Sequence[float] | None = None,
    ) -> bool:
        return not self.validate(
            weights,
            group_labels=group_labels,
            previous_weights=previous_weights,
        )
