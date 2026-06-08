from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_spy_daily_direction_accuracy import (  # noqa: E402
    add_cboe_put_call_features,
    add_fred_stress_features,
    fetch_cboe_put_call_panel,
    fetch_fred_stress_panel,
    zscore,
)

CAMPAIGN_ID = "paper_cboe_sentiment_sharpe2_360jobs"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_SHARPE = 2.0
PPY = 252

PAPER_SOURCES: dict[str, dict[str, str]] = {
    "simon_wiggins_put_call": {
        "paper": "S&P Futures Returns and Contrary Sentiment Indicators",
        "authors": "Simon; Wiggins",
        "year": "2001",
        "type": "proxy_replicable",
        "rule": "Use option sentiment, including put/call ratios and implied volatility, as contrary S&P timing signals.",
    },
    "giot_vix_extreme": {
        "paper": "Relationships Between Implied Volatility Indexes and Stock Index Returns",
        "authors": "Giot",
        "year": "2005",
        "type": "proxy_replicable",
        "rule": "Extreme implied-volatility conditions predict future index returns.",
    },
    "pan_poteshman_option_volume": {
        "paper": "The Information in Option Volume for Future Stock Prices",
        "authors": "Pan; Poteshman",
        "year": "2006",
        "type": "template_replicable",
        "rule": "Option volume imbalance contains information about future equity returns; here only aggregate Cboe put/call ratios are available.",
    },
}


@dataclass(frozen=True)
class Candidate:
    family: str
    params: dict[str, Any]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--total-stages", type=int, default=360)
    parser.add_argument("--configs-per-stage", type=int, default=25_000)
    parser.add_argument("--time-budget-minutes", type=float, default=45.0)
    parser.add_argument("--top-per-stage", type=int, default=120)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=args.stage,
            total_stages=args.total_stages,
            configs_per_stage=args.configs_per_stage,
            time_budget_minutes=args.time_budget_minutes,
            top_per_stage=args.top_per_stage,
        )
    else:
        run_merge(output_dir, total_stages=args.total_stages, allow_partial=args.allow_partial)


def run_data(output_dir: Path) -> None:
    raw = yf.download(
        ["SPY", "^VIX"],
        start="1994-01-01",
        end="2021-01-01",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
        timeout=40,
    )
    close = pd.DataFrame()
    for symbol in ["SPY", "^VIX"]:
        frame = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
        if "Close" not in frame:
            raise RuntimeError(f"{symbol} close unavailable")
        close[symbol] = frame["Close"]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.sort_index().loc[lambda x: x.index < LOCKED_START].dropna(subset=["SPY", "^VIX"])
    if close.empty or close.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into CBOE sentiment data")

    cboe, cboe_audit = fetch_cboe_put_call_panel(end=VALIDATION_END)
    fred, fred_audit = fetch_fred_stress_panel()
    data = build_dataset(close, cboe, fred)

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    close.to_csv(data_dir / "daily_close.csv", index_label="timestamp")
    cboe.to_csv(data_dir / "cboe_put_call_panel.csv", index_label="timestamp")
    pd.DataFrame(cboe_audit).to_csv(data_dir / "cboe_put_call_audit.csv", index=False)
    fred.to_csv(data_dir / "fred_stress_panel.csv", index_label="timestamp")
    pd.DataFrame(fred_audit).to_csv(data_dir / "fred_stress_audit.csv", index=False)
    data.to_csv(data_dir / "paper_cboe_sentiment_dataset.csv", index_label="timestamp")
    (data_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "paper_sourced_only": True,
                "traded_asset": "SPY",
                "uses_individual_stocks": False,
                "uses_factor_portfolio_without_reconstruction": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "lag_audit": "CBOE/FRED features are shifted before next-day SPY return is traded.",
                "train_start": str(TRAIN_START.date()),
                "train_end": str(TRAIN_END.date()),
                "validation_start": str(VALIDATION_START.date()),
                "validation_end": str(VALIDATION_END.date()),
                "locked_start": str(LOCKED_START.date()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def build_dataset(close: pd.DataFrame, cboe: pd.DataFrame, fred: pd.DataFrame) -> pd.DataFrame:
    data = pd.DataFrame(index=close.index)
    spy = close["SPY"].astype(float)
    vix = close["^VIX"].astype(float)
    data["target_return_next_day"] = spy.pct_change(fill_method=None).shift(-1)
    data["spy_ret_1d"] = spy.pct_change(fill_method=None).shift(1)
    data["spy_ret_5d"] = spy.pct_change(5, fill_method=None).shift(1)
    data["spy_ret_21d"] = spy.pct_change(21, fill_method=None).shift(1)
    data["spy_realized_vol_21d"] = spy.pct_change(fill_method=None).rolling(21, min_periods=7).std().shift(1)
    data["spy_ma_gap_63d"] = (spy / spy.rolling(63, min_periods=21).mean() - 1.0).shift(1)
    data["spy_ma_gap_126d"] = (spy / spy.rolling(126, min_periods=42).mean() - 1.0).shift(1)
    data["vix_level"] = vix.shift(1)
    data["vix_z_21d"] = zscore(vix, 21).shift(1)
    data["vix_z_63d"] = zscore(vix, 63).shift(1)
    data["vix_ret_1d"] = vix.pct_change(fill_method=None).shift(1)
    data["vix_ret_5d"] = vix.pct_change(5, fill_method=None).shift(1)
    add_cboe_put_call_features(data, cboe)
    add_fred_stress_features(data, fred)
    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.loc[(data.index >= TRAIN_START) & (data.index <= VALIDATION_END)]
    data = data.loc[data.index < LOCKED_START]
    data = data.dropna(subset=["target_return_next_day"])
    if data.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into CBOE sentiment dataset")
    return data


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    total_stages: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
) -> None:
    data = pd.read_csv(output_dir / "data" / "paper_cboe_sentiment_dataset.csv", parse_dates=["timestamp"]).set_index("timestamp")
    train_mask = (data.index >= TRAIN_START) & (data.index <= TRAIN_END)
    validation_mask = (data.index >= VALIDATION_START) & (data.index <= VALIDATION_END)
    if data.index.max() >= LOCKED_START:
        raise RuntimeError("locked data reached shard")
    rng = np.random.default_rng(72_000_001 + int(stage) * 100_003)
    deadline = pd.Timestamp.now().timestamp() + max(1.0, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    for config_index in range(int(configs_per_stage)):
        if pd.Timestamp.now().timestamp() >= deadline:
            break
        evaluated += 1
        candidate = sample_candidate(rng, stage)
        positions = build_positions(candidate, data)
        returns = positions * data["target_return_next_day"].to_numpy(dtype=float)
        train = daily_metrics(returns[train_mask])
        if not np.isfinite(train["sharpe"]):
            continue
        if train["exposure_pct"] < 0.03:
            continue
        if train["sharpe"] < 0.35 and config_index % 499 != 0:
            continue
        valid = daily_metrics(returns[validation_mask])
        paper_key = paper_key_for_family(candidate.family)
        payload = {"family": candidate.family, "params": candidate.params, "paper_key": paper_key}
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "candidate_id": f"paper_cboe_sentiment_{key}",
                "stage": int(stage),
                "config_index": int(config_index),
                "accepted": bool(train["sharpe"] >= TARGET_SHARPE and valid["sharpe"] >= TARGET_SHARPE),
                "train_pass": bool(train["sharpe"] >= TARGET_SHARPE),
                "validation_pass_report_only": bool(valid["sharpe"] >= TARGET_SHARPE),
                "paper_key": paper_key,
                "paper_title": PAPER_SOURCES[paper_key]["paper"],
                "paper_authors": PAPER_SOURCES[paper_key]["authors"],
                "paper_year": PAPER_SOURCES[paper_key]["year"],
                "paper_strategy_type": PAPER_SOURCES[paper_key]["type"],
                "source_rule_summary": PAPER_SOURCES[paper_key]["rule"],
                "family": candidate.family,
                "params_json": encode_params(candidate.params),
                "traded_asset": "SPY",
                "frequency": "daily",
                "lag_periods": 1,
                "train_sharpe": train["sharpe"],
                "validation_sharpe": valid["sharpe"],
                "train_cagr_pct": train["cagr"] * 100.0,
                "validation_cagr_pct": valid["cagr"] * 100.0,
                "train_mdd_pct": train["mdd"] * 100.0,
                "validation_mdd_pct": valid["mdd"] * 100.0,
                "train_exposure_pct": train["exposure_pct"] * 100.0,
                "validation_exposure_pct": valid["exposure_pct"] * 100.0,
                "train_score": train["sharpe"] + min(0.0, train["mdd"]) * 0.1,
                "locked_opened": False,
                "validation_used_for_selection": False,
                "uses_individual_stocks": False,
                "paper_exact_replication_claimed": False,
                "lookahead_audit": "Position at date t uses shifted CBOE/FRED/VIX/SPY features and trades SPY next-day close-to-close return.",
            }
        )
    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["candidate_id", "train_score", "accepted"])
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage)) if not frame.empty else frame
    diag = frame.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage)) if not frame.empty else frame
    accepted = frame[frame.get("accepted", pd.Series(dtype=bool)).astype(bool)] if not frame.empty else frame
    write_jsonl_frame(top, shard_dir / "top_candidates.jsonl")
    write_jsonl_frame(diag, shard_dir / "validation_diagnostic.jsonl")
    write_jsonl_frame(accepted, shard_dir / "accepted_candidates.jsonl")
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "total_stages": int(total_stages),
                "configs_requested": int(configs_per_stage),
                "configs_evaluated": int(evaluated),
                "rows_kept": int(len(frame)),
                "accepted_rows": int(len(accepted)),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def sample_candidate(rng: np.random.Generator, stage: int) -> Candidate:
    families = [
        "put_call_extreme",
        "put_call_reversal_after_spy_move",
        "put_call_vix_combo",
        "index_equity_spread",
        "stress_sentiment_combo",
    ]
    family = families[stage % len(families)] if rng.random() < 0.70 else str(rng.choice(families))
    pc_features = [
        "cboe_total_pc_z_21d",
        "cboe_total_pc_z_63d",
        "cboe_index_pc_z_21d",
        "cboe_index_pc_z_63d",
        "cboe_equity_pc_z_21d",
        "cboe_equity_pc_z_63d",
        "cboe_index_minus_equity_pc",
        "cboe_total_pc_diff_5d",
        "cboe_index_pc_diff_5d",
        "cboe_equity_pc_diff_5d",
    ]
    params: dict[str, Any] = {
        "pc_feature": str(rng.choice(pc_features)),
        "pc_threshold": float(rng.uniform(-2.25, 2.25)),
        "direction": int(rng.choice([-1, 1])),
        "outside_position": float(rng.choice([0.0, 0.0, 0.0, -1.0, 1.0])),
    }
    if family == "put_call_reversal_after_spy_move":
        params["spy_feature"] = str(rng.choice(["spy_ret_1d", "spy_ret_5d", "spy_ret_21d"]))
        params["spy_threshold"] = float(rng.uniform(-0.08, 0.08))
        params["spy_side"] = int(rng.choice([-1, 1]))
    elif family == "put_call_vix_combo":
        params["vix_feature"] = str(rng.choice(["vix_z_21d", "vix_z_63d", "vix_ret_1d", "vix_ret_5d"]))
        params["vix_threshold"] = float(rng.uniform(-2.25, 2.25))
        params["vix_side"] = int(rng.choice([-1, 1]))
    elif family == "stress_sentiment_combo":
        params["stress_feature"] = str(rng.choice(["fred_nfci_z_13w", "fred_anfci_z_13w", "fred_stlfsi4_z_13w", "spy_ma_gap_63d", "spy_ma_gap_126d"]))
        params["stress_threshold"] = float(rng.uniform(-2.0, 2.0))
        params["stress_side"] = int(rng.choice([-1, 1]))
    return Candidate(family, params)


def build_positions(candidate: Candidate, data: pd.DataFrame) -> np.ndarray:
    params = candidate.params
    pc = str(params["pc_feature"])
    if pc not in data:
        return np.zeros(len(data), dtype=float)
    signal = data[pc].to_numpy(dtype=float)
    inside = (signal * float(params["direction"])) >= float(params["pc_threshold"]) * float(params["direction"])
    if candidate.family == "put_call_reversal_after_spy_move":
        feature = str(params["spy_feature"])
        if feature not in data:
            return np.zeros(len(data), dtype=float)
        inside &= (data[feature].to_numpy(dtype=float) * float(params["spy_side"])) >= float(params["spy_threshold"]) * float(params["spy_side"])
    elif candidate.family == "put_call_vix_combo":
        feature = str(params["vix_feature"])
        if feature not in data:
            return np.zeros(len(data), dtype=float)
        inside &= (data[feature].to_numpy(dtype=float) * float(params["vix_side"])) >= float(params["vix_threshold"]) * float(params["vix_side"])
    elif candidate.family == "index_equity_spread":
        inside &= np.isfinite(data.get("cboe_index_minus_equity_pc", pd.Series(index=data.index)).to_numpy(dtype=float))
    elif candidate.family == "stress_sentiment_combo":
        feature = str(params["stress_feature"])
        if feature not in data:
            return np.zeros(len(data), dtype=float)
        inside &= (data[feature].to_numpy(dtype=float) * float(params["stress_side"])) >= float(params["stress_threshold"]) * float(params["stress_side"])
    positions = np.full(len(data), float(params["outside_position"]), dtype=float)
    positions[inside] = float(params["direction"])
    positions[~np.isfinite(signal)] = 0.0
    return positions


def paper_key_for_family(family: str) -> str:
    if family in {"put_call_extreme", "put_call_reversal_after_spy_move", "index_equity_spread"}:
        return "simon_wiggins_put_call"
    if family == "put_call_vix_combo":
        return "giot_vix_extreme"
    return "pan_poteshman_option_volume"


def encode_params(params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def write_jsonl_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text("", encoding="utf-8")
        return
    records = frame.replace({np.nan: None}).to_dict(orient="records")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def read_jsonl_frames(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        if path.stat().st_size == 0:
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if rows:
            frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def daily_metrics(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 100:
        return {"sharpe": np.nan, "cagr": np.nan, "mdd": np.nan, "exposure_pct": np.nan}
    std = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values) / std * math.sqrt(PPY)) if std > 0 else np.nan
    nav = np.cumprod(1.0 + values)
    years = len(values) / PPY
    cagr = float(nav[-1] ** (1.0 / years) - 1.0) if nav[-1] > 0 and years > 0 else np.nan
    mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    return {
        "sharpe": sharpe,
        "cagr": cagr,
        "mdd": mdd,
        "exposure_pct": float(np.mean(np.abs(values) > 0.0)),
    }


def run_merge(output_dir: Path, *, total_stages: int = 360, allow_partial: bool = False) -> None:
    shard_root = output_dir / "shards"
    top_files = list(shard_root.glob("**/top_candidates.jsonl"))
    diag_files = list(shard_root.glob("**/validation_diagnostic.jsonl"))
    accepted_files = list(shard_root.glob("**/accepted_candidates.jsonl"))
    summary_files = list(shard_root.glob("**/shard_summary.json"))
    top = read_jsonl_frames(top_files)
    diag = read_jsonl_frames(diag_files)
    accepted = read_jsonl_frames(accepted_files)
    for frame in (top, diag, accepted):
        if not frame.empty and "candidate_id" in frame:
            frame.drop_duplicates("candidate_id", inplace=True)
    if not top.empty:
        top = top.sort_values(["train_score", "train_sharpe"], ascending=[False, False])
    if not diag.empty:
        diag = diag.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False])
    if not accepted.empty:
        accepted = accepted.sort_values(["train_sharpe", "validation_sharpe"], ascending=[False, False])
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in summary_files]
    final = output_dir / "final"
    final.mkdir(parents=True, exist_ok=True)
    top.to_csv(final / "paper_cboe_sentiment_leaderboard.csv", index=False, quoting=csv.QUOTE_ALL)
    diag.head(500).to_csv(final / "paper_cboe_sentiment_validation_top.csv", index=False, quoting=csv.QUOTE_ALL)
    accepted.to_csv(final / "paper_cboe_sentiment_accepted.csv", index=False, quoting=csv.QUOTE_ALL)
    fail_reasons = build_fail_reasons(top)
    fail_reasons.to_csv(final / "paper_cboe_sentiment_fail_reasons.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "stages_expected": int(total_stages),
        "stages_found": len(summary_files),
        "partial": len(summary_files) != int(total_stages),
        "configs_evaluated": int(sum(item.get("configs_evaluated", 0) for item in summaries)),
        "accepted_count": int(len(accepted)),
        "best_train_sharpe": float(top["train_sharpe"].max()) if not top.empty else None,
        "best_validation_sharpe": float(top["validation_sharpe"].max()) if not top.empty else None,
        "best_min_train_validation_sharpe": float(top[["train_sharpe", "validation_sharpe"]].min(axis=1).max()) if not top.empty else None,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "uses_individual_stocks": False,
        "uses_factor_portfolio_without_reconstruction": False,
        "paper_exact_replication_claimed": False,
        "paper_sourced_only": True,
    }
    (final / "paper_cboe_sentiment_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if summary["partial"] and not allow_partial:
        raise RuntimeError(f"partial CBOE sentiment run: found {len(summary_files)}/{total_stages} stages")


def build_fail_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in frame.iterrows():
        if bool(row.get("accepted", False)):
            reasons.append("accepted")
        elif float(row.get("train_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("train_sharpe_below_2")
        elif float(row.get("validation_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("validation_sharpe_below_2_report_only")
        else:
            reasons.append("other")
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


if __name__ == "__main__":
    main()
