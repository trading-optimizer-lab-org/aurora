"""Pre-trade safety checks (preflight).

Run all checks before allowing a strategy to go paper or live. Returns a
PreflightReport. Any check with passed=False populates `blockers`.

Convention: validate_pipeline writes a marker file under
`quantforge/data_cache_qf/.validation_passed_<strategy_name>.json` when
overall_passed=True. Preflight verifies that marker exists for the strategy.
"""
from __future__ import annotations

# Re-export module-level dependencies that tests historically monkey-patched
# via ``aurora.deployment.preflight``. The submodules use these directly,
# but tests like ``test_preflight.py`` reach into ``pf.shutil``,
# ``pf.socket``, etc., so they must remain reachable from the package
# namespace.
import shutil  # noqa: F401  -- re-export for test monkey-patching
import socket  # noqa: F401  -- re-export for test monkey-patching

# Re-export ``load_asset`` so tests that monkey-patch
# ``aurora.deployment.preflight.load_asset`` reach the lookup that the
# submodules perform via ``import aurora.deployment.preflight as _pkg;
# _pkg.load_asset(...)``.
from aurora.core.data_layer import QF_CACHE, load_asset  # noqa: F401

from aurora.deployment.preflight._broker import (
    check_broker_connection,
    check_buying_power,
    check_no_conflicting_positions,
)
from aurora.deployment.preflight._data_check import (
    _resolve_min_bars,
    check_anti_lookahead,
    check_data_availability,
    check_data_freshness,
    check_strategy_callable,
)
from aurora.deployment.preflight._market import check_market_hours
from aurora.deployment.preflight._marker import (
    _marker_path,
    _resolve_project_dir,
    check_validation_marker,
    write_validation_marker,
)
from aurora.deployment.preflight._models import (
    PreflightCheck,
    PreflightReport,
)
from aurora.deployment.preflight._orchestrator import run_preflight
from aurora.deployment.preflight._position import (
    check_disk_space,
    check_files_exist,
    check_position_sizing,
)
from aurora.deployment.preflight._system_time import (
    _NTP_FALLBACK_SERVERS,
    _query_ntp_server,
    check_system_time,
)


__all__ = [
    "PreflightCheck",
    "PreflightReport",
    "check_anti_lookahead",
    "check_broker_connection",
    "check_buying_power",
    "check_data_availability",
    "check_data_freshness",
    "check_disk_space",
    "check_files_exist",
    "check_market_hours",
    "check_no_conflicting_positions",
    "check_position_sizing",
    "check_strategy_callable",
    "check_system_time",
    "check_validation_marker",
    "run_preflight",
    "write_validation_marker",
]
