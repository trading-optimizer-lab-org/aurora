"""OpenBB provider stub.

Lazy-imports the optional ``openbb`` package. If the package is not
installed, every fetch raises :exc:`ProviderUnavailable`. When installed,
calls ``obb.equity.price.historical(symbol, start_date=..., end_date=...)``
and adapts the result.

OpenBB upstream does not guarantee point-in-time correctness across all
of its data sources, so the provider is conservatively marked
``point_in_time=False`` with ``tier_permission="IS_TRAIN"``. Researchers
who curate a PIT-correct OpenBB workflow can override both via the
construction kwargs.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import BaseDataProvider, ProviderError, ProviderUnavailable


class OpenBBProvider(BaseDataProvider):
    """OpenBB SDK adapter (lazy-import).

    Construction kwargs:
        endpoint: dotted attribute path on the OpenBB SDK to call.
            Defaults to ``"equity.price.historical"``. Override for
            other endpoints (e.g. ``"crypto.price.historical"``).
        point_in_time: opt-in PIT flag.
        tier_permission: per-instance override.
    """

    name: str = "openbb"
    version: str = "openbb:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"

    def __init__(
        self,
        *,
        endpoint: str = "equity.price.historical",
        point_in_time: Optional[bool] = None,
        tier_permission: Optional[str] = None,
    ) -> None:
        self.endpoint = endpoint
        if point_in_time is not None:
            object.__setattr__(self, "point_in_time", bool(point_in_time))
        if tier_permission is not None:
            object.__setattr__(self, "tier_permission", tier_permission)

    def _import_obb(self):
        try:
            from openbb import obb
        except Exception as exc:  # pragma: no cover - openbb optional
            raise ProviderUnavailable(
                "openbb provider requires the optional ``openbb`` package; "
                "install with ``pip install openbb``"
            ) from exc
        return obb

    def _resolve_endpoint(self, obb: Any) -> Any:
        node: Any = obb
        for part in self.endpoint.split("."):
            node = getattr(node, part)
        if not callable(node):
            raise ProviderError(
                f"openbb provider: endpoint {self.endpoint!r} is not callable"
            )
        return node

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> pd.Series:
        obb = self._import_obb()
        endpoint = self._resolve_endpoint(obb)
        s_arg = start.strftime("%Y-%m-%d") if start is not None else None
        e_arg = end.strftime("%Y-%m-%d") if end is not None else None
        column = kwargs.pop("column", "close")
        # OpenBB Workspace returns an OBBject; ``to_df()`` materializes it.
        result = endpoint(symbol=symbol, start_date=s_arg, end_date=e_arg, **kwargs)
        if hasattr(result, "to_df"):
            df = result.to_df()
        elif isinstance(result, pd.DataFrame):
            df = result
        else:
            raise ProviderError(
                f"openbb provider: unrecognized return type {type(result).__name__}"
            )
        if column in df.columns:
            s = df[column]
        else:
            # Fall back to a case-insensitive lookup.
            cols_lower = {c.lower(): c for c in df.columns}
            if column.lower() in cols_lower:
                s = df[cols_lower[column.lower()]]
            else:
                s = df.iloc[:, 0]
        idx = pd.to_datetime(s.index)
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        s = pd.Series(s.values.astype(float), index=idx, name=symbol)
        return s.dropna().sort_index()
