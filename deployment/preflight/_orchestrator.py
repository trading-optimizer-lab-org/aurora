"""run_preflight orchestrator -- runs the full check suite."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from aurora.core.data_layer import OOSGuard
from aurora.deployment.preflight._broker import (
    check_broker_connection,
    check_buying_power,
    check_no_conflicting_positions,
)
from aurora.deployment.preflight._data_check import (
    check_anti_lookahead,
    check_data_availability,
    check_data_freshness,
    check_strategy_callable,
)
from aurora.deployment.preflight._market import check_market_hours
from aurora.deployment.preflight._marker import check_validation_marker
from aurora.deployment.preflight._models import PreflightCheck, PreflightReport
from aurora.deployment.preflight._position import (
    check_disk_space,
    check_files_exist,
    check_position_sizing,
)
from aurora.deployment.preflight._system_time import check_system_time


def run_preflight(strategy, symbol: str, broker=None,
                  min_data_bars: int = 200,
                  max_position_pct: float = 1.0,
                  required_files: Optional[list] = None,
                  project_dir: str = ".",
                  prices: Optional[pd.Series] = None,
                  recent_weights: Optional[np.ndarray] = None,
                  min_disk_mb: int = 500,
                  check_ntp: bool = False,
                  required_cash: Optional[float] = None,
                  exchange: str = "NYSE",
                  data_freshness_hours: Optional[float] = None,
                  ) -> PreflightReport:
    """Run all preflight checks and return a PreflightReport.

    Args:
        strategy: object exposing signals(prices) -> ndarray
        symbol: ticker the strategy will trade
        broker: optional broker handle (Lumibot or duck-typed)
        min_data_bars: minimum cached bars required
        max_position_pct: max abs weight (1.0 = full notional)
        required_files: list of paths that must exist (configs, secrets)
        project_dir: project root for marker lookup
        prices: optional pre-loaded series (skips fetch when provided)
        recent_weights: optional array of recent weights to validate sizing
        min_disk_mb: minimum free disk space in MB
        check_ntp: if True, attempt NTP sync check (skips on no internet)
        required_cash: when > 0, gates the run with ``check_buying_power``.
            Skipped when None or <= 0.
        exchange: market calendar for ``check_market_hours`` (default NYSE).
        data_freshness_hours: when set, asserts the most recent bar is no
            older than the given hours via ``check_data_freshness``. Skipped
            when None.
    """
    checks: list[PreflightCheck] = []

    # 1. Strategy callable
    checks.append(check_strategy_callable(strategy))
    # Capture strategy_ok BY NAME once so subsequent appends shifting list
    # indices cannot poison downstream gates (see issue Round W #11).
    strategy_ok = checks[0].passed

    # 2. Data availability (respects strategy.min_bars/warmup if present)
    data_check = check_data_availability(symbol, min_data_bars,
                                         strategy=strategy)
    checks.append(data_check)

    # Load prices once for downstream checks if not supplied. Wrapped in
    # an OOSGuard("preflight_check") so the access is recorded under the
    # round-2 ``authorized_reads`` audit list and never marked as a
    # violation; preflight is a legitimate analysis path.
    if prices is None and data_check.passed:
        try:
            with OOSGuard("preflight_check"):
                # Resolve through the package so test monkey-patches of
                # ``aurora.deployment.preflight.load_asset`` are honoured.
                import aurora.deployment.preflight as _pkg
                prices = _pkg.load_asset(symbol, include_oos=True)
        except Exception:
            prices = None

    # 3. Anti-lookahead
    if strategy_ok and prices is not None:
        # Use a small slice for speed; runtime check shuffles half the series
        slice_n = min(len(prices), max(min_data_bars, 500))
        checks.append(check_anti_lookahead(strategy, prices.iloc[-slice_n:]))
    else:
        checks.append(PreflightCheck(
            "anti_lookahead", False, "skipped (strategy or data missing)",
        ))

    # 4. Validation marker
    strat_name = type(strategy).__name__ if strategy is not None else "?"
    checks.append(check_validation_marker(strat_name, project_dir))

    # 5. Broker connection
    checks.append(check_broker_connection(broker))

    # 6. No conflicting position
    checks.append(check_no_conflicting_positions(broker, symbol))

    # 7. Position sizing
    if recent_weights is None and strategy_ok and prices is not None:
        try:
            recent_weights = np.asarray(strategy.signals(prices))
        except Exception:
            recent_weights = None
    if recent_weights is not None:
        checks.append(check_position_sizing(recent_weights, max_position_pct))
    else:
        checks.append(PreflightCheck(
            "position_sizing", False, "no weights available",
        ))

    # 8. Required files
    checks.append(check_files_exist(required_files or []))

    # 9. Disk space
    checks.append(check_disk_space(project_dir, min_disk_mb))

    # 10. System time
    if check_ntp:
        checks.append(check_system_time())
    else:
        checks.append(PreflightCheck("system_time", True, "skipped (check_ntp=False)"))

    # 11. Market hours (gated by exchange).
    checks.append(check_market_hours(symbol, exchange=exchange))

    # 12. Data freshness (only when caller asks).
    if data_freshness_hours is not None and prices is not None:
        checks.append(check_data_freshness(
            prices, max_age_hours=float(data_freshness_hours),
        ))
    else:
        checks.append(PreflightCheck(
            "data_freshness", True,
            "skipped (data_freshness_hours not configured)",
        ))

    # 13. Buying power (only when caller asks).
    if required_cash is not None and float(required_cash) > 0:
        checks.append(check_buying_power(broker, float(required_cash)))
    else:
        checks.append(PreflightCheck(
            "buying_power", True, "skipped (required_cash not configured)",
        ))

    blockers = [f"{c.name}: {c.detail}" for c in checks if not c.passed]
    return PreflightReport(
        checks=checks,
        all_passed=len(blockers) == 0,
        blockers=blockers,
    )
