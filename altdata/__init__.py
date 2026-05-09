"""Alternative data ingestion adapters for QuantForge v2.0.

Each module exposes a ``*Adapter`` class with a dataclass config and a primary
fetch function. Optional vendor SDKs are imported lazily inside fetch methods so
the package remains importable without those dependencies installed. All
adapters ship with a deterministic ``mock=True`` path so tests can run offline.
"""
from __future__ import annotations

__all__: list[str] = []


def _try_export(module_name: str, symbols: tuple[str, ...]) -> None:
    """Best-effort import a sibling module and re-export selected symbols.

    Failures are swallowed so that a single broken optional-dep submodule does
    not block ``import aurora.altdata``. Importers can still target
    submodules directly to surface the underlying ImportError.
    """
    try:
        mod = __import__(f"aurora.altdata.{module_name}", fromlist=symbols)
    except Exception:  # noqa: BLE001 - optional dep failures must not crash init
        return
    for sym in symbols:
        if hasattr(mod, sym):
            globals()[sym] = getattr(mod, sym)
            __all__.append(sym)


_try_export("twitter_sentiment", ("TwitterSentimentAdapter", "TwitterConfig"))
_try_export("reddit_scraper", ("RedditAdapter", "RedditConfig"))
_try_export("sec_filings", ("SECFilingsAdapter", "SECConfig"))
_try_export("options_flow", ("OptionsFlowAdapter", "OptionsFlowConfig"))
_try_export("onchain_crypto", ("OnchainAdapter", "OnchainConfig"))
_try_export("fred_macro", ("FREDAdapter", "FREDConfig"))
_try_export("earnings_transcripts",
            ("EarningsTranscriptAdapter", "EarningsConfig"))
_try_export("google_trends", ("GoogleTrendsAdapter", "GoogleTrendsConfig"))
_try_export("satellite_geo", ("SatelliteAdapter", "SatelliteConfig"))
_try_export("news_llm_sentiment",
            ("NewsLLMSentimentAdapter", "NewsLLMConfig"))
