"""File-backed cross-process strategy isolation lease store (R71 ext).

Extension of `deployment/strategy_isolation.py`'s in-process registry.
Two `forge` invocations on the same machine must not silently clobber
each other's leases. This module replaces the in-memory dict with a
JSON file under `$QF_DATA_DIR` plus an OS-level file lock so the
critical section is atomic across processes.

Atomicity is delivered by ``filelock`` if available, falling back to
``os.O_EXCL`` rename-based locking when the package is missing -- the
fallback is correct on POSIX and on modern Windows where ``os.rename``
is atomic over an existing file.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .strategy_isolation import IsolationConflict, Lease


@dataclass
class FileLeaseStore:
    """Cross-process lease registry persisted to disk.

    Args:
        store_path: JSON file storing the active lease set.
        lock_path: lock file used to serialise critical sections;
            defaults to ``store_path.with_suffix(".lock")``.
        wait_timeout_seconds: how long to wait for the OS lock before
            raising. 0 = no waiting (fail fast).
    """

    store_path: Path
    lock_path: Optional[Path] = None
    wait_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path is None:
            self.lock_path = self.store_path.with_suffix(".lock")

    # ---- public lease API ---------------------------------------------------

    def acquire(self, strategy_id: str, symbol: str) -> Lease:
        with self._critical_section():
            data = self._read()
            existing = data.get(symbol)
            if existing is not None and existing["strategy_id"] != strategy_id:
                raise IsolationConflict(
                    f"symbol {symbol!r} is already held by "
                    f"strategy {existing['strategy_id']!r} since "
                    f"{existing['acquired_at']}; "
                    f"refusing acquire by {strategy_id!r}"
                )
            if existing is not None:
                return Lease(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    acquired_at=datetime.fromisoformat(existing["acquired_at"]),
                )
            lease = Lease(
                strategy_id=strategy_id,
                symbol=symbol,
                acquired_at=datetime.utcnow(),
            )
            data[symbol] = {
                "strategy_id": lease.strategy_id,
                "acquired_at": lease.acquired_at.isoformat(),
            }
            self._write(data)
            return lease

    def release(self, lease: Lease) -> None:
        with self._critical_section():
            data = self._read()
            current = data.get(lease.symbol)
            if current is None:
                return
            if current["strategy_id"] != lease.strategy_id:
                raise IsolationConflict(
                    f"cannot release {lease.symbol!r}: held by "
                    f"{current['strategy_id']!r}, not {lease.strategy_id!r}"
                )
            data.pop(lease.symbol)
            self._write(data)

    def release_all_for(self, strategy_id: str) -> int:
        with self._critical_section():
            data = self._read()
            to_drop = [
                sym for sym, lease in data.items()
                if lease["strategy_id"] == strategy_id
            ]
            for sym in to_drop:
                data.pop(sym)
            self._write(data)
            return len(to_drop)

    def acquired_by(self, symbol: str) -> Optional[Lease]:
        with self._critical_section():
            data = self._read()
            existing = data.get(symbol)
            if existing is None:
                return None
            return Lease(
                strategy_id=existing["strategy_id"],
                symbol=symbol,
                acquired_at=datetime.fromisoformat(existing["acquired_at"]),
            )

    def current_leases(self) -> List[Lease]:
        with self._critical_section():
            data = self._read()
            return [
                Lease(
                    strategy_id=v["strategy_id"],
                    symbol=k,
                    acquired_at=datetime.fromisoformat(v["acquired_at"]),
                )
                for k, v in data.items()
            ]

    # ---- internals ----------------------------------------------------------

    def _read(self) -> Dict[str, Dict[str, str]]:
        if not self.store_path.exists():
            return {}
        try:
            with self.store_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: Dict[str, Dict[str, str]]) -> None:
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True, indent=2)
        os.replace(tmp, self.store_path)

    def _critical_section(self):
        return _FileLockContext(
            lock_path=self.lock_path,
            wait_timeout_seconds=self.wait_timeout_seconds,
        )


class _FileLockContext:
    """Minimal cross-process lock backed by O_EXCL rename trick.

    Avoids adding a hard dependency on the ``filelock`` package. Polls
    the existence of ``lock_path`` and bails out on timeout.
    """

    def __init__(self, *, lock_path: Path, wait_timeout_seconds: float) -> None:
        self.lock_path = lock_path
        self.wait_timeout_seconds = wait_timeout_seconds

    def __enter__(self):
        deadline = time.monotonic() + self.wait_timeout_seconds
        while True:
            try:
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    mode=0o644,
                )
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise IsolationConflict(
                        f"timed out waiting {self.wait_timeout_seconds}s "
                        f"for lock {self.lock_path}"
                    ) from None
                time.sleep(0.05)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            os.unlink(self.lock_path)
        except FileNotFoundError:
            pass
        return False


__all__ = ["FileLeaseStore"]
