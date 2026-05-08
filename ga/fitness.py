"""GA fitness functions.

Architectural rule: OOS sagrado.
The genetic algorithm MUST never see OOS data. All optimization signals are
derived strictly from in-sample (IS) prices. OOS is touched only AFTER the
GA selects candidates, by ``validate_oos`` as a final pass / hold-out gate.

Public API:
    multi_objective_fitness_is(prices_is, signal_fn, ...) -> tuple
        Returns (calmar_is, sharpe_is, robustness_wf, mdd_penalty_is).
        Robustness here = walk-forward stability across IS sub-windows
        (NOT IS-vs-OOS comparison). Never touches OOS.

    scalar_fitness_is(prices_is, signal_fn, ...) -> float
        Weighted sum of the IS objectives. Never touches OOS.

    validate_oos(prices_oos, signal_fn, ...) -> dict
        Run candidate against OOS. Used AFTER GA selection only.
        Returns metrics dict (calmar / sharpe / mdd / cagr / final_nav).
        This is the gate, not a fitness target.

Deprecated (kept as aliases for backwards compat with existing imports):
    multi_objective_fitness(prices_is, prices_oos, signal_fn, ...)
        DEPRECATED. Now delegates to multi_objective_fitness_is and ignores
        prices_oos. Emits a warning at first call.

    scalar_fitness(prices_is, prices_oos, signal_fn, ...)
        DEPRECATED. Now delegates to scalar_fitness_is and ignores prices_oos.
"""
from __future__ import annotations
import warnings
import numpy as np
from quantforge.core.engine import run_backtest
from quantforge.core.costs import IBKR_costs


_DEPRECATION_WARNED = {"multi_objective_fitness": False, "scalar_fitness": False}


def _walk_forward_robustness(prices_is, signal_fn, costs, ppy, n_windows: int = 4) -> float:
    """Compute walk-forward stability over n_windows sub-windows of IS data.

    Splits prices_is into n_windows roughly equal contiguous chunks, computes
    Calmar per chunk, returns -std(calmars) so higher is better (lower std =
    more stable across regimes).

    Per-chunk failures (engine raises, NaN/inf Calmar) are SKIPPED rather
    than poisoning the whole estimate with the -99 sentinel. We aggregate
    -std over the surviving chunks. Only when every chunk fails do we fall
    back to -99. This avoids the previous behavior where a single brittle
    chunk dominated the GA's robustness signal and zeroed out otherwise
    sensible candidates.

    Returns:
        float: -std of per-chunk Calmar over surviving chunks. If all chunks
        fail, returns -99 as a sentinel.
    """
    n = len(prices_is)
    if n < n_windows * 30:
        # Too short to split meaningfully.
        return 0.0
    chunk = n // n_windows
    calmars: list[float] = []
    failures = 0
    for i in range(n_windows):
        lo = i * chunk
        hi = (i + 1) * chunk if i < n_windows - 1 else n
        sub = prices_is.iloc[lo:hi]
        if len(sub) < 20:
            continue
        try:
            res = run_backtest(sub, signal_fn, costs=costs, ppy=ppy)
            cal = float(res.calmar)
        except Exception:
            failures += 1
            continue
        if not np.isfinite(cal):
            failures += 1
            continue
        calmars.append(cal)
    if not calmars:
        return -99.0
    return -float(np.std(calmars))


# Typical magnitudes per objective; used when normalize=True so each
# objective sits roughly in [-1, 1] and weights tuple (1, 1, 1, -1) is
# meaningful in NSGA-II's hypervolume / crowding-distance metrics. Scales
# are set conservatively (slightly above typical worst-case) so the bulk
# of values stay within [-1, 1] but rare outliers may extend beyond.
_TYPICAL_SCALES = {
    "calmar": 5.0,    # Calmar typically [-2, 5]
    "sharpe": 4.0,    # Sharpe typically [-2, 4]
    "robust": 5.0,    # robustness = -std(calmars). Empirically can dip
                       # below -4 on choppy IS series; 5.0 keeps it bounded.
    "mdd_pen": 0.5,   # mdd penalty typically [0, 0.5]
}


def multi_objective_fitness_is(prices_is, signal_fn,
                                costs=IBKR_costs, ppy=252,
                                max_mdd: float = 0.20,
                                wf_windows: int = 4,
                                normalize: bool = False,
                                **kwargs) -> tuple:
    """IS-only multi-objective fitness for NSGA-II.

    Returns ``(calmar_is, sharpe_is, robustness_wf, mdd_penalty_is)``.

    - ``calmar_is``: Calmar ratio computed on the full IS window. Higher = better.
    - ``sharpe_is``: Sharpe ratio computed on the full IS window. Higher = better.
    - ``robustness_wf``: -std of Calmar across ``wf_windows`` IS sub-windows.
        Higher (closer to 0) = more stable. NEVER uses OOS.
    - ``mdd_penalty_is``: max(0, |mdd_is| - max_mdd). Lower = better.

    NEVER touches OOS data. Caller's responsibility to keep the price series
    sliced to IS only.

    Args:
        prices_is: pd.Series of IS prices.
        signal_fn: callable signal generator.
        costs: cost model.
        ppy: periods per year.
        max_mdd: max acceptable absolute drawdown (fraction). Excess penalized.
        wf_windows: number of walk-forward sub-windows for robustness signal.
        normalize: if True, divide each objective by its typical scale so
            the four objectives are on comparable magnitudes. Useful when
            using NSGA-II weights tuple (1, 1, 1, -1) — without normalization
            Calmar (ratio) and MDD (%) live on different scales and the
            weighted sum is dominated by Calmar/Sharpe. Defaults to False
            for backwards compatibility.

    Returns:
        4-tuple of objectives. Maximize first 3, minimize 4th.
    """
    try:
        res_is = run_backtest(prices_is, signal_fn, costs=costs, ppy=ppy, **kwargs)
    except Exception:
        return (-99.0, -99.0, -99.0, 99.0)

    cal_is = res_is.calmar
    sh_is = res_is.sharpe
    robust = _walk_forward_robustness(prices_is, signal_fn, costs, ppy, wf_windows)
    # res_is.mdd is stored as a percent (see core/metrics.py: round(mdd*100, 4)).
    # Divide by 100 to compare against max_mdd which is a fraction. Coerce
    # NaN/inf to a worst-case value (99.0%) so the penalty branches reliably.
    mdd_pct = float(res_is.mdd)
    if not np.isfinite(mdd_pct):
        mdd_pct = 99.0
    mdd_pen = max(0.0, abs(mdd_pct / 100.0) - max_mdd)

    if normalize:
        cal_is = cal_is / _TYPICAL_SCALES["calmar"]
        sh_is = sh_is / _TYPICAL_SCALES["sharpe"]
        robust = robust / _TYPICAL_SCALES["robust"]
        mdd_pen = mdd_pen / _TYPICAL_SCALES["mdd_pen"]

    return (cal_is, sh_is, robust, mdd_pen)


def scalar_fitness_is(prices_is, signal_fn,
                       costs=IBKR_costs, ppy=252,
                       weights=(0.5, 0.3, 0.2),
                       wf_windows: int = 4) -> float:
    """IS-only scalar (weighted-sum) fitness.

    Args:
        weights: (w_calmar, w_sharpe, w_robust)
        wf_windows: walk-forward windows for the robustness term.

    Returns:
        float scalar fitness (higher = better). NEVER touches OOS.
    """
    try:
        res_is = run_backtest(prices_is, signal_fn, costs=costs, ppy=ppy)
    except Exception:
        return -99.0
    cal = res_is.calmar
    sh = res_is.sharpe
    robust = _walk_forward_robustness(prices_is, signal_fn, costs, ppy, wf_windows)
    return weights[0] * cal + weights[1] * sh + weights[2] * robust


def validate_oos(prices_oos, signal_fn,
                  costs=IBKR_costs, ppy=252,
                  **kwargs) -> dict:
    """Run a candidate strategy against OOS data.

    Used AFTER GA selection only. This is the OOS gate, not a fitness target.
    The caller is expected to wrap this in ``with OOSGuard(...)`` so the
    OOS read is logged.

    Args:
        prices_oos: pd.Series of OOS prices.
        signal_fn: callable signal generator.
        costs: cost model.
        ppy: periods per year.

    Returns:
        dict with keys: calmar, sharpe, mdd, cagr, final_nav, n_periods.
        On engine failure, returns a dict with NaN values and an "error" key.
    """
    try:
        res = run_backtest(prices_oos, signal_fn, costs=costs, ppy=ppy, **kwargs)
    except Exception as e:
        nan = float("nan")
        return {
            "calmar": nan, "sharpe": nan, "mdd": nan, "cagr": nan,
            "final_nav": nan, "n_periods": 0, "error": repr(e),
        }
    return {
        "calmar": float(res.calmar),
        "sharpe": float(res.sharpe),
        "mdd": float(res.mdd),
        "cagr": float(res.cagr),
        "final_nav": float(res.metrics.final_nav),
        "n_periods": int(res.metrics.n_periods),
    }


# ---------------------------------------------------------------------------
# Deprecated aliases — kept so existing callers (run_ga, examples, tests)
# keep working. They IGNORE prices_oos and delegate to the IS-only versions.
# ---------------------------------------------------------------------------


def multi_objective_fitness(prices_is, prices_oos, signal_fn,
                            costs=IBKR_costs, ppy=252,
                            max_mdd: float = 0.20,
                            **kwargs) -> tuple:
    """DEPRECATED. Now delegates to multi_objective_fitness_is.

    The legacy signature accepted ``(prices_is, prices_oos, signal_fn, ...)``
    and computed objectives against OOS — that violates the OOS-sagrado rule.
    This shim ignores ``prices_oos`` entirely so the GA cannot see OOS even
    if older code passes it.
    """
    if not _DEPRECATION_WARNED["multi_objective_fitness"]:
        warnings.warn(
            "multi_objective_fitness(prices_is, prices_oos, ...) is deprecated; "
            "use multi_objective_fitness_is(prices_is, ...). prices_oos is ignored.",
            DeprecationWarning,
            stacklevel=2,
        )
        _DEPRECATION_WARNED["multi_objective_fitness"] = True
    return multi_objective_fitness_is(
        prices_is, signal_fn,
        costs=costs, ppy=ppy,
        max_mdd=max_mdd,
        **kwargs,
    )


def scalar_fitness(prices_is, prices_oos, signal_fn,
                   costs=IBKR_costs, ppy=252,
                   weights=(0.5, 0.3, 0.2)) -> float:
    """DEPRECATED. Now delegates to scalar_fitness_is. ``prices_oos`` is ignored."""
    if not _DEPRECATION_WARNED["scalar_fitness"]:
        warnings.warn(
            "scalar_fitness(prices_is, prices_oos, ...) is deprecated; "
            "use scalar_fitness_is(prices_is, ...). prices_oos is ignored.",
            DeprecationWarning,
            stacklevel=2,
        )
        _DEPRECATION_WARNED["scalar_fitness"] = True
    return scalar_fitness_is(prices_is, signal_fn, costs=costs, ppy=ppy, weights=weights)
