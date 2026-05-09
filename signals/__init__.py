"""QuantForge signal modules.

Signal-only (not full strategies). Each returns pd.Series or pd.DataFrame
of {-1, 0, +1} aligned to dates. Combine with sizing/risk wrappers downstream.
"""
from aurora.signals.vol_surface import VolSurfaceSignal, VolSurfaceConfig
from aurora.signals.cross_asset_momentum import (
    CrossAssetMomentum, CrossAssetMomentumConfig,
)
from aurora.signals.event_driven import EventDrivenSignal, EventDrivenConfig
from aurora.signals.calendar_effects import (
    CalendarEffectsSignal, CalendarEffectsConfig,
)
from aurora.signals.microstructure_hft import (
    MicrostructureSignal, MicrostructureConfig,
)
from aurora.signals.cross_listing_arb import (
    CrossListingArbSignal, CrossListingArbConfig,
)
from aurora.signals.risk_premia import (
    RiskPremiaHarvester, RiskPremiaConfig,
)
from aurora.signals.crypto_funding_arb import (
    CryptoFundingArbSignal, CryptoFundingArbConfig,
)

__all__ = [
    "VolSurfaceSignal", "VolSurfaceConfig",
    "CrossAssetMomentum", "CrossAssetMomentumConfig",
    "EventDrivenSignal", "EventDrivenConfig",
    "CalendarEffectsSignal", "CalendarEffectsConfig",
    "MicrostructureSignal", "MicrostructureConfig",
    "CrossListingArbSignal", "CrossListingArbConfig",
    "RiskPremiaHarvester", "RiskPremiaConfig",
    "CryptoFundingArbSignal", "CryptoFundingArbConfig",
]
