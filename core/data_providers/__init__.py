"""Versioned, point-in-time-aware DataProviderRegistry (P0.B).

Centralizes data sourcing across QuantForge. Every dataset returned by the
registry carries provenance metadata (``DatasetMetadata``): source, version,
asof_date, content_hash, point_in_time flag, and tier_permission. The
registry's ``fetch`` integrates with :class:`~aurora.core.data_layer.OOSGuard`
so a provider that is not point-in-time cannot deliver data into a locked
OOS / FORWARD ceremony unless the caller has performed the explicit unlock.

Inspired by OpenBB's provider pattern + qlib's calendar/PIT discipline.

Public API
----------
* :class:`DatasetMetadata` -- frozen dataclass stamped on every fetch.
* :class:`Dataset` -- ``(metadata, data)`` pair.
* :class:`DataProvider` -- :class:`typing.Protocol` for adapters.
* :class:`DataProviderRegistry` -- registers providers, gates by tier.
* :func:`compute_content_hash` -- deterministic sha256 of a frame/series.
* :func:`get_default_registry` -- module-level singleton.
* :exc:`ProviderUnavailable`, :exc:`ProviderNotRegistered`,
  :exc:`TierPermissionError` -- error types.

Built-in providers (re-exported for convenience): :mod:`.yahoo`,
:mod:`.snapshot`, :mod:`.csv`, :mod:`.openbb`, :mod:`.synthetic`.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Literal, Optional, Protocol, Tuple, Union, runtime_checkable

import numpy as np
import pandas as pd

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider role policy (R155 -- free bulk daily market-data programme)
# ---------------------------------------------------------------------------


class ProviderRole(str, Enum):
    """Functional role a provider fills in the data programme.

    Roles are explicit so the registry can answer questions like "give me
    the universe sources" or "which provider is the price primary" without
    hard-coding provider names.
    """

    UNIVERSE = "UNIVERSE"
    PRICE_PRIMARY = "PRICE_PRIMARY"
    PRICE_FALLBACK = "PRICE_FALLBACK"
    CRYPTO_PRIMARY = "CRYPTO_PRIMARY"
    CRYPTO_METADATA = "CRYPTO_METADATA"
    CRYPTO_MULTI = "CRYPTO_MULTI"
    MACRO = "MACRO"
    EXPERIMENTAL = "EXPERIMENTAL"
    # R156 complementary provider roles
    IDENTITY_MAPPING = "IDENTITY_MAPPING"
    FUNDAMENTALS = "FUNDAMENTALS"
    MACRO_MULTI_SOURCE = "MACRO_MULTI_SOURCE"
    CRYPTO_METRICS = "CRYPTO_METRICS"
    FX_REFERENCE = "FX_REFERENCE"
    OPTIONAL_PRICE_FALLBACK = "OPTIONAL_PRICE_FALLBACK"
    FX_TICK_RESEARCH = "FX_TICK_RESEARCH"
    OPTIONS_LIMITED = "OPTIONS_LIMITED"


ReliabilityLiteral = Literal["OFFICIAL", "COMMUNITY", "EXPERIMENTAL"]
AdjustmentLiteral = Literal["ADJUSTED", "RAW", "MIXED"]


@dataclass(frozen=True)
class ProviderDescriptor:
    """Static metadata describing a provider's role and licensing terms."""

    name: str
    role: ProviderRole
    licence_terms_url: str
    rate_limits: str
    auth_required: bool
    asset_classes: Tuple[str, ...]
    intervals: Tuple[str, ...]
    adjustment_posture: AdjustmentLiteral
    reliability: ReliabilityLiteral

    def __post_init__(self) -> None:
        if not isinstance(self.role, ProviderRole):
            raise TypeError(
                f"role must be ProviderRole, got {type(self.role).__name__}"
            )
        if self.adjustment_posture not in ("ADJUSTED", "RAW", "MIXED"):
            raise ValueError(
                f"adjustment_posture={self.adjustment_posture!r} invalid"
            )
        if self.reliability not in ("OFFICIAL", "COMMUNITY", "EXPERIMENTAL"):
            raise ValueError(f"reliability={self.reliability!r} invalid")


# Tier labels mirror :mod:`aurora.core.data_tiers`. ``ANY`` means the
# provider may serve any tier (typically the snapshot provider, which is
# point-in-time by construction).
TIER_LABELS: tuple[str, ...] = (
    "IS_TRAIN",
    "IS_VALID",
    "OOS_DEV",
    "OOS_LOCKED",
    "FORWARD",
    "ANY",
)

# Phases that an OOSGuard must declare in order to authorize a non-PIT
# provider into a locked tier. Mirrors the equivalent set in
# :mod:`aurora.core.snapshots`.
_LOCKED_TIER_UNLOCK_PHASES: frozenset[str] = frozenset({
    "explicit_unlock",
    "explicit_unlock_snapshot",
    "explicit_unlock_oos_locked",
    "explicit_unlock_forward",
    "explicit_unlock_full_tier",
})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base exception for provider-related failures."""


class ProviderNotRegistered(ProviderError):
    """Raised when ``DataProviderRegistry.get`` cannot find a provider name."""


class ProviderUnavailable(ProviderError):
    """Raised by a provider when its backing dependency is not installed.

    Example: the ``openbb`` provider raises this if the ``openbb`` package
    is not importable.
    """


class TierPermissionError(ProviderError):
    """Raised when a fetch is refused because the active OOSGuard tier
    does not match the provider's PIT/tier permission."""


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetMetadata:
    """Provenance and PIT metadata stamped on every Dataset.

    Attributes:
        name: human-readable dataset identifier, e.g. ``"yahoo:SPY:1d"``.
        source: provider name (e.g. ``"yahoo"``, ``"snapshot"``).
        source_version: the provider adapter's ``version`` string at the
            time of fetch.
        asof_date: data snapshot date (when the provider fetched/froze
            the data).
        point_in_time: True if the data is PIT-correct (no future leak,
            no retroactive adjustment).
        content_hash: sha256 of the canonical bytes of the underlying
            ``data`` (see :func:`compute_content_hash`).
        tier_permission: which tier may load this without ceremony.
            One of :data:`TIER_LABELS`. ``"ANY"`` means no gating.
        schema_version: version string for the data schema (so a
            downstream consumer can branch on schema bumps).
        extra: free-form provider-specific metadata.
    """

    name: str
    source: str
    source_version: str
    asof_date: pd.Timestamp
    point_in_time: bool
    content_hash: str
    tier_permission: str
    schema_version: str = "1.0"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate tier label so a typo lands at construction time, not
        # later at gate time. ``object.__setattr__`` bypasses frozen.
        if self.tier_permission not in TIER_LABELS:
            raise ValueError(
                f"tier_permission={self.tier_permission!r} not in {TIER_LABELS}"
            )
        if not isinstance(self.asof_date, pd.Timestamp):
            object.__setattr__(self, "asof_date", pd.Timestamp(self.asof_date))


@dataclass(frozen=True)
class Dataset:
    """A frame/series plus its :class:`DatasetMetadata`.

    Frozen so callers cannot rebind ``data`` and lose the link with
    ``metadata``. The underlying ``data`` itself is a mutable pandas
    object; callers that need an immutable view should copy it.
    """

    metadata: DatasetMetadata
    data: Union[pd.DataFrame, pd.Series]


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


def _series_to_canonical_bytes(s: pd.Series) -> bytes:
    """Canonical little-endian byte representation of a Series.

    Matches the contract used by :func:`aurora.core.snapshots._compute_sha256`
    so a Series that round-trips through SnapshotStore retains the same hash.
    """
    h = hashlib.sha256()
    name = str(s.name) if s.name is not None else ""
    h.update(name.encode("utf-8"))
    h.update(b"\x00")
    arr = np.ascontiguousarray(s.to_numpy(dtype=np.float64), dtype="<f8")
    h.update(arr.tobytes())
    h.update(b"\x00")
    if isinstance(s.index, pd.DatetimeIndex):
        idx = s.index
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        idx_ns = np.ascontiguousarray(
            idx.values.astype("datetime64[ns]").view("int64"),
            dtype="<i8",
        )
        h.update(idx_ns.tobytes())
    else:
        # Fall back to repr -- non-datetime indexes are uncommon for this
        # codebase but we hash *something* deterministic.
        h.update(repr(list(s.index)).encode("utf-8"))
    return h.digest()


def compute_content_hash(data: Union[pd.DataFrame, pd.Series]) -> str:
    """Deterministic sha256 over the canonical bytes of ``data``.

    For a Series, hashes (name, values, index) in little-endian byte order
    so two machines (or two pandas versions) yield identical digests for
    identical inputs.

    For a DataFrame, hashes column names in declared order followed by
    each column treated as a Series. Index hashing follows the Series
    rule above.

    Two semantically-identical frames whose columns differ only in order
    will hash differently; if a caller wants order-invariant hashing,
    sort columns before calling.
    """
    if isinstance(data, pd.Series):
        digest = hashlib.sha256()
        digest.update(_series_to_canonical_bytes(data))
        return digest.hexdigest()
    if isinstance(data, pd.DataFrame):
        digest = hashlib.sha256()
        # Column names in declared order
        for col in data.columns:
            digest.update(str(col).encode("utf-8"))
            digest.update(b"\x00")
        digest.update(b"\xff")
        for col in data.columns:
            digest.update(_series_to_canonical_bytes(data[col]))
            digest.update(b"\x00")
        # Index once (already hashed inside each column too, but include
        # at the frame level so an empty frame still has index info).
        if isinstance(data.index, pd.DatetimeIndex):
            idx = data.index
            if idx.tz is not None:
                idx = idx.tz_convert("UTC").tz_localize(None)
            idx_ns = np.ascontiguousarray(
                idx.values.astype("datetime64[ns]").view("int64"),
                dtype="<i8",
            )
            digest.update(idx_ns.tobytes())
        return digest.hexdigest()
    raise TypeError(
        f"compute_content_hash expects DataFrame/Series, got {type(data).__name__}"
    )


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DataProvider(Protocol):
    """Protocol every provider must satisfy.

    Concrete providers live in this package's submodules. They do NOT have
    to inherit from this Protocol -- duck typing is enough -- but
    implementing it (or subclassing :class:`BaseDataProvider`) keeps the
    contract honest.

    Required attributes:
        name: stable provider identifier (e.g. ``"yahoo"``).
        version: adapter version string (e.g. ``"yahoo:1.0"``).

    Required methods:
        :meth:`fetch`, :meth:`is_point_in_time`, :meth:`supported_tiers`.
    """

    name: str
    version: str

    def fetch(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> Dataset: ...

    def is_point_in_time(self) -> bool: ...

    def supported_tiers(self) -> set[str]: ...


class BaseDataProvider:
    """Convenience base that fills the Protocol contract.

    Subclasses set ``name``, ``version``, ``point_in_time``, and
    ``tier_permission`` and override :meth:`_fetch_raw` to return the
    underlying frame/series. The base class then stamps the
    :class:`DatasetMetadata`.
    """

    name: str = "base"
    version: str = "0.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def is_point_in_time(self) -> bool:
        return bool(self.point_in_time)

    def supported_tiers(self) -> set[str]:
        if self.tier_permission == "ANY":
            return {"IS_TRAIN", "IS_VALID", "OOS_DEV", "OOS_LOCKED", "FORWARD"}
        # A provider that opts into a specific tier supports every tier
        # at-or-before its declared permission. Tier ordering matches
        # data_tiers._TIER_END_DATES (chronological).
        order = ("IS_TRAIN", "IS_VALID", "OOS_DEV", "OOS_LOCKED", "FORWARD")
        try:
            cap = order.index(self.tier_permission)
        except ValueError:
            return {self.tier_permission}
        return set(order[: cap + 1])

    # -- subclass hook ------------------------------------------------------

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> Union[pd.DataFrame, pd.Series]:
        raise NotImplementedError

    # -- public API ---------------------------------------------------------

    def fetch(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> Dataset:
        data = self._fetch_raw(symbol, start, end, **kwargs)
        return self._build_dataset(symbol, data, start, end, kwargs)

    # -- helper -------------------------------------------------------------

    def _build_dataset(
        self,
        symbol: str,
        data: Union[pd.DataFrame, pd.Series],
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        extra: Optional[dict[str, Any]] = None,
    ) -> Dataset:
        if extra is None:
            extra = {}
        # Stamp asof = max(index) when available, else now-UTC. Snapshot
        # providers override this in ``_fetch_raw`` -> ``extra``.
        asof: pd.Timestamp
        if isinstance(data, (pd.Series, pd.DataFrame)) and len(data) > 0 \
                and isinstance(data.index, pd.DatetimeIndex):
            asof = pd.Timestamp(data.index.max())
        else:
            asof = pd.Timestamp.utcnow().tz_localize(None)
        metadata = DatasetMetadata(
            name=f"{self.name}:{symbol}",
            source=self.name,
            source_version=self.version,
            asof_date=asof,
            point_in_time=self.is_point_in_time(),
            content_hash=compute_content_hash(data),
            tier_permission=self.tier_permission,
            schema_version=self.schema_version,
            extra=dict(extra),
        )
        return Dataset(metadata=metadata, data=data)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class DataProviderRegistry:
    """Registry of named :class:`DataProvider` instances.

    Thread-safe register/get. ``fetch(provider_name, ...)`` is the
    front-door used by ``data_layer.load_asset`` -- it stamps metadata,
    enforces tier gating against the active :class:`OOSGuard`, and records
    the read in the OOS lock file's ``authorized_reads`` audit trail.
    """

    def __init__(self) -> None:
        self._providers: dict[str, DataProvider] = {}
        self._descriptors: dict[str, ProviderDescriptor] = {}
        self._last_success: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- public API ---------------------------------------------------------

    def register(
        self,
        provider: DataProvider,
        *,
        descriptor: Optional[ProviderDescriptor] = None,
        replace: bool = False,
    ) -> None:
        """Register a provider by its ``name``.

        Args:
            provider: any object that satisfies :class:`DataProvider`.
            descriptor: optional :class:`ProviderDescriptor` recording the
                provider's role, licensing posture and reliability label.
                Required for the R155 role-aware CLI surface.
            replace: when False (default), re-registering the same name
                raises :class:`ValueError`. Pass True to overwrite.
        """
        if not hasattr(provider, "name") or not isinstance(provider.name, str):
            raise TypeError("provider must expose a string ``name`` attribute")
        if descriptor is not None and descriptor.name != provider.name:
            raise ValueError(
                f"descriptor name {descriptor.name!r} != provider name "
                f"{provider.name!r}"
            )
        with self._lock:
            if not replace and provider.name in self._providers:
                raise ValueError(
                    f"provider {provider.name!r} already registered; "
                    "pass replace=True to overwrite"
                )
            self._providers[provider.name] = provider
            if descriptor is not None:
                self._descriptors[provider.name] = descriptor

    def get(self, name: str) -> DataProvider:
        """Return a registered provider by name."""
        with self._lock:
            if name not in self._providers:
                raise ProviderNotRegistered(
                    f"provider {name!r} not registered. "
                    f"known={sorted(self._providers)}"
                )
            return self._providers[name]

    def list(self) -> List[str]:
        """Return the sorted list of registered provider names."""
        with self._lock:
            return sorted(self._providers)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._providers.pop(name, None)
            self._descriptors.pop(name, None)
            self._last_success.pop(name, None)

    def descriptor_for(self, name: str) -> Optional[ProviderDescriptor]:
        """Return the :class:`ProviderDescriptor` for ``name``, or ``None``."""
        with self._lock:
            return self._descriptors.get(name)

    def list_by_role(self, role: ProviderRole) -> List[str]:
        """Return registered provider names matching ``role``, sorted."""
        with self._lock:
            return sorted(
                n for n, d in self._descriptors.items() if d.role == role
            )

    def role_status(self) -> List[dict[str, Any]]:
        """Return the role-aware status table used by ``provider-status``."""
        with self._lock:
            out: list[dict[str, Any]] = []
            for name in sorted(self._providers):
                p = self._providers[name]
                d = self._descriptors.get(name)
                out.append({
                    "name": name,
                    "version": getattr(p, "version", "?"),
                    "role": d.role.value if d is not None else "unknown",
                    "reliability": d.reliability if d is not None else "unknown",
                    "auth_required": d.auth_required if d is not None else False,
                    "adjustment_posture": (
                        d.adjustment_posture if d is not None else "unknown"
                    ),
                    "licence_terms_url": (
                        d.licence_terms_url if d is not None else ""
                    ),
                    "rate_limits": d.rate_limits if d is not None else "",
                    "asset_classes": list(d.asset_classes) if d is not None else [],
                    "intervals": list(d.intervals) if d is not None else [],
                    "last_success": self._last_success.get(name, ""),
                    "point_in_time": p.is_point_in_time(),
                })
            return out

    def record_success(self, name: str, when_iso: str) -> None:
        """Stamp the last successful fetch timestamp for ``name``."""
        with self._lock:
            if name in self._providers:
                self._last_success[name] = when_iso

    def describe(self) -> List[dict[str, Any]]:
        """Return a list of dicts summarizing each registered provider."""
        with self._lock:
            out: list[dict[str, Any]] = []
            for name in sorted(self._providers):
                p = self._providers[name]
                out.append({
                    "name": name,
                    "version": getattr(p, "version", "?"),
                    "point_in_time": p.is_point_in_time(),
                    "supported_tiers": sorted(p.supported_tiers()),
                    "tier_permission": getattr(p, "tier_permission", "?"),
                })
            return out

    def fetch(
        self,
        provider_name: str,
        symbol: str,
        start: Optional[Union[str, pd.Timestamp]] = None,
        end: Optional[Union[str, pd.Timestamp]] = None,
        **kwargs: Any,
    ) -> Dataset:
        """Fetch ``symbol`` from ``provider_name`` with tier-aware gating.

        Resolves ``provider_name`` via :meth:`get`, calls its ``fetch``,
        then enforces the gate:

        * IS_TRAIN/IS_VALID guards: any provider OK, no gating.
        * OOS_DEV guard: any provider OK; non-PIT providers emit a
          :class:`UserWarning`.
        * OOS_LOCKED / FORWARD guard: a non-PIT provider is refused
          unless the active guard's phase is in
          :data:`_LOCKED_TIER_UNLOCK_PHASES` (explicit unlock ceremony).
        * No active guard: pass through. The data layer's hard guard
          on ``include_oos`` is the perimeter for unguarded callers;
          tier gating only applies when an OOSGuard context is open.

        Records the fetch in the OOS lock file as an ``authorized_read``
        whenever a guard is active OR the call goes through ``include_oos``
        upstream.
        """
        provider = self.get(provider_name)
        norm_start = pd.Timestamp(start) if start is not None else None
        norm_end = pd.Timestamp(end) if end is not None else None

        active_guard, active_phase = self._active_guard_phase()
        self._enforce_tier_gate(provider, active_guard, active_phase)

        ds = provider.fetch(symbol, norm_start, norm_end, **kwargs)
        # Record provenance on the active guard / lock file so an auditor
        # can see "registry served dataset H from provider P at time T".
        self._record_authorized_fetch(ds, active_guard, active_phase)
        return ds

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _active_guard_phase() -> tuple[Optional[Any], Optional[str]]:
        """Return (active OOSGuard, phase) or (None, None)."""
        try:
            from aurora.core.data_layer import OOSGuard
        except Exception:
            return None, None
        guard = OOSGuard.active()
        if guard is None:
            return None, None
        return guard, str(getattr(guard, "phase", "") or "")

    @staticmethod
    def _enforce_tier_gate(
        provider: DataProvider,
        guard: Optional[Any],
        phase: Optional[str],
    ) -> None:
        if guard is None:
            return
        # Map ceremony phase -> tier scope.
        is_locked_tier = phase in _LOCKED_TIER_UNLOCK_PHASES
        is_oos_dev_phase = phase in (
            "post_ga_validation", "preflight_check", "snapshot_freeze",
            "oos_dev",
        )
        if is_locked_tier:
            # Locked unlock: PIT providers OK, non-PIT only if explicit
            # unlock matches and the provider declares it supports
            # OOS_LOCKED/FORWARD.
            if not provider.is_point_in_time():
                # Even with an explicit unlock, a provider that did not
                # declare OOS_LOCKED/FORWARD support is refused -- the
                # ceremony unlocks the data, not the provider.
                supported = provider.supported_tiers()
                if not (supported & {"OOS_LOCKED", "FORWARD"}):
                    raise TierPermissionError(
                        f"provider {provider.name!r} is not point-in-time and "
                        f"does not declare OOS_LOCKED/FORWARD support; "
                        f"refusing to serve under guard phase {phase!r}."
                    )
        elif is_oos_dev_phase:
            if not provider.is_point_in_time():
                import warnings
                warnings.warn(
                    f"provider {provider.name!r} is not point-in-time; "
                    f"reading inside OOSGuard({phase!r}) may permit "
                    "retroactive adjustments to leak into validation.",
                    UserWarning,
                    stacklevel=3,
                )
        # IS_TRAIN/IS_VALID and unspecified phases: no gate.

    @staticmethod
    def _record_authorized_fetch(
        ds: Dataset,
        guard: Optional[Any],
        phase: Optional[str],
    ) -> None:
        where = (
            f"DataProviderRegistry.fetch("
            f"{ds.metadata.source}:{ds.metadata.name}, "
            f"hash={ds.metadata.content_hash[:12]}, "
            f"pit={ds.metadata.point_in_time})"
        )
        try:
            from aurora.core.data_layer import OOSGuard
        except Exception:
            return
        if guard is not None:
            try:
                guard.record_oos_read(where)
            except Exception:
                _log.debug("record_oos_read failed", exc_info=True)
            return
        # No guard -> still leave a paper trail when the metadata is
        # tier_permission="OOS_*" or "FORWARD" or non-PIT, so external
        # auditors can correlate fetches with downstream artifacts.
        if ds.metadata.tier_permission in ("OOS_DEV", "OOS_LOCKED", "FORWARD"):
            try:
                OOSGuard._record_external_authorized_read(
                    where=where,
                    phase="data_provider_fetch",
                )
            except Exception:
                _log.debug("external authorized_read failed", exc_info=True)


# ---------------------------------------------------------------------------
# Singleton + bootstrap
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY: Optional[DataProviderRegistry] = None
_DEFAULT_REGISTRY_LOCK = threading.Lock()


class _DeferredScaffoldStub:
    """Stub provider for env-gated R156 deferred scaffolds.

    Advertises its descriptor to the registry (so ``provider-status``
    surfaces the role and licence terms) but raises
    :class:`ProviderUnavailable` on any actual fetch. Real fetches go
    through the dedicated client classes (``DukascopyClient``,
    ``MarketDataAppClient``), which trip their own env-var gate at
    construction time.
    """

    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"

    def __init__(self, descriptor: ProviderDescriptor) -> None:
        self.name = descriptor.name
        self.version = f"{descriptor.name}:scaffold"
        self._descriptor = descriptor

    def is_point_in_time(self) -> bool:
        return False

    def supported_tiers(self) -> set[str]:
        return {"IS_TRAIN"}

    def fetch(self, *args: Any, **kwargs: Any) -> Dataset:
        raise ProviderUnavailable(
            f"provider {self.name!r} is a deferred R156 scaffold; "
            "use the dedicated client class directly after setting the "
            "gate env var."
        )


def get_default_registry() -> DataProviderRegistry:
    """Return the module-level singleton :class:`DataProviderRegistry`.

    Lazily registers the built-in providers (``yahoo``, ``snapshot``,
    ``csv``, ``synthetic``, ``openbb``) on first call. ``openbb`` is
    registered as a stub that raises :class:`ProviderUnavailable` at
    fetch time when the optional ``openbb`` dependency is missing.
    """
    global _DEFAULT_REGISTRY
    with _DEFAULT_REGISTRY_LOCK:
        if _DEFAULT_REGISTRY is not None:
            return _DEFAULT_REGISTRY
        registry = DataProviderRegistry()
        # Register built-ins. Each provider import is wrapped so a single
        # broken adapter cannot prevent the registry from booting.
        for mod_name, cls_name in (
            ("yahoo", "YahooProvider"),
            ("snapshot", "SnapshotProvider"),
            ("csv", "CSVProvider"),
            ("synthetic", "SyntheticProvider"),
            ("openbb", "OpenBBProvider"),
        ):
            try:
                mod = __import__(
                    f"aurora.core.data_providers.{mod_name}",
                    fromlist=[cls_name],
                )
                cls = getattr(mod, cls_name)
                registry.register(cls())
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "failed to bootstrap provider %s: %s", mod_name, exc,
                )
        # Optional providers: only register when their backing dep is
        # importable. Keeps "from aurora.core.data_providers import ..."
        # cheap and avoids surfacing a stub provider that always raises.
        try:
            import ccxt  # noqa: F401
        except Exception:
            pass
        else:
            try:
                from aurora.core.data_providers.ccxt_provider import (
                    CCXTProvider,
                )
                registry.register(CCXTProvider())
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "failed to bootstrap provider ccxt: %s", exc,
                )
        # R156 deferred env-gated providers. We always advertise their
        # descriptors so ``provider-status`` can list them, but the
        # provider instance is a stub that refuses to fetch unless the
        # relevant gate env var is set. The static descriptors are
        # imported lazily so the gate (which lives in the module body
        # for some providers) is not tripped at registry boot.
        for stub_mod, stub_attr, descriptor_attr in (
            (
                "aurora.core.data_providers.dukascopy_fx_history",
                "DukascopyClient",
                "DUKASCOPY_DESCRIPTOR",
            ),
            (
                "aurora.core.data_providers.marketdata_app_limited",
                "MarketDataAppClient",
                "MARKETDATA_APP_DESCRIPTOR",
            ),
            (
                "aurora.core.data_providers.sec_edgar_companyfacts",
                "SECEdgarClient",
                "SEC_EDGAR_DESCRIPTOR",
            ),
            # R156 priority 3 + 5 macro/context providers. The registry
            # surfaces their descriptors so ``provider-status`` can list
            # them and the role-aware CLI can find the right name; real
            # fetches require constructing the client directly with a
            # caller-supplied http_get to avoid silent network calls.
            (
                "aurora.core.data_providers.dbnomics_macro",
                "DBnomicsClient",
                "DBNOMICS_DESCRIPTOR",
            ),
            (
                "aurora.core.data_providers.ecb_data_portal",
                "ECBClient",
                "ECB_DESCRIPTOR",
            ),
        ):
            try:
                mod = __import__(stub_mod, fromlist=[descriptor_attr])
                desc = getattr(mod, descriptor_attr)
                stub = _DeferredScaffoldStub(desc)
                registry.register(stub, descriptor=desc)
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "failed to register deferred provider %s: %s",
                    stub_mod, exc,
                )
        _DEFAULT_REGISTRY = registry
        return registry


def reset_default_registry() -> None:
    """Test helper: drop the singleton so the next call re-bootstraps."""
    global _DEFAULT_REGISTRY
    with _DEFAULT_REGISTRY_LOCK:
        _DEFAULT_REGISTRY = None


# Re-exports kept stable for ``from aurora.core.data_providers import ...``
__all__ = [
    "AdjustmentLiteral",
    "BaseDataProvider",
    "DataProvider",
    "DataProviderRegistry",
    "Dataset",
    "DatasetMetadata",
    "DBNOMICS_DESCRIPTOR",
    "ECB_DESCRIPTOR",
    "ProviderDescriptor",
    "ProviderError",
    "ProviderNotRegistered",
    "ProviderRole",
    "ProviderUnavailable",
    "ReliabilityLiteral",
    "TIER_LABELS",
    "TierPermissionError",
    "compute_content_hash",
    "get_default_registry",
    "reset_default_registry",
]


def __getattr__(attr_name: str) -> Any:
    """Lazy re-export of R156 macro provider descriptor singletons.

    Keeps the package import light: pulling the descriptor only triggers
    the provider module's import on first access.
    """
    if attr_name == "DBNOMICS_DESCRIPTOR":
        from aurora.core.data_providers.dbnomics_macro import (
            DBNOMICS_DESCRIPTOR as _D,
        )
        return _D
    if attr_name == "ECB_DESCRIPTOR":
        from aurora.core.data_providers.ecb_data_portal import (
            ECB_DESCRIPTOR as _E,
        )
        return _E
    raise AttributeError(
        f"module 'aurora.core.data_providers' has no attribute {attr_name!r}"
    )
