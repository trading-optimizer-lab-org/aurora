"""Price-based causal signals used by the supported protocol tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dataset import ResearchPanel


def _features(panel: ResearchPanel) -> pd.DataFrame:
    frame = panel.frame.sort_values(["symbol", "date"]).copy()
    grouped = frame.groupby("symbol", group_keys=False)
    frame["ret_1d"] = grouped["adj_close"].pct_change()
    frame["mom_12_1"] = grouped["adj_close"].transform(lambda x: x.shift(21).pct_change(252))
    frame["mom_6_1"] = grouped["adj_close"].transform(lambda x: x.shift(21).pct_change(126))
    frame["vol_12_1"] = grouped["ret_1d"].transform(lambda x: x.shift(21).rolling(252, min_periods=126).std() * np.sqrt(252))
    frame["h52"] = frame["close"] / grouped["high"].transform(lambda x: x.shift(1).rolling(252, min_periods=126).max())
    frame["sma_150"] = grouped["close"].transform(lambda x: x.shift(1).rolling(150, min_periods=100).mean())
    frame["sma_200"] = grouped["close"].transform(lambda x: x.shift(1).rolling(200, min_periods=130).mean())
    frame["sma_250"] = grouped["close"].transform(lambda x: x.shift(1).rolling(250, min_periods=160).mean())
    frame["rvol50"] = frame["volume"] / grouped["volume"].transform(lambda x: x.shift(1).rolling(50, min_periods=25).mean())
    frame["atr20"] = grouped["ret_1d"].transform(lambda x: x.abs().shift(1).rolling(20, min_periods=10).mean()) * grouped["close"].transform(lambda x: x.shift(1))
    frame["breakout_high"] = frame["close"] > grouped["high"].transform(lambda x: x.shift(1).rolling(252, min_periods=100).max())
    neg = grouped["ret_1d"].transform(lambda x: (x < 0).shift(21).rolling(252, min_periods=126).sum())
    pos = grouped["ret_1d"].transform(lambda x: (x > 0).shift(21).rolling(252, min_periods=126).sum())
    frame["information_discreteness"] = np.sign(frame["mom_12_1"]) * (neg - pos) / (neg + pos).replace(0, np.nan)
    frame["price_score"] = (
        frame["mom_12_1"].rank(pct=True) * 0.5
        + frame["h52"].rank(pct=True) * 0.3
        - frame["information_discreteness"].rank(pct=True) * 0.2
    )
    return frame


def compute_signal(panel: ResearchPanel, test_id: int, variant: dict[str, object]) -> pd.DataFrame:
    """Return one causal signal row per eligible symbol/date."""

    frame = _features(panel)
    if test_id == 1:
        score = frame["mom_12_1"]
    elif test_id == 2:
        score = frame["mom_6_1"]
    elif test_id == 3:
        score = frame["mom_12_1"] / frame["vol_12_1"].replace(0, np.nan)
    elif test_id == 8:
        score = frame["h52"]
    elif test_id == 9:
        score = -frame["information_discreteness"]
    elif test_id == 13:
        score = frame["price_score"]
    elif test_id == 16:
        window = int(variant.get("window", 20))
        group = frame.groupby("symbol", group_keys=False)
        score = (frame["close"] > group["high"].transform(lambda x: x.shift(1).rolling(window, min_periods=max(10, window // 2)).max())).astype(float)
    elif test_id == 17:
        window = int(variant.get("window", 20))
        group = frame.groupby("symbol", group_keys=False)
        high = group["high"].transform(lambda x: x.shift(1).rolling(window, min_periods=max(10, window // 2)).max())
        low = group["low"].transform(lambda x: x.shift(1).rolling(window, min_periods=max(10, window // 2)).min())
        score = -(high - low) / frame["close"].replace(0, np.nan)
    elif test_id == 18:
        threshold = float(variant.get("threshold", 1.5))
        score = frame["breakout_high"].astype(float) * (frame["rvol50"] >= threshold).astype(float)
    elif test_id == 20:
        sma = int(variant.get("sma", 200))
        score = (frame["close"] > frame[f"sma_{sma}"]).astype(float)
    else:
        score = frame["price_score"]
    frame["score"] = pd.to_numeric(score, errors="coerce")
    frame["signal"] = frame["score"].notna() & np.isfinite(frame["score"])
    frame["signal_date"] = frame["date"]
    frame["available_at"] = frame["date"]
    return frame.loc[frame["signal"], ["signal_date", "available_at", "symbol", "score", "close", "high", "low", "atr20"]].reset_index(drop=True)

