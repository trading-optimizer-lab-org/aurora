"""Exotic / multi-asset markets adapters for Aurora v3.0.

Each module exposes an analyzer/builder/trader class with a dataclass config
and primary ``analyze``/``signals`` method. All modules ship with deterministic
mock data generators so tests can run offline.

Modules:
    forex                  - FX majors + crosses with spread/pip handling
    futures                - Continuous futures contract construction
    options_strategies     - Vertical spreads, condors, butterflies + greeks
    bonds                  - Yield curve, butterfly, duration, convexity
    credit                 - CDS spreads, IG/HY index returns
    commodities_physical   - Roll yield, contango / backwardation
    volatility_products    - VIX term structure, VXX/SVXY decay
    crypto_basis           - Perp + dated basis, cash-and-carry
    etf_arbitrage          - NAV vs price, AP model
    cef_premium            - Closed-end fund premium / discount z-scores
"""
from __future__ import annotations

__all__: list[str] = []


def _try_export(module_name: str, symbols: tuple[str, ...]) -> None:
    """Best-effort import of sibling module; failures swallowed."""
    try:
        mod = __import__(f"aurora.markets.{module_name}", fromlist=symbols)
    except Exception:  # noqa: BLE001
        return
    for sym in symbols:
        if hasattr(mod, sym):
            globals()[sym] = getattr(mod, sym)
            __all__.append(sym)


_try_export("forex", ("ForexUniverse", "ForexConfig"))
_try_export("futures", ("FuturesContinuous", "FuturesConfig"))
_try_export("options_strategies",
            ("OptionsStrategyBuilder", "OptionsStrategyConfig"))
_try_export("bonds", ("BondYieldCurve", "BondConfig"))
_try_export("credit", ("CreditMarket", "CreditConfig"))
_try_export("commodities_physical",
            ("CommoditiesRollAnalyzer", "CommoditiesRollConfig"))
_try_export("volatility_products",
            ("VolatilityProductsTrader", "VolatilityProductsConfig"))
_try_export("crypto_basis", ("CryptoBasisTrader", "CryptoBasisConfig"))
_try_export("etf_arbitrage", ("ETFArbitrageDetector", "ETFArbitrageConfig"))
_try_export("cef_premium", ("CEFPremiumDiscount", "CEFPremiumConfig"))
