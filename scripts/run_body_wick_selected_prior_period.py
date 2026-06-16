from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

_AURORA_POLICY_ROOT = Path(__file__).resolve().parents[1]
if str(_AURORA_POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(_AURORA_POLICY_ROOT))

from scripts.run_body_wick_sr_15m_backtest import (  # noqa: E402
    PRICE_COLUMNS,
    StrategyVariant,
    detect_trades_for_symbol,
    metrics_for_returns,
    normalise_bars,
)

try:
    from core.execution_policy import require_github_actions_or_explicit_local_permission
except ModuleNotFoundError:

    def require_github_actions_or_explicit_local_permission(run_kind: str = "research run") -> None:
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            return
        if os.environ.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == "USER_REQUESTED_LOCAL_RUN_THIS_TURN":
            return
        raise RuntimeError(
            "Run local bloqueado por politica Aurora. "
            f"Lanzalo en GitHub Actions o pide explicitamente ejecucion local. Tipo: {run_kind}."
        )


SYMBOLS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "AVGO",
    "LLY",
    "JPM",
    "TSLA",
    "V",
    "UNH",
    "XOM",
    "MA",
    "COST",
    "NFLX",
    "WMT",
    "PG",
    "HD",
    "KO",
    "SPY",
)

SELECTED_VARIANT_ID = (
    "long__deep_half__color__atr0__close_inside__color_only__close_break"
    "__minage5__age26__time__h4__r1"
)


def main() -> None:
    require_github_actions_or_explicit_local_permission("selected body-wick prior-period backtest")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs/body_wick_selected_prior_period")
    parser.add_argument("--start", default="2026-01-20")
    parser.add_argument("--end", default="2026-03-19")
    parser.add_argument("--interval", default="15m", choices=["15m"])
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument("--min-symbols", type=int, default=21)
    parser.add_argument("--min-bars", type=int, default=300)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    frames: dict[str, pd.DataFrame] = {}
    failures: list[dict[str, str]] = []
    for symbol in SYMBOLS:
        try:
            frame = fetch_symbol(symbol, start=args.start, end=args.end, interval=args.interval)
            if len(frame) < args.min_bars:
                raise RuntimeError(f"muy pocas barras: {len(frame)}")
            frames[symbol] = frame
        except Exception as exc:
            failures.append({"symbol": symbol, "error": str(exc)})

    if len(frames) < args.min_symbols:
        write_unavailable(
            output_dir,
            start=args.start,
            end=args.end,
            interval=args.interval,
            failures=failures,
            frames=frames,
            reason=(
                f"Solo {len(frames)}/{args.min_symbols} simbolos con al menos {args.min_bars} barras. "
                "Yahoo/yfinance suele limitar intradia 15m a unos 60 dias recientes."
            ),
        )
        return

    try:
        aligned = align_frames(frames, min_bars=args.min_bars)
    except Exception as exc:
        write_unavailable(
            output_dir,
            start=args.start,
            end=args.end,
            interval=args.interval,
            failures=failures,
            frames=frames,
            reason=str(exc),
        )
        return

    for symbol, frame in aligned.items():
        frame.to_csv(data_dir / f"{symbol}_15m.csv", index_label="timestamp")

    variant = StrategyVariant(
        variant_id=SELECTED_VARIANT_ID,
        side="long",
        zone_method="deep_half",
        setup_candle="color",
        min_range_atr=0.0,
        touch_rule="close_inside",
        confirmation_rule="color_only",
        invalidation_rule="close_break",
        min_zone_age_bars=5,
        max_zone_age_bars=26,
        exit_rule="time",
        hold_bars=4,
        stop_buffer_atr=0.0,
        target_r=1.0,
    )

    trades: list[dict[str, Any]] = []
    for symbol, frame in aligned.items():
        trades.extend(detect_trades_for_symbol(frame, symbol, variant, cost_bps=args.cost_bps))

    trades_frame = pd.DataFrame(trades)
    if trades_frame.empty:
        trades_frame = pd.DataFrame(columns=["variant_id", "symbol", "split", "net_return"])
    trades_frame.to_csv(output_dir / "trades.csv", index=False)

    summary = build_summary(
        trades_frame,
        start=args.start,
        end=args.end,
        interval=args.interval,
        symbols=sorted(aligned),
        rows_per_symbol={symbol: len(frame) for symbol, frame in aligned.items()},
        cost_bps=args.cost_bps,
    )
    pd.DataFrame([summary["overall"]]).to_csv(output_dir / "summary.csv", index=False)
    if not trades_frame.empty:
        symbol_rows = []
        for symbol, group in trades_frame.groupby("symbol"):
            row = {"symbol": symbol}
            row.update(metrics_for_returns(group["net_return"].tolist()))
            symbol_rows.append(row)
        pd.DataFrame(symbol_rows).sort_values("total_return", ascending=False).to_csv(
            output_dir / "symbol_summary.csv", index=False
        )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def fetch_symbol(symbol: str, *, start: str, end: str, interval: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            raw = yf.download(
                symbol,
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                progress=False,
                prepost=False,
                threads=False,
                timeout=60,
            )
            frame = normalise_yfinance_ohlcv(raw, symbol=symbol)
            return frame
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2.0 * attempt)
    raise RuntimeError(f"No se pudo descargar {symbol}: {last_error}")


def normalise_yfinance_ohlcv(raw: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance devolvio datos vacios para {symbol}")
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        if symbol in frame.columns.get_level_values(-1):
            frame = frame.xs(symbol, axis=1, level=-1, drop_level=True)
        else:
            frame.columns = frame.columns.get_level_values(0)
    frame = frame.rename(columns={column: str(column).title() for column in frame.columns})
    missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"faltan columnas {missing}")
    frame = frame.loc[:, list(PRICE_COLUMNS)].copy()
    frame.index = pd.to_datetime(frame.index)
    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    frame = normalise_bars(frame)
    idx = pd.to_datetime(frame.index)
    regular = (
        (idx.dayofweek < 5)
        & ((idx.hour > 9) | ((idx.hour == 9) & (idx.minute >= 30)))
        & (idx.hour < 16)
    )
    return frame.loc[regular].copy()


def align_frames(frames: dict[str, pd.DataFrame], *, min_bars: int) -> dict[str, pd.DataFrame]:
    common_start = max(frame.index.min() for frame in frames.values())
    common_end = min(frame.index.max() for frame in frames.values())
    if common_start >= common_end:
        raise RuntimeError(f"No hay periodo comun: {common_start} >= {common_end}")
    common_index: pd.Index | None = None
    for frame in frames.values():
        index = frame.loc[(frame.index >= common_start) & (frame.index <= common_end)].index
        common_index = index if common_index is None else common_index.intersection(index)
    assert common_index is not None
    common_index = pd.DatetimeIndex(common_index).sort_values()
    if len(common_index) < min_bars:
        raise RuntimeError(f"Indice comun insuficiente: {len(common_index)} barras, minimo {min_bars}")
    return {
        symbol: frame.reindex(common_index).dropna(subset=["Open", "High", "Low", "Close"])
        for symbol, frame in frames.items()
    }


def build_summary(
    trades: pd.DataFrame,
    *,
    start: str,
    end: str,
    interval: str,
    symbols: list[str],
    rows_per_symbol: dict[str, int],
    cost_bps: float,
) -> dict[str, Any]:
    returns = trades["net_return"].tolist() if "net_return" in trades else []
    overall = metrics_for_returns(returns)
    split_metrics = {
        split: metrics_for_returns(trades.loc[trades["split"] == split, "net_return"].tolist())
        for split in ("train", "validation", "locked")
        if "split" in trades
    }
    by_symbol = {}
    if not trades.empty:
        for symbol, group in trades.groupby("symbol"):
            by_symbol[symbol] = metrics_for_returns(group["net_return"].tolist())
    return {
        "status": "completed",
        "variant_id": SELECTED_VARIANT_ID,
        "period": {"start": start, "end": end, "interval": interval},
        "source": "yfinance_free_no_api_key_start_end",
        "cost_bps": cost_bps,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "rows_per_symbol": rows_per_symbol,
        "overall": overall,
        "split_metrics": split_metrics,
        "by_symbol": by_symbol,
    }


def write_unavailable(
    output_dir: Path,
    *,
    start: str,
    end: str,
    interval: str,
    failures: list[dict[str, str]],
    frames: dict[str, pd.DataFrame],
    reason: str,
) -> None:
    summary = {
        "status": "data_unavailable",
        "variant_id": SELECTED_VARIANT_ID,
        "period": {"start": start, "end": end, "interval": interval},
        "source": "yfinance_free_no_api_key_start_end",
        "reason": reason,
        "downloaded_symbol_count": len(frames),
        "downloaded_symbols": sorted(frames),
        "rows_per_downloaded_symbol": {symbol: len(frame) for symbol, frame in frames.items()},
        "failures": failures,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pd.DataFrame(failures).to_csv(output_dir / "failures.csv", index=False)
    pd.DataFrame([summary]).drop(columns=["failures"], errors="ignore").to_csv(
        output_dir / "summary.csv", index=False
    )


if __name__ == "__main__":
    main()
