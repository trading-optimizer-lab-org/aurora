"""Deep market data modules for QuantForge v3.0 Batch A.

Each submodule exposes a primary class plus a dataclass config. All modules
ship with deterministic mock data paths so tests run offline. Optional vendor
SDKs are imported lazily.
"""
from __future__ import annotations

__all__: list[str] = []


def _try_export(module_name: str, symbols: tuple[str, ...]) -> None:
    """Best-effort import a sibling module and re-export selected symbols.

    Failures are swallowed so that a single broken optional-dep submodule does
    not block ``import aurora.marketdata``. Importers can still target
    submodules directly to surface the underlying ImportError.
    """
    try:
        mod = __import__(f"aurora.marketdata.{module_name}", fromlist=symbols)
    except Exception:  # noqa: BLE001 - optional dep failures must not crash init
        return
    for sym in symbols:
        if hasattr(mod, sym):
            globals()[sym] = getattr(mod, sym)
            __all__.append(sym)


_try_export("taq_reconstruction", ("TAQReconstructor", "TAQConfig"))
_try_export("level3_book", ("Level3OrderBook", "Level3Config", "Level3Order"))
_try_export("trade_microstructure",
            ("TradeMicrostructureAnalyzer", "MicrostructureConfig"))
_try_export("dark_pool_prints", ("DarkPoolDetector", "DarkPoolConfig"))
_try_export("block_trades", ("BlockTradeDetector", "BlockTradeConfig"))
_try_export("lit_dark_routing", ("LitDarkAnalyzer", "LitDarkConfig"))
_try_export("auction_imbalance",
            ("AuctionImbalanceTracker", "AuctionConfig"))
_try_export("extended_hours", ("ExtendedHoursBars", "ExtendedHoursConfig"))
_try_export("corporate_actions",
            ("CorporateActionsAdjuster", "CorporateActionsConfig"))
_try_export("survivorship_free",
            ("SurvivorshipFreeUniverse", "UniverseConfig"))
