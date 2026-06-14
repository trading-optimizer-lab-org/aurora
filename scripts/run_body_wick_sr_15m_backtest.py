from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_AURORA_POLICY_ROOT = Path(__file__).resolve().parents[1]
if str(_AURORA_POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(_AURORA_POLICY_ROOT))

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


CAMPAIGN_ID = "body_wick_sr_15m_21symbols_backtest"
FINAL_ARTIFACT_NAME = "body-wick-sr-15m-21symbols-backtest-results"
PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
SPLITS = ("train", "validation", "locked")
BARS_PER_YEAR = 252 * 26
TRADE_COLUMNS = (
    "variant_id",
    "symbol",
    "side",
    "split",
    "setup_time",
    "touch_time",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "gross_return",
    "net_return",
    "exit_reason",
    "hold_bars",
    "zone_bottom",
    "zone_top",
)


@dataclass(frozen=True)
class Zone:
    bottom: float
    top: float


@dataclass(frozen=True)
class StrategyVariant:
    variant_id: str
    side: str
    zone_method: str
    setup_candle: str
    min_range_atr: float
    touch_rule: str
    confirmation_rule: str
    invalidation_rule: str
    exit_rule: str
    hold_bars: int
    stop_buffer_atr: float
    target_r: float


def main() -> None:
    require_github_actions_or_explicit_local_permission("body-wick support/resistance 15m backtest")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["shard", "merge"], required=True)
    parser.add_argument("--input-dir", default="")
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--total-stages", type=int, default=1)
    parser.add_argument("--min-symbols", type=int, default=21)
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument("--target-sharpe", type=float, default=1.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if args.mode == "shard":
        run_shard(
            output_dir,
            input_dir=Path(args.input_dir),
            stage=args.stage,
            total_stages=args.total_stages,
            min_symbols=args.min_symbols,
            cost_bps=args.cost_bps,
        )
    else:
        run_merge(output_dir, target_sharpe=args.target_sharpe)


def compute_zone_from_candle(
    candle: pd.Series,
    *,
    side: str,
    zone_method: str,
    atr: float,
) -> Zone | None:
    open_ = float(candle["Open"])
    high = float(candle["High"])
    low = float(candle["Low"])
    close = float(candle["Close"])
    atr = max(float(atr), 0.0)

    if side == "long":
        body_edge = min(open_, close)
        if low >= body_edge:
            return None
        if zone_method == "body_wick":
            bottom, top = low, body_edge
        elif zone_method == "deep_half":
            bottom, top = low, low + (body_edge - low) * 0.5
        elif zone_method == "atr_buffered":
            bottom, top = low, body_edge + atr * 0.05
        else:
            raise ValueError(f"unknown zone method: {zone_method}")
    elif side == "short":
        body_edge = max(open_, close)
        if high <= body_edge:
            return None
        if zone_method == "body_wick":
            bottom, top = body_edge, high
        elif zone_method == "deep_half":
            bottom, top = high - (high - body_edge) * 0.5, high
        elif zone_method == "atr_buffered":
            bottom, top = body_edge - atr * 0.05, high
        else:
            raise ValueError(f"unknown zone method: {zone_method}")
    else:
        raise ValueError(f"unknown side: {side}")

    if not np.isfinite(bottom) or not np.isfinite(top) or bottom >= top:
        return None
    return Zone(bottom=float(bottom), top=float(top))


def build_variant_catalog() -> list[StrategyVariant]:
    variants: list[StrategyVariant] = []
    for side in ("long", "short"):
        for zone_method in ("body_wick", "deep_half", "atr_buffered"):
            for setup_candle in ("color", "range_expansion"):
                for min_range_atr in (0.0, 0.75, 1.25):
                    for touch_rule in ("wick_intersects", "close_inside", "body_overlaps"):
                        for confirmation_rule in (
                            "color_only",
                            "color_and_close_beyond_touch_close",
                            "break_touch_extreme",
                            "engulf_touch_body",
                        ):
                            for invalidation_rule in ("wick_break", "close_break"):
                                for exit_rule in ("time", "zone_stop_time", "zone_stop_target"):
                                    for hold_bars in (2, 4, 8, 13):
                                        target_rs = (1.0, 1.5) if exit_rule == "zone_stop_target" else (1.0,)
                                        for target_r in target_rs:
                                            variant_id = (
                                                f"{side}__{zone_method}__{setup_candle}"
                                                f"__atr{min_range_atr:g}__{touch_rule}"
                                                f"__{confirmation_rule}__{invalidation_rule}"
                                                f"__{exit_rule}__h{hold_bars}__r{target_r:g}"
                                            )
                                            variants.append(
                                                StrategyVariant(
                                                    variant_id=variant_id,
                                                    side=side,
                                                    zone_method=zone_method,
                                                    setup_candle=setup_candle,
                                                    min_range_atr=min_range_atr,
                                                    touch_rule=touch_rule,
                                                    confirmation_rule=confirmation_rule,
                                                    invalidation_rule=invalidation_rule,
                                                    exit_rule=exit_rule,
                                                    hold_bars=hold_bars,
                                                    stop_buffer_atr=0.0,
                                                    target_r=target_r,
                                                )
                                            )
    return variants


def run_shard(
    output_dir: Path,
    *,
    input_dir: Path,
    stage: int,
    total_stages: int,
    min_symbols: int,
    cost_bps: float,
) -> None:
    if total_stages <= 0:
        raise ValueError("total_stages must be positive")
    variants = [v for i, v in enumerate(build_variant_catalog()) if i % total_stages == stage]
    if not variants:
        raise RuntimeError(f"No variants assigned to stage {stage}/{total_stages}")

    bars_by_symbol = load_symbol_bars(input_dir, min_symbols=min_symbols)
    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for variant in variants:
        variant_trades: list[dict[str, Any]] = []
        for symbol, bars in bars_by_symbol.items():
            detected = detect_trades_for_symbol(bars, symbol, variant, cost_bps=cost_bps)
            variant_trades.extend(detected)
        rows.append(summarise_variant(variant, variant_trades))
        trades.extend(variant_trades)

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(
        ["validation_sharpe", "train_sharpe", "trade_count"],
        ascending=[False, False, False],
    ).to_csv(shard_dir / "leaderboard.csv", index=False)
    trades_frame = pd.DataFrame(trades)
    if trades_frame.empty:
        trades_frame = pd.DataFrame(columns=list(TRADE_COLUMNS))
    trades_frame.to_csv(shard_dir / "trades.csv", index=False)
    pd.DataFrame([asdict(v) for v in variants]).to_csv(shard_dir / "variant_catalog.csv", index=False)
    manifest = {
        "campaign_id": CAMPAIGN_ID,
        "stage": stage,
        "total_stages": total_stages,
        "symbols": sorted(bars_by_symbol),
        "symbol_count": len(bars_by_symbol),
        "variant_count": len(variants),
        "cost_bps": cost_bps,
        "selection_policy": "train_ranks_validation_filters_locked_reported_only",
    }
    (shard_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_merge(output_dir: Path, *, target_sharpe: float) -> None:
    shard_root = output_dir / "shards"
    leaderboard_paths = sorted(shard_root.glob("stage_*/leaderboard.csv"))
    trade_paths = sorted(shard_root.glob("stage_*/trades.csv"))
    if not leaderboard_paths:
        raise RuntimeError(f"No shard leaderboards found under {shard_root}")

    leaderboard = pd.concat([pd.read_csv(path) for path in leaderboard_paths], ignore_index=True)
    trade_frames = []
    for path in trade_paths:
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            trade_frames.append(frame)
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame(columns=list(TRADE_COLUMNS))

    leaderboard = leaderboard.sort_values(
        ["validation_sharpe", "train_sharpe", "trade_count"],
        ascending=[False, False, False],
    )
    accepted = leaderboard[
        (leaderboard["train_sharpe"] >= target_sharpe)
        & (leaderboard["validation_sharpe"] >= target_sharpe)
        & (leaderboard["validation_trades"] >= 20)
        & (leaderboard["locked_trades"] >= 20)
        & (leaderboard["locked_profit_factor"] >= 1.0)
    ].copy()

    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    leaderboard.to_csv(final_dir / "leaderboard.csv", index=False)
    accepted.to_csv(final_dir / "accepted.csv", index=False)
    trades.to_csv(final_dir / "trades.csv", index=False)

    symbol_summary = summarise_by_symbol(trades) if not trades.empty else pd.DataFrame()
    symbol_summary.to_csv(final_dir / "symbol_summary.csv", index=False)
    variant_catalog = pd.DataFrame([asdict(v) for v in build_variant_catalog()])
    variant_catalog.to_csv(final_dir / "variant_catalog.csv", index=False)

    symbols = sorted(trades["symbol"].dropna().unique().tolist()) if not trades.empty else []
    manifest = {
        "campaign_id": CAMPAIGN_ID,
        "artifact": FINAL_ARTIFACT_NAME,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "variant_count": int(len(leaderboard)),
        "accepted_count": int(len(accepted)),
        "selection_policy": "train_ranks_validation_filters_locked_reported_only",
        "locked_policy": "reported_after_train_validation_selection_not_used_for_tuning",
    }
    (final_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def load_symbol_bars(input_dir: Path, *, min_symbols: int) -> dict[str, pd.DataFrame]:
    data_dir = find_raw_data_dir(input_dir)
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(data_dir.glob("*_15m.csv")):
        symbol = path.name.removesuffix("_15m.csv").upper()
        frame = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp")
        frame = normalise_bars(frame)
        if len(frame) >= 3:
            frames[symbol] = frame
    if len(frames) < min_symbols:
        raise RuntimeError(f"Solo hay {len(frames)} simbolos validos, minimo requerido {min_symbols}")
    return frames


def find_raw_data_dir(input_dir: Path) -> Path:
    if (input_dir / "data").is_dir():
        return input_dir / "data"
    candidates = sorted(path for path in input_dir.rglob("data") if path.is_dir() and list(path.glob("*_15m.csv")))
    if not candidates:
        raise RuntimeError(f"No encuentro data/*_15m.csv bajo {input_dir}")
    return candidates[0]


def normalise_bars(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.loc[:, list(PRICE_COLUMNS)].copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
    frame["Volume"] = frame["Volume"].fillna(0.0)
    return frame.astype(float)


def detect_trades_for_symbol(
    bars: pd.DataFrame,
    symbol: str,
    variant: StrategyVariant,
    *,
    cost_bps: float = 0.0,
) -> list[dict[str, Any]]:
    frame = normalise_bars(bars)
    if len(frame) < 3:
        return []
    ranges = frame["High"] - frame["Low"]
    atr = ranges.rolling(14, min_periods=1).mean().replace(0.0, np.nan).ffill().fillna(ranges.mean())
    split_by_pos = split_labels(len(frame))
    trades: list[dict[str, Any]] = []

    for setup_pos in range(0, len(frame) - 2):
        setup = frame.iloc[setup_pos]
        setup_atr = float(atr.iloc[setup_pos]) if np.isfinite(atr.iloc[setup_pos]) else float(ranges.mean())
        if not is_setup_candle(frame, setup_pos, variant, setup_atr):
            continue
        zone = compute_zone_from_candle(
            setup,
            side=variant.side,
            zone_method=variant.zone_method,
            atr=setup_atr,
        )
        if zone is None:
            continue

        for touch_pos in range(setup_pos + 1, len(frame) - 1):
            touch = frame.iloc[touch_pos]
            if breaks_zone(touch, zone, side=variant.side, invalidation_rule=variant.invalidation_rule):
                break
            if not touches_zone(touch, zone, touch_rule=variant.touch_rule):
                continue
            confirm_pos = touch_pos + 1
            confirm = frame.iloc[confirm_pos]
            if breaks_zone(confirm, zone, side=variant.side, invalidation_rule=variant.invalidation_rule):
                break
            if not confirms_entry(confirm, touch, side=variant.side, confirmation_rule=variant.confirmation_rule):
                break

            trade = build_trade(
                frame,
                symbol,
                variant,
                zone,
                setup_pos=setup_pos,
                touch_pos=touch_pos,
                entry_pos=confirm_pos,
                split=split_by_pos[confirm_pos],
                atr=float(atr.iloc[confirm_pos]) if np.isfinite(atr.iloc[confirm_pos]) else setup_atr,
                cost_bps=cost_bps,
            )
            if trade is not None:
                trades.append(trade)
            break
    return trades


def split_labels(n: int) -> list[str]:
    third = max(n // 3, 1)
    labels = ["locked"] * n
    for i in range(n):
        if i < third:
            labels[i] = "train"
        elif i < third * 2:
            labels[i] = "validation"
    return labels


def is_setup_candle(frame: pd.DataFrame, pos: int, variant: StrategyVariant, atr: float) -> bool:
    row = frame.iloc[pos]
    is_color = (row["Close"] < row["Open"]) if variant.side == "long" else (row["Close"] > row["Open"])
    if not is_color:
        return False
    candle_range = float(row["High"] - row["Low"])
    if atr > 0 and candle_range / atr < variant.min_range_atr:
        return False
    if variant.setup_candle == "range_expansion":
        lookback = frame.iloc[max(0, pos - 10) : pos]
        if not lookback.empty:
            median_range = float((lookback["High"] - lookback["Low"]).median())
            if median_range > 0 and candle_range < median_range * 1.1:
                return False
    elif variant.setup_candle != "color":
        raise ValueError(f"unknown setup candle rule: {variant.setup_candle}")
    return True


def breaks_zone(candle: pd.Series, zone: Zone, *, side: str, invalidation_rule: str) -> bool:
    if side == "long":
        value = float(candle["Low"] if invalidation_rule == "wick_break" else candle["Close"])
        return value < zone.bottom
    if side == "short":
        value = float(candle["High"] if invalidation_rule == "wick_break" else candle["Close"])
        return value > zone.top
    raise ValueError(f"unknown side: {side}")


def touches_zone(candle: pd.Series, zone: Zone, *, touch_rule: str) -> bool:
    open_ = float(candle["Open"])
    high = float(candle["High"])
    low = float(candle["Low"])
    close = float(candle["Close"])
    if touch_rule == "wick_intersects":
        return low <= zone.top and high >= zone.bottom
    if touch_rule == "close_inside":
        return zone.bottom <= close <= zone.top
    if touch_rule == "body_overlaps":
        body_low = min(open_, close)
        body_high = max(open_, close)
        return body_low <= zone.top and body_high >= zone.bottom
    raise ValueError(f"unknown touch rule: {touch_rule}")


def confirms_entry(confirm: pd.Series, touch: pd.Series, *, side: str, confirmation_rule: str) -> bool:
    open_ = float(confirm["Open"])
    close = float(confirm["Close"])
    touch_open = float(touch["Open"])
    touch_high = float(touch["High"])
    touch_low = float(touch["Low"])
    touch_close = float(touch["Close"])
    if side == "long":
        color_ok = close > open_
        if confirmation_rule == "color_only":
            return color_ok
        if confirmation_rule == "color_and_close_beyond_touch_close":
            return color_ok and close > touch_close
        if confirmation_rule == "break_touch_extreme":
            return color_ok and close > touch_high
        if confirmation_rule == "engulf_touch_body":
            return color_ok and open_ <= touch_close and close >= touch_open
    elif side == "short":
        color_ok = close < open_
        if confirmation_rule == "color_only":
            return color_ok
        if confirmation_rule == "color_and_close_beyond_touch_close":
            return color_ok and close < touch_close
        if confirmation_rule == "break_touch_extreme":
            return color_ok and close < touch_low
        if confirmation_rule == "engulf_touch_body":
            return color_ok and open_ >= touch_close and close <= touch_open
    else:
        raise ValueError(f"unknown side: {side}")
    raise ValueError(f"unknown confirmation rule: {confirmation_rule}")


def build_trade(
    frame: pd.DataFrame,
    symbol: str,
    variant: StrategyVariant,
    zone: Zone,
    *,
    setup_pos: int,
    touch_pos: int,
    entry_pos: int,
    split: str,
    atr: float,
    cost_bps: float,
) -> dict[str, Any] | None:
    entry_price = float(frame.iloc[entry_pos]["Close"])
    if entry_price <= 0 or not np.isfinite(entry_price):
        return None
    exit_pos, exit_price, exit_reason = resolve_exit(
        frame,
        variant,
        zone,
        entry_pos=entry_pos,
        entry_price=entry_price,
        atr=atr,
    )
    if exit_pos <= entry_pos or exit_price <= 0 or not np.isfinite(exit_price):
        return None
    gross_return = (exit_price / entry_price - 1.0) if variant.side == "long" else (entry_price / exit_price - 1.0)
    net_return = gross_return - (2.0 * cost_bps / 10_000.0)
    return {
        "variant_id": variant.variant_id,
        "symbol": symbol,
        "side": variant.side,
        "split": split,
        "setup_time": str(frame.index[setup_pos]),
        "touch_time": str(frame.index[touch_pos]),
        "entry_time": str(frame.index[entry_pos]),
        "exit_time": str(frame.index[exit_pos]),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_return": gross_return,
        "net_return": net_return,
        "exit_reason": exit_reason,
        "hold_bars": int(exit_pos - entry_pos),
        "zone_bottom": zone.bottom,
        "zone_top": zone.top,
        **{f"variant_{k}": v for k, v in asdict(variant).items() if k != "variant_id"},
    }


def resolve_exit(
    frame: pd.DataFrame,
    variant: StrategyVariant,
    zone: Zone,
    *,
    entry_pos: int,
    entry_price: float,
    atr: float,
) -> tuple[int, float, str]:
    last_pos = min(len(frame) - 1, entry_pos + variant.hold_bars)
    if variant.exit_rule == "time":
        return last_pos, float(frame.iloc[last_pos]["Close"]), "time"

    if variant.side == "long":
        stop = zone.bottom - atr * variant.stop_buffer_atr
        risk = max(entry_price - stop, entry_price * 0.001)
        target = entry_price + risk * variant.target_r
        for pos in range(entry_pos + 1, last_pos + 1):
            row = frame.iloc[pos]
            if float(row["Low"]) <= stop:
                return pos, stop, "zone_stop"
            if variant.exit_rule == "zone_stop_target" and float(row["High"]) >= target:
                return pos, target, "target_r"
    elif variant.side == "short":
        stop = zone.top + atr * variant.stop_buffer_atr
        risk = max(stop - entry_price, entry_price * 0.001)
        target = entry_price - risk * variant.target_r
        for pos in range(entry_pos + 1, last_pos + 1):
            row = frame.iloc[pos]
            if float(row["High"]) >= stop:
                return pos, stop, "zone_stop"
            if variant.exit_rule == "zone_stop_target" and float(row["Low"]) <= target:
                return pos, target, "target_r"
    else:
        raise ValueError(f"unknown side: {variant.side}")

    if variant.exit_rule in {"zone_stop_time", "zone_stop_target"}:
        return last_pos, float(frame.iloc[last_pos]["Close"]), "time"
    raise ValueError(f"unknown exit rule: {variant.exit_rule}")


def summarise_variant(variant: StrategyVariant, trades: list[dict[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = asdict(variant)
    row["trade_count"] = len(trades)
    for split in SPLITS:
        metrics = metrics_for_returns([t["net_return"] for t in trades if t["split"] == split])
        row.update({f"{split}_{k}": v for k, v in metrics.items()})
    all_metrics = metrics_for_returns([t["net_return"] for t in trades])
    row.update({f"pooled_{k}": v for k, v in all_metrics.items()})
    row["positive_symbols_locked"] = count_positive_symbols(trades, split="locked")
    return row


def metrics_for_returns(returns: list[float]) -> dict[str, float | int]:
    values = np.asarray([r for r in returns if np.isfinite(r)], dtype=float)
    if len(values) == 0:
        return {
            "trades": 0,
            "mean_return": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_return": 0.0,
        }
    wins = values[values > 0]
    losses = values[values < 0]
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    sharpe = float(values.mean() / std * math.sqrt(BARS_PER_YEAR)) if std > 0 else 0.0
    gross_win = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)
    return {
        "trades": int(len(values)),
        "mean_return": float(values.mean()),
        "sharpe": sharpe,
        "win_rate": float((values > 0).mean()),
        "profit_factor": float(profit_factor),
        "total_return": float(values.sum()),
    }


def count_positive_symbols(trades: list[dict[str, Any]], *, split: str) -> int:
    by_symbol: dict[str, float] = {}
    for trade in trades:
        if trade["split"] != split:
            continue
        by_symbol[trade["symbol"]] = by_symbol.get(trade["symbol"], 0.0) + float(trade["net_return"])
    return sum(1 for value in by_symbol.values() if value > 0)


def summarise_by_symbol(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (symbol, split), group in trades.groupby(["symbol", "split"], dropna=True):
        metrics = metrics_for_returns(group["net_return"].astype(float).tolist())
        rows.append({"symbol": symbol, "split": split, **metrics})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
