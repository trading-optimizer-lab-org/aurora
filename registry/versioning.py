"""Strategy versioning + provenance hash (Task K.2).

Deterministic StrategyVersion = sha256(code_hash + params_hash)[:16].

- code_hash: sha256 of strategy class source (signal method + class body), with base
  class source folded in when the strategy is a subclass of another Strategy.
- params_hash: sha256 of canonical-JSON of params dict (sorted keys, type-stable).
- git_hash / git_dirty: best-effort capture via subprocess; None / False if unavailable.

VersionRegistry: append-only JSON-lines log at quantforge/data_cache_qf/version_history.jsonl.
- register(): idempotent (skipped if version_id already present).
- mark_validated(): rewrites the file with the updated row (versions are rare; OK).
- lineage(): walks parent_version chain (oldest -> ... -> requested version_id).
- diff_versions(): structured param + metric delta.
"""
from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import os
import random
import subprocess
import sys
import textwrap
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# Cross-platform advisory file lock used to serialize concurrent writes to
# the JSON-lines version history. POSIX uses fcntl.flock; Windows uses
# msvcrt.locking. Both block until the lock is released.
if sys.platform == "win32":  # pragma: no cover - exercised on Windows
    import msvcrt

    # Total time we are willing to spend retrying LK_LOCK before giving up.
    # The previous ``while True`` retry loop could spin forever if the
    # holder of the lock never released — bound the wait so a stuck
    # peer surfaces as a TimeoutError instead of a hang.
    _LOCK_TOTAL_WAIT_S = 30.0
    _LOCK_BACKOFF_BASE_S = 0.05
    _LOCK_BACKOFF_CAP_S = 0.5

    def _lock_file(fp) -> None:
        # msvcrt.locking acquires a 1-byte lock at the current file pointer.
        fp.seek(0)
        # LK_LOCK fails immediately if it cannot acquire after ~10s;
        # LK_NBLCK is non-blocking. Retry with bounded total wait and
        # jittered exponential backoff so concurrent writers don't
        # synchronize their retries (thundering-herd) and no caller
        # blocks forever.
        deadline = time.monotonic() + _LOCK_TOTAL_WAIT_S
        backoff = _LOCK_BACKOFF_BASE_S
        last_exc: Optional[OSError] = None
        while True:
            try:
                msvcrt.locking(fp.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError as exc:
                last_exc = exc
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"_lock_file: failed to acquire lock within "
                        f"{_LOCK_TOTAL_WAIT_S}s (last error: {exc!r})"
                    ) from exc
                # Full-jitter backoff: pick a random sleep in [0, backoff]
                # and double the cap up to _LOCK_BACKOFF_CAP_S.
                time.sleep(random.uniform(0.0, backoff))
                backoff = min(backoff * 2, _LOCK_BACKOFF_CAP_S)

    def _unlock_file(fp) -> None:
        try:
            fp.seek(0)
            msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock_file(fp) -> None:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)

    def _unlock_file(fp) -> None:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextlib.contextmanager
def _exclusive_file_lock(path: str):
    """Cross-platform exclusive lock against ``path``.

    Holds the lock on a sibling ``.lock`` file so the write target itself
    can be opened/replaced freely. The lock file is left in place to avoid
    races between create and lock.

    The ``open()``, ``_lock_file()``, and ``yield`` calls all live inside
    a single ``try`` so that an exception in ``_lock_file`` (e.g. msvcrt
    raising past the retry loop, or the underlying handle being yanked)
    cannot leak the file descriptor — the ``finally`` always runs and
    always closes ``fp`` if it was successfully opened.
    """
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    fp = None
    locked = False
    try:
        fp = open(lock_path, "ab")
        _lock_file(fp)
        locked = True
        yield
    finally:
        if fp is not None:
            if locked:
                _unlock_file(fp)
            fp.close()

def _default_history_path() -> str:
    """Resolve the version-history JSONL path via runtime_paths (R75)."""
    from quantforge.core.runtime_paths import cache_dir
    return str(cache_dir() / "version_history.jsonl")


_DEFAULT_HISTORY = _default_history_path()


@dataclass
class StrategyVersion:
    version_id: str
    strategy_class: str
    code_hash: str
    params_hash: str
    git_hash: Optional[str]
    git_dirty: bool
    created_at: str
    validated: bool = False
    validation_metrics: dict = field(default_factory=dict)
    parent_version: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyVersion":
        return cls(
            version_id=d["version_id"],
            strategy_class=d["strategy_class"],
            code_hash=d["code_hash"],
            params_hash=d["params_hash"],
            git_hash=d.get("git_hash"),
            git_dirty=bool(d.get("git_dirty", False)),
            created_at=d["created_at"],
            validated=bool(d.get("validated", False)),
            validation_metrics=dict(d.get("validation_metrics") or {}),
            parent_version=d.get("parent_version"),
        )


# ---------- hash helpers ----------

def _canonical_params(params: dict) -> str:
    """Stable JSON of params: sorted keys, type-coerced for floats/ints/bools/strings/lists."""
    def _coerce(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float, str)) or v is None:
            return v
        if isinstance(v, (list, tuple)):
            return [_coerce(x) for x in v]
        if isinstance(v, dict):
            return {str(k): _coerce(vv) for k, vv in sorted(v.items())}
        # fallback: stringify
        return str(v)
    coerced = {str(k): _coerce(v) for k, v in sorted(params.items())}
    return json.dumps(coerced, sort_keys=True, separators=(",", ":"))


def hash_strategy_code(strategy_class) -> str:
    """SHA256 of strategy class source + its Strategy-base ancestor sources.

    Folds in source of every base class in MRO that is itself a subclass of
    Strategy (excluding object/ABC). Falls back to qualified name if source
    cannot be retrieved (e.g., dynamically-generated classes).

    Caveat
    ------
    numba / Cython-compiled functions and classes cannot be source-hashed:
    ``inspect.getsource`` raises ``OSError`` or ``TypeError`` on AOT/JIT
    compiled artifacts. In that case we fall back to a qualname-only key
    (``module.__qualname__``), which means edits to the underlying source
    will NOT change the hash for compiled artifacts. Callers depending on
    code-fingerprinting for compiled code should pin the build hash via
    git or include the wheel hash in ``params``.
    """
    parts: list[str] = []
    try:
        parts.append(textwrap.dedent(inspect.getsource(strategy_class)))
    except (OSError, TypeError):
        # numba/Cython-compiled or dynamically-generated -> qualname key.
        parts.append(_qualname_fallback(strategy_class))

    # walk MRO, include intermediate Strategy subclasses
    try:
        from quantforge.strategies.base import Strategy as _Strategy  # noqa: WPS433
        for base in strategy_class.__mro__[1:]:
            if base is object or base is _Strategy:
                continue
            if not issubclass(base, _Strategy):
                continue
            try:
                parts.append(textwrap.dedent(inspect.getsource(base)))
            except (OSError, TypeError):
                parts.append(_qualname_fallback(base))
    except Exception:
        # base not importable in some test contexts; ignore
        pass

    blob = "\n\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _qualname_fallback(obj) -> str:
    """Fallback identifier when inspect.getsource fails (numba/Cython)."""
    module = getattr(obj, "__module__", "?")
    qual = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", "?")
    return f"{module}.{qual}"


def _hash_params(params: dict) -> str:
    return hashlib.sha256(_canonical_params(params).encode("utf-8")).hexdigest()


# ---------- git helpers ----------

# Sentinel returned by ``_git_head`` when the subprocess call timed out.
# Surfaces in ``StrategyVersion.git_hash`` so consumers can distinguish a
# timeout (busy / hung repo) from "git binary missing".
GIT_UNAVAILABLE = "git_unavailable"


def _run_git_proc(args: list[str], timeout: float) -> tuple[Optional[int], str]:
    """Run a git subprocess via ``Popen`` and force-terminate on timeout.

    Returns ``(returncode, stdout)``. ``returncode`` is ``None`` if the
    subprocess timed out (and was terminated). ``subprocess.run`` with a
    ``timeout=`` raises ``TimeoutExpired`` but does not always reap the
    child cleanly on Windows — ``proc.kill_on_timeout`` (or the implicit
    ``__exit__`` cleanup) can block on a stuck git process. We call
    ``terminate()`` first and then ``kill()`` with a hard wait to make
    sure no zombie ``git.exe`` lingers.
    """
    proc = subprocess.Popen(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_PROJ,
    )
    try:
        out, _err = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        return None, ""
    finally:
        # Defensive: on the happy path stdout/stderr are already closed by
        # communicate(); on the failure path we may still hold open pipes.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass


def _git(*args: str, timeout: float = 5.0) -> Optional[str]:
    """Run a git subprocess with a soft timeout.

    Returns stdout on success, ``None`` on any failure or timeout. The
    bounded timeout prevents a hung ``git`` process (e.g., interactive
    auth prompt, network filesystem stall) from freezing strategy
    versioning during live trading.
    """
    try:
        rc, out = _run_git_proc(list(args), timeout=timeout)
    except Exception:
        return None
    if rc != 0:
        return None
    return out


def _git_head() -> Optional[str]:
    """Return current HEAD short hash. Falls back to ``GIT_UNAVAILABLE`` on timeout."""
    try:
        rc, out = _run_git_proc(["rev-parse", "HEAD"], timeout=5.0)
    except Exception:
        return None
    if rc is None:
        return GIT_UNAVAILABLE
    if rc != 0:
        return None
    return out.strip() or None


def is_git_dirty() -> bool:
    """True if `git status --porcelain` reports any uncommitted changes.

    Uses a 5s subprocess timeout to avoid hanging on stalled repos. Returns
    False on timeout (treat unknown state as clean rather than blocking).
    """
    out = _git("status", "--porcelain", timeout=5.0)
    if out is None:
        return False
    return bool(out.strip())


# ---------- public API ----------

def compute_strategy_version(
    strategy_class,
    params: dict,
    include_git: bool = True,
    parent_version: Optional[str] = None,
) -> StrategyVersion:
    """Compute deterministic StrategyVersion from class + params (+ git state).

    git_hash / git_dirty are recorded but NOT mixed into version_id, so the same
    code+params produces the same id regardless of repo state.
    """
    code_h = hash_strategy_code(strategy_class)
    params_h = _hash_params(params or {})
    vid = hashlib.sha256((code_h + params_h).encode("utf-8")).hexdigest()[:16]
    if include_git:
        gh = _git_head()
        gd = is_git_dirty()
    else:
        gh, gd = None, False
    return StrategyVersion(
        version_id=vid,
        strategy_class=strategy_class.__name__,
        code_hash=code_h,
        params_hash=params_h,
        git_hash=gh,
        git_dirty=gd,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        validated=False,
        validation_metrics={},
        parent_version=parent_version,
    )


# ---------- registry ----------

class VersionRegistry:
    """Append-only JSON-lines log of StrategyVersion entries."""

    def __init__(self, history_path: Optional[str] = None):
        self.history_path = history_path or _DEFAULT_HISTORY
        # Bare filenames (no directory component) yield "" from
        # ``os.path.dirname``; ``os.makedirs("", exist_ok=True)`` raises
        # FileNotFoundError on some platforms. Guard so that a registry
        # rooted in cwd works without a fake "" directory create.
        parent = os.path.dirname(self.history_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _read_all(self) -> list[StrategyVersion]:
        if not os.path.exists(self.history_path):
            return []
        out: list[StrategyVersion] = []
        with open(self.history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(StrategyVersion.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue
        return out

    def _write_all(self, versions: list[StrategyVersion]) -> None:
        tmp = self.history_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for v in versions:
                f.write(json.dumps(v.to_dict(), sort_keys=True))
                f.write("\n")
            # fsync before rename: flush() pushes Python's buffer to the OS,
            # os.fsync forces the OS to push to disk. Without this, a crash
            # between os.replace returning and the kernel flushing the
            # written bytes can leave a zero-length history.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.history_path)

    def register(self, version: StrategyVersion) -> None:
        """Append to log if not already present (idempotent).

        Concurrent registrations are serialized via an advisory file lock
        on a sibling ``.lock`` file: without the lock two threads/processes
        racing to register the same ``version_id`` could both read the file
        before either appends, leading to duplicate lines.
        """
        with _exclusive_file_lock(self.history_path):
            existing = self._read_all()
            if any(v.version_id == version.version_id for v in existing):
                return
            with open(self.history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(version.to_dict(), sort_keys=True))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())

    def get(self, version_id: str) -> Optional[StrategyVersion]:
        for v in self._read_all():
            if v.version_id == version_id:
                return v
        return None

    def lineage(self, version_id: str) -> list[StrategyVersion]:
        """Trace ancestry oldest -> ... -> requested version_id (inclusive)."""
        all_v = {v.version_id: v for v in self._read_all()}
        cur = all_v.get(version_id)
        if cur is None:
            return []
        chain: list[StrategyVersion] = [cur]
        seen = {cur.version_id}
        while cur.parent_version and cur.parent_version in all_v:
            if cur.parent_version in seen:
                break  # cycle guard
            cur = all_v[cur.parent_version]
            seen.add(cur.version_id)
            chain.append(cur)
        return list(reversed(chain))

    def all_versions(self, strategy_class: Optional[str] = None) -> list[StrategyVersion]:
        vs = self._read_all()
        if strategy_class is None:
            return vs
        return [v for v in vs if v.strategy_class == strategy_class]

    def mark_validated(self, version_id: str, metrics: dict) -> None:
        """Update version row with validation results (rewrites file).

        Serialized against ``register()`` via the same advisory file lock.
        """
        with _exclusive_file_lock(self.history_path):
            versions = self._read_all()
            found = False
            for i, v in enumerate(versions):
                if v.version_id == version_id:
                    versions[i] = StrategyVersion(
                        version_id=v.version_id,
                        strategy_class=v.strategy_class,
                        code_hash=v.code_hash,
                        params_hash=v.params_hash,
                        git_hash=v.git_hash,
                        git_dirty=v.git_dirty,
                        created_at=v.created_at,
                        validated=True,
                        validation_metrics=dict(metrics),
                        parent_version=v.parent_version,
                    )
                    found = True
                    break
            if not found:
                raise KeyError(f"version_id not found: {version_id}")
            self._write_all(versions)


def diff_versions(v1: StrategyVersion, v2: StrategyVersion) -> dict:
    """Show differences between two versions (params via hash, metrics field-by-field)."""
    metric_diff: dict[str, Any] = {}
    keys = set(v1.validation_metrics.keys()) | set(v2.validation_metrics.keys())
    for k in sorted(keys):
        a = v1.validation_metrics.get(k)
        b = v2.validation_metrics.get(k)
        if a != b:
            metric_diff[k] = {"v1": a, "v2": b}
    return {
        "version_id": {"v1": v1.version_id, "v2": v2.version_id},
        "strategy_class": {
            "v1": v1.strategy_class, "v2": v2.strategy_class,
            "changed": v1.strategy_class != v2.strategy_class,
        },
        "code_changed": v1.code_hash != v2.code_hash,
        "params_changed": v1.params_hash != v2.params_hash,
        "git_hash": {"v1": v1.git_hash, "v2": v2.git_hash},
        "validated": {"v1": v1.validated, "v2": v2.validated},
        "metric_diff": metric_diff,
    }
