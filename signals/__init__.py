"""QuantForge signal modules.

Signal-only (not full strategies). Each returns pd.Series or pd.DataFrame
of {-1, 0, +1} aligned to dates. Combine with sizing/risk wrappers downstream.
"""
from quantforge.signals.vol_surface import VolSurfaceSignal, VolSurfaceConfig
from quantforge.signals.cross_asset_momentum import (
    CrossAssetMomentum, CrossAssetMomentumConfig,
)
from quantforge.signals.event_driven import EventDrivenSignal, EventDrivenConfig
from quantforge.signals.calendar_effects import (
    CalendarEffectsSignal, CalendarEffectsConfig,
)
from quantforge.signals.microstructure_hft import (
    MicrostructureSignal, MicrostructureConfig,
)
from quantforge.signals.cross_listing_arb import (
    CrossListingArbSignal, CrossListingArbConfig,
)
from quantforge.signals.risk_premia import (
    RiskPremiaHarvester, RiskPremiaConfig,
)
from quantforge.signals.crypto_funding_arb import (
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
