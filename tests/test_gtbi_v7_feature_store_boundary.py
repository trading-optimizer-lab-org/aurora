from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import global_technical_buy_indicator as gtbi


def _frames(rows: int = 120) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2009-09-01", periods=rows, freq="B")
    close = np.full(rows, 100.0)
    close[70:] = np.linspace(112.0, 142.0, rows - 70)
    open_ = np.r_[close[0], close[:-1] * 1.001]
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.r_[np.full(70, 100_000.0), np.full(rows - 70, 300_000.0)],
            "symbol": "AAA",
        }
    )
    spy_close = np.linspace(100.0, 112.0, rows)
    spy = pd.DataFrame(
        {
            "date": dates,
            "open": spy_close,
            "high": spy_close * 1.002,
            "low": spy_close * 0.998,
            "close": spy_close,
            "adj_close": spy_close,
            "volume": np.full(rows, 1_000_000.0),
            "symbol": "SPY",
        }
    )
    return frame, spy


def _config() -> gtbi.IndicatorConfig:
    return gtbi.IndicatorConfig(
        family="minervini_sepa",
        minervini_trend=False,
        require_rs=False,
        require_market_trend=False,
        require_base_tight=True,
        require_breakout=True,
        require_pocket_pivot=False,
        breakout_lookback=20,
        base_lookback=20,
        max_base_range_pct=0.20,
        volume_lookback=20,
        volume_multiple=1.5,
        rsi_max=100.0,
        max_holding_days=15,
    )


def test_authoritative_feature_store_matches_uncached_science() -> None:
    frame, spy = _frames()
    config = _config()
    store = gtbi.build_feature_store({"AAA": frame}, spy, enabled=True)
    primitives = store.primitives_for("AAA", frame, spy)

    cached_signal = gtbi._entry_signal_optimized(frame, spy, config, primitive_store=primitives)
    uncached_signal = gtbi._entry_signal_optimized(frame, spy, config)
    pd.testing.assert_series_equal(cached_signal, uncached_signal)

    cached_trades = gtbi.simulate_trades("AAA", frame, cached_signal, config, split="validation")
    uncached_trades = gtbi.simulate_trades(
        "AAA", frame, uncached_signal, config, split="validation"
    )
    pd.testing.assert_frame_equal(cached_trades, uncached_trades)
    assert not cached_trades.empty

    assert gtbi.summarize_trades(cached_trades, years=1.0) == gtbi.summarize_trades(
        uncached_trades, years=1.0
    )
    pd.testing.assert_frame_equal(
        gtbi.yearly_trade_performance(cached_trades, spy),
        gtbi.yearly_trade_performance(uncached_trades, spy),
    )


def test_feature_store_invalidates_in_place_source_change() -> None:
    frame, spy = _frames()
    store = gtbi.build_feature_store({"AAA": frame}, spy, enabled=True)
    original = store.primitives_for("AAA", frame, spy)
    changed = frame.copy()
    changed.loc[changed.index[-1], "close"] *= 1.02
    refreshed = store.primitives_for("AAA", changed, spy)
    assert refreshed is not original
    assert refreshed.frame_identity != original.frame_identity


def test_feature_store_module_has_no_io_or_network_calls() -> None:
    source = Path("core/gtbi_feature_store.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"open", "urlopen", "requests", "subprocess", "socket"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert names.isdisjoint(forbidden)
