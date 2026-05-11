"""FinanceDatabase universe downloader (R155 -- catalogue, no prices).

FinanceDatabase ships a static catalogue of equities, ETFs, FX pairs,
cryptos, indices and funds. We use it as a *universe* source only --
prices are NEVER fetched from it. The provider returns a normalised
DataFrame matching :data:`UNIVERSE_V1`.

In production the real client reads JSON snapshots that ship with the
``financedatabase`` PyPI package. In tests, callers inject a fixture
loader (``client``) that returns a list of dicts; this keeps the test
path pure stdlib + no network.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Sequence

import pandas as pd

from aurora.core.runtime_paths import cache_dir

from . import BaseDataProvider, ProviderUnavailable
from ._free_bulk_common import (
    UNIVERSE_V1,
    FreeBulkLineage,
    assert_universe_frame,
    build_lineage,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "finance_database"
PROVIDER_URL = "https://github.com/JerBouma/FinanceDatabase"
ASSET_CLASS_DEFAULT = "equities"


# ---------------------------------------------------------------------------
# Default loader (production path).
# ---------------------------------------------------------------------------


def _default_loader(asset_class: str) -> List[Mapping[str, Any]]:
    """Production loader: reads cached JSON under ``cache_dir()/finance_database``.

    The file format mirrors what the FinanceDatabase package exports:
    ``{ <symbol>: { name, exchange, currency, summary, ... } }``.
    Tests should NOT rely on this path -- pass a callable explicitly.
    """
    cache_root = cache_dir() / "finance_database"
    cache_root.mkdir(parents=True, exist_ok=True)
    snapshot = cache_root / f"{asset_class}.json"
    if not snapshot.exists():
        raise ProviderUnavailable(
            f"finance_database universe cache missing for asset_class="
            f"{asset_class!r}; expected JSON file at {snapshot}. "
            "In production, populate via the financedatabase PyPI package; "
            "in tests, pass a custom client."
        )
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows: list[dict[str, Any]] = []
        for sym, attrs in payload.items():
            row = {"symbol": str(sym)}
            if isinstance(attrs, Mapping):
                row.update(dict(attrs))
            rows.append(row)
        return rows
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    raise ValueError(
        f"finance_database snapshot at {snapshot} has unexpected shape: "
        f"{type(payload).__name__}"
    )


# ---------------------------------------------------------------------------
# Provider class.
# ---------------------------------------------------------------------------


class FinanceDatabaseUniverseProvider(BaseDataProvider):
    """Catalogue (no prices) provider.

    The provider's :meth:`fetch_universe` returns a *DataFrame* matching
    UNIVERSE_V1 plus a :class:`FreeBulkLineage` envelope. ``fetch`` is
    intentionally not implemented for OHLCV -- this provider is
    universe-only.
    """

    name: str = PROVIDER_NAME
    version: str = "finance_database:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[Callable[[str], Sequence[Mapping[str, Any]]]] = None,
    ) -> None:
        self._client = client or _default_loader

    # -- universe API -------------------------------------------------------

    def fetch_universe(
        self,
        *,
        asset_class: str = ASSET_CLASS_DEFAULT,
        active_only: bool = True,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        """Return ``(universe_df, lineage)`` for ``asset_class``.

        Raises :class:`FreeBulkContractViolation` when the normalised
        frame does not satisfy :data:`UNIVERSE_V1`.
        """
        rows = list(self._client(asset_class))
        if not rows:
            df = self._empty_universe()
        else:
            df = self._normalise(rows, asset_class=asset_class)
        if active_only:
            df = df[df["active"]].reset_index(drop=True)
        snapshot_hash = assert_universe_frame(df)
        lineage = build_lineage(
            df=df,
            contract=UNIVERSE_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={"asset_class": asset_class, "active_only": active_only},
            snapshot_hash=snapshot_hash,
            symbol_count=int(df["canonical_symbol"].nunique()),
            extra={"reliability": "OFFICIAL", "source": "FinanceDatabase"},
        )
        return df, lineage

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _empty_universe() -> pd.DataFrame:
        return pd.DataFrame(
            columns=(
                "provider_symbol",
                "canonical_symbol",
                "exchange",
                "asset_class",
                "currency",
                "active",
                "source_timestamp",
            )
        )

    @staticmethod
    def _normalise(
        rows: Sequence[Mapping[str, Any]], *, asset_class: str
    ) -> pd.DataFrame:
        ts = pd.Timestamp(utcnow_iso().replace("Z", "+00:00"))
        out: list[dict[str, Any]] = []
        for raw in rows:
            sym = str(raw.get("symbol") or raw.get("provider_symbol") or "").strip()
            if not sym:
                continue
            canonical = str(raw.get("canonical_symbol") or sym).strip()
            exchange = raw.get("exchange")
            currency = raw.get("currency")
            active_flag = raw.get("active")
            if active_flag is None:
                # Default: a row with no explicit deactivation is active.
                active_bool = True
            else:
                active_bool = bool(active_flag)
            out.append({
                "provider_symbol": sym,
                "canonical_symbol": canonical,
                "exchange": str(exchange) if exchange else None,
                "asset_class": str(raw.get("asset_class") or asset_class),
                "currency": str(currency) if currency else None,
                "active": active_bool,
                "source_timestamp": ts,
            })
        if not out:
            return FinanceDatabaseUniverseProvider._empty_universe()
        return pd.DataFrame(out)

    # -- BaseDataProvider plumbing -----------------------------------------

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        raise NotImplementedError(
            "finance_database is a universe provider; use fetch_universe()"
        )


# ---------------------------------------------------------------------------
# Default descriptor.
# ---------------------------------------------------------------------------


def descriptor():
    """Return the registry-friendly :class:`ProviderDescriptor`."""
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.UNIVERSE,
        licence_terms_url="https://github.com/JerBouma/FinanceDatabase/blob/main/LICENSE",
        rate_limits="none (static catalogue)",
        auth_required=False,
        asset_classes=("equities", "etf", "crypto", "forex", "index", "fund"),
        intervals=(),
        adjustment_posture="MIXED",
        reliability="OFFICIAL",
    )


# Optional helper for tests -- write fixture rows under cache_dir() so the
# default loader picks them up.
def _write_cache_fixture(asset_class: str, payload: Any) -> Path:
    cache_root = cache_dir() / "finance_database"
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / f"{asset_class}.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


__all__ = [
    "FinanceDatabaseUniverseProvider",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
]
