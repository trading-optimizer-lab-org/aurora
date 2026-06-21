from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_spy_monthly_trend_following_paper21 import (  # noqa: E402
    LOCKED_START,
    TRAIN_END,
    TRAIN_START,
    VALIDATION_END,
    VALIDATION_START,
    _close,
    _has_symbol,
    build_signal,
    metrics,
    monthly_tbill_return,
)


def require_github() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("This locked report must run in GitHub Actions.")


def main() -> None:
    require_github()
    output_dir = Path(os.environ.get("OUTPUT_DIR", "outputs/spy_monthly_tf21_ma10_locked_table"))
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = output_dir / "yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(str(cache_dir))
    if hasattr(yf, "cache") and hasattr(yf.cache, "set_cache_location"):
        yf.cache.set_cache_location(str(cache_dir))

    raw = pd.DataFrame()
    last_error: Exception | None = None
    end = (pd.Timestamp.utcnow().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    for attempt in range(3):
        try:
            raw = yf.download(
                ["SPY", "^IRX"],
                start="1994-01-01",
                end=end,
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=False,
            )
            if not raw.empty and not _close(raw, "SPY").dropna().empty:
                break
        except Exception as exc:
            last_error = exc
        time.sleep(2.0 * (attempt + 1))
    if raw.empty:
        if last_error is not None:
            raise RuntimeError("yfinance returned no data") from last_error
        raise RuntimeError("yfinance returned no data")

    spy = _close(raw, "SPY").dropna()
    if spy.empty:
        raise RuntimeError("missing SPY close")
    irx = _close(raw, "^IRX").reindex(spy.index).ffill() if _has_symbol(raw, "^IRX") else pd.Series(0.0, index=spy.index)
    daily = pd.DataFrame({"SPY": spy, "IRX": irx}, index=spy.index).dropna(subset=["SPY"])

    monthly_price = daily["SPY"].resample("ME").last().dropna()
    monthly_spy_ret = monthly_price.pct_change(fill_method=None)
    monthly_cash = monthly_tbill_return(daily["IRX"]).reindex(monthly_spy_ret.index).fillna(0.0)
    monthly = pd.DataFrame(
        {"SPY": monthly_spy_ret, "CASH_TBILL": monthly_cash},
        index=monthly_spy_ret.index,
    ).dropna(subset=["SPY"])
    monthly = monthly[monthly.index >= TRAIN_START]
    monthly_price = monthly_price.reindex(monthly.index)

    params = {
        "family": "ma_monthly_close",
        "daily_window": 250,
        "monthly_window": 10,
        "confirm_months": 1,
        "buffer": 0.01,
        "cash_source": "tbill",
        "lag_months": 1,
    }
    signal = build_signal(params, daily["SPY"], monthly_price).reindex(monthly.index).fillna(False)
    position = signal.shift(1).fillna(False).astype(float).clip(0.0, 1.0)
    strategy = position * monthly["SPY"] + (1.0 - position) * monthly["CASH_TBILL"].fillna(0.0)
    frame = pd.DataFrame({"strategy": strategy, "spy": monthly["SPY"]}).dropna()

    annual = (1.0 + frame).resample("YE").prod(min_count=1) - 1.0
    annual.index = annual.index.year
    annual["split"] = "locked"
    annual.loc[annual.index <= TRAIN_END.year, "split"] = "train"
    annual.loc[(annual.index >= VALIDATION_START.year) & (annual.index <= VALIDATION_END.year), "split"] = "validation"
    annual = annual[annual.index >= TRAIN_START.year].reset_index(names="year")
    annual = annual.rename(columns={"strategy": "strategy_return", "spy": "spy_return"})
    annual.to_csv(output_dir / "annual_returns.csv", index=False)

    summary = {
        "strategy": params,
        "locked_opened": True,
        "locked_start": str(LOCKED_START.date()),
        "data_start": str(frame.index.min().date()),
        "data_end": str(frame.index.max().date()),
        "train": metrics(frame.loc[(frame.index >= TRAIN_START) & (frame.index <= TRAIN_END), "strategy"]),
        "validation": metrics(frame.loc[(frame.index >= VALIDATION_START) & (frame.index <= VALIDATION_END), "strategy"]),
        "locked": metrics(frame.loc[frame.index >= LOCKED_START, "strategy"]),
        "spy_locked": metrics(frame.loc[frame.index >= LOCKED_START, "spy"]),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
