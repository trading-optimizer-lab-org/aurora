# ruff: noqa: N806
"""Portfolio return and risk attribution.

Decompose a portfolio's *single-period* return and total variance into
per-asset contributions.

Conventions
-----------
- ``weights`` is a 1-D vector of length N (asset weights at the start of
  the period).
- ``asset_returns`` is a 1-D vector of length N (per-asset return for
  that period).
- ``cov_matrix`` is a (N, N) symmetric positive semi-definite covariance
  matrix.
- Names are not passed in; positional indices map to ``"asset_<i>"`` keys.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _as_1d(x: Sequence[float]) -> np.ndarray:
    return np.asarray(x, dtype=float).ravel()


def _check_same_length(a: np.ndarray, b: np.ndarray, names: tuple[str, str]) -> None:
    if a.size != b.size:
        raise ValueError(
            f"length mismatch: len({names[0]})={a.size}, len({names[1]})={b.size}"
        )


def contribution_to_return(
    weights: Sequence[float], asset_returns: Sequence[float]
) -> np.ndarray:
    """Per-asset return contribution.

    Returns ``w_i * r_i`` for each asset. The sum equals the portfolio
    return ``w . r`` for that period.
    """
    w = _as_1d(weights)
    r = _as_1d(asset_returns)
    _check_same_length(w, r, ("weights", "asset_returns"))
    return w * r


def contribution_to_risk(
    weights: Sequence[float], cov_matrix: Sequence[Sequence[float]]
) -> np.ndarray:
    """Per-asset contribution to portfolio variance.

    Uses the marginal contribution to risk: ``c_i = w_i * (Sigma w)_i``.
    By construction ``sum(c) == w.T @ Sigma @ w == portfolio variance``.

    For a long-only portfolio with a PSD covariance matrix every entry is
    non-negative.
    """
    w = _as_1d(weights)
    Sigma = np.asarray(cov_matrix, dtype=float)
    if Sigma.ndim != 2:
        raise ValueError(f"cov_matrix must be 2-D, got ndim={Sigma.ndim}")
    if Sigma.shape[0] != Sigma.shape[1]:
        raise ValueError(
            f"cov_matrix must be square, got shape {Sigma.shape}"
        )
    if Sigma.shape[0] != w.size:
        raise ValueError(
            f"cov_matrix size {Sigma.shape[0]} != weights size {w.size}"
        )
    # Sigma w  gives the marginal contributions.
    sw = Sigma @ w
    return w * sw


def decompose_return(
    weights: Sequence[float], asset_returns: Sequence[float]
) -> dict[str, object]:
    """Decompose a portfolio period return into headline + ranked contributions.

    Returns a dict with:

    - ``portfolio_return``: float, sum of per-asset contributions.
    - ``contributions``: tuple of ``(name, value)`` pairs in input order.
    - ``top_contributors``: tuple of the 3 largest ``(name, value)`` pairs.
    - ``bottom_contributors``: tuple of the 3 smallest ``(name, value)`` pairs.

    Asset names are synthesised as ``"asset_<i>"`` because no labels are
    provided. ``top`` and ``bottom`` are always length 3; if there are
    fewer than 3 assets the lists pad with the available entries (so a
    2-asset portfolio yields a length-2 tuple).
    """
    w = _as_1d(weights)
    r = _as_1d(asset_returns)
    _check_same_length(w, r, ("weights", "asset_returns"))

    contribs = w * r
    pairs = tuple(
        (f"asset_{i}", float(contribs[i])) for i in range(contribs.size)
    )
    portfolio_return = float(np.sum(contribs))

    # Sort by contribution value. Stable sort keeps original index order
    # on ties so the output is deterministic.
    sorted_desc = sorted(pairs, key=lambda p: p[1], reverse=True)
    sorted_asc = sorted(pairs, key=lambda p: p[1])

    top = tuple(sorted_desc[: min(3, len(pairs))])
    bottom = tuple(sorted_asc[: min(3, len(pairs))])

    return {
        "portfolio_return": portfolio_return,
        "contributions": pairs,
        "top_contributors": top,
        "bottom_contributors": bottom,
    }


__all__ = [
    "contribution_to_return",
    "contribution_to_risk",
    "decompose_return",
]
