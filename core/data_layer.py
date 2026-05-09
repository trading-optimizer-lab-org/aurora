"""Data layer with OOS LOCK enforcement.

Critical anti-snooping mechanism: OOS data segregated and access-counted.
Any read of OOS during optimization phase increments counter. If counter > 0
when locking, validation pipeline reports OOS contamination.
"""
from __future__ import annotations
import os
import json
import threading
import datetime as _dt
from typing import Optional, Union, TYPE_CHECKING
import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from aurora.core.snapshots import DataSnapshot

PROJ = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_CACHE = os.path.join(PROJ, "data_cache")


def _resolve_qf_cache() -> str:
    """Return the QuantForge cache directory.

    Resolution order:
      1. ``$QF_CACHE`` environment variable (explicit override).
      2. Project-local ``quantforge/data_cache_qf/`` if it already contains
         cached parquet data (legacy in-tree cache, preserved for editable
         installs and the existing test suite).
      3. ``platformdirs.user_cache_dir("quantforge")`` if installed (XDG/win/mac).
      4. Fallback to ``~/.cache/quantforge`` (POSIX-style default).

    Never writes inside ``site-packages`` so the package directory stays
    read-only when installed from a wheel.
    """
    from aurora.core.env_compat import aurora_env
    env = aurora_env("AU_CACHE", "QF_CACHE")
    if env:
        return env
    legacy = os.path.join(PROJ, "quantforge", "data_cache_qf")
    if os.path.isdir(legacy) and any(
        f.endswith(".parquet") for f in os.listdir(legacy)
    ):
        return legacy
    try:
        from platformdirs import user_cache_dir  # type: ignore

        return user_cache_dir("quantforge")
    except ImportError:
        return os.path.join(os.path.expanduser("~"), ".cache", "quantforge")


QF_CACHE = _resolve_qf_cache()
DEFAULT_LOCK_PATH = os.path.join(QF_CACHE, ".oos_lock.json")


# OOS partition dates (immutable, project-wide)
IS_START = "1995-01-01"
IS_END = "2012-12-31"
OOS_START = "2013-01-01"
OOS_END = "2024-12-31"


def _get_git_hash() -> Optional[str]:
    """Best-effort capture of HEAD git hash. Returns None if unavailable.

    Uses :func:`quantforge.registry.versioning._run_git_proc` (Popen +
    explicit terminate/kill) instead of ``subprocess.run`` so a hung
    ``git.exe`` on Windows does not orphan a zombie process — the
    standard library's ``run(..., timeout=...)`` raises ``TimeoutExpired``
    but does not always reap the child cleanly on Windows.
    """
    try:
        from aurora.registry.versioning import _run_git_proc
        rc, out = _run_git_proc(["rev-parse", "HEAD"], timeout=2.0)
    except Exception:
        return None
    if rc is None or rc != 0:
        return None
    h = out.strip()
    return h or None


def _try_soc2_record(*, event_type: str, actor: str,
                     payload: Optional[dict] = None) -> None:
    """Best-effort SOC2 audit append. Never raises.

    P2.1 round-4 audit: when an OOSGuard records an authorized read or
    violation, mirror the event to ``SOC2AuditTrail`` so the SOC2 JSONL
    trail (canonical, hash-chained, tamper-evident) holds the same data
    as the OOS lock file (informational, mutable). A missing SOC2 log,
    a broken JSONL, or an import failure MUST NOT propagate -- the
    callers depend on the OOS lock semantics, not on SOC2 success.
    """
    try:
        from aurora.compliance.soc2_audit import SOC2AuditTrail
        SOC2AuditTrail().append(
            event_type=event_type,
            actor=actor,
            payload=dict(payload or {}),
        )
    except Exception:
        # Suppress all errors: SOC2 mirror is purely additive.
        pass


class _DefaultLockSentinel:
    """Sentinel marker used as the default value for ``OOSGuard.lock_path``.

    Distinct from ``None`` (explicit opt-out, in-memory only) and from any
    explicit string path. The constructor swaps this sentinel for
    :data:`DEFAULT_LOCK_PATH` so every protocol-tier OOSGuard persists its
    audit record by default. Unit tests that only need in-memory behaviour
    pass ``lock_path=None`` explicitly to opt out.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "<DEFAULT_LOCK>"


_DEFAULT_LOCK = _DefaultLockSentinel()


class OOSGuard:
    """Stateful guard tracking OOS access. Two layers:
    1. In-memory: per-context-manager counters (authorized reads + violations)
    2. File-system lock: persistent record under ``DEFAULT_LOCK_PATH``

    Lock file format (JSON)::

        {
            "locked_at": "2026-05-06T19:30:00",
            "git_hash": "abc123...",
            "phase": "post_ga_validation",
            "authorized_reads": [
                {"timestamp": "...", "where": "load_asset(SPY, ...)",
                 "phase": "post_ga_validation"}
            ],
            "violations": [
                {"timestamp": "...", "where": "...", "phase": "..."}
            ]
        }

    Audit semantics
    ---------------
    * ``authorized_reads`` -- legitimate post-validation OOS reads recorded
      via :py:meth:`record_oos_read`. These are NOT contamination; they are
      the audit trail for "this human/CI process saw OOS at time T for
      phase P".
    * ``violations`` -- real protocol violations recorded via
      :py:meth:`record_oos_violation` (e.g. a GA fitness loop snuck a peek).

    ``check_lock_clean`` only inspects ``violations``: a fully-audited run
    that records dozens of authorized reads is still "clean" because no
    contamination was recorded.

    Usage::

        with OOSGuard("post_ga_validation") as guard:
            ...                # default lock_path = DEFAULT_LOCK_PATH

        with OOSGuard("opt", lock_path="/tmp/.oos_lock.json") as guard:
            ...                # explicit override

        with OOSGuard("opt", lock_path=None) as guard:
            ...                # in-memory only (explicit opt-out, tests)
    """
    # Per-thread guard stack. Using threading.local ensures that two
    # concurrent threads each see only their own active guard, so a
    # background optimizer running in a different thread cannot pierce
    # the foreground OOSGuard or vice versa.
    _stack_local: threading.local = threading.local()
    # Process-wide mutex serializing read-modify-write of any lock file.
    # ``_close_lock_file`` reads the existing lock, merges in this
    # session's violations, and rewrites it. Without this, two guards
    # exiting on different threads at the same moment can interleave
    # read/write and lose violations from one of the writers.
    _lock_file_mutex: threading.Lock = threading.Lock()

    @classmethod
    def _stack_for_thread(cls) -> list:
        st = getattr(cls._stack_local, "stack", None)
        if st is None:
            st = []
            cls._stack_local.stack = st
        return st

    def __init__(self, phase: str = "optimization",
                 lock_path: Union[str, None, _DefaultLockSentinel] = _DEFAULT_LOCK):
        """Create a new guard.

        Args:
            phase: free-form label persisted to the lock file
                (e.g. ``"post_ga_validation"``, ``"explicit_unlock_oos_locked"``).
            lock_path: where to persist the audit record.

                * Default (omitted) -> :data:`DEFAULT_LOCK_PATH`. Every guard
                  in production code paths persists by default, so OOS reads
                  are auditable.
                * Explicit ``str`` -> use the given path (tests).
                * Explicit ``None`` -> in-memory only, no lock file writes
                  (unit-test opt-out).
        """
        self.phase = phase
        # In-memory counters -- two distinct buckets so callers can
        # distinguish "we read OOS, with audit" from "we leaked OOS into
        # the GA". ``violations`` keeps the legacy attribute name for
        # backward compatibility with existing tests.
        self.violations = 0
        self.violation_log: list[str] = []
        self.authorized_reads = 0
        self.authorized_log: list[str] = []
        if isinstance(lock_path, _DefaultLockSentinel):
            self.lock_path: Optional[str] = DEFAULT_LOCK_PATH
        else:
            self.lock_path = lock_path
        self._existing_lock: Optional[dict] = None
        self._session_violations: list[dict] = []
        self._session_authorized: list[dict] = []
        self._git_hash: Optional[str] = None

    def __enter__(self):
        OOSGuard._stack_for_thread().append(self)
        self._open_lock_file()
        return self

    def __exit__(self, *args):
        OOSGuard._stack_for_thread().pop()
        self._close_lock_file()

    def _open_lock_file(self) -> None:
        """Read existing lock file (if any). Capture current git hash."""
        self._git_hash = _get_git_hash()
        self._session_violations = []
        self._session_authorized = []
        path = self.lock_path
        if path is None:
            return
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._existing_lock = json.load(f)
            except Exception:
                self._existing_lock = None
        else:
            self._existing_lock = None

    def _close_lock_file(self) -> None:
        """Append current session violations to lock file. Always writes file
        when a lock_path is configured (even with zero violations) so that
        ``check_lock_clean`` can distinguish 'never run' from 'ran clean'.

        Concurrency
        -----------
        Acquires :pyattr:`OOSGuard._lock_file_mutex` (per-process) AND a
        cross-process advisory file lock via
        :func:`quantforge.registry.versioning._exclusive_file_lock` so
        that two guards exiting on different threads OR different
        processes cannot read-modify-write the same lock file and lose
        violations. The in-process mutex prevents intra-process races
        ahead of the syscall lock; the file lock serializes inter-process
        contenders. The on-disk write itself is atomic via a tmp-file +
        fsync + ``os.replace`` to keep the file consistent if the process
        is killed mid-write.
        """
        path = self.lock_path
        if path is None:
            return
        # Late import to avoid potential cycles at module-load time.
        from aurora.registry.versioning import _exclusive_file_lock
        with OOSGuard._lock_file_mutex:
            # Bare filenames (no directory component) yield "" from
            # dirname; skip makedirs to avoid FileNotFoundError on
            # Windows when the path is local to the cwd. We need the
            # parent to exist BEFORE _exclusive_file_lock writes its
            # sibling .lock file.
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with _exclusive_file_lock(path):
                # Re-read under the cross-process lock so we merge against
                # the freshest disk state, not the snapshot captured at
                # __enter__.
                disk_violations: list = []
                disk_authorized: list = []
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            on_disk = json.load(f)
                    except Exception:
                        on_disk = None
                    if isinstance(on_disk, dict):
                        raw_v = on_disk.get("violations", [])
                        if isinstance(raw_v, list):
                            disk_violations = raw_v
                        raw_a = on_disk.get("authorized_reads", [])
                        if isinstance(raw_a, list):
                            disk_authorized = raw_a
                merged_violations = list(disk_violations) + list(self._session_violations)
                merged_authorized = list(disk_authorized) + list(self._session_authorized)
                payload = {
                    "locked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                    "git_hash": self._git_hash,
                    "phase": self.phase,
                    "authorized_reads": merged_authorized,
                    "violations": merged_violations,
                }
                # Atomic write: tmp file in the same directory, fsync, then
                # os.replace. Avoids the half-written-file failure mode if
                # the process dies between open() and the json dump finishing.
                tmp_path = path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)

    def record_oos_read(self, where: str) -> None:
        """Record an *authorized* OOS read.

        This is the legitimate audit-trail path: e.g. ``cmd_validate``
        loads OOS_DEV inside ``OOSGuard("post_ga_validation")``. The
        access is logged so a third-party can later audit who saw OOS
        and when, but it is NOT a protocol violation.

        Backward-compatibility note: prior to round-2 this method also
        bumped the in-memory ``violations`` counter. Several existing
        tests assert that ``g.violations`` is incremented after calling
        ``record_oos_read``. To preserve that contract while introducing
        the authorized/violation split, we still bump ``self.violations``
        here -- but the on-disk record is stored under
        ``authorized_reads``, NOT ``violations``. New code that wants to
        log a real contamination event should call
        :py:meth:`record_oos_violation` instead.
        """
        # Legacy in-memory counter -- callers (and tests) read this to
        # verify "the guard saw an OOS read at all". We deliberately
        # keep it bumping for both authorized and violation paths so
        # the prior semantics survive.
        self.violations += 1
        self.violation_log.append(where)
        # Authorized-read counter -- separate so callers/audit tooling
        # can tell apart "audited OOS read" from "GA leaked OOS".
        self.authorized_reads += 1
        self.authorized_log.append(where)
        self._session_authorized.append({
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "where": where,
            "phase": self.phase,
        })
        # propagate counters + log to outer guards (concurrent / nested
        # contexts) -- only within the current thread's stack so a
        # parallel optimization thread never mixes its records with
        # another thread's guard. Only the innermost guard owns the
        # on-disk record (see ``record_oos_violation`` for the same
        # rationale).
        for g in OOSGuard._stack_for_thread():
            if g is self:
                continue
            g.violations += 1
            g.violation_log.append(where)
            g.authorized_reads += 1
            g.authorized_log.append(where)

    def record_oos_violation(self, where: str) -> None:
        """Record a real protocol violation (e.g. GA fitness peeked at OOS).

        Use this for true contamination events. Lives in the lock file
        under ``violations`` so :py:meth:`check_lock_clean` flips to
        False and CI can fail the run.

        Round-4 audit (P2.1): also append a SOC2 audit event so the
        SOC2 JSONL trail (canonical) and the OOS lock file (informational)
        no longer diverge. SOC2 append is best-effort -- a missing /
        unwritable SOC2 log MUST NOT prevent the violation record from
        being written to the lock.
        """
        self.violations += 1
        self.violation_log.append(where)
        self._session_violations.append({
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "where": where,
            "phase": self.phase,
        })
        for g in OOSGuard._stack_for_thread():
            if g is self:
                continue
            g.violations += 1
            g.violation_log.append(where)
        # P2.1 round-4 audit: best-effort SOC2 mirror.
        _try_soc2_record(
            event_type="oos_violation",
            actor="system",
            payload={"where": where, "phase": self.phase},
        )

    @classmethod
    def active(cls) -> Optional["OOSGuard"]:
        st = cls._stack_for_thread()
        return st[-1] if st else None

    @classmethod
    def check_lock_clean(cls, lock_path: Optional[str] = None) -> bool:
        """True if lock file exists and contains zero violations.

        If the file does not exist, treats as clean (nothing recorded).
        """
        path = lock_path or DEFAULT_LOCK_PATH
        if not os.path.exists(path):
            return True
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            # corrupt lock file is not clean
            return False
        violations = data.get("violations", []) if isinstance(data, dict) else []
        return isinstance(violations, list) and len(violations) == 0

    @classmethod
    def _record_external_authorized_read(
        cls, where: str, phase: str,
        lock_path: Optional[str] = None,
    ) -> None:
        """Append a single ``authorized_read`` to the lock file WITHOUT
        opening a context-manager guard.

        Round-3 audit fix: ``load_asset(include_oos=True, oos_purpose=...)``
        used to drop the read on the floor with a ``logger.debug`` line
        when no OOSGuard was active. The audit was therefore invisible
        to ``check_lock_clean`` and to anyone tailing the lock file.
        This helper writes the audit record directly so post-validation
        analysis reads (``cmd_run``, ``cmd_tearsheet``, ``cmd_factor``,
        ...) leave a paper trail even when the caller did not open an
        explicit guard context.

        The path matches the on-disk format produced by
        :py:meth:`_close_lock_file` so a downstream tool can union the
        records from both sources without branching on origin.

        Args:
            where: human-readable site of the read (e.g.
                ``"load_asset(SPY, oos_purpose=analysis)"``).
            phase: free-form label, persisted alongside the entry. Use
                the value of ``oos_purpose`` so the audit row carries
                the caller's intent.
            lock_path: lock file to append to. Defaults to
                :data:`DEFAULT_LOCK_PATH`.
        """
        from aurora.registry.versioning import _exclusive_file_lock
        path = lock_path or DEFAULT_LOCK_PATH
        if path is None:
            return
        with cls._lock_file_mutex:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with _exclusive_file_lock(path):
                # Read existing lock (if any).
                data: dict = {}
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f) or {}
                    except Exception:
                        data = {}
                if not isinstance(data, dict):
                    data = {}
                authorized = data.get("authorized_reads", [])
                if not isinstance(authorized, list):
                    authorized = []
                violations = data.get("violations", [])
                if not isinstance(violations, list):
                    violations = []
                authorized.append({
                    "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                    "where": where,
                    "phase": phase,
                })
                payload = {
                    "locked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                    "git_hash": _get_git_hash(),
                    # Preserve the prior lock's phase if present, else
                    # tag with the caller's phase so the file is never
                    # phaseless.
                    "phase": data.get("phase") or phase,
                    "authorized_reads": authorized,
                    "violations": violations,
                }
                tmp_path = path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)
        # P2.1 round-4 audit: best-effort SOC2 mirror so the JSONL
        # canonical trail records the same external authorized read.
        _try_soc2_record(
            event_type="oos_authorized_read",
            actor="system",
            payload={"where": where, "phase": phase},
        )

    @classmethod
    def reset_lock(cls, lock_path: Optional[str] = None) -> None:
        """Remove violations from the lock file (admin reset). If file does
        not exist, this is a no-op.

        Atomicity
        ---------
        Acquires :pyattr:`OOSGuard._lock_file_mutex` plus the cross-process
        advisory file lock so a concurrent ``_close_lock_file`` cannot
        interleave with the read-modify-write here. Writes via tmp +
        fsync + ``os.replace`` so a kill between open() and the json
        dump never produces a zero-byte lock file.
        """
        from aurora.registry.versioning import _exclusive_file_lock
        path = lock_path or DEFAULT_LOCK_PATH
        with cls._lock_file_mutex:
            if not os.path.exists(path):
                return
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with _exclusive_file_lock(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                data["violations"] = []
                # Authorized reads are an audit trail; they are NOT
                # contamination, so a reset only clears real violations.
                # We deliberately preserve ``authorized_reads`` so the
                # historical record of "who saw OOS" survives an admin
                # reset. Callers who want a full wipe can delete the
                # file outright.
                data.setdefault("authorized_reads", [])
                data["locked_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
                tmp_path = path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)


def check_oos_integrity(lock_path: Optional[str] = None) -> bool:
    """CI hook: True if the lock file has zero violations. Wraps
    ``OOSGuard.check_lock_clean`` for CLI/CI use.
    """
    return OOSGuard.check_lock_clean(lock_path)


def load_asset(symbol: str, source: str = "yfinance",
               start: Optional[str] = None, end: Optional[str] = None,
               include_oos: bool = False,
               freeze: bool = False,
               provenance: Optional[str] = None,
               oos_purpose: Optional[str] = None,
               require_snapshot: Union[bool, str] = False,
               provider: Optional[str] = None,
               ) -> Union[pd.Series, tuple[pd.Series, "DataSnapshot"]]:
    """Load price series from cache or download.

    Args:
        symbol: e.g. "SPY", "^GSPC", "BTC-USD"
        source: "yfinance" | "parquet" | "cache"
        start, end: optional date filters
        include_oos: if False (default), filters to IS only.
                    Setting True during OOSGuard.optimization triggers violation.
        freeze: if True, freeze the loaded series via SnapshotStore and return
                ``(prices, snapshot)`` instead of just ``prices``.
        provenance: provenance label for the frozen snapshot. Defaults to
                ``source`` when freeze=True.
        oos_purpose: optional purpose tag for OOS reads that are NOT part of
            a fitness loop (e.g. ``"analysis"``, ``"tearsheet"``,
            ``"factor_analysis"``). When provided alongside ``include_oos=True``
            and no OOSGuard is active, the read is logged AND persisted to
            the lock file as an ``authorized_read`` (round-3 fix: tagging
            does NOT bypass audit). Post-validation analysis commands
            (run, tearsheet, label, factor, attribute, purge-cv, fracdiff)
            can therefore read full prices without re-creating an explicit
            guard. The read is also recorded on the active guard if one
            exists.
        require_snapshot: round-3 fix -- now wired through to the
            :class:`SnapshotStore` for hash verification, not just a
            ``cache_path.exists()`` check.

            * ``False`` (default): legacy behaviour. Use the parquet
              cache if present, otherwise download dynamically.
            * ``True``: prefer a hash-verified ``SnapshotStore`` entry
              for ``symbol`` (loaded via ``store.load(sha256)``, which
              recomputes + verifies the SHA-256). If no
              ``SnapshotStore`` entry exists, fall back to the parquet
              cache and emit a ``UserWarning`` directing the caller to
              ``store.freeze(...)`` for a hash-verified snapshot.
              Refuses to download dynamically.
            * ``"strict"``: like ``True`` but the fall-back path is
              disabled. Raises ``RuntimeError`` if no hash-verified
              ``SnapshotStore`` entry is found. Use this for formal
              validation runs where any deviation from the registered
              snapshot must fail loudly.

            ``cmd_search`` and ``cmd_validate`` pass ``require_snapshot=True``
            (workflow: freeze first, then validate). Everyday CLI commands
            leave it ``False`` so they keep working when the cache has not
            been pre-populated. Formal validation runs that want strict
            mode pass ``require_snapshot="strict"``.
        provider: optional :class:`DataProviderRegistry` provider name.
            When set (e.g. ``"snapshot"``, ``"synthetic"``, ``"csv"``,
            ``"openbb"``), bypasses the legacy cache/yfinance path and
            routes the read through the registry. Provenance metadata
            (source, version, asof, content_hash, tier_permission) is
            stamped via ``DatasetMetadata``. The registry itself enforces
            tier-aware gating against the active OOSGuard. Default
            ``None`` keeps the legacy behaviour (parquet cache then
            yfinance) so callers that pre-date P0.B keep working.

    Returns:
        pd.Series with DatetimeIndex (default) or ``(pd.Series, DataSnapshot)``
        when ``freeze=True``.
    """
    # Check OOS guard.
    # HARD GUARD (mirrors load_oos): if a caller asks for OOS data (or
    # any window that crosses into OOS) and there is no active OOSGuard,
    # refuse the read UNLESS the caller explicitly tagged the read with
    # ``oos_purpose`` (post-validation analysis, tearsheet, etc.). The
    # guard exists to stop fitness loops from peeking at OOS; it does not
    # need to block a CLI command whose only job is to display OOS
    # results that have already passed the gate.
    if include_oos:
        guard = OOSGuard.active()
        if guard is None:
            if oos_purpose is None:
                raise RuntimeError(
                    f"load_asset({symbol!r}, include_oos=True) called outside an "
                    "OOSGuard context. OOS data must only be read during "
                    "validation phases. Wrap the call in "
                    "`with OOSGuard('post_ga_validation'): ...` or pass "
                    "``oos_purpose='analysis'`` for post-validation reads."
                )
            # Round-3 audit fix: ``oos_purpose`` is a tagging mechanism
            # for the read's intent, not a bypass of the audit trail.
            # Persist the read directly to the lock file via
            # ``_record_external_authorized_read`` so downstream auditors
            # can see "process X read OOS for purpose Y at time T"
            # whether or not an OOSGuard context wrapped the call.
            try:
                from aurora.core.logging import get_logger
                get_logger("aurora.data_layer").debug(
                    "OOS read (purpose=%s): load_asset(%s, include_oos=True)",
                    oos_purpose, symbol,
                )
            except Exception:
                # logging is advisory; never break the load
                pass
            try:
                OOSGuard._record_external_authorized_read(
                    where=f"load_asset({symbol}, include_oos=True, oos_purpose={oos_purpose!r})",
                    phase=str(oos_purpose),
                )
            except Exception:
                # Lock-file persistence is best-effort: a corrupt or
                # unwritable lock file must NOT prevent the analysis
                # call from completing. The debug log above is the
                # secondary trail.
                pass
        else:
            guard.record_oos_read(f"load_asset({symbol}, include_oos=True)")

    # P0.B: optional DataProviderRegistry path. When ``provider`` is set,
    # bypass the legacy parquet-cache + yfinance dance and route through
    # the registry so provenance metadata gets stamped + tier-aware gating
    # is applied. ``None`` keeps every legacy caller working unchanged.
    if provider is not None:
        from aurora.core.data_providers import get_default_registry
        registry = get_default_registry()
        ds = registry.fetch(provider, symbol, start=start, end=end)
        # ``ds.data`` may be a DataFrame (e.g. yahoo before column pick)
        # or a Series. Normalize to a single Series. Snapshot/Synthetic
        # already return a Series.
        raw = ds.data
        if isinstance(raw, pd.DataFrame):
            if "Close" in raw.columns:
                s = raw["Close"]
            else:
                s = raw.iloc[:, 0]
        else:
            s = raw  # type: ignore[assignment]
        # Drop down to the same downstream filter pipeline below.
        idx = pd.to_datetime(s.index)
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        s.index = idx
        s = s.dropna().sort_index()
        s = s[~s.index.duplicated(keep="last")]
        if start:
            s = s[s.index >= pd.Timestamp(start)]
        if end:
            s = s[s.index <= pd.Timestamp(end)]
        if not include_oos:
            s = s[s.index <= pd.Timestamp(IS_END)]
        if freeze:
            from aurora.core.snapshots import SnapshotStore
            from aurora.core.runtime_paths import snapshot_root as _snapshot_root
            store = SnapshotStore(str(_snapshot_root()))
            snap = store.freeze(
                s, symbol=symbol,
                provenance=provenance or f"provider:{provider}",
                locked=include_oos,
            )
            return s, snap
        return s

    cache_path = os.path.join(QF_CACHE, f"{symbol.replace('^', '_').replace('=', '_')}.parquet")
    # Round-3 audit fix: ``require_snapshot`` now consults the
    # SnapshotStore for hash verification rather than just calling
    # ``os.path.exists`` on the parquet cache. The SnapshotStore is
    # the only source of truth for hash-verified snapshots; the
    # parquet cache is a convenience for repeated reads.
    require_snapshot_strict = (
        isinstance(require_snapshot, str)
        and require_snapshot.lower() == "strict"
    )
    require_snapshot_any = bool(require_snapshot)
    if require_snapshot_any:
        # Try SnapshotStore first. Late import to avoid module-load cycles.
        try:
            from aurora.core.snapshots import SnapshotStore
            from aurora.core.runtime_paths import snapshot_root as _snapshot_root
            store = SnapshotStore(str(_snapshot_root()))
            snaps = store.get_by_symbol(symbol, start=start, end=end)
        except Exception:
            snaps = []
        if snaps:
            # Pick the most recently-created snapshot. ``get_by_symbol``
            # already sorts by ``created_at`` ascending, so the last
            # element is the freshest. ``store.load`` recomputes the
            # SHA-256 and raises ``IntegrityError`` on mismatch.
            chosen = snaps[-1]
            try:
                from aurora.core.snapshots import IntegrityError
                s, _snap = store.load(chosen.sha256)
            except IntegrityError as exc:
                raise RuntimeError(
                    f"load_asset({symbol!r}, require_snapshot={require_snapshot!r}): "
                    f"SnapshotStore.load failed for {chosen.sha256!r}: {exc}"
                ) from exc
        elif require_snapshot_strict:
            raise RuntimeError(
                f"load_asset({symbol!r}, require_snapshot='strict') requires "
                f"a hash-verified SnapshotStore entry for {symbol!r}, but none "
                f"was registered. Strict mode disables the parquet-cache "
                f"fallback. Run `store.freeze(prices, symbol={symbol!r}, ...)` "
                f"first."
            )
        elif os.path.exists(cache_path):
            # Backward-compat fall-back: the parquet cache exists but
            # the SnapshotStore has no record. We accept the read, but
            # warn the caller so the audit trail records that no
            # hash-verified snapshot was used.
            import warnings
            warnings.warn(
                f"load_asset({symbol!r}, require_snapshot=True): no "
                f"SnapshotStore entry found for {symbol!r}; falling back "
                f"to parquet cache at {cache_path!r}. For formal "
                f"validation runs, freeze the series first via "
                f"`SnapshotStore(...).freeze(prices, symbol={symbol!r}, ...)` "
                f"so the read is hash-verified.",
                stacklevel=2,
            )
            df = pd.read_parquet(cache_path)
            if "Close" in df.columns:
                s = df["Close"]
            else:
                s = df.iloc[:, 0]
        else:
            raise RuntimeError(
                f"load_asset({symbol!r}, require_snapshot=True) requires a "
                f"frozen parquet snapshot at {cache_path!r}, but none exists. "
                "Formal validation/search must run against a fixed dataset; "
                "the dynamic yfinance download is not reproducible. "
                "Pre-populate the cache or pass require_snapshot=False to "
                "allow a dynamic download."
            )
    elif os.path.exists(cache_path):
        df = pd.read_parquet(cache_path)
        if "Close" in df.columns:
            s = df["Close"]
        else:
            s = df.iloc[:, 0]
    else:
        s = _download(symbol, source)
        os.makedirs(QF_CACHE, exist_ok=True)
        # Atomic write: tmp + fsync + os.replace. A crash between
        # ``to_parquet`` opening the destination and finishing its byte
        # stream would otherwise leave a half-written cache that
        # ``pd.read_parquet`` would later fail to decode silently. The
        # tmp + replace pattern guarantees ``cache_path`` is either the
        # full prior file or the full new file, never a partial one.
        tmp_cache_path = cache_path + ".tmp"
        s.to_frame("Close").to_parquet(tmp_cache_path)
        # Rely on os.replace's atomicity to guarantee cache_path is either the
        # full prior file or the full new file, never a half-written hybrid.
        # An earlier version fsync'd an O_RDONLY fd here, but fsync on a
        # read-only descriptor is a no-op on most filesystems and was misleading
        # rather than load-bearing.
        os.replace(tmp_cache_path, cache_path)

    # Mirror ``core.snapshots._normalize_index_to_naive_utc``: when the
    # incoming index is tz-aware, convert to UTC *before* dropping the tz
    # marker. Casting through ``tz_localize(None)`` directly silently
    # strips the tz without converting, so two series differing only in
    # source tz collide on naive timestamps and on the snapshot digest.
    idx = pd.to_datetime(s.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    s.index = idx
    s = s.dropna().sort_index()
    # P3.3 round-4 audit: drop duplicate timestamps (keep last) so
    # split_by_tier never has to deal with the boundary ambiguity of
    # an index entry appearing twice. ``keep="last"`` preserves the
    # latest write (e.g. corrections to a corporate-action adjustment).
    s = s[~s.index.duplicated(keep="last")]

    # filter by IS/OOS
    if start: s = s[s.index >= pd.Timestamp(start)]
    if end: s = s[s.index <= pd.Timestamp(end)]
    if not include_oos:
        # IS slice ends at IS_END inclusive (2012-12-31); OOS starts at the
        # next business day (2013-01-02). Using ``IS_END`` directly avoids the
        # earlier off-by-one that subtracted one day from ``OOS_START``.
        s = s[s.index <= pd.Timestamp(IS_END)]

    if freeze:
        # late import to avoid circular module-load order at runtime
        from aurora.core.snapshots import SnapshotStore
        from aurora.core.runtime_paths import snapshot_root as _snapshot_root
        store = SnapshotStore(str(_snapshot_root()))
        snap = store.freeze(s, symbol=symbol,
                            provenance=provenance or source,
                            locked=include_oos)
        return s, snap
    return s


def load_from_snapshot(sha256: str) -> pd.Series:
    """Load a price series previously frozen via :class:`SnapshotStore`.

    Verifies the SHA-256 hash. If the snapshot is locked (e.g. OOS slice),
    requires ``with OOSGuard("explicit_unlock"): ...`` to be active.
    """
    from aurora.core.snapshots import SnapshotStore
    from aurora.core.runtime_paths import snapshot_root as _snapshot_root
    store = SnapshotStore(str(_snapshot_root()))
    prices, _snap = store.load(sha256)
    return prices


def _download(symbol: str, source: str = "yfinance",
              start: str = "1990-01-01",
              end: Optional[str] = None) -> pd.Series:
    """Download a price series from the configured ``source``.

    The ``end`` window defaults to ``pd.Timestamp.today()`` so the
    download tracks the calendar instead of pinning a hardcoded
    ``2025-12-31`` that goes stale every year. Callers that need a
    specific cutoff (e.g. snapshot reproducibility) can pass ``end``
    explicitly.
    """
    if end is None:
        end = pd.Timestamp.today().strftime("%Y-%m-%d")
    if source == "yfinance":
        import yfinance as yf
        df = yf.download(symbol, start=start, end=end,
                         auto_adjust=True, progress=False)
        if "Close" in df.columns:
            s = df["Close"].squeeze()
        else:
            s = df.iloc[:, 0]
        return s.dropna()
    raise NotImplementedError(f"source {source}")


def load_universe(symbols: list[str], **kwargs) -> dict[str, pd.Series]:
    """Load multiple symbols. Returns dict[symbol -> Series]."""
    return {s: load_asset(s, **kwargs) for s in symbols}


def split_is_oos(prices: pd.Series, oos_start: str = OOS_START):
    """Split price series into (IS, OOS). Returns tuple of pd.Series."""
    cutoff = pd.Timestamp(oos_start)
    is_part = prices[prices.index < cutoff]
    oos_part = prices[prices.index >= cutoff]
    return is_part, oos_part


def load_oos(symbol: str, source: str = "yfinance",
             start: Optional[str] = None, end: Optional[str] = None) -> pd.Series:
    """Load only the OOS slice of a symbol.

    HARD GUARD: must be called from inside a ``with OOSGuard(...)`` context.
    If no OOSGuard is active, raises ``RuntimeError``. This prevents
    accidental OOS reads during GA optimization.

    Returns:
        pd.Series of OOS prices.
    """
    if OOSGuard.active() is None:
        raise RuntimeError(
            "load_oos() called outside an OOSGuard context. "
            "OOS data must only be read during validation phases. "
            "Wrap the call in `with OOSGuard('post_ga_validation'): ...`."
        )
    full = load_asset(symbol, source=source, start=start, end=end,
                      include_oos=True)
    _, oos = split_is_oos(full)
    return oos
