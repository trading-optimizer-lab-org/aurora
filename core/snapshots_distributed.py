"""Distributed snapshot backend interface (R7).

Today :class:`quantforge.core.snapshots.SnapshotStore` persists its parquet
blobs and sqlite index on the local filesystem. That is fine for one
machine. For a team, replicas, or production data provenance, a remote
or shared backend is needed.

This module introduces the *backend interface* and a working
``LocalSnapshotBackend`` reference implementation. Remote backends
(PostgreSQL metadata, S3-compatible object storage, ...) plug in by
implementing :class:`SnapshotBackend`.

Design contract
---------------

* The interface deliberately stays narrow: ``put_blob``, ``get_blob``,
  ``put_metadata``, ``get_metadata``, ``list_metadata``, ``exists``.
  These are the operations :class:`SnapshotStore` actually needs. Tier
  rules and policy-hash binding stay in :mod:`core.snapshots`; backends
  carry bytes and rows, not policy.
* ``content_addressed=True`` for blobs: keys are sha256 hex digests so
  any backend trivially deduplicates.
* Every backend MUST preserve sha256 and policy_hash semantics. A
  blob written and read back must be byte-identical; a metadata row
  inserted and read back must round-trip its ``policy_hash`` field.
* ``local`` remains the default backend in any path that does not
  explicitly opt in to a remote backend. No SQLite database is moved
  off-disk silently.

Remote backends are intentionally NOT implemented in this module --
they require credentials, infra, and integration tests against real
S3 / Postgres. This is the contract; concrete drivers ship in their
own modules and gate behind extras.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger("quantforge.core.snapshots_distributed")


# ===========================================================================
# Interface
# ===========================================================================


class SnapshotBackend(ABC):
    """Storage backend for the SnapshotStore.

    Implementations are responsible for byte storage of the parquet blob
    and row storage for the snapshot metadata. Hashing, content
    addressing, and policy binding remain the SnapshotStore's
    responsibility -- the backend only carries bytes faithfully.
    """

    name: str = "abstract"

    # ---- blob byte storage -----------------------------------------------

    @abstractmethod
    def put_blob(self, key: str, data: bytes) -> None:
        """Persist a content-addressed blob. ``key`` is a sha256 hex digest."""
        raise NotImplementedError

    @abstractmethod
    def get_blob(self, key: str) -> bytes:
        """Return the bytes previously stored under ``key``.

        Raises ``KeyError`` if the blob is missing.
        """
        raise NotImplementedError

    @abstractmethod
    def has_blob(self, key: str) -> bool:
        """Cheap existence check without reading the blob."""
        raise NotImplementedError

    # ---- metadata storage ------------------------------------------------

    @abstractmethod
    def put_metadata(self, key: str, payload: Mapping[str, Any]) -> None:
        """Persist a metadata row keyed by sha256 ``key``.

        Implementations may serialize as JSON, INSERT into a SQL row,
        write a Postgres column, etc. Round-trip via :meth:`get_metadata`
        must preserve every key in ``payload``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_metadata(self, key: str) -> Mapping[str, Any]:
        """Return the metadata previously stored under ``key``.

        Raises ``KeyError`` if the row is missing.
        """
        raise NotImplementedError

    @abstractmethod
    def list_metadata(self) -> list[Mapping[str, Any]]:
        """Return every metadata row in insertion order."""
        raise NotImplementedError

    # ---- integrity -------------------------------------------------------

    def verify(self, key: str) -> bool:
        """Re-hash the blob under ``key`` and compare to ``key`` itself.

        Default implementation reads the blob, hashes it, and compares.
        Backends with native checksum support can override.
        """
        import hashlib

        try:
            data = self.get_blob(key)
        except KeyError:
            return False
        return hashlib.sha256(data).hexdigest() == key


# ===========================================================================
# Local reference implementation
# ===========================================================================


@dataclass
class LocalSnapshotBackend(SnapshotBackend):
    """Filesystem + sidecar JSON metadata.

    Layout::

        <root>/blobs/<sha256>.parquet
        <root>/meta/<sha256>.json

    Suitable for single-machine setups. Used as the default backend by
    higher-level callers; remote backends should match its semantics.
    """

    root_dir: Path
    name: str = "local"

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)
        (self.root_dir / "blobs").mkdir(parents=True, exist_ok=True)
        (self.root_dir / "meta").mkdir(parents=True, exist_ok=True)

    # ---- blob ------------------------------------------------------------

    def _blob_path(self, key: str) -> Path:
        return self.root_dir / "blobs" / f"{key}.parquet"

    def put_blob(self, key: str, data: bytes) -> None:
        self._blob_path(key).write_bytes(data)

    def get_blob(self, key: str) -> bytes:
        p = self._blob_path(key)
        if not p.exists():
            raise KeyError(key)
        return p.read_bytes()

    def has_blob(self, key: str) -> bool:
        return self._blob_path(key).exists()

    # ---- metadata --------------------------------------------------------

    def _meta_path(self, key: str) -> Path:
        return self.root_dir / "meta" / f"{key}.json"

    def put_metadata(self, key: str, payload: Mapping[str, Any]) -> None:
        self._meta_path(key).write_text(
            json.dumps(dict(payload), sort_keys=True, default=str),
            encoding="utf-8",
        )

    def get_metadata(self, key: str) -> Mapping[str, Any]:
        p = self._meta_path(key)
        if not p.exists():
            raise KeyError(key)
        return json.loads(p.read_text(encoding="utf-8"))

    def list_metadata(self) -> list[Mapping[str, Any]]:
        out: list[Mapping[str, Any]] = []
        meta_dir = self.root_dir / "meta"
        for p in sorted(meta_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except json.JSONDecodeError as exc:
                _log.warning("skipping malformed meta file %s: %s", p, exc)
        return out


# ===========================================================================
# Backend factory
# ===========================================================================


def make_backend(
    kind: str = "local",
    *,
    root_dir: Path | None = None,
    **kwargs: Any,
) -> SnapshotBackend:
    """Return a :class:`SnapshotBackend` of the requested kind.

    Currently supported kinds:

    - ``"local"``: :class:`LocalSnapshotBackend`. Requires ``root_dir``.

    Remote kinds (``"s3"``, ``"postgres"``) are reserved names. Calling
    this factory with one of them raises :class:`NotImplementedError`
    rather than silently falling back to local, so misconfigured
    deployments fail loud.
    """
    if kind == "local":
        if root_dir is None:
            raise ValueError("local backend requires root_dir")
        return LocalSnapshotBackend(root_dir=Path(root_dir))
    if kind in {"s3", "postgres", "gcs", "azure_blob"}:
        raise NotImplementedError(
            f"backend '{kind}' is reserved but not yet implemented; ship "
            "its driver in a separate module before requesting it"
        )
    raise ValueError(f"unknown backend kind: {kind!r}")


__all__ = [
    "SnapshotBackend",
    "LocalSnapshotBackend",
    "make_backend",
]
