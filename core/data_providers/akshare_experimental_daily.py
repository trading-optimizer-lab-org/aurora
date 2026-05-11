"""AKShare experimental daily provider (R155 EXPERIMENTAL).

AKShare scrapes various Chinese / global market sources. The
upstream is volatile and the legal posture is unclear in some
jurisdictions. We refuse to import this module unless the operator
opts in via the ``AU_ENABLE_AKSHARE=1`` environment variable. This
ensures AKShare never runs silently as part of a default ingestion
job.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

import pandas as pd

from . import BaseDataProvider, ProviderUnavailable
from ._free_bulk_common import (
    OHLCV_DAILY_V1,
    FreeBulkLineage,
    assert_against_contract,
    build_lineage,
    empty_ohlcv_frame,
    normalise_ohlcv_frame,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "akshare_experimental"
PROVIDER_URL = "https://github.com/akfamily/akshare"
ENABLE_ENV_VAR = "AU_ENABLE_AKSHARE"


def _opt_in_check() -> None:
    """Refuse to load unless the env var is set to ``1``.

    Tests that exercise the *enabled* path use ``monkeypatch.setenv``
    before importing the module. The disabled path is the default and
    raises on import-time use.
    """
    if os.environ.get(ENABLE_ENV_VAR, "") != "1":
        raise RuntimeError(
            "AKShare experimental provider is disabled. "
            f"Set {ENABLE_ENV_VAR}=1 to opt in. "
            "AKShare scrapes volatile sources and is not approved for "
            "production research without explicit operator review."
        )


# Trigger the gate at module import time so a stray `import` line
# anywhere in the codebase fails loudly when AKShare is disabled.
_opt_in_check()


def _default_client(symbol: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    try:
        import akshare as ak  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise ProviderUnavailable(
            "akshare_experimental requires the optional ``akshare`` package"
        ) from exc
    df = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


class AKShareExperimentalDailyProvider(BaseDataProvider):
    """AKShare experimental adapter."""

    name: str = PROVIDER_NAME
    version: str = "akshare_experimental:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[
            Callable[[str, Optional[str], Optional[str]], pd.DataFrame]
        ] = None,
    ) -> None:
        _opt_in_check()
        self._client = client or _default_client

    def fetch_daily(
        self,
        symbol: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        raw = self._client(symbol, start, end)
        if raw is None or len(raw) == 0:
            df = empty_ohlcv_frame()
        else:
            df = normalise_ohlcv_frame(raw)
        snapshot_hash = assert_against_contract(df, OHLCV_DAILY_V1)
        lineage = build_lineage(
            df=df,
            contract=OHLCV_DAILY_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={"symbol": symbol, "start": start, "end": end},
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "EXPERIMENTAL",
                "source": "AKShare",
                "experimental": True,
                "warning": (
                    "AKShare scrapes volatile sources; treat as research "
                    "draft, never as primary."
                ),
                "adjustment_posture": "MIXED",
            },
        )
        return df, lineage

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        df, _ = self.fetch_daily(
            symbol,
            start=start.strftime("%Y-%m-%d") if start is not None else None,
            end=end.strftime("%Y-%m-%d") if end is not None else None,
        )
        return df


def descriptor():
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.EXPERIMENTAL,
        licence_terms_url="https://github.com/akfamily/akshare/blob/main/LICENSE",
        rate_limits="upstream-defined; volatile",
        auth_required=False,
        asset_classes=("equities",),
        intervals=("1d",),
        adjustment_posture="MIXED",
        reliability="EXPERIMENTAL",
    )


def _coerce_str(x: Any) -> str:  # pragma: no cover - trivial
    return str(x)


__all__ = [
    "AKShareExperimentalDailyProvider",
    "ENABLE_ENV_VAR",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
]
