from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
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

from scripts.run_spy_15m_support_resistance import (  # noqa: E402
    BARS_PER_YEAR,
    build_feature_frame as build_base_sr_feature_frame,
    feature_families,
    feature_family_for_name,
)


CAMPAIGN_ID = "sr_15m_equity_universe_feature_search"
FINAL_ARTIFACT_NAME = "sr-15m-equity-universe-feature-search-results"
DEFAULT_TARGET_HORIZONS = (1, 2, 4, 8, 13)
DEFAULT_RULES = (
    "linear",
    "threshold_vote",
    "single_feature",
    "pair_spread",
    "mean_reversion",
    "breakout_retest",
    "support_bounce",
    "resistance_reject",
)
PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
NON_FEATURE_COLUMNS = {"target_return", "target_direction", "split", "target_valid"}


def main() -> None:
    require_github_actions_or_explicit_local_permission("15m support/resistance equity universe run")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["features", "screen", "family-search", "mixed-search", "retest", "merge"],
        required=True,
    )
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--input-dir", default="")
    parser.add_argument("--source-candidates", default="")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--total-stages", type=int, default=1)
    parser.add_argument("--min-symbols", type=int, default=20)
    parser.add_argument("--target-bars", type=int, default=4)
    parser.add_argument("--target-horizons", default="1,2,4,8,13")
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument("--target-sharpe", type=float, default=1.0)
    parser.add_argument("--top-n", type=int, default=1000)
    parser.add_argument("--time-budget-minutes", type=float, default=10.0)
    parser.add_argument("--candidates-per-stage", type=int, default=5000)
    parser.add_argument("--min-validation-symbols", type=int, default=8)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    horizons = parse_int_list(args.target_horizons)
    if args.mode == "features":
        run_features(
            output_dir,
            input_dir=Path(args.input_dir) if args.input_dir else output_dir / "source",
            min_symbols=args.min_symbols,
            target_bars=args.target_bars,
            target_horizons=horizons,
        )
    elif args.mode == "screen":
        run_screen(
            output_dir,
            stage=args.stage,
            total_stages=args.total_stages,
            top_n=args.top_n,
            cost_bps=args.cost_bps,
            target_bars=args.target_bars,
            target_horizons=horizons,
        )
    elif args.mode == "family-search":
        run_family_search(
            output_dir,
            stage=args.stage,
            total_stages=args.total_stages,
            top_n=args.top_n,
            cost_bps=args.cost_bps,
            target_bars=args.target_bars,
            target_horizons=horizons,
            time_budget_minutes=args.time_budget_minutes,
        )
    elif args.mode == "mixed-search":
        run_mixed_search(
            output_dir,
            stage=args.stage,
            total_stages=args.total_stages,
            top_n=args.top_n,
            cost_bps=args.cost_bps,
            target_bars=args.target_bars,
            target_horizons=horizons,
            time_budget_minutes=args.time_budget_minutes,
        )
    elif args.mode == "retest":
        run_locked_retest(
            output_dir,
            source_candidates=Path(args.source_candidates) if args.source_candidates else output_dir / "final" / "accepted.csv",
            stage=args.stage,
            candidates_per_stage=args.candidates_per_stage,
            top_n=args.top_n,
            cost_bps=args.cost_bps,
            target_bars=args.target_bars,
        )
    else:
        run_merge(
            output_dir,
            target_sharpe=args.target_sharpe,
            top_n=args.top_n,
            min_validation_symbols=args.min_validation_symbols,
        )


def parse_int_list(raw: str) -> tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not values:
        raise ValueError("target horizons cannot be empty")
    return values


def equal_thirds_split_masks(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if n < 3:
        raise ValueError("Need at least 3 rows for train/validation/locked")
    third = n // 3
    usable = third * 3
    train = np.zeros(n, dtype=bool)
    validation = np.zeros(n, dtype=bool)
    locked = np.zeros(n, dtype=bool)
    train[:third] = True
    validation[third : third * 2] = True
    locked[third * 2 : usable] = True
    return train, validation, locked


def build_equity_feature_panel(
    bars: pd.DataFrame,
    *,
    symbol: str,
    target_bars: int,
    target_horizons: tuple[int, ...] = DEFAULT_TARGET_HORIZONS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    clean = normalise_input_bars(bars)
    usable = (len(clean) // 3) * 3
    if usable < 300:
        raise RuntimeError(f"{symbol}: muy pocas barras para split 3x: {len(clean)}")
    clean = clean.iloc[:usable].copy()

    synthetic = append_synthetic_future_bars(clean, max(max(target_horizons), target_bars))
    base = build_base_sr_feature_frame(synthetic, target_bars=target_bars)
    panel = base.reindex(clean.index).copy()
    add_extended_sr_features(panel, clean)

    close = clean["Close"]
    for horizon in sorted(set(target_horizons) | {target_bars}):
        panel[f"target_return_{horizon}b"] = close.shift(-horizon) / close.replace(0.0, np.nan) - 1.0
        panel[f"target_direction_{horizon}b"] = np.sign(panel[f"target_return_{horizon}b"])
    panel["target_return"] = panel[f"target_return_{target_bars}b"]
    panel["target_direction"] = panel[f"target_direction_{target_bars}b"]
    target_valid = np.ones(len(panel), dtype=bool)
    target_valid[-max(max(target_horizons), target_bars) :] = False
    panel["target_valid"] = target_valid

    train, validation, locked = equal_thirds_split_masks(len(panel))
    split = np.full(len(panel), "", dtype=object)
    split[train] = "train"
    split[validation] = "validation"
    split[locked] = "locked"
    panel["split"] = split
    panel = panel.replace([np.inf, -np.inf], np.nan)

    feature_cols = sr_feature_columns(panel)
    families = feature_families(feature_cols)
    audit = {
        "symbol": symbol,
        "interval": "15m",
        "rows_raw": int(len(clean)),
        "rows_panel": int(len(panel)),
        "first_timestamp": str(panel.index.min()),
        "last_timestamp": str(panel.index.max()),
        "target_bars": int(target_bars),
        "target_horizons": list(target_horizons),
        "split_policy": "equal_temporal_thirds_train_validation_locked",
        "split_rows": {
            "train": int(train.sum()),
            "validation": int(validation.sum()),
            "locked": int(locked.sum()),
        },
        "feature_count": int(len(feature_cols)),
        "feature_families": {name: int(len(cols)) for name, cols in families.items()},
        "locked_policy": "not_used_for_selection_threshold_tuning_or_validation_filter",
    }
    return panel, audit


def normalise_input_bars(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.loc[:, list(PRICE_COLUMNS)]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame.astype(float)


def append_synthetic_future_bars(bars: pd.DataFrame, count: int) -> pd.DataFrame:
    if count <= 0:
        return bars
    last = bars.iloc[-1].copy()
    rows = []
    stamps = []
    current = pd.Timestamp(bars.index[-1])
    for _ in range(count):
        current = current + pd.Timedelta(minutes=15)
        stamps.append(current)
        rows.append(last)
    extra = pd.DataFrame(rows, index=pd.DatetimeIndex(stamps), columns=bars.columns)
    return pd.concat([bars, extra])


def add_extended_sr_features(panel: pd.DataFrame, bars: pd.DataFrame) -> None:
    high = bars["High"]
    low = bars["Low"]
    close = bars["Close"]
    open_ = bars["Open"]
    tr = pd.concat([(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=5).mean().replace(0.0, np.nan)
    tolerance = (atr / close.replace(0.0, np.nan)).fillna(0.0025).clip(0.001, 0.02)
    for window in [8, 26, 52, 130, 260]:
        prior_high = high.rolling(window, min_periods=max(4, window // 4)).max().shift(1)
        prior_low = low.rolling(window, min_periods=max(4, window // 4)).min().shift(1)
        high_gap = close / prior_high.replace(0.0, np.nan) - 1.0
        low_gap = close / prior_low.replace(0.0, np.nan) - 1.0
        near_high = high_gap.abs() <= tolerance
        near_low = low_gap.abs() <= tolerance
        broke_high = close.shift(1) > prior_high.shift(1)
        broke_low = close.shift(1) < prior_low.shift(1)
        panel[f"sr_retest_resistance_after_breakout_{window}b"] = (broke_high & (low <= prior_high) & (close >= prior_high)).astype(float)
        panel[f"sr_retest_support_after_breakdown_{window}b"] = (broke_low & (high >= prior_low) & (close <= prior_low)).astype(float)
        panel[f"sr_fakeout_above_resistance_{window}b"] = ((high > prior_high) & (close < prior_high)).astype(float)
        panel[f"sr_fakeout_below_support_{window}b"] = ((low < prior_low) & (close > prior_low)).astype(float)
        panel[f"sr_reclaim_support_{window}b"] = ((low < prior_low) & (close > prior_low) & (open_ < prior_low)).astype(float)
        panel[f"sr_reject_resistance_{window}b"] = ((high > prior_high) & (close < prior_high) & (open_ > prior_high)).astype(float)
        panel[f"sr_near_resistance_cluster_{window}b"] = near_high.astype(float)
        panel[f"sr_near_support_cluster_{window}b"] = near_low.astype(float)
        panel[f"sr_support_touch_count_{window}b"] = near_low.astype(float).rolling(window, min_periods=3).sum().shift(1)
        panel[f"sr_resistance_touch_count_{window}b"] = near_high.astype(float).rolling(window, min_periods=3).sum().shift(1)


def sr_feature_columns(panel: pd.DataFrame) -> list[str]:
    return [c for c in panel.columns if c.startswith("sr_")]


def run_features(
    output_dir: Path,
    *,
    input_dir: Path,
    min_symbols: int,
    target_bars: int,
    target_horizons: tuple[int, ...] = DEFAULT_TARGET_HORIZONS,
) -> None:
    raw_dir = find_raw_data_dir(input_dir)
    files = sorted(raw_dir.glob("*_15m.csv"))
    if len(files) < min_symbols:
        raise RuntimeError(f"Hay {len(files)} simbolos, minimo requerido {min_symbols}")
    frames: dict[str, pd.DataFrame] = {}
    reference_index: pd.DatetimeIndex | None = None
    for path in files:
        symbol = path.name.replace("_15m.csv", "")
        frame = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp")
        frame = normalise_input_bars(frame)
        reference_index = frame.index if reference_index is None else reference_index
        if not frame.index.equals(reference_index):
            raise RuntimeError(f"{symbol}: timestamps no coinciden con el universo comun")
        frames[symbol] = frame
    if len(frames) < min_symbols:
        raise RuntimeError(f"Hay {len(frames)} simbolos validos, minimo requerido {min_symbols}")

    features_dir = output_dir / "data" / "features"
    features_dir.mkdir(parents=True, exist_ok=True)
    audits: list[dict[str, Any]] = []
    catalog_rows: list[dict[str, Any]] = []
    feature_presence: dict[str, set[str]] = {}
    for symbol, bars in frames.items():
        panel, audit = build_equity_feature_panel(
            bars,
            symbol=symbol,
            target_bars=target_bars,
            target_horizons=target_horizons,
        )
        panel.to_csv(features_dir / f"{symbol}_feature_panel.csv", index_label="timestamp")
        (features_dir / f"{symbol}_feature_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        audits.append(audit)
        for feature in sr_feature_columns(panel):
            feature_presence.setdefault(feature, set()).add(symbol)
    for feature, symbols in sorted(feature_presence.items()):
        catalog_rows.append(
            {
                "feature": feature,
                "family": feature_family_for_name(feature),
                "symbol_count": len(symbols),
                "symbols": "|".join(sorted(symbols)),
            }
        )
    pd.DataFrame(catalog_rows).to_csv(features_dir / "feature_catalog.csv", index=False)
    manifest = {
        "campaign_id": CAMPAIGN_ID,
        "symbols": sorted(frames),
        "symbol_count": len(frames),
        "target_bars": int(target_bars),
        "target_horizons": list(target_horizons),
        "split_policy": "equal_temporal_thirds_train_validation_locked",
        "rows_per_symbol": int(len(next(iter(frames.values())))),
        "feature_count": int(len(catalog_rows)),
        "feature_families": pd.DataFrame(catalog_rows).groupby("family").size().to_dict() if catalog_rows else {},
        "audits": audits,
    }
    (features_dir / "feature_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def find_raw_data_dir(input_dir: Path) -> Path:
    direct = input_dir / "data"
    if list(direct.glob("*_15m.csv")):
        return direct
    matches = sorted(input_dir.glob("**/data/*_15m.csv"))
    if not matches:
        raise RuntimeError(f"No se encontraron CSV 15m bajo {input_dir}")
    return matches[0].parent


def run_screen(
    output_dir: Path,
    *,
    stage: int,
    total_stages: int,
    top_n: int,
    cost_bps: float,
    target_bars: int,
    target_horizons: tuple[int, ...] = DEFAULT_TARGET_HORIZONS,
) -> None:
    universe = load_feature_universe(output_dir)
    features = load_feature_catalog(output_dir)
    tasks: list[dict[str, Any]] = []
    for feature in features:
        for rule in ["linear", "mean_reversion", "support_bounce", "resistance_reject", "breakout_retest"]:
            for horizon in target_horizons:
                tasks.append({"features": [feature], "rule_type": rule, "target_bars": int(horizon), "source": "screen"})
    rows = evaluate_task_slice(tasks, universe, stage=stage, total_stages=total_stages, cost_bps=cost_bps, top_n=top_n)
    write_stage(output_dir / "screen" / f"stage_{stage:03d}", rows, stage=stage, mode="screen")


def run_family_search(
    output_dir: Path,
    *,
    stage: int,
    total_stages: int,
    top_n: int,
    cost_bps: float,
    target_bars: int,
    target_horizons: tuple[int, ...],
    time_budget_minutes: float,
) -> None:
    universe = load_feature_universe(output_dir)
    catalog = pd.read_csv(output_dir / "data" / "features" / "feature_catalog.csv")
    by_family = {
        family: frame["feature"].tolist()
        for family, frame in catalog.groupby("family")
        if len(frame) > 0
    }
    family_names = sorted(by_family)
    rng = np.random.default_rng(20_000 + stage)
    deadline = time.monotonic() + max(0.1, time_budget_minutes) * 60.0
    tasks: list[dict[str, Any]] = []
    attempts = 0
    while time.monotonic() < deadline and attempts < 2500:
        family = family_names[(stage + attempts) % len(family_names)]
        pool = by_family[family]
        size = int(rng.integers(2, min(8, len(pool)) + 1)) if len(pool) >= 2 else 1
        features = sorted(rng.choice(pool, size=size, replace=False).tolist())
        tasks.append(
            {
                "features": features,
                "rule_type": str(rng.choice(DEFAULT_RULES)),
                "target_bars": int(rng.choice(target_horizons)),
                "source": "family-search",
                "focus_family": family,
            }
        )
        attempts += 1
    rows = evaluate_task_slice(tasks, universe, stage=0, total_stages=1, cost_bps=cost_bps, top_n=top_n)
    write_stage(output_dir / "family_search" / f"stage_{stage:03d}", rows, stage=stage, mode="family-search")


def run_mixed_search(
    output_dir: Path,
    *,
    stage: int,
    total_stages: int,
    top_n: int,
    cost_bps: float,
    target_bars: int,
    target_horizons: tuple[int, ...],
    time_budget_minutes: float,
) -> None:
    universe = load_feature_universe(output_dir)
    catalog = pd.read_csv(output_dir / "data" / "features" / "feature_catalog.csv")
    families = {
        family: frame["feature"].tolist()
        for family, frame in catalog.groupby("family")
        if len(frame) > 0
    }
    confluences = [
        ("vwap", "pivots"),
        ("opening_range", "rolling_levels"),
        ("fractal_pivots", "round_numbers"),
        ("volume_profile", "gaps"),
        ("fibonacci", "fractal_pivots"),
        ("session", "candles"),
        ("confluence", "rolling_levels"),
    ]
    rng = np.random.default_rng(30_000 + stage)
    deadline = time.monotonic() + max(0.1, time_budget_minutes) * 60.0
    tasks: list[dict[str, Any]] = []
    attempts = 0
    while time.monotonic() < deadline and attempts < 2500:
        left, right = confluences[(stage + attempts) % len(confluences)]
        if left not in families or right not in families:
            attempts += 1
            continue
        features = [
            str(rng.choice(families[left])),
            str(rng.choice(families[right])),
        ]
        tasks.append(
            {
                "features": sorted(set(features)),
                "rule_type": str(rng.choice(DEFAULT_RULES)),
                "target_bars": int(rng.choice(target_horizons)),
                "source": "mixed-search",
                "focus_family": f"{left}+{right}",
            }
        )
        attempts += 1
    rows = evaluate_task_slice(tasks, universe, stage=0, total_stages=1, cost_bps=cost_bps, top_n=top_n)
    write_stage(output_dir / "mixed_search" / f"stage_{stage:03d}", rows, stage=stage, mode="mixed-search")


def load_feature_catalog(output_dir: Path) -> list[str]:
    catalog = pd.read_csv(output_dir / "data" / "features" / "feature_catalog.csv")
    return [str(v) for v in catalog["feature"].tolist() if str(v).startswith("sr_")]


def load_feature_universe(output_dir: Path) -> dict[str, pd.DataFrame]:
    features_dir = output_dir / "data" / "features"
    out: dict[str, pd.DataFrame] = {}
    for path in sorted(features_dir.glob("*_feature_panel.csv")):
        symbol = path.name.replace("_feature_panel.csv", "")
        if symbol in {"feature_catalog", "feature_manifest"}:
            continue
        out[symbol] = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp")
    if not out:
        raise RuntimeError(f"No feature panels found under {features_dir}")
    return out


def evaluate_task_slice(
    tasks: list[dict[str, Any]],
    universe: dict[str, pd.DataFrame],
    *,
    stage: int,
    total_stages: int,
    cost_bps: float,
    top_n: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_stages = max(1, int(total_stages))
    for i, task in enumerate(tasks):
        if i % total_stages != int(stage):
            continue
        try:
            rows.append(evaluate_candidate_on_universe(task, universe, cost_bps=cost_bps, include_locked=False))
        except Exception as exc:
            rows.append(
                {
                    "strategy_id": strategy_id(task),
                    "accepted": False,
                    "score": -999.0,
                    "error": str(exc),
                    "params_json": json.dumps(task, sort_keys=True),
                    "selection_split": "train_validation_only",
                }
            )
        if len(rows) > top_n * 4:
            rows = select_top(rows, top_n * 2)
    return select_top(rows, top_n)


def evaluate_candidate_on_universe(
    task: dict[str, Any],
    universe: dict[str, pd.DataFrame],
    *,
    cost_bps: float,
    include_locked: bool,
) -> dict[str, Any]:
    target_col = f"target_return_{int(task.get('target_bars', 4))}b"
    features = [str(f) for f in task["features"] if str(f).startswith("sr_")]
    if not features:
        raise RuntimeError("Candidate has no sr_* features")
    train_scores: list[np.ndarray] = []
    train_targets: list[np.ndarray] = []
    per_symbol_prepared: dict[str, dict[str, np.ndarray]] = {}
    for symbol, panel in universe.items():
        prepared = prepare_symbol_arrays(panel, features, target_col)
        per_symbol_prepared[symbol] = prepared
        train_scores.append(build_score(prepared["x"], task)[prepared["train"]])
        train_targets.append(prepared["target"][prepared["train"]])
    pooled_train_score = np.concatenate(train_scores)
    pooled_train_target = np.concatenate(train_targets)
    threshold, side_policy, invert, train_metrics = choose_policy_train_only(
        pooled_train_score,
        pooled_train_target,
        cost_bps=cost_bps,
        target_bars=int(task.get("target_bars", 4)),
    )
    validation_metrics_by_symbol: list[dict[str, float]] = []
    locked_metrics_by_symbol: list[dict[str, float]] = []
    validation_net_by_symbol: dict[str, float] = {}
    locked_net_by_symbol: dict[str, float] = {}
    validation_positions: list[np.ndarray] = []
    validation_targets: list[np.ndarray] = []
    locked_positions: list[np.ndarray] = []
    locked_targets: list[np.ndarray] = []
    for symbol, prepared in per_symbol_prepared.items():
        score = build_score(prepared["x"], task)
        oriented = -score if invert else score
        positions = positions_from_score(oriented, threshold, side_policy)
        val = prepared["validation"]
        validation_positions.append(positions[val])
        validation_targets.append(prepared["target"][val])
        val_metrics = metrics(positions[val], prepared["target"][val], cost_bps=cost_bps, target_bars=int(task.get("target_bars", 4)))
        validation_metrics_by_symbol.append(val_metrics)
        validation_net_by_symbol[symbol] = float(val_metrics["total_return"])
        if include_locked:
            locked = prepared["locked"]
            locked_positions.append(positions[locked])
            locked_targets.append(prepared["target"][locked])
            locked_metrics = metrics(positions[locked], prepared["target"][locked], cost_bps=cost_bps, target_bars=int(task.get("target_bars", 4)))
            locked_metrics_by_symbol.append(locked_metrics)
            locked_net_by_symbol[symbol] = float(locked_metrics["total_return"])

    validation_pooled = metrics(
        np.concatenate(validation_positions),
        np.concatenate(validation_targets),
        cost_bps=cost_bps,
        target_bars=int(task.get("target_bars", 4)),
    )
    validation_positive_symbols = sum(v > 0.0 for v in validation_net_by_symbol.values())
    row: dict[str, Any] = {
        "strategy_id": strategy_id(task),
        "accepted": bool(train_metrics["sharpe"] >= 0.0 and validation_pooled["sharpe"] >= 0.0),
        "score": float(validation_pooled["sharpe"] + 0.25 * train_metrics["sharpe"]),
        "train_sharpe": float(train_metrics["sharpe"]),
        "validation_sharpe": float(validation_pooled["sharpe"]),
        "validation_median_symbol_sharpe": float(np.median([m["sharpe"] for m in validation_metrics_by_symbol])),
        "validation_profit_factor": float(validation_pooled["profit_factor"]),
        "validation_max_drawdown": float(validation_pooled["max_drawdown"]),
        "validation_trades": int(validation_pooled["trades"]),
        "validation_positive_symbols": int(validation_positive_symbols),
        "threshold": float(threshold),
        "side_policy": side_policy,
        "invert": int(invert),
        "rule_type": str(task.get("rule_type", "linear")),
        "focus_family": str(task.get("focus_family", feature_family_for_name(features[0]))),
        "families": "|".join(sorted({feature_family_for_name(f) for f in features})),
        "features": "|".join(features),
        "target_bars": int(task.get("target_bars", 4)),
        "params_json": json.dumps({**task, "threshold": threshold, "side_policy": side_policy, "invert": invert}, sort_keys=True),
        "selection_split": "train_validation_only",
    }
    if include_locked:
        locked_pooled = metrics(
            np.concatenate(locked_positions),
            np.concatenate(locked_targets),
            cost_bps=cost_bps,
            target_bars=int(task.get("target_bars", 4)),
        )
        locked_symbol_sharpes = [m["sharpe"] for m in locked_metrics_by_symbol]
        locked_positive_symbols = sum(v > 0.0 for v in locked_net_by_symbol.values())
        largest_symbol_share = largest_abs_share(locked_net_by_symbol)
        validation_sharpe = float(row["validation_sharpe"])
        row.update(
            {
                "locked_sharpe_pooled": float(locked_pooled["sharpe"]),
                "locked_median_symbol_sharpe": float(np.median(locked_symbol_sharpes)) if locked_symbol_sharpes else 0.0,
                "locked_profit_factor_pooled": float(locked_pooled["profit_factor"]),
                "locked_max_drawdown_pooled": float(locked_pooled["max_drawdown"]),
                "locked_trades_pooled": int(locked_pooled["trades"]),
                "locked_positive_symbols": int(locked_positive_symbols),
                "locked_largest_symbol_pnl_share": float(largest_symbol_share),
                "final_accepted": bool(
                    (np.median(locked_symbol_sharpes) if locked_symbol_sharpes else 0.0) >= 1.0
                    and locked_pooled["profit_factor"] >= 1.05
                    and locked_positive_symbols >= 12
                    and locked_pooled["trades"] >= 60
                    and locked_pooled["max_drawdown"] >= -0.10
                    and largest_symbol_share <= 0.25
                    and (validation_sharpe <= 0.0 or locked_pooled["sharpe"] >= validation_sharpe * 0.30)
                ),
            }
        )
    return row


def prepare_symbol_arrays(panel: pd.DataFrame, features: list[str], target_col: str) -> dict[str, np.ndarray]:
    missing = [f for f in features if f not in panel.columns]
    if missing:
        raise RuntimeError(f"Missing features: {missing}")
    if target_col not in panel.columns:
        raise RuntimeError(f"Missing target column: {target_col}")
    split = panel["split"].astype(str)
    target = pd.to_numeric(panel[target_col], errors="coerce")
    valid_target = target.notna() & panel.get("target_valid", True).astype(bool)
    train_mask = (split == "train") & valid_target
    validation_mask = (split == "validation") & valid_target
    locked_mask = (split == "locked") & valid_target
    x = panel[features].replace([np.inf, -np.inf], np.nan)
    med = x.loc[train_mask].median(numeric_only=True).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    filled = x.fillna(med).fillna(0.0)
    mean = filled.loc[train_mask].mean()
    std = filled.loc[train_mask].std().replace(0.0, np.nan).fillna(1.0)
    z = ((filled - mean) / std).clip(-8.0, 8.0).fillna(0.0)
    return {
        "x": z.to_numpy(dtype=float),
        "target": target.fillna(0.0).to_numpy(dtype=float),
        "train": train_mask.to_numpy(dtype=bool),
        "validation": validation_mask.to_numpy(dtype=bool),
        "locked": locked_mask.to_numpy(dtype=bool),
    }


def build_score(x: np.ndarray, task: dict[str, Any]) -> np.ndarray:
    rule = str(task.get("rule_type", "linear"))
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    if rule == "threshold_vote":
        return np.sign(x).sum(axis=1)
    if rule == "single_feature":
        return x[:, 0]
    if rule == "pair_spread" and x.shape[1] >= 2:
        return x[:, 0] - x[:, 1]
    if rule in {"mean_reversion", "support_bounce"}:
        return -x.mean(axis=1)
    if rule in {"resistance_reject", "breakout_retest"}:
        return x.mean(axis=1)
    return x.mean(axis=1)


def choose_policy_train_only(
    score: np.ndarray,
    target: np.ndarray,
    *,
    cost_bps: float,
    target_bars: int,
) -> tuple[float, str, int, dict[str, float]]:
    if len(score) == 0 or np.nanstd(score) == 0.0:
        return 0.0, "long_flat", 0, empty_metrics()
    quantiles = np.unique(np.nanquantile(score, [0.20, 0.35, 0.50, 0.65, 0.80]))
    best: tuple[float, str, int, dict[str, float]] | None = None
    best_objective = -float("inf")
    for invert in [0, 1]:
        oriented = -score if invert else score
        for threshold in quantiles:
            for policy in ["long_short", "long_flat", "short_flat"]:
                positions = positions_from_score(oriented, float(threshold), policy)
                out = metrics(positions, target, cost_bps=cost_bps, target_bars=target_bars)
                objective = out["sharpe"] + 0.10 * math.log1p(max(out["trades"], 0.0))
                if objective > best_objective:
                    best_objective = objective
                    best = (float(threshold), policy, invert, out)
    assert best is not None
    return best


def positions_from_score(score: np.ndarray, threshold: float, policy: str) -> np.ndarray:
    if policy == "long_flat":
        return np.where(score >= threshold, 1.0, 0.0)
    if policy == "short_flat":
        return np.where(score <= threshold, -1.0, 0.0)
    return np.where(score >= threshold, 1.0, -1.0)


def metrics(positions: np.ndarray, returns: np.ndarray, *, cost_bps: float, target_bars: int) -> dict[str, float]:
    positions = np.asarray(positions, dtype=float)
    returns = np.asarray(returns, dtype=float)
    finite = np.isfinite(positions) & np.isfinite(returns)
    positions = positions[finite]
    returns = returns[finite]
    if len(positions) == 0:
        return empty_metrics()
    turnover = np.abs(np.diff(np.r_[0.0, positions]))
    net = positions * returns - turnover * (cost_bps / 10_000.0)
    active = np.abs(positions) > 0.0
    sharpe = float(np.nanmean(net) / np.nanstd(net) * math.sqrt(BARS_PER_YEAR / max(1, target_bars))) if np.nanstd(net) > 0.0 else 0.0
    gains = float(net[net > 0.0].sum())
    losses = float(net[net < 0.0].sum())
    equity = np.cumprod(1.0 + np.nan_to_num(net, nan=0.0))
    peak = np.maximum.accumulate(equity) if len(equity) else np.asarray([1.0])
    drawdown = equity / np.where(peak == 0.0, 1.0, peak) - 1.0
    return {
        "sharpe": sharpe,
        "profit_factor": gains / abs(losses) if losses < 0.0 else float("inf") if gains > 0.0 else 0.0,
        "hit_rate": float(np.mean(net[active] > 0.0)) if np.any(active) else 0.0,
        "max_drawdown": float(np.nanmin(drawdown)) if len(drawdown) else 0.0,
        "trades": float(np.sum(turnover > 0.0)),
        "exposure": float(np.mean(active)),
        "total_return": float(np.prod(1.0 + np.nan_to_num(net, nan=0.0)) - 1.0),
        "mean_return": float(np.nanmean(net)),
    }


def empty_metrics() -> dict[str, float]:
    return {
        "sharpe": 0.0,
        "profit_factor": 0.0,
        "hit_rate": 0.0,
        "max_drawdown": 0.0,
        "trades": 0.0,
        "exposure": 0.0,
        "total_return": 0.0,
        "mean_return": 0.0,
    }


def largest_abs_share(values: dict[str, float]) -> float:
    if not values:
        return 0.0
    total = sum(abs(v) for v in values.values())
    if total <= 0.0:
        return 0.0
    return max(abs(v) for v in values.values()) / total


def strategy_id(task: dict[str, Any]) -> str:
    text = json.dumps(task, sort_keys=True)
    return "sr20_15m_" + f"{abs(hash(text)) % 10_000_000:07d}"


def select_top(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            bool(row.get("final_accepted", row.get("accepted", False))),
            float(row.get("score", row.get("locked_sharpe_pooled", 0.0)) or 0.0),
            float(row.get("validation_sharpe", 0.0) or 0.0),
        ),
        reverse=True,
    )[:limit]


def write_stage(path: Path, rows: list[dict[str, Any]], *, stage: int, mode: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path / "top_candidates.csv", index=False)
    (path / "stage_summary.json").write_text(
        json.dumps({"stage": int(stage), "mode": mode, "rows": len(rows)}, indent=2),
        encoding="utf-8",
    )


def run_merge(
    output_dir: Path,
    *,
    target_sharpe: float,
    top_n: int,
    min_validation_symbols: int,
) -> None:
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    candidate_frames = []
    for root in ["screen", "family_search", "mixed_search"]:
        for path in (output_dir / root).glob("**/top_candidates.csv"):
            try:
                frame = pd.read_csv(path)
            except Exception:
                continue
            if not frame.empty:
                candidate_frames.append(frame)
    if candidate_frames:
        data = pd.concat(candidate_frames, ignore_index=True)
        data = data.drop_duplicates(subset=["strategy_id"], keep="first")
        data["accepted"] = (
            (pd.to_numeric(data["train_sharpe"], errors="coerce") >= target_sharpe)
            & (pd.to_numeric(data["validation_sharpe"], errors="coerce") >= target_sharpe)
            & (pd.to_numeric(data["validation_positive_symbols"], errors="coerce") >= min_validation_symbols)
        )
        data = pd.DataFrame(select_top(data.to_dict("records"), top_n))
    else:
        data = pd.DataFrame()
    data.to_csv(final_dir / "leaderboard.csv", index=False)
    accepted = data[data["accepted"].astype(bool)].copy() if not data.empty and "accepted" in data else data
    accepted.to_csv(final_dir / "accepted.csv", index=False)
    write_summary_files(output_dir, data)

    locked_frames = []
    for path in (output_dir / "locked").glob("**/locked_results.csv"):
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if not frame.empty:
            locked_frames.append(frame)
    if locked_frames:
        locked = pd.concat(locked_frames, ignore_index=True)
        locked = locked.drop_duplicates(subset=["strategy_id"], keep="first")
        locked = pd.DataFrame(select_top(locked.to_dict("records"), top_n))
        locked.to_csv(final_dir / "locked_results.csv", index=False)
        locked[locked["final_accepted"].astype(bool)].to_csv(final_dir / "accepted.csv", index=False)
        (final_dir / "retest_summary.json").write_text(
            json.dumps(
                {
                    "locked_rows": int(len(locked)),
                    "final_accepted": int(locked["final_accepted"].astype(bool).sum()),
                    "best_locked_sharpe": float(pd.to_numeric(locked["locked_sharpe_pooled"], errors="coerce").max()),
                    "locked_policy": "opened_only_after_train_validation_candidate_selection",
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def write_summary_files(output_dir: Path, data: pd.DataFrame) -> None:
    final_dir = output_dir / "final"
    if data.empty:
        pd.DataFrame().to_csv(final_dir / "feature_summary.csv", index=False)
        pd.DataFrame().to_csv(final_dir / "family_summary.csv", index=False)
        pd.DataFrame().to_csv(final_dir / "symbol_summary.csv", index=False)
        (final_dir / "retest_summary.json").write_text(json.dumps({"rows": 0}, indent=2), encoding="utf-8")
        return
    feature_rows = []
    for feature in sorted({part for value in data["features"].fillna("") for part in str(value).split("|") if part}):
        subset = data[data["features"].fillna("").str.contains(feature, regex=False)]
        feature_rows.append(
            {
                "feature": feature,
                "family": feature_family_for_name(feature),
                "rows": int(len(subset)),
                "accepted": int(subset["accepted"].astype(bool).sum()),
                "best_validation_sharpe": float(pd.to_numeric(subset["validation_sharpe"], errors="coerce").max()),
            }
        )
    pd.DataFrame(feature_rows).to_csv(final_dir / "feature_summary.csv", index=False)
    family_rows = []
    for family in sorted({part for value in data["families"].fillna("") for part in str(value).split("|") if part}):
        subset = data[data["families"].fillna("").str.contains(family, regex=False)]
        family_rows.append(
            {
                "family": family,
                "rows": int(len(subset)),
                "accepted": int(subset["accepted"].astype(bool).sum()),
                "best_validation_sharpe": float(pd.to_numeric(subset["validation_sharpe"], errors="coerce").max()),
            }
        )
    pd.DataFrame(family_rows).to_csv(final_dir / "family_summary.csv", index=False)
    manifest_path = output_dir / "data" / "features" / "feature_manifest.json"
    symbols = json.loads(manifest_path.read_text(encoding="utf-8")).get("symbols", []) if manifest_path.exists() else []
    pd.DataFrame({"symbol": symbols}).to_csv(final_dir / "symbol_summary.csv", index=False)
    (final_dir / "retest_summary.json").write_text(
        json.dumps(
            {
                "rows": int(len(data)),
                "accepted": int(data["accepted"].astype(bool).sum()),
                "best_validation_sharpe": float(pd.to_numeric(data["validation_sharpe"], errors="coerce").max()),
                "locked_opened": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_locked_retest(
    output_dir: Path,
    *,
    source_candidates: Path,
    stage: int,
    candidates_per_stage: int,
    top_n: int,
    cost_bps: float,
    target_bars: int,
) -> None:
    if not source_candidates.exists():
        raise RuntimeError(f"Source candidates not found: {source_candidates}")
    candidates = pd.read_csv(source_candidates)
    start = int(stage) * int(candidates_per_stage)
    stop = min(len(candidates), start + int(candidates_per_stage))
    universe = load_feature_universe(output_dir)
    rows: list[dict[str, Any]] = []
    for _, row in candidates.iloc[start:stop].iterrows():
        task = json.loads(str(row["params_json"]))
        evaluated = evaluate_candidate_on_universe(task, universe, cost_bps=cost_bps, include_locked=True)
        evaluated["strategy_id"] = str(row.get("strategy_id", evaluated["strategy_id"]))
        rows.append(evaluated)
    out_dir = output_dir / "locked" / f"stage_{stage:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(select_top(rows, top_n)).to_csv(out_dir / "locked_results.csv", index=False)
    (out_dir / "locked_summary.json").write_text(
        json.dumps({"stage": int(stage), "rows": len(rows), "locked_opened": True}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
