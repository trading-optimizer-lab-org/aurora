"""Meta-portfolio allocator.

Combines N validated single-asset strategies into a meta-portfolio, recomputing
weights at a chosen rebalance frequency from prior-window strategy returns.

Allocation methods:
- 'equal_weight': 1/N each
- 'equal_vol':    weight ~ 1 / realized_vol(strategy_returns)
- 'risk_parity':  iterative risk-parity (each strategy contributes equal risk)
- 'inverse_dd':   weight ~ 1 / max_drawdown(strategy_returns)

Rebalance schedules: 'daily', 'weekly' (Monday), 'monthly' (1st bar of month),
'quarterly' (1st bar of Jan/Apr/Jul/Oct).

Conventions:
- Weights are computed at rebalance bar i using returns up to and including i,
  then APPLIED starting at bar i+1 (anti-lookahead — weights at bar t consume
  returns at bar t+1 in the meta-portfolio).
- Per-strategy returns come from aurora.core.engine.run_backtest with the
  user-supplied CostModel; the allocator does not double-charge costs.
- Final weights sum to 1.0 (fully invested across strategies). Each strategy
  signal can still be in [-1, 1] internally.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math
import numpy as np
import pandas as pd

from aurora.core.costs import CostModel, ZERO_costs
from aurora.core.engine import run_backtest
from aurora.core.metrics import Metrics, compute_metrics
from aurora.strategies.base import Strategy


_VALID_METHODS = ("equal_weight", "equal_vol", "risk_parity", "inverse_dd")
_VALID_REBALANCE = ("daily", "weekly", "monthly", "quarterly")


# --------------------------------------------------------------------------- #
# Allocation primitives                                                       #
# --------------------------------------------------------------------------- #
def equal_weight(strat_returns: dict) -> dict:
    """1/N each."""
    n = len(strat_returns)
    if n == 0:
        return {}
    w = 1.0 / n
    return {k: w for k in strat_returns}


def equal_vol(strat_returns: dict, lookback: int, ppy: int = 252) -> dict:
    """Inverse-vol weighting on last `lookback` returns."""
    if not strat_returns:
        return {}
    inv_vols = {}
    for k, r in strat_returns.items():
        r = np.asarray(r, dtype=float)
        window = r[-lookback:] if len(r) >= lookback else r
        if len(window) < 2:
            inv_vols[k] = 0.0
            continue
        vol = float(window.std(ddof=1)) * math.sqrt(ppy)
        inv_vols[k] = 1.0 / vol if vol > 1e-12 else 0.0
    total = sum(inv_vols.values())
    if total <= 0:
        return equal_weight(strat_returns)
    return {k: v / total for k, v in inv_vols.items()}


def inverse_dd(strat_returns: dict, lookback: int) -> dict:
    """Weight inversely proportional to max drawdown over the last `lookback` bars."""
    if not strat_returns:
        return {}
    inv_mdds = {}
    for k, r in strat_returns.items():
        r = np.asarray(r, dtype=float)
        window = r[-lookback:] if len(r) >= lookback else r
        if len(window) < 2:
            inv_mdds[k] = 0.0
            continue
        nav = np.cumprod(1.0 + window)
        cummax = np.maximum.accumulate(nav)
        dd = (nav - cummax) / np.maximum(cummax, 1e-12)
        mdd = float(abs(dd.min()))
        # floor MDD so a flawless strategy doesn't blow up the weight
        inv_mdds[k] = 1.0 / max(mdd, 1e-4)
    total = sum(inv_mdds.values())
    if total <= 0:
        return equal_weight(strat_returns)
    return {k: v / total for k, v in inv_mdds.items()}


def risk_parity(strat_returns: dict, lookback: int, max_iter: int = 200,
                tol: float = 1e-8) -> dict:
    """Iterative equal-risk-contribution weights.

    Solves for w >= 0, sum(w) = 1, such that w_i * (Sigma w)_i is constant for
    all i, where Sigma is the sample covariance of strategy returns over the
    last `lookback` bars. Uses the cyclic coordinate-descent update from Maillard
    et al. (2010): w_i <- w_i * sqrt(b_i / (w_i * (Sigma w)_i)), then renormalize.
    Falls back to equal_weight for degenerate / singular covariance.
    """
    keys = list(strat_returns.keys())
    n = len(keys)
    if n == 0:
        return {}
    if n == 1:
        return {keys[0]: 1.0}

    # Build aligned matrix of returns (truncate to common minimum length)
    arrs = []
    min_len = min(len(np.asarray(strat_returns[k])) for k in keys)
    use_len = min(min_len, lookback)
    if use_len < 2:
        return equal_weight(strat_returns)
    for k in keys:
        r = np.asarray(strat_returns[k], dtype=float)
        arrs.append(r[-use_len:])
    R = np.column_stack(arrs)  # (T, N)
    cov = np.cov(R, rowvar=False, ddof=1)
    if not np.all(np.isfinite(cov)):
        return equal_weight(strat_returns)

    # Degenerate: any variance ~ 0 -> punt to equal_weight to avoid /0
    diag = np.diag(cov)
    if np.any(diag <= 1e-16):
        return equal_weight(strat_returns)

    # Initial guess: inverse-vol normalized
    w = 1.0 / np.sqrt(diag)
    w = w / w.sum()
    target = 1.0 / n  # equal risk-contribution target

    for _ in range(max_iter):
        sigma_w = cov @ w
        rc = w * sigma_w
        total_risk = rc.sum()
        if total_risk <= 0:
            return equal_weight(strat_returns)
        rc_norm = rc / total_risk
        if np.max(np.abs(rc_norm - target)) < tol:
            break
        # Update: w_i <- sqrt(target / sigma_w_i), then renormalize.
        denom = np.maximum(sigma_w, 1e-16)
        w = np.sqrt(target / denom)
        w = np.maximum(w, 0.0)
        s = w.sum()
        if s <= 0:
            return equal_weight(strat_returns)
        w = w / s

    return {k: float(w[i]) for i, k in enumerate(keys)}


# --------------------------------------------------------------------------- #
# Rebalance schedule                                                          #
# --------------------------------------------------------------------------- #
def rebalance_dates(index: pd.DatetimeIndex, schedule: str) -> np.ndarray:
    """Return boolean mask (len == len(index)) marking rebalance bars.

    'daily':     every bar
    'weekly':    first bar of each ISO week (typically Monday)
    'monthly':   first bar of each calendar month
    'quarterly': first bar of each calendar quarter (Jan/Apr/Jul/Oct)
    """
    if schedule not in _VALID_REBALANCE:
        raise ValueError(f"unknown rebalance schedule: {schedule}")
    n = len(index)
    mask: np.ndarray = np.zeros(n, dtype=bool)
    if n == 0:
        return mask

    if schedule == "daily":
        mask[:] = True
        return mask

    # First bar always rebalances so the portfolio starts allocated.
    mask[0] = True

    if schedule == "weekly":
        prev_week = (index[0].isocalendar().year, index[0].isocalendar().week)
        for i in range(1, n):
            ic = index[i].isocalendar()
            cur = (ic.year, ic.week)
            if cur != prev_week:
                mask[i] = True
                prev_week = cur
    elif schedule == "monthly":
        prev = (index[0].year, index[0].month)
        for i in range(1, n):
            cur = (index[i].year, index[i].month)
            if cur != prev:
                mask[i] = True
                prev = cur
    elif schedule == "quarterly":
        prev_q = (index[0].year, (index[0].month - 1) // 3)
        for i in range(1, n):
            cur = (index[i].year, (index[i].month - 1) // 3)
            if cur != prev_q:
                mask[i] = True
                prev_q = cur

    return mask


# --------------------------------------------------------------------------- #
# Result                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class AllocatorResult:
    """Output of StrategyAllocator.run()."""
    metrics: Metrics                   # meta-portfolio metrics
    nav: np.ndarray                    # meta-portfolio NAV (T,)
    rets: np.ndarray                   # meta-portfolio net returns (T,)
    weights: np.ndarray                # weight matrix (T, N) — applied weights at bar t
    strategy_names: list               # ordered list of strategy keys (same as cols of weights)
    timestamps: np.ndarray             # DatetimeIndex.values for the meta-portfolio
    rebalance_mask: np.ndarray         # bool (T,) where weights were recomputed
    per_strategy_returns: dict         # name -> per-bar net returns (np.array)
    per_strategy_attribution: dict     # name -> total contribution to portfolio return (sum of w*r)
    method: str
    rebalance: str
    lookback: int
    rebalance_cost_bps: float = 0.0    # input bps charged per rebalance
    total_rebalance_cost: float = 0.0  # cumulative cost charged across all rebalances (return-space)

    @property
    def calmar(self): return self.metrics.calmar
    @property
    def sharpe(self): return self.metrics.sharpe
    @property
    def cagr(self): return self.metrics.cagr
    @property
    def mdd(self): return self.metrics.mdd


# --------------------------------------------------------------------------- #
# Allocator                                                                   #
# --------------------------------------------------------------------------- #
class StrategyAllocator:
    """Combines N validated strategies into a meta-portfolio."""

    def __init__(self, strategies: dict, prices: dict,
                 method: str = "equal_vol",
                 rebalance: str = "monthly",
                 lookback: int = 60,
                 rebalance_cost_bps: float = 0.0):
        """
        Args:
            strategies: dict[name -> Strategy] (each Strategy is single-asset)
            prices:     dict[name -> pd.Series of prices for that strategy's asset]
            method:     'equal_weight' | 'equal_vol' | 'risk_parity' | 'inverse_dd'
            rebalance:  'daily' | 'weekly' | 'monthly' | 'quarterly'
            lookback:   rolling window size (in bars) for vol / dd / cov estimation
            rebalance_cost_bps: round-trip cost in basis points charged per rebalance,
                proportional to total weight turnover sum(|delta_w|). 0 = no cost (default).
        """
        if not strategies:
            raise ValueError("strategies dict is empty")
        if set(strategies.keys()) != set(prices.keys()):
            raise ValueError(
                f"strategies keys {set(strategies.keys())} != "
                f"prices keys {set(prices.keys())}"
            )
        for name, strat in strategies.items():
            if not isinstance(strat, Strategy):
                raise TypeError(f"strategies[{name}] must be a Strategy instance")
        for name, ps in prices.items():
            if not isinstance(ps, pd.Series):
                raise TypeError(f"prices[{name}] must be a pd.Series")
            if not isinstance(ps.index, pd.DatetimeIndex):
                raise TypeError(f"prices[{name}].index must be a DatetimeIndex")
        if method not in _VALID_METHODS:
            raise ValueError(f"unknown method: {method}, valid: {_VALID_METHODS}")
        if rebalance not in _VALID_REBALANCE:
            raise ValueError(
                f"unknown rebalance: {rebalance}, valid: {_VALID_REBALANCE}"
            )
        if lookback < 2:
            raise ValueError(f"lookback must be >= 2, got {lookback}")
        if rebalance_cost_bps < 0:
            raise ValueError(
                f"rebalance_cost_bps must be >= 0, got {rebalance_cost_bps}"
            )

        self.strategies = dict(strategies)
        self.prices = dict(prices)
        self.method = method
        self.rebalance = rebalance
        self.lookback = int(lookback)
        self.rebalance_cost_bps = float(rebalance_cost_bps)
        self.names = sorted(self.strategies.keys())

    # --------------------------------------------------------------------- #
    def _allocate(self, history: dict) -> dict:
        """Pick weights for `history` = dict[name -> array of recent returns]."""
        if self.method == "equal_weight":
            return equal_weight(history)
        if self.method == "equal_vol":
            return equal_vol(history, self.lookback)
        if self.method == "inverse_dd":
            return inverse_dd(history, self.lookback)
        if self.method == "risk_parity":
            return risk_parity(history, self.lookback)
        raise ValueError(f"unknown method: {self.method}")

    # --------------------------------------------------------------------- #
    def run(self, costs: Optional[dict] = None, ppy: int = 252) -> AllocatorResult:
        """Run meta-portfolio backtest.

        Args:
            costs: dict[name -> CostModel], default ZERO_costs each
            ppy:   periods per year for metrics

        Returns:
            AllocatorResult.
        """
        costs = costs or {}

        # 1. Run each strategy's backtest on its own asset.
        per_strat_rets_full: dict[str, np.ndarray] = {}
        per_strat_index: dict[str, pd.DatetimeIndex] = {}
        for name in self.names:
            strat = self.strategies[name]
            ps = self.prices[name]
            cm = costs.get(name, ZERO_costs)
            res = run_backtest(ps, strat.signals, costs=cm, ppy=ppy)
            per_strat_rets_full[name] = np.asarray(res.rets, dtype=float)
            per_strat_index[name] = ps.index

        # 2. Align all strategies to the common DatetimeIndex (intersection).
        common_idx = None
        for name in self.names:
            idx = per_strat_index[name]
            common_idx = idx if common_idx is None else common_idx.intersection(idx)
        if common_idx is None or len(common_idx) < max(self.lookback, 20):
            raise ValueError(
                f"insufficient overlapping bars: "
                f"{0 if common_idx is None else len(common_idx)}, "
                f"need >= max(lookback, 20)"
            )
        common_idx = pd.DatetimeIndex(common_idx).sort_values()
        T = len(common_idx)
        N = len(self.names)

        # Re-index per-strategy returns onto the common index.
        rets_mat: np.ndarray = np.zeros((T, N), dtype=float)
        for j, name in enumerate(self.names):
            r_full = pd.Series(per_strat_rets_full[name], index=per_strat_index[name])
            r_aligned = r_full.reindex(common_idx).fillna(0.0).values.astype(float)
            rets_mat[:, j] = r_aligned

        # 3. Determine rebalance bars.
        rb_mask = rebalance_dates(common_idx, self.rebalance)

        # 4. Walk forward: at each rebalance bar t, recompute weights from
        #    prior-window returns (rets_mat[max(0, t-lookback):t+1]) and APPLY
        #    those weights starting at bar t+1.
        weights_mat: np.ndarray = np.zeros((T, N), dtype=float)
        rebalance_costs: np.ndarray = np.zeros(T, dtype=float)  # cost charged at bar t (return-space)
        cur_w = np.full(N, 1.0 / N)  # start equal-weight before first rebalance
        cost_factor = self.rebalance_cost_bps / 10_000.0
        total_rebalance_cost = 0.0
        for t in range(T):
            weights_mat[t] = cur_w
            if rb_mask[t]:
                # Build history window (prior returns up to and including t).
                start = max(0, t - self.lookback + 1)
                window = rets_mat[start:t + 1, :]  # shape (W, N)
                if window.shape[0] < 2:
                    # Not enough history -> stay equal-weight
                    new_w = np.full(N, 1.0 / N)
                else:
                    history = {self.names[j]: window[:, j] for j in range(N)}
                    w_dict = self._allocate(history)
                    new_w = np.array([w_dict.get(self.names[j], 0.0)
                                      for j in range(N)], dtype=float)
                    # Renormalize defensively (allocators should already sum to 1).
                    s = new_w.sum()
                    if s > 0:
                        new_w = new_w / s
                    else:
                        new_w = np.full(N, 1.0 / N)
                # Charge rebalance cost on the turnover sum(|delta_w|).
                # First bar charge counts entry from cash (cur_w starts at equal-weight,
                # but we still treat it as turnover relative to the freshly chosen weights).
                if cost_factor > 0.0:
                    turnover = float(np.abs(new_w - cur_w).sum())
                    cost = cost_factor * turnover
                    rebalance_costs[t] = cost
                    total_rebalance_cost += cost
                cur_w = new_w

        # 5. Apply weights to next-bar returns: portfolio_ret[t] = sum_i w_i[t-1] * r_i[t]
        #    Rebalance cost is charged at the bar of the rebalance (return-space).
        port_rets: np.ndarray = np.zeros(T, dtype=float)
        port_rets[1:] = np.einsum("tn,tn->t",
                                  weights_mat[:-1, :], rets_mat[1:, :])
        port_rets = port_rets - rebalance_costs
        nav = np.cumprod(1.0 + port_rets)
        nav[0] = 1.0

        # 6. Per-strategy contributions (additive in continuously-rebalanced port).
        per_strat_contrib: np.ndarray = np.zeros((T, N), dtype=float)
        per_strat_contrib[1:, :] = weights_mat[:-1, :] * rets_mat[1:, :]
        per_strategy_returns = {self.names[j]: per_strat_contrib[:, j]
                                for j in range(N)}
        per_strategy_attribution = {self.names[j]: float(per_strat_contrib[:, j].sum())
                                    for j in range(N)}

        metrics = compute_metrics(port_rets[1:], ppy=ppy)
        return AllocatorResult(
            metrics=metrics,
            nav=nav,
            rets=port_rets,
            weights=weights_mat,
            strategy_names=list(self.names),
            timestamps=common_idx.values,
            rebalance_mask=rb_mask,
            per_strategy_returns=per_strategy_returns,
            per_strategy_attribution=per_strategy_attribution,
            method=self.method,
            rebalance=self.rebalance,
            lookback=self.lookback,
            rebalance_cost_bps=self.rebalance_cost_bps,
            total_rebalance_cost=float(total_rebalance_cost),
        )
