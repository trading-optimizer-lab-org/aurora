"""Data-availability and anti-lookahead preflight checks."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from aurora.core.data_layer import OOSGuard
from aurora.deployment.preflight._models import PreflightCheck
from aurora.validation.lookahead_check import runtime_lookahead_check


def _load_asset(symbol: str, *, include_oos: bool = True):
    """Resolve ``load_asset`` through the package so test monkey-patches
    on ``aurora.deployment.preflight.load_asset`` take effect.

    The package ``__init__.py`` exposes ``load_asset`` as a module-level
    attribute (re-exported from ``aurora.core.data_layer``); tests replace
    that attribute via ``monkeypatch.setattr(pf, "load_asset", ...)``.
    Indirecting through ``sys.modules`` keeps the patch reachable instead
    of binding to the original function at import time.
    """
    import aurora.deployment.preflight as _pkg
    return _pkg.load_asset(symbol, include_oos=include_oos)


def check_strategy_callable(strategy) -> PreflightCheck:
    """Strategy must expose a callable signals() method."""
    if strategy is None:
        return PreflightCheck("strategy_callable", False, "strategy is None")
    fn = getattr(strategy, "signals", None)
    if fn is None:
        return PreflightCheck("strategy_callable", False, "missing signals attr")
    if not callable(fn):
        return PreflightCheck("strategy_callable", False, "signals not callable")
    return PreflightCheck("strategy_callable", True, "signals() callable")


def _resolve_min_bars(strategy, fallback: int = 200) -> int:
    """Resolve the minimum-bars requirement for a strategy.

    Order of precedence:
        1. ``strategy.min_bars`` attribute
        2. ``strategy.warmup`` attribute
        3. ``fallback`` (default 200)

    Non-positive or non-integer attribute values are ignored. Strategies that
    declare a longer lookback than the fallback are honored as-is so preflight
    surfaces 'not enough data' before the strategy tries to run on a short
    cache.
    """
    for attr in ("min_bars", "warmup"):
        val = getattr(strategy, attr, None) if strategy is not None else None
        if val is None:
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return int(fallback)


def check_data_availability(symbol: str, min_bars: int = 200,
                            strategy=None) -> PreflightCheck:
    """Verify enough historical bars are loadable for the symbol.

    If ``strategy`` is provided and exposes a ``min_bars`` or ``warmup``
    attribute, that value overrides ``min_bars`` so the data check tracks the
    strategy's actual warmup needs.
    """
    if strategy is not None:
        min_bars = _resolve_min_bars(strategy, fallback=min_bars)
    try:
        # Allow OOS so paper-time data is included if cached. Preflight
        # is a legitimate post-validation analysis path, so we wrap the
        # call in ``OOSGuard("preflight_check")`` -- this records an
        # authorized_read in the lock file (per round-2 schema) so the
        # access is auditable without tripping check_lock_clean.
        with OOSGuard("preflight_check"):
            prices = _load_asset(symbol, include_oos=True)
    except Exception as e:
        return PreflightCheck("data_availability", False, f"load failed: {e}")
    n = len(prices)
    if n < min_bars:
        return PreflightCheck(
            "data_availability", False,
            f"only {n} bars available, need >= {min_bars}",
        )
    return PreflightCheck(
        "data_availability", True, f"{n} bars (>= {min_bars})"
    )


def check_anti_lookahead(strategy, prices: pd.Series,
                         n_shuffles: int = 5,
                         seeds: tuple[int, ...] | None = None,
                         z_threshold: float = 3.0) -> PreflightCheck:
    """Runtime lookahead check using multi-shuffle ensemble.

    Runs ``runtime_lookahead_check`` across ``n_shuffles`` seeds, then computes
    mean and std of the leak metric. Fails if any individual shuffle reports a
    runtime violation, OR if the mean leak metric exceeds ``z_threshold * std``
    (poor man's CI: a leak metric well above noise level is suspicious even if
    the per-seed boolean flag did not trip).

    Args:
        strategy: object exposing signals(prices).
        prices: prior price series.
        n_shuffles: number of independent shuffles (default 5).
        seeds: optional tuple of explicit seeds; default derives from n_shuffles.
        z_threshold: multiple of std used for the noise-level guardrail.
    """
    if prices is None or len(prices) < 50:
        return PreflightCheck("anti_lookahead", False, "insufficient prices for check")
    if n_shuffles < 1:
        return PreflightCheck("anti_lookahead", False, "n_shuffles must be >= 1")
    if seeds is None:
        seeds = tuple(range(42, 42 + n_shuffles))
    elif len(seeds) != n_shuffles:
        n_shuffles = len(seeds)

    deltas: list[float] = []
    any_violation = False
    try:
        for seed in seeds:
            rep = runtime_lookahead_check(
                strategy.signals, prices, seed=int(seed),
            )
            deltas.append(float(rep.runtime_metric_delta))
            if not rep.passed:
                any_violation = True
    except Exception as e:
        return PreflightCheck("anti_lookahead", False, f"check error: {e}")

    if not deltas:
        return PreflightCheck("anti_lookahead", False, "no shuffle deltas computed")

    arr = np.asarray(deltas, dtype=float)
    mean_d = float(arr.mean())
    std_d = float(arr.std(ddof=0))
    detail_stats = (
        f"n={len(arr)} mean={mean_d:.3e} std={std_d:.3e}"
    )

    if any_violation:
        return PreflightCheck(
            "anti_lookahead", False,
            f"runtime leak across shuffles ({detail_stats})",
        )

    # Guardrail: even when no per-seed flag tripped, flag if mean clearly
    # exceeds noise. Skip when std is effectively zero (deterministic clean
    # strategy: every delta is ~0, so mean is ~0 and std is ~0; treating that
    # as a leak would be a false positive).
    if std_d > 1e-12 and mean_d > z_threshold * std_d:
        return PreflightCheck(
            "anti_lookahead", False,
            f"leak metric mean > {z_threshold:.1f}*std ({detail_stats})",
        )

    return PreflightCheck(
        "anti_lookahead", True,
        f"no runtime leak detected ({detail_stats})",
    )


def check_data_freshness(prices, max_age_hours: float = 24.0,
                         now_utc: Optional[pd.Timestamp] = None
                         ) -> PreflightCheck:
    """Verify the most recent bar is within ``max_age_hours`` of now.

    Stale price data is a frequent cause of bad live decisions; this check
    blocks the deploy so the operator notices the feed lag.
    """
    if prices is None:
        return PreflightCheck("data_freshness", False, "prices is None")
    try:
        idx = getattr(prices, "index", None)
        if idx is None or len(idx) == 0:
            return PreflightCheck("data_freshness", False, "no bars in prices")
        last = pd.Timestamp(idx[-1])
        if last.tzinfo is None:
            last = last.tz_localize("UTC")
        now = (pd.Timestamp.now(tz="UTC")
               if now_utc is None else now_utc)
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        age_hours = float((now - last).total_seconds()) / 3600.0
    except Exception as e:
        return PreflightCheck("data_freshness", False, f"probe error: {e}")
    if age_hours > float(max_age_hours):
        return PreflightCheck(
            "data_freshness", False,
            f"last bar {last.isoformat()} is {age_hours:.2f}h old "
            f"> {max_age_hours}h max",
        )
    return PreflightCheck(
        "data_freshness", True,
        f"last bar age {age_hours:.2f}h <= {max_age_hours}h",
    )
