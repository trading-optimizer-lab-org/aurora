from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

_AURORA_POLICY_ROOT = Path(__file__).resolve().parents[1]
if str(_AURORA_POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(_AURORA_POLICY_ROOT))

from core.execution_policy import require_github_actions_or_explicit_local_permission

import numpy as np
import pandas as pd
import yfinance as yf

from scripts.run_spy_weekly_longshort_sharpe2 import (
    TRAIN_END,
    VALIDATION_END,
    VALIDATION_START,
    annual_excess_metrics,
    build_feature_frame,
    build_positions_train_only,
    build_spy_daily_weekly_features,
    metrics,
    position_audit,
    turnover,
)


LOCKED_START = pd.Timestamp("2021-01-01")
REQUIRED_SYMBOLS = [
    "SPY",
    "^VIX",
    "^TNX",
    "^IRX",
    "^FVX",
    "^TYX",
    "DX-Y.NYB",
    "^GSPC",
    "^IXIC",
    "^RUT",
    "^DJI",
    "^FTSE",
    "^N225",
    "^GDAXI",
    "^HSI",
]
OPTIONAL_SYMBOLS = [
    "QQQ",
    "DIA",
    "IWM",
    "XLY",
    "XLP",
    "XLK",
    "XLU",
    "XLF",
    "XLE",
    "XLV",
    "XLI",
    "XLB",
    "TLT",
    "IEF",
    "SHY",
    "GLD",
    "LQD",
    "HYG",
    "EFA",
    "EEM",
]


def main() -> None:
    require_github_actions_or_explicit_local_permission("spy weekly longshort locked strategy report")
    parser = argparse.ArgumentParser(description="Open locked report for one saved SPY weekly long/short strategy.")
    parser.add_argument("--source-dir", required=True, help="Directory containing downloaded source run artifacts.")
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--output-dir", default="outputs/spy_weekly_longshort_locked_strategy_report")
    parser.add_argument("--start", default="1995-01-01")
    parser.add_argument("--locked-start", default="2021-01-01")
    args = parser.parse_args()

    locked_start = pd.Timestamp(args.locked_start)
    source_dir = Path(args.source_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    row, row_path = _find_strategy_row(source_dir, args.strategy_id)
    prices, returns = _download_weekly_data(start=args.start)
    feature_frame = build_feature_frame(prices, returns)
    spy_rets = returns["SPY"].reindex(feature_frame.index).astype(float)

    train_mask = feature_frame.index <= TRAIN_END
    validation_mask = (feature_frame.index >= VALIDATION_START) & (feature_frame.index <= VALIDATION_END)
    locked_mask = feature_frame.index >= locked_start
    if int(np.sum(locked_mask)) < 20:
        raise RuntimeError("Not enough locked rows to report.")

    params = json.loads(row["params_json"])
    base_positions, train_selected = build_positions_train_only(
        feature_frame.to_numpy(dtype=float),
        spy_rets.to_numpy(dtype=float),
        train_mask.to_numpy(dtype=bool) if hasattr(train_mask, "to_numpy") else np.asarray(train_mask, dtype=bool),
        params,
    )
    base_positions = np.asarray(base_positions, dtype=float)
    original_scale = float(row.get("exposure_scale") or params.get("exposure_scale") or 1.0)
    versions = [
        ("original_scale", original_scale),
        ("normalized_1x", 1.0),
    ]

    summary_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    weekly_rows: list[dict[str, Any]] = []
    for version, scale in versions:
        positions = base_positions * float(scale)
        strategy_returns = positions * spy_rets.to_numpy(dtype=float)
        _append_period_summary(
            summary_rows,
            version=version,
            period="train",
            dates=feature_frame.index[train_mask],
            strategy_returns=strategy_returns[train_mask],
            spy_returns=spy_rets.to_numpy(dtype=float)[train_mask],
            positions=positions[train_mask],
        )
        _append_period_summary(
            summary_rows,
            version=version,
            period="validation",
            dates=feature_frame.index[validation_mask],
            strategy_returns=strategy_returns[validation_mask],
            spy_returns=spy_rets.to_numpy(dtype=float)[validation_mask],
            positions=positions[validation_mask],
        )
        _append_period_summary(
            summary_rows,
            version=version,
            period="locked",
            dates=feature_frame.index[locked_mask],
            strategy_returns=strategy_returns[locked_mask],
            spy_returns=spy_rets.to_numpy(dtype=float)[locked_mask],
            positions=positions[locked_mask],
        )
        annual_rows.extend(
            _annual_rows(
                version=version,
                period="train",
                dates=feature_frame.index[train_mask],
                strategy_returns=strategy_returns[train_mask],
                spy_returns=spy_rets.to_numpy(dtype=float)[train_mask],
                expected_years=range(1995, 2011),
            )
        )
        annual_rows.extend(
            _annual_rows(
                version=version,
                period="validation",
                dates=feature_frame.index[validation_mask],
                strategy_returns=strategy_returns[validation_mask],
                spy_returns=spy_rets.to_numpy(dtype=float)[validation_mask],
                expected_years=range(2011, 2021),
            )
        )
        locked_years = range(int(locked_start.year), int(feature_frame.index[locked_mask].max().year) + 1)
        annual_rows.extend(
            _annual_rows(
                version=version,
                period="locked",
                dates=feature_frame.index[locked_mask],
                strategy_returns=strategy_returns[locked_mask],
                spy_returns=spy_rets.to_numpy(dtype=float)[locked_mask],
                expected_years=locked_years,
            )
        )
        for ts, strat_ret, spy_ret, pos in zip(
            feature_frame.index[locked_mask],
            strategy_returns[locked_mask],
            spy_rets.to_numpy(dtype=float)[locked_mask],
            positions[locked_mask],
            strict=False,
        ):
            weekly_rows.append(
                {
                    "strategy_id": args.strategy_id,
                    "version": version,
                    "timestamp": ts.date().isoformat(),
                    "strategy_return": float(strat_ret),
                    "spy_return": float(spy_ret),
                    "position": float(pos),
                }
            )

    pd.DataFrame(summary_rows).to_csv(output_dir / "spy_weekly_locked_summary.csv", index=False)
    pd.DataFrame(annual_rows).to_csv(output_dir / "spy_weekly_locked_annual_returns.csv", index=False)
    pd.DataFrame(weekly_rows).to_csv(output_dir / "spy_weekly_locked_weekly_returns.csv", index=False)
    _write_strategy_spec(output_dir, row=row, row_path=row_path, params=params, train_selected=train_selected)
    audit = {
        "strategy_id": args.strategy_id,
        "source_row_path": str(row_path),
        "locked_opened": True,
        "locked_requested_by_user": True,
        "locked_start": locked_start.date().isoformat(),
        "locked_end": feature_frame.index[locked_mask].max().date().isoformat(),
        "validation_used_for_selection": False,
        "data_start": feature_frame.index.min().date().isoformat(),
        "data_end": feature_frame.index.max().date().isoformat(),
        "versions": [{"name": name, "scale": scale} for name, scale in versions],
        "source_train_sharpe": _float_or_nan(row.get("train_sharpe")),
        "source_validation_sharpe": _float_or_nan(row.get("validation_sharpe")),
        "source_exposure_scale": original_scale,
    }
    (output_dir / "locked_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")


def _find_strategy_row(source_dir: Path, strategy_id: str) -> tuple[dict[str, str], Path]:
    preferred = [
        "spy_weekly_longshort_beat_spy_all_years_verified.csv",
        "spy_weekly_longshort_sharpe2_verified.csv",
        "spy_weekly_longshort_sharpe2_leaderboard.csv",
        "verified_candidates_report_only.csv",
        "top_candidates.csv",
        "validation_ceiling_diagnostic.csv",
    ]
    candidates = sorted(source_dir.rglob("*.csv"), key=lambda p: (preferred.index(p.name) if p.name in preferred else 999, str(p)))
    for path in candidates:
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames or "strategy_id" not in reader.fieldnames:
                    continue
                for row in reader:
                    if str(row.get("strategy_id", "")) == strategy_id:
                        return row, path
        except UnicodeDecodeError:
            continue
    raise FileNotFoundError(f"Strategy {strategy_id} not found under {source_dir}")


def _download_weekly_data(*, start: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    symbols = REQUIRED_SYMBOLS + OPTIONAL_SYMBOLS
    end = (pd.Timestamp.utcnow().normalize() + pd.Timedelta(days=1)).date().isoformat()
    raw = yf.download(
        symbols,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    prices = pd.DataFrame()
    for symbol in symbols:
        try:
            prices[symbol] = raw[symbol]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
        except Exception:
            prices[symbol] = np.nan
    prices = prices.dropna(subset=REQUIRED_SYMBOLS, how="any")
    weekly_prices = prices.resample("W-FRI").last().dropna(subset=REQUIRED_SYMBOLS, how="any")
    spy_raw = raw["SPY"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw.copy()
    spy_ohlcv = pd.DataFrame(
        {
            "SPY_OPEN": spy_raw["Open"].resample("W-FRI").first(),
            "SPY_HIGH": spy_raw["High"].resample("W-FRI").max(),
            "SPY_LOW": spy_raw["Low"].resample("W-FRI").min(),
            "SPY_VOLUME": spy_raw["Volume"].resample("W-FRI").sum(),
        }
    )
    spy_daily_features = build_spy_daily_weekly_features(spy_raw)
    weekly_prices = weekly_prices.join(spy_ohlcv, how="left").join(spy_daily_features, how="left")
    weekly_prices = weekly_prices.dropna(subset=REQUIRED_SYMBOLS + ["SPY_OPEN", "SPY_HIGH", "SPY_LOW", "SPY_VOLUME"], how="any")
    weekly_returns = weekly_prices[symbols].pct_change(fill_method=None).dropna(subset=["SPY"], how="any")
    return weekly_prices, weekly_returns


def _append_period_summary(
    rows: list[dict[str, Any]],
    *,
    version: str,
    period: str,
    dates: pd.DatetimeIndex,
    strategy_returns: np.ndarray,
    spy_returns: np.ndarray,
    positions: np.ndarray,
) -> None:
    strat = metrics(strategy_returns)
    spy = metrics(spy_returns)
    audit = position_audit(positions)
    rows.append(
        {
            "version": version,
            "period": period,
            "start": dates.min().date().isoformat(),
            "end": dates.max().date().isoformat(),
            "weeks": int(len(dates)),
            "strategy_cagr": strat["cagr"],
            "spy_cagr": spy["cagr"],
            "strategy_sharpe": strat["sharpe"],
            "spy_sharpe": spy["sharpe"],
            "strategy_mdd": strat["mdd"],
            "spy_mdd": spy["mdd"],
            "strategy_positive_weeks_pct": strat["positive_weeks_pct"],
            "spy_positive_weeks_pct": spy["positive_weeks_pct"],
            "turnover_weekly": turnover(positions),
            **audit,
        }
    )


def _annual_rows(
    *,
    version: str,
    period: str,
    dates: pd.DatetimeIndex,
    strategy_returns: np.ndarray,
    spy_returns: np.ndarray,
    expected_years: range,
) -> list[dict[str, Any]]:
    annual = annual_excess_metrics(strategy_returns, spy_returns, dates, expected_years=expected_years)
    out = []
    for year in expected_years:
        key = str(int(year))
        out.append(
            {
                "version": version,
                "period": period,
                "year": int(year),
                "strategy_return": annual["strategy_returns"].get(key, np.nan),
                "spy_return": annual["spy_returns"].get(key, np.nan),
                "excess_vs_spy": annual["excess"].get(key, np.nan),
                "beats_or_equals_spy": bool(
                    np.isfinite(annual["excess"].get(key, np.nan)) and annual["excess"].get(key, np.nan) >= 0.0
                ),
            }
        )
    return out


def _write_strategy_spec(output_dir: Path, *, row: dict[str, str], row_path: Path, params: dict[str, Any], train_selected: dict[str, float]) -> None:
    payload = {
        "source_row_path": str(row_path),
        "strategy_id": row.get("strategy_id"),
        "traded_asset": row.get("traded_asset"),
        "frequency": row.get("frequency"),
        "position_policy": row.get("position_policy"),
        "cash_allowed": row.get("cash_allowed"),
        "leverage_allowed": row.get("leverage_allowed"),
        "max_leverage": row.get("max_leverage"),
        "exposure_scale": row.get("exposure_scale"),
        "rule_type": row.get("rule_type"),
        "features": row.get("features"),
        "threshold": row.get("threshold"),
        "invert": row.get("invert"),
        "params": params,
        "recomputed_train_selection_metrics": train_selected,
    }
    (output_dir / "strategy_spec.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _float_or_nan(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return math.nan


if __name__ == "__main__":
    main()
