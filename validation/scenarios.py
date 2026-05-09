"""Synthetic crash scenario stress tests.

Inject a hard-coded historical crash return path into a price series at a chosen
timestamp, re-run the strategy, and compare metrics before/after. Unlike
gap_sim (random small gaps) or noise_injection (gaussian per-bar perturbation),
a scenario splices a deterministic, named historical crash pattern (1987 black
monday, 2008 GFC, 2020 covid, etc.) into the path.

The crash propagates forward permanently: prices after the splice are scaled
by the cumulative drawdown of the scenario, then continue from the new level.

Useful for: "would this strategy have survived 2008?" / "what happens under a
1987-style overnight gap?" — without needing the actual historical S&P series.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs


@dataclass
class CrashScenario:
    """Hard-coded historical crash template.

    return_path: array of daily returns spanning the crash window.
    peak_to_trough: cumulative drop (negative, e.g. -0.34 for -34%).
    duration_days: length of return_path.
    """
    name: str
    start: str
    end: str
    return_path: np.ndarray
    peak_to_trough: float
    duration_days: int
    description: str = ""


def _build(name: str, start: str, end: str, daily_returns,
           description: str) -> CrashScenario:
    arr = np.asarray(daily_returns, dtype=float)
    cum = float(np.prod(1.0 + arr) - 1.0)
    return CrashScenario(
        name=name, start=start, end=end, return_path=arr,
        peak_to_trough=cum, duration_days=len(arr), description=description,
    )


# Pre-built historical crash patterns.
#
# IMPORTANT: these are SYNTHETIC TEMPLATES. They are short hard-coded daily
# return arrays sized so the cumulative drop and duration are roughly in line
# with the historical crash they are named after. They are NOT historical
# replays of the actual S&P 500 path. The longer arrays (_R_2000, _R_2008,
# _R_2022) are generated from a fixed-seed numpy Generator so the templates
# are reproducible across runs but do not reflect the real day-by-day return
# series of those events. Treat them as "stress shapes", not as historical
# data.

# 1987 Black Monday: Oct 12 -> Oct 26, ~-22% in a few sessions, dominated by
# a single -20.5% session on Oct 19.
_R_1987 = [-0.026, -0.029, -0.022, -0.052, -0.205, 0.054, -0.082, -0.039, 0.018, 0.030]

# 1998 LTCM crisis: Aug -> Oct 1998, S&P drew down ~-20% peak-to-trough.
_R_1998 = [
    -0.014, -0.022, -0.011, -0.016, -0.029, -0.034, -0.014, 0.011, -0.018,
    -0.025, 0.014, -0.040, -0.048, 0.021, -0.025, -0.018, 0.015, -0.012,
    -0.020, -0.016, 0.007, -0.011, -0.018, 0.005, -0.014, -0.012, -0.009,
    0.008, -0.010, -0.012,
]

# 2000 dotcom: Sep 2000 -> Sep 2002, ~-49% over ~500 sessions. Use a
# compressed template (~250 bars) with average daily return ~-0.27%.
# The RNG is created at module import with a hard-coded seed (2000) so the
# template is byte-for-byte deterministic across processes and is independent
# of the global ``set_global_seed`` state. This is intentional: the crash
# templates must always represent the same shape, regardless of when in the
# session they are referenced.
_rng_dotcom = np.random.default_rng(2000)
_drift_dotcom = -0.0027
_vol_dotcom = 0.0145
_R_2000 = (_drift_dotcom + _vol_dotcom * _rng_dotcom.standard_normal(250)).tolist()

# 2008 GFC: Sep 2008 -> Mar 2009, ~-56% over ~125 sessions. Heavier tail in
# Oct 2008 (-9% on Oct 15, -7.6% on Oct 9, etc.).
# Same convention as 2000_dotcom: hard-coded import-time seed so the template
# stays byte-identical across processes regardless of GLOBAL_SEED.
_rng_gfc = np.random.default_rng(2008)
_R_2008 = []
# Oct 2008 panic block (~-30% over 22 sessions)
_R_2008 += [-0.045, -0.035, 0.038, -0.076, -0.044, -0.012, 0.115, -0.023,
            -0.090, 0.044, -0.061, 0.015, -0.030, -0.047, 0.054, -0.034,
            0.018, -0.010, -0.030, 0.010, -0.029, -0.037]
# Following months: noisy decline averaging ~-0.4% / day for ~100 more sessions
_R_2008 += (-0.004 + 0.018 * _rng_gfc.standard_normal(103)).tolist()

# 2010 Flash Crash: 2010-05-06 single session, intra-day spike of roughly
# -9% that almost fully recovered the same day. Daily close was ~-3.2%.
# Modeled as a single-bar return reflecting the closing print, since
# the splice operates on daily bars (intra-bar price round-trip is not
# observable in a daily series). Treat as a one-day liquidity shock.
_R_2010 = [-0.0316]

# 2020 covid: Feb 19 -> Mar 23 2020, ~-34% over 23 sessions. Heavy clustering
# of -7% to -12% sessions.
_R_2020 = [
    -0.011, -0.038, -0.030, -0.034, -0.045, 0.046, -0.028, -0.034, -0.026,
    -0.075, 0.049, -0.077, -0.059, 0.094, -0.121, -0.029, 0.060, -0.052,
    -0.044, 0.061, -0.042, -0.029, 0.024,
]

# 2022 drawdown: Jan -> Oct 2022, ~-25% over ~200 sessions. Slow grind.
# Same convention as 2000_dotcom and 2008_gfc: hard-coded import-time seed
# so the template stays byte-identical across processes regardless of
# GLOBAL_SEED.
_rng_22 = np.random.default_rng(2022)
_R_2022 = (-0.0014 + 0.013 * _rng_22.standard_normal(200)).tolist()


KNOWN_CRASHES: dict[str, CrashScenario] = {
    "1987_black_monday": _build(
        "1987_black_monday", "1987-10-12", "1987-10-26", _R_1987,
        "Black Monday: ~-22% in two weeks, single -20.5% session on Oct 19.",
    ),
    "1998_ltcm": _build(
        "1998_ltcm", "1998-08-01", "1998-10-08", _R_1998,
        "LTCM / Russia default crisis: ~-20% over ~30 sessions.",
    ),
    "2000_dotcom": _build(
        "2000_dotcom", "2000-09-01", "2002-09-30", _R_2000,
        "Dotcom bust: ~-49% peak to trough over ~2 years (compressed template).",
    ),
    "2008_gfc": _build(
        "2008_gfc", "2008-09-01", "2009-03-09", _R_2008,
        "Global Financial Crisis: ~-56% peak to trough Sep '08 - Mar '09.",
    ),
    "2010_flash_crash": _build(
        "2010_flash_crash", "2010-05-06", "2010-05-06", _R_2010,
        "Flash Crash: intra-day -9% spike, closed ~-3.2% same day. Single-bar shock.",
    ),
    "2020_covid": _build(
        "2020_covid", "2020-02-19", "2020-03-23", _R_2020,
        "COVID crash: ~-34% in 23 sessions. Fastest bear market on record.",
    ),
    "2022_drawdown": _build(
        "2022_drawdown", "2022-01-03", "2022-10-12", _R_2022,
        "2022 rates-driven bear: ~-25% over ~200 sessions, slow grind.",
    ),
}


@dataclass
class StressResult:
    scenario_name: str
    base_metrics: dict
    stressed_metrics: dict
    cagr_drop_pct: float       # (base - stressed) / |base| * 100
    mdd_increase_pct: float    # (|stressed| / |base| - 1) * 100
    sharpe_drop: float         # base - stressed (absolute units)
    survived: bool             # stressed mdd >= survived_threshold

    def to_dict(self) -> dict:
        return {
            "scenario_name": self.scenario_name,
            "base_metrics": dict(self.base_metrics),
            "stressed_metrics": dict(self.stressed_metrics),
            "cagr_drop_pct": self.cagr_drop_pct,
            "mdd_increase_pct": self.mdd_increase_pct,
            "sharpe_drop": self.sharpe_drop,
            "survived": self.survived,
        }


def _compare(base: dict, stressed: dict, name: str,
             survived_threshold: float) -> StressResult:
    base_cagr = float(base.get("cagr", 0.0))
    base_mdd = float(base.get("mdd", 0.0))
    base_sharpe = float(base.get("sharpe", 0.0))
    s_cagr = float(stressed.get("cagr", 0.0))
    s_mdd = float(stressed.get("mdd", 0.0))
    s_sharpe = float(stressed.get("sharpe", 0.0))

    if abs(base_cagr) > 1e-12:
        cagr_drop_pct = (base_cagr - s_cagr) / abs(base_cagr) * 100.0
    else:
        cagr_drop_pct = 0.0
    if abs(base_mdd) > 1e-12:
        mdd_increase_pct = (abs(s_mdd) / abs(base_mdd) - 1.0) * 100.0
    else:
        mdd_increase_pct = 0.0
    sharpe_drop = base_sharpe - s_sharpe
    survived = bool(s_mdd >= survived_threshold)
    return StressResult(
        scenario_name=name,
        base_metrics=dict(base),
        stressed_metrics=dict(stressed),
        cagr_drop_pct=float(cagr_drop_pct),
        mdd_increase_pct=float(mdd_increase_pct),
        sharpe_drop=float(sharpe_drop),
        survived=survived,
    )


def replay_crash(strategy_factory: Callable, prices: pd.Series,
                 scenario: CrashScenario,
                 inject_at: Optional[pd.Timestamp] = None,
                 costs: CostModel = ZERO_costs,
                 ppy: int = 252,
                 survived_threshold: float = -0.50) -> StressResult:
    """Inject a historical crash return path into prices and re-run strategy.

    The crash splices in starting at `inject_at`: the next `duration_days` bars
    are overwritten by the scenario's return path, applied multiplicatively to
    the price level at the splice point. All bars AFTER the splice continue
    from the new (post-crash) level using the original returns from that bar
    onward — i.e. the crash is permanent (level shift) but normal dynamics
    resume after.

    Args:
        strategy_factory: callable() -> Strategy
        prices: original price series (DatetimeIndex)
        scenario: CrashScenario template
        inject_at: timestamp to start injection. Default: middle of the series.
        costs: cost model for backtest
        ppy: periods/year
        survived_threshold: stressed MDD must be >= this to count as survived
            (default -0.50 = strategy survives if MDD shallower than -50%).

    Returns:
        StressResult with base vs stressed metrics.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be pd.Series with DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be DatetimeIndex")
    if scenario.duration_days <= 0:
        raise ValueError("scenario duration must be > 0")

    n = len(prices)
    if scenario.duration_days >= n - 10:
        raise ValueError(
            f"scenario duration {scenario.duration_days} too long for series of length {n}"
        )

    # Decide injection bar index. Clip to leave room for the full crash so we
    # never silently truncate scenario.return_path (which the inner loop guards
    # against with ``if splice_start + k < n``).
    if inject_at is None:
        inject_idx = min(n // 2, n - scenario.duration_days - 1)
    else:
        ts = pd.Timestamp(inject_at)
        # nearest index >= ts (clip into valid range)
        loc = prices.index.searchsorted(ts)
        inject_idx = int(min(max(loc, 1), n - scenario.duration_days - 1))

    # Build stressed price path
    base_p = prices.values.astype(float)
    stressed_p = base_p.copy()
    splice_start = inject_idx
    splice_end = inject_idx + scenario.duration_days  # exclusive

    # Apply scenario returns starting from price at splice_start
    p_anchor = stressed_p[splice_start - 1] if splice_start > 0 else stressed_p[0]
    cur = p_anchor
    for k, r in enumerate(scenario.return_path):
        cur = cur * (1.0 + float(r))
        if splice_start + k < n:
            stressed_p[splice_start + k] = cur

    # After splice: continue with original returns from splice_end onward,
    # but starting from the post-crash level. This preserves "permanence".
    # Compute the propagation factor in log space (np.exp(log p_i - log p_{i-1}))
    # rather than via simple division so that very small base prices and tiny
    # bar-to-bar moves accumulate without drift from float-division round-off.
    if splice_end < n:
        log_base = np.log(np.maximum(base_p, 1e-30))
        for i in range(splice_end, n):
            base_ret = float(np.exp(log_base[i] - log_base[i - 1]))
            stressed_p[i] = stressed_p[i - 1] * base_ret

    stressed_p = np.maximum(stressed_p, 1e-9)
    stressed_prices = pd.Series(stressed_p, index=prices.index, name=prices.name)

    # Run backtest before / after
    base_strat = strategy_factory()
    base_res = run_backtest(prices, base_strat.signals, costs=costs, ppy=ppy)
    stressed_strat = strategy_factory()
    s_res = run_backtest(stressed_prices, stressed_strat.signals, costs=costs, ppy=ppy)

    return _compare(
        base=base_res.metrics.to_dict(),
        stressed=s_res.metrics.to_dict(),
        name=scenario.name,
        survived_threshold=survived_threshold,
    )


def stress_test_all_known(strategy_factory: Callable, prices: pd.Series,
                          costs: CostModel = ZERO_costs,
                          ppy: int = 252,
                          survived_threshold: float = -0.50,
                          inject_at: Optional[pd.Timestamp] = None,
                          ) -> dict[str, StressResult]:
    """Run every KNOWN_CRASHES scenario against the strategy.

    Returns:
        dict mapping scenario name -> StressResult.
    """
    out: dict[str, StressResult] = {}
    for key, scenario in KNOWN_CRASHES.items():
        if scenario.duration_days >= len(prices) - 10:
            # Skip scenarios too long for this series; record a placeholder.
            continue
        out[key] = replay_crash(
            strategy_factory=strategy_factory,
            prices=prices,
            scenario=scenario,
            inject_at=inject_at,
            costs=costs,
            ppy=ppy,
            survived_threshold=survived_threshold,
        )
    return out


def custom_scenario(returns: pd.Series, name: str = "custom",
                    description: str = "") -> CrashScenario:
    """Build a CrashScenario from a custom returns series.

    Args:
        returns: pd.Series of daily returns (index optional).
        name: scenario name.
        description: free-form description.
    """
    if not isinstance(returns, pd.Series):
        raise TypeError("returns must be pd.Series")
    arr = returns.values.astype(float)
    if len(arr) == 0:
        raise ValueError("returns must be non-empty")
    if isinstance(returns.index, pd.DatetimeIndex) and len(returns.index) > 0:
        start = str(returns.index[0].date())
        end = str(returns.index[-1].date())
    else:
        start, end = "custom", "custom"
    cum = float(np.prod(1.0 + arr) - 1.0)
    return CrashScenario(
        name=name, start=start, end=end, return_path=arr,
        peak_to_trough=cum, duration_days=len(arr), description=description,
    )


def amplify_scenario(scenario: CrashScenario, factor: float = 1.5) -> CrashScenario:
    """Return a new scenario with returns scaled by factor (deeper or shallower).

    Args:
        scenario: source CrashScenario.
        factor: multiplier applied to each return. factor > 1 deepens the
            crash (and expands rallies); factor < 1 softens it.
    """
    if factor <= 0:
        raise ValueError(f"factor must be > 0 (got {factor})")
    new_path = scenario.return_path * float(factor)
    cum = float(np.prod(1.0 + new_path) - 1.0)
    return CrashScenario(
        name=f"{scenario.name}_x{factor:g}",
        start=scenario.start,
        end=scenario.end,
        return_path=new_path,
        peak_to_trough=cum,
        duration_days=scenario.duration_days,
        description=f"{scenario.description} (amplified x{factor:g})",
    )
