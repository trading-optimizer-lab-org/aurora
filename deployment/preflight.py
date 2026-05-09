"""Pre-trade safety checks (preflight).

Run all checks before allowing a strategy to go paper or live. Returns a
PreflightReport. Any check with passed=False populates `blockers`.

Convention: validate_pipeline writes a marker file under
`quantforge/data_cache_qf/.validation_passed_<strategy_name>.json` when
overall_passed=True. Preflight verifies that marker exists for the strategy.
"""
from __future__ import annotations
import json
import logging
import os
import shutil
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from aurora.core.data_layer import OOSGuard, QF_CACHE, load_asset
from aurora.validation.lookahead_check import runtime_lookahead_check

_log = logging.getLogger(__name__)

# NTP fallback chain. Probed in order; first server that responds within the
# per-attempt timeout wins. If all fail, callers fall back to time.time().
_NTP_FALLBACK_SERVERS: tuple[str, ...] = (
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
    "time.nist.gov",
)


@dataclass
class PreflightCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PreflightReport:
    checks: list[PreflightCheck]
    all_passed: bool
    blockers: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = ["=" * 70, "PREFLIGHT REPORT", "=" * 70]
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            line = f"[{status}] {c.name}"
            if c.detail:
                line += f" - {c.detail}"
            lines.append(line)
        lines.append("-" * 70)
        lines.append(f"OVERALL: {'PASS' if self.all_passed else 'FAIL'}")
        if self.blockers:
            lines.append("Blockers:")
            for b in self.blockers:
                lines.append(f"  - {b}")
        lines.append("=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


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
            prices = load_asset(symbol, include_oos=True)
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


def _resolve_project_dir(project_dir: str = ".") -> str:
    """Resolve ``project_dir`` to a usable absolute path.

    Resolution order
    ----------------
    1. If ``project_dir`` is an absolute path, return it as-is (operators
       can pin a known location for the cache).
    2. Otherwise, walk upward from the current working directory looking
       for a ``pyproject.toml`` marker; the first directory containing it
       is treated as the project root.
    3. If no marker is found, fall back to ``os.path.abspath(project_dir)``
       so legacy behavior (relative paths joined with cwd) still works.

    This keeps ``check_validation_marker`` and ``write_validation_marker``
    co-located with the repository regardless of where the live process
    happens to be invoked from.
    """
    if os.path.isabs(project_dir):
        return project_dir
    here = os.path.abspath(os.getcwd())
    cur = here
    while True:
        if os.path.isfile(os.path.join(cur, "pyproject.toml")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(project_dir)


def _marker_path(strategy_name: str, project_dir: str = ".",
                 cache_dir: Optional[str] = None) -> str:
    """Compute the marker JSON path for ``strategy_name``.

    ``cache_dir`` (optional, absolute) overrides the ``project_dir`` resolution
    entirely so callers running outside the repo (e.g. CI containers) can pin
    the marker location explicitly.
    """
    if cache_dir is not None:
        if not os.path.isabs(cache_dir):
            cache_dir = os.path.abspath(cache_dir)
        return os.path.join(cache_dir, f".validation_passed_{strategy_name}.json")
    root = _resolve_project_dir(project_dir)
    cache = os.path.join(root, "quantforge", "data_cache_qf")
    return os.path.join(cache, f".validation_passed_{strategy_name}.json")


def check_validation_marker(strategy_name: str,
                            project_dir: str = ".",
                            max_age_days: int = 7,
                            cache_dir: Optional[str] = None) -> PreflightCheck:
    """Look for marker JSON written by validate_pipeline on overall_passed=True.

    Marker staleness
    ----------------
    A marker older than ``max_age_days`` (default 7) FAILS the check so a
    stale validation cannot let an out-of-date strategy ship to live. The
    marker timestamp is parsed from the JSON ``timestamp`` field; markers
    without a parseable timestamp are treated as stale.

    Path resolution
    ---------------
    Relative ``project_dir`` values are walked upward from the current
    working directory until a ``pyproject.toml`` is found, so live processes
    started outside the repo still locate the cache. Absolute ``project_dir``
    or ``cache_dir`` values bypass the walk.
    """
    path = _marker_path(strategy_name, project_dir, cache_dir=cache_dir)
    if not os.path.exists(path):
        return PreflightCheck(
            "validation_marker", False,
            f"missing marker: {path} (run validate_pipeline first)",
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return PreflightCheck(
            "validation_marker", False, f"unreadable marker: {e}",
        )
    ts = data.get("timestamp", "?")
    # Staleness check: parse the ISO timestamp; if absent or unparseable,
    # treat as stale to err on the safe side.
    try:
        marker_ts = pd.Timestamp(ts)
        if marker_ts.tzinfo is None:
            marker_ts = marker_ts.tz_localize("UTC")
        now_ts = pd.Timestamp.now(tz="UTC")
        age = now_ts - marker_ts
        age_days = float(age.total_seconds()) / 86400.0
    except Exception:
        return PreflightCheck(
            "validation_marker", False,
            f"marker timestamp unparseable ({ts!r}); rerun validate_pipeline",
        )
    if age_days > float(max_age_days):
        return PreflightCheck(
            "validation_marker", False,
            f"stale marker: age {age_days:.2f}d > {max_age_days}d "
            f"(rerun validate_pipeline)",
        )
    return PreflightCheck(
        "validation_marker", True,
        f"present @ {ts} (age {age_days:.2f}d <= {max_age_days}d)",
    )


def check_broker_connection(broker) -> PreflightCheck:
    """Probe broker. Accepts duck-typed object with is_connected() or connected attr.

    Skipped (passes) when broker exposes neither ``is_connected`` nor
    ``connected``, matching the duck-typed skip policy used by
    ``check_no_conflicting_positions`` for ``get_position``.
    """
    if broker is None:
        return PreflightCheck("broker_connection", True, "no broker (skipped)")
    if not (hasattr(broker, "is_connected") or hasattr(broker, "connected")):
        return PreflightCheck(
            "broker_connection", True,
            "broker has no is_connected/connected interface (skipped)",
        )
    try:
        if hasattr(broker, "is_connected"):
            ok = bool(broker.is_connected())
        else:
            ok = bool(broker.connected)
    except Exception as e:
        return PreflightCheck("broker_connection", False, f"probe error: {e}")
    if not ok:
        return PreflightCheck("broker_connection", False, "broker not connected")
    return PreflightCheck("broker_connection", True, "broker connected")


def check_no_conflicting_positions(broker, symbol: str) -> PreflightCheck:
    """Verify broker has no open position for symbol that would conflict."""
    if broker is None:
        return PreflightCheck("no_conflicting_positions", True, "no broker (skipped)")
    try:
        getp = getattr(broker, "get_position", None)
        if getp is None:
            return PreflightCheck(
                "no_conflicting_positions", True,
                "broker has no get_position (skipped)",
            )
        pos = getp(symbol)
    except Exception as e:
        return PreflightCheck("no_conflicting_positions", False, f"probe error: {e}")
    if pos is None:
        return PreflightCheck("no_conflicting_positions", True, f"no open {symbol}")
    qty = getattr(pos, "quantity", 0)
    if qty == 0:
        return PreflightCheck("no_conflicting_positions", True, f"flat {symbol}")
    return PreflightCheck(
        "no_conflicting_positions", False,
        f"existing {symbol} position qty={qty}",
    )


def check_market_hours(symbol: str, exchange: str = "NYSE",
                       now_utc: Optional[pd.Timestamp] = None
                       ) -> PreflightCheck:
    """Verify the market is open RIGHT NOW for ``symbol`` on ``exchange``.

    Skipped (passes) when ``pandas_market_calendars`` is not installed so
    paper deployments without that optional dep keep working.
    """
    try:
        import pandas_market_calendars as mcal  # type: ignore
    except Exception:
        return PreflightCheck(
            "market_hours", True,
            "skipped (pandas_market_calendars not installed)",
        )
    try:
        cal = mcal.get_calendar(exchange)
    except Exception as e:
        return PreflightCheck(
            "market_hours", False,
            f"unknown exchange calendar {exchange!r}: {e}",
        )
    now = pd.Timestamp.now(tz="UTC") if now_utc is None else now_utc
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    today = now.normalize().date()
    try:
        sched = cal.schedule(start_date=today.isoformat(),
                             end_date=today.isoformat())
    except Exception as e:
        return PreflightCheck(
            "market_hours", False,
            f"calendar query failed for {exchange}: {e}",
        )
    if sched.empty:
        return PreflightCheck(
            "market_hours", False,
            f"{exchange} closed on {today}",
        )
    open_ts = pd.Timestamp(sched.iloc[0]["market_open"]).tz_convert("UTC")
    close_ts = pd.Timestamp(sched.iloc[0]["market_close"]).tz_convert("UTC")
    if open_ts <= now <= close_ts:
        return PreflightCheck(
            "market_hours", True,
            f"{exchange} open ({open_ts.isoformat()} -> {close_ts.isoformat()})",
        )
    return PreflightCheck(
        "market_hours", False,
        f"{exchange} session window {open_ts.isoformat()} -> "
        f"{close_ts.isoformat()} does not include now={now.isoformat()}",
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


def check_buying_power(broker, required_cash: float) -> PreflightCheck:
    """Verify the broker reports >= ``required_cash`` buying power.

    Skipped when ``broker`` is None. ``required_cash`` must be > 0.
    """
    if broker is None:
        return PreflightCheck(
            "buying_power", True, "no broker (skipped)",
        )
    if required_cash <= 0:
        return PreflightCheck(
            "buying_power", False,
            f"required_cash must be > 0, got {required_cash}",
        )
    try:
        if hasattr(broker, "get_account"):
            acct = broker.get_account()
            if isinstance(acct, dict):
                bp = float(acct.get("buying_power", acct.get("cash", 0.0)))
            else:
                bp = float(getattr(acct, "buying_power",
                                   getattr(acct, "cash", 0.0)))
        elif hasattr(broker, "get_buying_power"):
            bp = float(broker.get_buying_power())
        else:
            return PreflightCheck(
                "buying_power", False,
                "broker has no get_account / get_buying_power",
            )
    except Exception as e:
        return PreflightCheck("buying_power", False, f"probe error: {e}")
    if bp < float(required_cash):
        return PreflightCheck(
            "buying_power", False,
            f"buying_power {bp:.2f} < required {float(required_cash):.2f}",
        )
    return PreflightCheck(
        "buying_power", True,
        f"buying_power {bp:.2f} >= required {float(required_cash):.2f}",
    )


def check_disk_space(path: str = ".", min_mb: int = 500) -> PreflightCheck:
    """Free disk space in MB on the volume containing `path`."""
    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free / (1024 * 1024)
    except Exception as e:
        return PreflightCheck("disk_space", False, f"disk probe error: {e}")
    if free_mb < min_mb:
        return PreflightCheck(
            "disk_space", False,
            f"only {free_mb:.0f} MB free, need >= {min_mb} MB",
        )
    return PreflightCheck("disk_space", True, f"{free_mb:.0f} MB free")


def check_position_sizing(weights_recent, max_pct: float = 1.0) -> PreflightCheck:
    """Verify max abs weight in recent signals does not exceed cap."""
    if weights_recent is None:
        return PreflightCheck("position_sizing", False, "weights is None")
    arr = np.asarray(weights_recent, dtype=float)
    if arr.size == 0:
        return PreflightCheck("position_sizing", False, "weights empty")
    if np.isnan(arr).any():
        return PreflightCheck("position_sizing", False, "NaN in weights")
    max_w = float(np.max(np.abs(arr)))
    if max_w > max_pct + 1e-9:
        return PreflightCheck(
            "position_sizing", False,
            f"max |weight|={max_w:.4f} > cap {max_pct:.4f}",
        )
    return PreflightCheck(
        "position_sizing", True,
        f"max |weight|={max_w:.4f} <= {max_pct:.4f}",
    )


def check_files_exist(paths: list) -> PreflightCheck:
    """All required files must exist."""
    if not paths:
        return PreflightCheck("files_exist", True, "no required files")
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        return PreflightCheck(
            "files_exist", False, f"missing: {', '.join(missing)}",
        )
    return PreflightCheck("files_exist", True, f"{len(paths)} files present")


def _query_ntp_server(ntp_server: str, timeout: float) -> float | None:
    """Send one NTP request; return server epoch seconds or None on failure."""
    NTP_PORT = 123
    NTP_PACKET = b"\x1b" + 47 * b"\0"
    NTP_DELTA = 2208988800  # 1900 -> 1970
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(NTP_PACKET, (ntp_server, NTP_PORT))
        data, _ = sock.recvfrom(48)
    except Exception:
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    try:
        secs = struct.unpack("!12I", data)[10]
        return float(secs - NTP_DELTA)
    except Exception:
        return None


def check_system_time(max_drift_sec: float = 1.0,
                      ntp_server: str | None = None,
                      timeout: float = 2.0,
                      ntp_servers: tuple[str, ...] | None = None,
                      soft_skip: bool = False,
                      ) -> PreflightCheck:
    """Compare local clock to NTP with fallback chain.

    Tries each server in ``ntp_servers`` (default: pool.ntp.org, time.google.com,
    time.cloudflare.com, time.nist.gov) in order. The first server to respond
    within ``timeout`` (default 2.0s) wins.

    All-fail behavior
    -----------------
    Default: when **every** server fails to respond, this check FAILS with
    detail "no NTP reachable". Live deployments that silently pass when the
    clock cannot be verified are dangerous — order timestamps, audit
    correlation, and broker session expiry all rely on accurate local time.
    Set ``soft_skip=True`` only in tightly-controlled environments where
    losing NTP is expected (offline labs, paper trading on isolated boxes).

    Args:
        max_drift_sec: max allowed |local - ntp| in seconds.
        ntp_server: optional single server (back-compat). If provided and
            ``ntp_servers`` is None, it is used as the only entry in the chain.
        timeout: per-server timeout in seconds.
        ntp_servers: explicit fallback chain. When None, uses
            ``_NTP_FALLBACK_SERVERS``.
        soft_skip: opt-in fallback that converts an all-fail outcome into a
            PASS instead of a FAIL. Defaults to False so live deployments
            block on unverified clocks.
    """
    if ntp_servers is None:
        if ntp_server is not None:
            servers: tuple[str, ...] = (ntp_server,)
        else:
            servers = _NTP_FALLBACK_SERVERS
    else:
        servers = tuple(ntp_servers)

    tried: list[str] = []
    for server in servers:
        tried.append(server)
        ntp_time = _query_ntp_server(server, timeout)
        if ntp_time is None:
            continue
        drift = abs(time.time() - ntp_time)
        if drift > max_drift_sec:
            return PreflightCheck(
                "system_time", False,
                f"clock drift {drift:.2f}s > {max_drift_sec:.2f}s "
                f"(server={server})",
            )
        return PreflightCheck(
            "system_time", True, f"drift={drift:.3f}s (server={server})",
        )

    # All servers failed.
    _log.warning(
        "preflight.check_system_time: all NTP servers unreachable (%s)",
        ", ".join(tried),
    )
    if soft_skip:
        return PreflightCheck(
            "system_time", True,
            f"skipped (soft_skip=True, no NTP from {len(tried)} servers)",
        )
    return PreflightCheck(
        "system_time", False,
        f"no NTP reachable (tried {len(tried)} servers: "
        f"{', '.join(tried)})",
    )


# ---------------------------------------------------------------------------
# Marker writer (used by validate_pipeline)
# ---------------------------------------------------------------------------


def write_validation_marker(strategy_name: str, metrics: dict,
                            project_dir: str = ".",
                            cache_dir: Optional[str] = None) -> str:
    """Write the marker JSON. Called by validate_pipeline when overall_passed.

    ``cache_dir`` (optional, absolute) bypasses ``project_dir`` and writes the
    marker directly into the supplied directory; useful when the caller knows
    the cache location regardless of the live process's working directory.
    """
    path = _marker_path(strategy_name, project_dir, cache_dir=cache_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "strategy_name": strategy_name,
        "metrics": metrics,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


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
                prices = load_asset(symbol, include_oos=True)
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
