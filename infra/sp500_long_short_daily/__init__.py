"""Frozen daily SPY +1/-1 research campaign."""

from aurora.infra.sp500_long_short_daily.contracts import (
    CampaignPackage,
    LockedBoundaryError,
)

__all__ = ["CampaignPackage", "LockedBoundaryError"]
