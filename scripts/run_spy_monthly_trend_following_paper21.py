from __future__ import annotations

import sys
from pathlib import Path as _AuroraPolicyPath

_AURORA_POLICY_ROOT = _AuroraPolicyPath(__file__).resolve().parents[1]
if str(_AURORA_POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(_AURORA_POLICY_ROOT))

try:
    from core.execution_policy import require_github_actions_or_explicit_local_permission
except ModuleNotFoundError:
    import os

    def require_github_actions_or_explicit_local_permission() -> None:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            return
        if os.environ.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == "USER_REQUESTED_LOCAL_RUN_THIS_TURN":
            return
        raise RuntimeError("Research runs must execute in GitHub Actions unless explicitly allowed this turn.")

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


CAMPAIGN_ID = "spy_monthly_trend_following_paper21_355jobs"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
PPY = 12

BASE_FAMILIES = ("breakout_daily_high", "ma_monthly_close", "ma_daily_close", "combo_vote")
DAILY_WINDOWS = (150, 180, 200, 220, 250, 275, 300, 350, 400, 450)
MONTHLY_WINDOWS = (6, 8, 10, 12, 14, 16, 18, 20)
BUFFERS = (-0.005, 0.0, 0.005, 0.01)
CONFIRM_MONTHS = (1, 2, 3)
CASH_SOURCES = ("zero", "tbill")
LAG_MONTHS = (1, 2)


def main() -> None:
    require_github_actions_or_explicit_local_permission()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=1000)
    parser.add_argument("--time-budget-minutes", type=float, default=8.0)
    parser.add_argument("--top-per-stage", type=int, default=80)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=int(args.stage),
            configs_per_stage=int(args.configs_per_stage),
            time_budget_minutes=float(args.time_budget_minutes),
            top_per_stage=int(args.top_per_stage),
        )
    else:
        run_merge(output_dir)


def run_data(output_dir: Path) -> None:
    cache_dir = output_dir / "yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(str(cache_dir))
    if hasattr(yf, "cache") and hasattr(yf.cache, "set_cache_location"):
        yf.cache.set_cache_location(str(cache_dir))

    raw = pd.DataFrame()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            raw = yf.download(
                ["SPY", "^IRX"],
                start="1994-01-01",
                end="2021-01-01",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=False,
            )
            if not raw.empty and not _close(raw, "SPY").dropna().empty:
                break
        except Exception as exc:  # yfinance may raise on transient cache/network faults.
            last_error = exc
        time.sleep(2.0 * (attempt + 1))
    if raw.empty:
        if last_error is not None:
            raise RuntimeError("yfinance returned no data") from last_error
        raise RuntimeError("yfinance returned no data")

    spy = _close(raw, "SPY").dropna()
    if spy.empty:
        raise RuntimeError("missing SPY close")
    spy = spy[spy.index < LOCKED_START]
    if spy.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into daily SPY")

    irx = _close(raw, "^IRX").reindex(spy.index).ffill() if _has_symbol(raw, "^IRX") else pd.Series(0.0, index=spy.index)
    daily = pd.DataFrame({"SPY": spy, "IRX": irx}, index=spy.index).dropna(subset=["SPY"])
    monthly_price = daily["SPY"].resample("ME").last().dropna()
    monthly_spy_ret = monthly_price.pct_change(fill_method=None)
    monthly_cash = monthly_tbill_return(daily["IRX"]).reindex(monthly_spy_ret.index).fillna(0.0)
    monthly = pd.DataFrame({"SPY": monthly_spy_ret, "CASH_ZERO": 0.0, "CASH_TBILL": monthly_cash}, index=monthly_spy_ret.index)
    monthly = monthly.dropna(subset=["SPY"])
    monthly = monthly[(monthly.index >= TRAIN_START) & (monthly.index < LOCKED_START)]
    monthly_price = monthly_price.reindex(monthly.index)

    if monthly.index.max() >= LOCKED_START or daily.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into prepared data")
    if monthly.index.min() > pd.Timestamp("1995-03-31"):
        raise RuntimeError(f"insufficient monthly history: {monthly.index.min()}")

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    daily.to_csv(data_dir / "daily_prices.csv", index_label="timestamp")
    monthly_price.to_frame("SPY").to_csv(data_dir / "monthly_prices.csv", index_label="timestamp")
    monthly.to_csv(data_dir / "monthly_returns.csv", index_label="timestamp")
    (data_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "asset": "SPY",
                "cash_allowed": True,
                "short_allowed": False,
                "leverage_allowed": False,
                "min_position": 0.0,
                "max_position": 1.0,
                "frequency": "monthly",
                "locked_opened": False,
                "locked_start": str(LOCKED_START.date()),
                "data_end_max": str(max(monthly.index.max(), daily.index.max()).date()),
                "source": "yfinance",
                "paper_source": "Clare Seaton Smith Thomas 2013 trend following stop losses frequency S&P500",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _has_symbol(raw: pd.DataFrame, symbol: str) -> bool:
    return isinstance(raw.columns, pd.MultiIndex) and symbol in raw.columns.get_level_values(0)


def _close(raw: pd.DataFrame, symbol: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol not in raw.columns.get_level_values(0):
            return pd.Series(dtype=float)
        return pd.to_numeric(raw[symbol]["Close"], errors="coerce")
    return pd.to_numeric(raw["Close"], errors="coerce")


def monthly_tbill_return(irx: pd.Series) -> pd.Series:
    annual_yield = pd.to_numeric(irx, errors="coerce").ffill().fillna(0.0) / 100.0
    daily_return = annual_yield / 360.0
    return (1.0 + daily_return).resample("ME").prod(min_count=1) - 1.0


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
) -> None:
    daily = pd.read_csv(output_dir / "data" / "daily_prices.csv", parse_dates=["timestamp"]).set_index("timestamp")
    monthly_prices = pd.read_csv(output_dir / "data" / "monthly_prices.csv", parse_dates=["timestamp"]).set_index("timestamp")["SPY"]
    monthly_returns = pd.read_csv(output_dir / "data" / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if daily.index.max() >= LOCKED_START or monthly_returns.index.max() >= LOCKED_START:
        raise RuntimeError("locked data reached shard")

    exact = exact_configs()
    rng = np.random.default_rng(20260621 + stage * 1_000_003)
    started = time.monotonic()
    deadline = started + max(1.0, time_budget_minutes) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    for idx in range(max(0, int(configs_per_stage))):
        if time.monotonic() >= deadline:
            break
        params = exact[idx] if idx < len(exact) and stage == 0 else sample_params(rng, stage)
        evaluated += 1
        row = evaluate_params(params, daily["SPY"], monthly_prices, monthly_returns)
        row["stage"] = int(stage)
        row["config_index"] = int(idx)
        rows.append(row)

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(
            ["validation_score", "train_score", "validation_sharpe", "train_sharpe"],
            ascending=[False, False, False, False],
        ).head(max(1, int(top_per_stage)))
    frame.to_csv(shard_dir / "candidates.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "configs_evaluated": int(evaluated),
                "rows_written": int(len(frame)),
                "families": list(BASE_FAMILIES),
                "locked_opened": False,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def exact_configs() -> list[dict[str, Any]]:
    return [
        {
            "family": "breakout_daily_high",
            "daily_window": 250,
            "monthly_window": 12,
            "confirm_months": 1,
            "buffer": 0.0,
            "cash_source": "tbill",
            "lag_months": 1,
        },
        {
            "family": "ma_monthly_close",
            "daily_window": 200,
            "monthly_window": 10,
            "confirm_months": 1,
            "buffer": 0.0,
            "cash_source": "tbill",
            "lag_months": 1,
        },
        {
            "family": "ma_monthly_close",
            "daily_window": 200,
            "monthly_window": 12,
            "confirm_months": 1,
            "buffer": 0.0,
            "cash_source": "tbill",
            "lag_months": 1,
        },
        {
            "family": "ma_daily_close",
            "daily_window": 200,
            "monthly_window": 10,
            "confirm_months": 1,
            "buffer": 0.0,
            "cash_source": "tbill",
            "lag_months": 1,
        },
    ]


def sample_params(rng: np.random.Generator, stage: int) -> dict[str, Any]:
    family = BASE_FAMILIES[stage % len(BASE_FAMILIES)] if rng.random() < 0.65 else str(rng.choice(BASE_FAMILIES))
    return {
        "family": family,
        "daily_window": int(rng.choice(DAILY_WINDOWS)),
        "monthly_window": int(rng.choice(MONTHLY_WINDOWS)),
        "confirm_months": int(rng.choice(CONFIRM_MONTHS)),
        "buffer": float(rng.choice(BUFFERS)),
        "cash_source": str(rng.choice(CASH_SOURCES)),
        "lag_months": int(rng.choice(LAG_MONTHS)),
    }


def evaluate_params(
    params: dict[str, Any],
    daily_price: pd.Series,
    monthly_price: pd.Series,
    monthly_returns: pd.DataFrame,
) -> dict[str, Any]:
    signal = build_signal(params, daily_price, monthly_price).reindex(monthly_returns.index).fillna(False)
    confirm = max(1, int(params["confirm_months"]))
    if confirm > 1:
        signal = signal.rolling(confirm, min_periods=confirm).sum().eq(confirm).fillna(False)
    lag = max(1, int(params["lag_months"]))
    position = signal.shift(lag).fillna(False).astype(float).clip(0.0, 1.0)
    cash_col = "CASH_TBILL" if params["cash_source"] == "tbill" else "CASH_ZERO"
    spy = pd.to_numeric(monthly_returns["SPY"], errors="coerce")
    cash = pd.to_numeric(monthly_returns[cash_col], errors="coerce").reindex(spy.index).fillna(0.0)
    strategy = position * spy + (1.0 - position) * cash

    train_mask = (strategy.index >= TRAIN_START) & (strategy.index <= TRAIN_END)
    validation_mask = (strategy.index >= VALIDATION_START) & (strategy.index <= VALIDATION_END)
    train = metrics(strategy[train_mask])
    validation = metrics(strategy[validation_mask])
    spy_train = metrics(spy[train_mask])
    spy_validation = metrics(spy[validation_mask])
    train_years = annual_score(strategy[train_mask], spy[train_mask])
    validation_years = annual_score(strategy[validation_mask], spy[validation_mask])

    payload = dict(params)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    train_score = score(train, spy_train, train_years)
    validation_score = score(validation, spy_validation, validation_years)
    return {
        "strategy_id": f"spy_monthly_tf21_{params['family']}_{digest}",
        **payload,
        "train_cagr": train["cagr"],
        "train_sharpe": train["sharpe"],
        "train_mdd": train["mdd"],
        "train_calmar": train["calmar"],
        "train_final_nav": train["final_nav"],
        "spy_train_cagr": spy_train["cagr"],
        "spy_train_sharpe": spy_train["sharpe"],
        "validation_cagr": validation["cagr"],
        "validation_sharpe": validation["sharpe"],
        "validation_mdd": validation["mdd"],
        "validation_calmar": validation["calmar"],
        "validation_final_nav": validation["final_nav"],
        "spy_validation_cagr": spy_validation["cagr"],
        "spy_validation_sharpe": spy_validation["sharpe"],
        "train_years_beating_spy": train_years["years_beating_spy"],
        "train_years_total": train_years["years_total"],
        "validation_years_beating_spy": validation_years["years_beating_spy"],
        "validation_years_total": validation_years["years_total"],
        "train_score": train_score,
        "validation_score": validation_score,
        "avg_position": float(position.mean()),
        "trades": int(position.diff().abs().fillna(0.0).sum()),
        "locked_opened": False,
        "leverage_allowed": False,
        "short_allowed": False,
    }


def build_signal(params: dict[str, Any], daily_price: pd.Series, monthly_price: pd.Series) -> pd.Series:
    family = str(params["family"])
    daily_window = int(params["daily_window"])
    monthly_window = int(params["monthly_window"])
    buffer = float(params["buffer"])

    daily_ma = daily_price.rolling(daily_window, min_periods=max(20, daily_window // 3)).mean().resample("ME").last()
    daily_high = daily_price.rolling(daily_window, min_periods=max(20, daily_window // 3)).max().resample("ME").last()
    monthly_ma = monthly_price.rolling(monthly_window, min_periods=max(3, monthly_window // 2)).mean()
    daily_ma = daily_ma.reindex(monthly_price.index).ffill()
    daily_high = daily_high.reindex(monthly_price.index).ffill()
    monthly_ma = monthly_ma.reindex(monthly_price.index)

    ma_daily = monthly_price > daily_ma * (1.0 + buffer)
    ma_monthly = monthly_price > monthly_ma * (1.0 + buffer)
    breakout = monthly_price >= daily_high * (1.0 + buffer)
    if family == "breakout_daily_high":
        return breakout
    if family == "ma_monthly_close":
        return ma_monthly
    if family == "ma_daily_close":
        return ma_daily
    if family == "combo_vote":
        votes = pd.concat([breakout, ma_monthly, ma_daily], axis=1).fillna(False).sum(axis=1)
        return votes >= 2
    raise ValueError(f"unknown family: {family}")


def metrics(values: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"cagr": float("nan"), "sharpe": float("nan"), "mdd": float("nan"), "calmar": float("nan"), "final_nav": float("nan")}
    nav = (1.0 + clean).cumprod()
    years = max(len(clean) / PPY, 1e-9)
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(clean.std(ddof=1) * np.sqrt(PPY)) if len(clean) > 1 else 0.0
    sharpe = float(clean.mean() * PPY / vol) if vol > 0 else float("nan")
    dd = nav / nav.cummax() - 1.0
    mdd = float(dd.min())
    calmar = float(cagr / abs(mdd)) if mdd < 0 else float("nan")
    return {"cagr": cagr, "sharpe": sharpe, "mdd": mdd, "calmar": calmar, "final_nav": float(nav.iloc[-1])}


def annual_score(strategy: pd.Series, benchmark: pd.Series) -> dict[str, int]:
    frame = pd.DataFrame({"strategy": strategy, "spy": benchmark}).dropna()
    if frame.empty:
        return {"years_beating_spy": 0, "years_total": 0}
    annual = (1.0 + frame).resample("YE").prod(min_count=1) - 1.0
    return {
        "years_beating_spy": int((annual["strategy"] > annual["spy"]).sum()),
        "years_total": int(len(annual)),
    }


def score(strategy: dict[str, float], spy: dict[str, float], annual: dict[str, int]) -> float:
    years_total = max(1, int(annual["years_total"]))
    beat_ratio = float(annual["years_beating_spy"]) / years_total
    return float(
        2.0 * safe(strategy["sharpe"])
        + safe(strategy["calmar"])
        + 4.0 * (safe(strategy["cagr"]) - safe(spy["cagr"]))
        + beat_ratio
        - 0.5 * max(0.0, abs(safe(strategy["mdd"])) - 0.35)
    )


def safe(value: float) -> float:
    return float(value) if np.isfinite(value) else -99.0


def run_merge(output_dir: Path) -> None:
    frames = []
    summaries = []
    for shard in sorted((output_dir / "shards").glob("**/candidates.csv")):
        if shard.stat().st_size > 0:
            frames.append(pd.read_csv(shard))
    for summary_path in sorted((output_dir / "shards").glob("**/shard_summary.json")):
        summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))

    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.drop_duplicates(subset=["strategy_id"]).sort_values(
            ["validation_score", "train_score", "validation_sharpe", "train_sharpe"],
            ascending=[False, False, False, False],
        )
    else:
        combined = pd.DataFrame()

    combined.to_csv(final_dir / "leaderboard.csv", index=False)
    top = combined.head(100).copy() if not combined.empty else combined
    top.to_csv(final_dir / "top100.csv", index=False)
    family_summary = family_summary_frame(combined)
    family_summary.to_csv(final_dir / "family_summary.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "stages_expected": 355,
        "stages_reported": len(summaries),
        "candidates": int(len(combined)),
        "best_strategy_id": str(top.iloc[0]["strategy_id"]) if not top.empty else "",
        "best_family": str(top.iloc[0]["family"]) if not top.empty else "",
        "best_validation_sharpe": float(top.iloc[0]["validation_sharpe"]) if not top.empty else None,
        "best_validation_cagr": float(top.iloc[0]["validation_cagr"]) if not top.empty else None,
        "locked_opened": False,
        "rules_tested": {
            "base": [
                "breakout mensual 250 dias",
                "media movil mensual 10 meses",
                "media movil mensual 12 meses",
                "media movil diaria 200 dias evaluada a cierre mensual",
            ],
            "families": list(BASE_FAMILIES),
            "daily_windows": list(DAILY_WINDOWS),
            "monthly_windows": list(MONTHLY_WINDOWS),
            "buffers": list(BUFFERS),
            "confirm_months": list(CONFIRM_MONTHS),
            "cash_sources": list(CASH_SOURCES),
            "lag_months": list(LAG_MONTHS),
        },
    }
    if summary["stages_reported"] == 0 or summary["candidates"] == 0:
        raise RuntimeError("No shard candidates were merged; refusing false-green final artifact.")
    (final_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def family_summary_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    rows = []
    for family, group in frame.groupby("family"):
        best = group.sort_values(["validation_score", "train_score"], ascending=[False, False]).iloc[0]
        rows.append(
            {
                "family": family,
                "candidates": int(len(group)),
                "best_strategy_id": str(best["strategy_id"]),
                "best_validation_sharpe": float(best["validation_sharpe"]),
                "best_validation_cagr": float(best["validation_cagr"]),
                "best_validation_mdd": float(best["validation_mdd"]),
                "best_train_sharpe": float(best["train_sharpe"]),
            }
        )
    return pd.DataFrame(rows).sort_values("best_validation_sharpe", ascending=False)


if __name__ == "__main__":
    main()
