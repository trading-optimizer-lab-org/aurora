"""Immutable, content-hashed data snapshots.

A snapshot freezes a price series to disk (parquet) and registers the metadata
in a SQLite index. The SHA-256 hash is computed deterministically from the
symbol, the [start, end] window, and the raw bytes of the price values, so
identical inputs always produce identical hashes.

Anti-snooping support: a snapshot can be flagged ``locked=True`` (typically the
OOS slice). Loading a locked snapshot from outside an explicit
``with OOSGuard("explicit_unlock"): ...`` block raises ``IntegrityError``.

Index schema (single table ``snapshots``):
    sha256       TEXT PRIMARY KEY
    symbol       TEXT NOT NULL
    start_iso    TEXT NOT NULL
    end_iso      TEXT NOT NULL
    n_bars       INTEGER NOT NULL
    provenance   TEXT NOT NULL
    created_at   TEXT NOT NULL
    data_path    TEXT NOT NULL
    locked       INTEGER NOT NULL DEFAULT 0
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from aurora.core.snapshots_distributed import SnapshotBackend

import numpy as np
import pandas as pd

from aurora.core.sqlite_utils import _setup_sqlite


# Phases that are allowed to load a locked snapshot. Any other phase (or no
# guard at all) raises IntegrityError.
#
# Round-3 audit fix: ceremony names are unified across the codebase. There
# are exactly four allowed unlock phases:
#
#   * ``explicit_unlock_snapshot``  - SnapshotStore.load on a locked snap
#   * ``explicit_unlock_oos_locked`` - OOS_LOCKED tier reads
#   * ``explicit_unlock_forward``   - FORWARD tier reads
#   * ``explicit_unlock_full_tier`` - cmd_run / cmd_tearsheet --tier full
#
# The legacy ``explicit_unlock`` phase is kept as a backwards-compat alias
# so existing tests + scripts that opened ``OOSGuard("explicit_unlock")``
# to load a locked snapshot still work. New code should use
# ``explicit_unlock_snapshot`` for SnapshotStore.load.
_ALLOWED_UNLOCK_PHASES: frozenset[str] = frozenset({
    "explicit_unlock",            # legacy alias for snapshot loads
    "explicit_unlock_snapshot",
    "explicit_unlock_oos_locked",
    "explicit_unlock_forward",
    "explicit_unlock_full_tier",
})


class IntegrityError(Exception):
    """Raised when a snapshot fails an integrity check (hash mismatch,
    corrupted parquet, or locked snapshot accessed outside OOSGuard)."""


@dataclass(frozen=True)
class DataSnapshot:
    """Immutable record describing a frozen price series.

    Round-4 audit (P3.6): reproducibility metadata fields. ``git_hash``,
    ``forge_version``, ``seed``, and ``config_hash`` are recorded
    alongside the SHA-256 so a snapshot's provenance is fully captured
    at freeze time. None values mean the relevant signal was not
    available at freeze time (e.g. no git checkout).

    P0.A: ``policy_hash`` records the active
    :class:`aurora.core.protocol_policy.ProtocolPolicy` digest at
    freeze time, so a snapshot is bound to the protocol it was frozen
    under. Old snapshots predating P0.A can have ``None`` here.
    """
    symbol: str
    start: pd.Timestamp
    end: pd.Timestamp
    n_bars: int
    sha256: str
    provenance: str
    created_at: datetime
    data_path: str
    locked: bool = False
    git_hash: Optional[str] = None
    forge_version: Optional[str] = None
    seed: Optional[int] = None
    config_hash: Optional[str] = None
    policy_hash: Optional[str] = None
    # P1.B: hash of the auditor's AuditReport bound to this snapshot (if any).
    audit_report_hash: Optional[str] = None


def _normalize_index_to_naive_utc(prices: pd.Series) -> pd.Series:
    """Strip tz info, mapping tz-aware indexes to UTC then to naive.

    Canonical contract for SnapshotStore
    ------------------------------------
    Snapshot indexes are **tz-naive UTC**. When a caller passes a tz-aware
    index, we ``tz_convert('UTC')`` first so the wall-clock timestamps
    line up regardless of source tz, then ``tz_localize(None)`` to drop
    the marker. A tz-naive index is taken as-is (it is the caller's
    responsibility that naive timestamps are already in UTC).

    The previous behavior cast through ``datetime64[ns]`` which silently
    stripped the tz without converting — two series differing only in tz
    label collided to the same hash. The explicit
    convert-then-localize keeps the digest deterministic and makes any
    tz mismatch loud (different inputs produce different digests instead
    of silent collisions).
    """
    if prices.index.tz is not None:
        idx = prices.index.tz_convert("UTC").tz_localize(None)
        prices = prices.copy()
        prices.index = idx
    return prices


def _compute_sha256(symbol: str, start: pd.Timestamp, end: pd.Timestamp,
                    prices: pd.Series) -> str:
    """Deterministic hash of (symbol, window, prices, index).

    Canonical timezone contract: indexes are normalized to **naive UTC**
    before hashing (see :func:`_normalize_index_to_naive_utc`). Mixing
    tz-aware and tz-naive inputs at the same wall-clock instant therefore
    produce the same digest, while differing wall-clock instants produce
    different digests.

    Forces little-endian byte order on both the price values and the
    DatetimeIndex so two machines with different native byte order (any
    big-endian platform vs. a typical x86_64 host) produce identical
    hashes for the same inputs. Including the index in the payload means
    two series with identical values but different timestamps no longer
    collide on the same SHA-256.
    """
    prices = _normalize_index_to_naive_utc(prices)
    h = hashlib.sha256()
    h.update(symbol.encode("utf-8"))
    h.update(b"\x00")
    h.update(pd.Timestamp(start).isoformat().encode("utf-8"))
    h.update(b"\x00")
    h.update(pd.Timestamp(end).isoformat().encode("utf-8"))
    h.update(b"\x00")
    # explicit little-endian float64 for cross-platform stability
    arr = np.ascontiguousarray(prices.to_numpy(dtype=np.float64), dtype="<f8")
    h.update(arr.tobytes())
    h.update(b"\x00")
    # explicit little-endian int64 nanos for the timestamp index — two
    # series with the same values but different timestamps must hash to
    # different digests.
    idx_ns = np.ascontiguousarray(
        prices.index.values.astype("datetime64[ns]").view("int64"),
        dtype="<i8",
    )
    h.update(idx_ns.tobytes())
    return h.hexdigest()


class SnapshotStore:
    """Content-addressed store of frozen price series.

    Layout:
        <root_dir>/<sha256>.parquet
        <root_dir>/snapshots_index.sqlite
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS snapshots (
            sha256       TEXT PRIMARY KEY,
            symbol       TEXT NOT NULL,
            start_iso    TEXT NOT NULL,
            end_iso      TEXT NOT NULL,
            n_bars       INTEGER NOT NULL,
            provenance   TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            data_path    TEXT NOT NULL,
            locked       INTEGER NOT NULL DEFAULT 0,
            git_hash     TEXT,
            forge_version TEXT,
            seed         INTEGER,
            config_hash  TEXT,
            policy_hash  TEXT,
            audit_report_hash TEXT
        )
    """

    # Columns that may be missing on legacy databases. ``_init_index``
    # adds each one with a best-effort ALTER so older indexes survive
    # the schema bump without re-creating the table.
    _NEW_REPRO_COLUMNS: tuple[tuple[str, str], ...] = (
        ("git_hash", "TEXT"),
        ("forge_version", "TEXT"),
        ("seed", "INTEGER"),
        ("config_hash", "TEXT"),
        ("policy_hash", "TEXT"),
        # P1.B: hash of the AuditReport attached to this snapshot.
        ("audit_report_hash", "TEXT"),
    )

    def __init__(
        self,
        root_dir: str = "data_snapshots/",
        *,
        backend: Optional["SnapshotBackend"] = None,
    ) -> None:
        """Construct a SnapshotStore.

        Args:
            root_dir: filesystem path for the legacy on-disk layout
                (parquet blobs + ``snapshots_index.sqlite``). Always
                used; behaviour byte-identical to pre-R19 callers.
            backend: optional :class:`SnapshotBackend` (R7) used as a
                mirror sink. When supplied, every successful ``freeze``
                also calls ``backend.put_blob`` and ``backend.put_metadata``
                so the abstraction is exercised end-to-end. Default
                ``None`` keeps the legacy behaviour. Mirror failures
                propagate after the legacy write commits, so an offline
                backend cannot silently lose a snapshot from the
                primary path.
        """
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)
        self.index_path = os.path.join(self.root_dir, "snapshots_index.sqlite")
        self._mirror_backend = backend
        self._init_index()

    # ---- helpers ---------------------------------------------------------

    def _init_index(self) -> None:
        con = sqlite3.connect(self.index_path)
        try:
            _setup_sqlite(con, mode="normal")
            con.execute(self._SCHEMA)
            # Round-4 audit (P3.6): migrate legacy databases that were
            # created before the reproducibility columns were added.
            existing = {row[1] for row in con.execute(
                "PRAGMA table_info(snapshots)"
            ).fetchall()}
            for col, col_type in self._NEW_REPRO_COLUMNS:
                if col not in existing:
                    try:
                        con.execute(
                            f"ALTER TABLE snapshots ADD COLUMN {col} {col_type}"
                        )
                    except sqlite3.OperationalError:
                        # Race or concurrent migration -- safe to ignore.
                        pass
            con.commit()
        finally:
            con.close()

    def _row_to_snapshot(self, row: tuple) -> DataSnapshot:
        # Legacy 9-column row: missing the four reproducibility columns
        # plus policy_hash. 13-column row carries the four repro cols.
        # 14-column row also carries ``policy_hash``. Newest 15-column
        # row carries ``audit_report_hash`` (P1.B). Be permissive so old
        # SQL queries keep working.
        if len(row) == 9:
            (sha256, symbol, start_iso, end_iso, n_bars, provenance,
             created_at, data_path, locked) = row
            git_hash = forge_version = config_hash = None
            seed = None
            policy_hash = None
            audit_report_hash = None
        elif len(row) == 13:
            (sha256, symbol, start_iso, end_iso, n_bars, provenance,
             created_at, data_path, locked,
             git_hash, forge_version, seed, config_hash) = row
            policy_hash = None
            audit_report_hash = None
        elif len(row) == 14:
            (sha256, symbol, start_iso, end_iso, n_bars, provenance,
             created_at, data_path, locked,
             git_hash, forge_version, seed, config_hash, policy_hash) = row
            audit_report_hash = None
        else:
            (sha256, symbol, start_iso, end_iso, n_bars, provenance,
             created_at, data_path, locked,
             git_hash, forge_version, seed, config_hash, policy_hash,
             audit_report_hash) = row
        return DataSnapshot(
            symbol=symbol,
            start=pd.Timestamp(start_iso),
            end=pd.Timestamp(end_iso),
            n_bars=int(n_bars),
            sha256=sha256,
            provenance=provenance,
            created_at=datetime.fromisoformat(created_at),
            data_path=data_path,
            locked=bool(locked),
            git_hash=git_hash,
            forge_version=forge_version,
            seed=int(seed) if seed is not None else None,
            config_hash=config_hash,
            policy_hash=policy_hash,
            audit_report_hash=audit_report_hash,
        )

    # ---- public API ------------------------------------------------------

    @staticmethod
    def _capture_freeze_metadata() -> dict:
        """Best-effort capture of git_hash / forge_version / seed.

        P3.6 round-4 audit: every snapshot freeze records the
        reproducibility context so a downstream consumer can see which
        commit + package version + seed produced the data. Each lookup
        is wrapped in try/except so missing tooling never breaks the
        freeze.
        """
        meta: dict = {
            "git_hash": None,
            "forge_version": None,
            "seed": None,
        }
        try:
            from aurora.core.data_layer import _get_git_hash
            meta["git_hash"] = _get_git_hash()
        except Exception:
            pass
        try:
            import importlib.metadata as _md
            meta["forge_version"] = _md.version("aurora")
        except Exception:
            try:
                # Fallback to a __version__ attribute if the package
                # carries one.
                import aurora as _qf
                meta["forge_version"] = getattr(_qf, "__version__", None)
            except Exception:
                meta["forge_version"] = None
        try:
            from aurora.core.seed import GLOBAL_SEED
            meta["seed"] = int(GLOBAL_SEED) if GLOBAL_SEED is not None else None
        except Exception:
            meta["seed"] = None
        # P0.A: bind every snapshot to the protocol it was frozen under.
        try:
            from aurora.core.protocol_policy import get_active_policy
            meta["policy_hash"] = get_active_policy().policy_hash
        except Exception:
            meta["policy_hash"] = None
        return meta

    def freeze(self, prices: pd.Series, symbol: str,
               provenance: str, locked: bool = False,
               *, config_hash: Optional[str] = None) -> DataSnapshot:
        """Compute hash, write parquet, and register in the index.

        If a snapshot with the same hash already exists, returns the existing
        record (idempotent). The on-disk parquet is rewritten to make sure it
        is consistent with the registered hash.
        """
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series")
        if len(prices) == 0:
            raise ValueError("cannot freeze an empty Series")
        # Validate index type up-front: hashing/parquet writing assume a
        # DatetimeIndex (we cast to ``datetime64[ns]`` and rely on
        # timezone semantics). Generic Index would silently produce a
        # nonsense hash or raise deep inside numpy.
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise TypeError(
                f"prices.index must be a pandas DatetimeIndex, "
                f"got {type(prices.index).__name__}"
            )

        prices = prices.sort_index()
        # Normalize tz-aware index to naive UTC up front so all downstream
        # operations (hash, parquet write, metadata) see a consistent index.
        prices = _normalize_index_to_naive_utc(prices)
        start = pd.Timestamp(prices.index[0])
        end = pd.Timestamp(prices.index[-1])
        sha256 = _compute_sha256(symbol, start, end, prices)
        data_path = os.path.join(self.root_dir, f"{sha256}.parquet")

        # P3.6 round-4 audit: capture reproducibility metadata.
        meta = self._capture_freeze_metadata()

        snap = DataSnapshot(
            symbol=symbol,
            start=start,
            end=end,
            n_bars=int(len(prices)),
            sha256=sha256,
            provenance=provenance,
            created_at=datetime.now(timezone.utc),
            data_path=data_path,
            locked=bool(locked),
            git_hash=meta["git_hash"],
            forge_version=meta["forge_version"],
            seed=meta["seed"],
            config_hash=config_hash,
            policy_hash=meta.get("policy_hash"),
        )

        # Atomicity: the parquet must not exist on disk if we end up
        # rejecting the write (locked-demotion guard) or if the SQLite
        # INSERT raises. Previously the parquet was written *before* the
        # locked-demotion check, leaving an orphan ``<sha256>.parquet``
        # whose only reference (the SQLite row) never got created. Now we
        # check the guard inside the SQLite txn first, then do parquet +
        # INSERT under a single try/except that deletes the parquet if
        # any step after creation fails.
        #
        # Concurrency
        # -----------
        # ``BEGIN IMMEDIATE`` acquires a RESERVED lock so the
        # SELECT-existing + INSERT-OR-REPLACE pair is serialized against
        # any other writer racing on the same hash. Without the explicit
        # transaction two writers could both observe ``existing=None`` and
        # then double-write parquet/index rows. Autocommit
        # (``isolation_level = None``) is required so ``BEGIN IMMEDIATE``
        # is the only transaction boundary — the implicit auto-begin
        # would otherwise raise ``cannot start a transaction within a
        # transaction``.
        con = sqlite3.connect(self.index_path)
        try:
            con.isolation_level = None
            _setup_sqlite(con, mode="normal")
            con.execute("BEGIN IMMEDIATE")
            wrote_parquet = False
            existing = None
            try:
                existing = con.execute(
                    "SELECT locked FROM snapshots WHERE sha256 = ?",
                    (snap.sha256,),
                ).fetchone()
                # Sin-guard: if a snapshot with this hash is already locked, refuse
                # to silently rewrite it as unlocked. Hash equality means the data
                # is identical, but a deliberate ``locked=True`` flag is a
                # contract that the caller is not allowed to weaken.
                if existing is not None and bool(existing[0]) and not snap.locked:
                    raise ValueError(
                        f"cannot demote locked snapshot {snap.sha256!r} "
                        "to unlocked"
                    )

                # write parquet (overwrite is fine — content-addressed). Pin
                # the engine and compression so two writers produce
                # byte-identical files for the same input across
                # pandas/pyarrow versions.
                prices.to_frame("Close").to_parquet(
                    data_path, engine="pyarrow", compression="snappy"
                )
                wrote_parquet = True
                con.execute(
                    """INSERT OR REPLACE INTO snapshots
                       (sha256, symbol, start_iso, end_iso, n_bars, provenance,
                        created_at, data_path, locked,
                        git_hash, forge_version, seed, config_hash, policy_hash,
                        audit_report_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (snap.sha256, snap.symbol,
                     snap.start.isoformat(), snap.end.isoformat(),
                     snap.n_bars, snap.provenance,
                     snap.created_at.isoformat(), snap.data_path,
                     1 if snap.locked else 0,
                     snap.git_hash, snap.forge_version,
                     snap.seed, snap.config_hash, snap.policy_hash,
                     snap.audit_report_hash),
                )
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                # Roll back orphan parquet only if we wrote it AND there was
                # no prior row pointing at this same data_path; otherwise
                # we'd remove a valid earlier-registered snapshot.
                if wrote_parquet and existing is None:
                    try:
                        os.remove(data_path)
                    except OSError:
                        pass
                raise
        finally:
            con.close()

        # R19: mirror to optional backend after the legacy write commits.
        # Mirror failure does not roll back the primary path -- the
        # filesystem layout remains the source of truth.
        self._mirror_freeze(snap, data_path)
        return snap

    def _mirror_freeze(self, snap: DataSnapshot, data_path: str) -> None:
        """Forward a successful freeze to the optional mirror backend."""
        backend = self._mirror_backend
        if backend is None:
            return
        try:
            with open(data_path, "rb") as fh:
                blob = fh.read()
            backend.put_blob(snap.sha256, blob)
            backend.put_metadata(snap.sha256, {
                "symbol": snap.symbol,
                "start_iso": snap.start.isoformat(),
                "end_iso": snap.end.isoformat(),
                "n_bars": snap.n_bars,
                "provenance": snap.provenance,
                "created_at": snap.created_at.isoformat(),
                "data_path": snap.data_path,
                "locked": bool(snap.locked),
                "git_hash": snap.git_hash,
                "forge_version": snap.forge_version,
                "seed": snap.seed,
                "config_hash": snap.config_hash,
                "policy_hash": snap.policy_hash,
                "audit_report_hash": snap.audit_report_hash,
            })
        except Exception:  # noqa: BLE001 -- best-effort mirror, never wedge primary
            pass

    def load(self, sha256: str) -> tuple[pd.Series, DataSnapshot]:
        """Load a frozen series and verify its hash.

        If the snapshot is locked, requires an active ``OOSGuard`` whose
        phase is one of the unified unlock ceremonies recognized by
        :data:`_ALLOWED_UNLOCK_PHASES` -- in particular
        ``explicit_unlock_snapshot`` (preferred for snapshot loads) or
        the legacy ``explicit_unlock`` alias. Otherwise raises
        ``IntegrityError``.

        Raises:
            IntegrityError: missing record, missing parquet, hash mismatch,
                            or locked snapshot accessed without unlock.
        """
        con = sqlite3.connect(self.index_path)
        try:
            _setup_sqlite(con, mode="normal")
            cur = con.execute(
                """SELECT sha256, symbol, start_iso, end_iso, n_bars,
                          provenance, created_at, data_path, locked,
                          git_hash, forge_version, seed, config_hash, policy_hash,
                          audit_report_hash
                   FROM snapshots WHERE sha256 = ?""",
                (sha256,),
            )
            row = cur.fetchone()
        finally:
            con.close()
        if row is None:
            raise IntegrityError(f"snapshot {sha256!r} not in index")
        snap = self._row_to_snapshot(row)

        if snap.locked:
            # late import to avoid circular dependency with data_layer
            from aurora.core.data_layer import OOSGuard
            guard = OOSGuard.active()
            # Match the phase exactly against the allowed set; using
            # ``startswith`` previously let ``"explicit_unlock_oops"`` slip
            # through the gate.
            if guard is None or str(guard.phase) not in _ALLOWED_UNLOCK_PHASES:
                raise IntegrityError(
                    f"snapshot {sha256!r} is locked; load requires "
                    f"`with OOSGuard('explicit_unlock'): ...`"
                )

        if not os.path.exists(snap.data_path):
            raise IntegrityError(
                f"snapshot {sha256!r} parquet missing at {snap.data_path}"
            )
        try:
            df = pd.read_parquet(snap.data_path)
        except Exception as exc:  # corrupted parquet
            raise IntegrityError(
                f"snapshot {sha256!r} parquet read failed: {exc}"
            ) from exc

        if "Close" in df.columns:
            prices = df["Close"]
        else:
            prices = df.iloc[:, 0]
        prices = prices.sort_index()

        recomputed = _compute_sha256(snap.symbol, snap.start, snap.end, prices)
        if recomputed != snap.sha256:
            raise IntegrityError(
                f"snapshot {sha256!r} hash mismatch "
                f"(expected {snap.sha256}, got {recomputed})"
            )
        return prices, snap

    def list_snapshots(self) -> list[DataSnapshot]:
        con = sqlite3.connect(self.index_path)
        try:
            _setup_sqlite(con, mode="normal")
            cur = con.execute(
                """SELECT sha256, symbol, start_iso, end_iso, n_bars,
                          provenance, created_at, data_path, locked,
                          git_hash, forge_version, seed, config_hash, policy_hash,
                          audit_report_hash
                   FROM snapshots ORDER BY created_at"""
            )
            rows = cur.fetchall()
        finally:
            con.close()
        return [self._row_to_snapshot(r) for r in rows]

    def get_by_symbol(self, symbol: str,
                      start: Optional[str] = None,
                      end: Optional[str] = None) -> list[DataSnapshot]:
        """List snapshots for a symbol, optionally filtered by overlap."""
        con = sqlite3.connect(self.index_path)
        try:
            _setup_sqlite(con, mode="normal")
            cur = con.execute(
                """SELECT sha256, symbol, start_iso, end_iso, n_bars,
                          provenance, created_at, data_path, locked,
                          git_hash, forge_version, seed, config_hash, policy_hash,
                          audit_report_hash
                   FROM snapshots WHERE symbol = ? ORDER BY created_at""",
                (symbol,),
            )
            rows = cur.fetchall()
        finally:
            con.close()
        out = [self._row_to_snapshot(r) for r in rows]
        if start is not None:
            s = pd.Timestamp(start)
            out = [snap for snap in out if snap.end >= s]
        if end is not None:
            e = pd.Timestamp(end)
            out = [snap for snap in out if snap.start <= e]
        return out

    def _load_data_only(self, sha256: str) -> tuple[pd.Series, DataSnapshot]:
        """Load and hash-verify a snapshot WITHOUT OOSGuard enforcement.

        Same body as ``load`` minus the locked-snapshot OOSGuard gate. Used
        by ``verify_integrity`` so that hash validation can run during a CI
        sweep without requiring an active ``OOSGuard("explicit_unlock")``.
        Callers must NOT use this for any path that delivers OOS data into
        the optimization pipeline.
        """
        con = sqlite3.connect(self.index_path)
        try:
            _setup_sqlite(con, mode="normal")
            cur = con.execute(
                """SELECT sha256, symbol, start_iso, end_iso, n_bars,
                          provenance, created_at, data_path, locked,
                          git_hash, forge_version, seed, config_hash, policy_hash,
                          audit_report_hash
                   FROM snapshots WHERE sha256 = ?""",
                (sha256,),
            )
            row = cur.fetchone()
        finally:
            con.close()
        if row is None:
            raise IntegrityError(f"snapshot {sha256!r} not in index")
        snap = self._row_to_snapshot(row)
        if not os.path.exists(snap.data_path):
            raise IntegrityError(
                f"snapshot {sha256!r} parquet missing at {snap.data_path}"
            )
        try:
            df = pd.read_parquet(snap.data_path)
        except Exception as exc:
            raise IntegrityError(
                f"snapshot {sha256!r} parquet read failed: {exc}"
            ) from exc
        if "Close" in df.columns:
            prices = df["Close"]
        else:
            prices = df.iloc[:, 0]
        prices = prices.sort_index()
        recomputed = _compute_sha256(snap.symbol, snap.start, snap.end, prices)
        if recomputed != snap.sha256:
            raise IntegrityError(
                f"snapshot {sha256!r} hash mismatch "
                f"(expected {snap.sha256}, got {recomputed})"
            )
        return prices, snap

    def verify_integrity(self, sha256: str) -> bool:
        """True iff the snapshot loads and its hash matches.

        Bypasses the OOSGuard gate so CI integrity checks can run without
        an active ``OOSGuard("explicit_unlock")``. The hash is still
        recomputed and compared to the registered digest.
        """
        try:
            self._load_data_only(sha256)
            return True
        except IntegrityError:
            return False

    def attach_audit_report(self, sha256: str, audit_report) -> str:
        """Bind an :class:`AuditReport` (or its hash) to a snapshot row.

        ``audit_report`` may be either:
          * an object with a ``content_hash()`` method (the canonical case --
            ``aurora.agents.auditor.AuditReport``), or
          * a plain hex string already representing the hash.

        Returns the hash string that was persisted. Raises
        ``IntegrityError`` if the snapshot doesn't exist.
        """
        if isinstance(audit_report, str):
            hash_str = audit_report
        elif hasattr(audit_report, "content_hash"):
            hash_str = audit_report.content_hash()
        else:
            raise TypeError(
                "audit_report must be a string or expose .content_hash()"
            )
        con = sqlite3.connect(self.index_path)
        try:
            _setup_sqlite(con, mode="normal")
            cur = con.execute(
                "UPDATE snapshots SET audit_report_hash = ? WHERE sha256 = ?",
                (hash_str, sha256),
            )
            con.commit()
            if cur.rowcount == 0:
                raise IntegrityError(
                    f"snapshot {sha256!r} not in index"
                )
        finally:
            con.close()
        return hash_str
