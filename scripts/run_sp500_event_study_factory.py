from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from core.execution_policy import require_github_actions_or_explicit_local_permission


CAMPAIGN_ID = "sp500_event_study_factory_core1950_v1"
SP500_SYMBOL = "^GSPC"
REQUESTED_START = "1950-01-01"
TRAIN_END = pd.Timestamp("1999-12-31")
VALIDATION_START = pd.Timestamp("2000-01-01")
MIN_CASES = 10
HORIZONS = [1, 5, 21, 63, 126, 252]
FRED_SERIES = {
    "USREC": "nber_recession",
    "CPIAUCSL": "cpi",
    "UNRATE": "unemployment_rate",
    "INDPRO": "industrial_production",
    "FEDFUNDS": "fed_funds",
    "TB3MS": "tbill_3m",
    "GS10": "treasury_10y",
}


def main() -> None:
    require_github_actions_or_explicit_local_permission()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--stages", type=int, default=360)
    parser.add_argument("--max-events-per-stage", type=int, default=250)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=int(args.stage),
            stages=int(args.stages),
            max_events_per_stage=int(args.max_events_per_stage),
        )
    else:
        run_merge(output_dir, stages=int(args.stages))


def run_data(output_dir: Path) -> None:
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sp500, raw_payload, source_url = fetch_yahoo_chart(SP500_SYMBOL, REQUESTED_START)
    sp500.to_csv(data_dir / "sp500_daily.csv", index_label="date")
    (data_dir / "sp500_daily_raw.json").write_bytes(raw_payload)

    fred_panel, fred_audit = fetch_fred_panel()
    fred_panel.to_csv(data_dir / "fred_macro_daily_aligned.csv", index_label="date")
    pd.DataFrame(fred_audit).to_csv(data_dir / "fred_macro_audit.csv", index=False)

    feature_frame = build_feature_frame(sp500, fred_panel)
    feature_frame.to_csv(data_dir / "event_feature_frame.csv", index_label="date")
    event_specs = build_event_specs(feature_frame)
    pd.DataFrame([spec_to_row(spec) for spec in event_specs]).to_csv(
        data_dir / "event_specs.csv",
        index=False,
    )

    manifest = {
        "campaign_id": CAMPAIGN_ID,
        "requested_start": REQUESTED_START,
        "sp500_source": "Yahoo Finance chart API",
        "sp500_source_url": source_url,
        "sp500_provider_reliability": "community/unofficial",
        "sp500_rows": int(len(sp500)),
        "sp500_first_date": str(sp500.index.min().date()),
        "sp500_last_date": str(sp500.index.max().date()),
        "sp500_raw_sha256": hashlib.sha256(raw_payload).hexdigest(),
        "feature_rows": int(len(feature_frame)),
        "feature_count": int(len([c for c in feature_frame.columns if c != "close"])),
        "event_specs": int(len(event_specs)),
        "fred_series": FRED_SERIES,
        "fred_audit_rows": fred_audit,
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "horizons_trading_days": HORIZONS,
        "min_cases": MIN_CASES,
        "lookahead_policy": "event condition uses data at date t; forward returns start after t",
        "backtest_enabled": False,
    }
    (data_dir / "event_factory_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def fetch_yahoo_chart(symbol: str, start_date: str) -> tuple[pd.DataFrame, bytes, str]:
    start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end = datetime.now(timezone.utc) + timedelta(days=1)
    period1 = int(start.timestamp())
    period2 = int(end.timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + quote(symbol, safe="")
        + f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=60) as resp:
        payload = resp.read()
    data = json.loads(payload)
    error = data.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo chart error: {error}")
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote_data = result["indicators"]["quote"][0]
    adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    rows = []
    for idx, ts in enumerate(timestamps):
        row = {
            "date": (epoch + timedelta(seconds=int(ts))).date().isoformat(),
            "open": value_at(quote_data.get("open"), idx),
            "high": value_at(quote_data.get("high"), idx),
            "low": value_at(quote_data.get("low"), idx),
            "close": value_at(quote_data.get("close"), idx),
            "adj_close": value_at(adj, idx),
            "volume": value_at(quote_data.get("volume"), idx),
        }
        if row["close"] is not None:
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    return frame, payload, url


def value_at(values: list[float] | None, idx: int) -> float | None:
    if values is None or idx >= len(values):
        return None
    value = values[idx]
    if value is None:
        return None
    return float(value)


def fetch_fred_panel() -> tuple[pd.DataFrame, list[dict[str, object]]]:
    frames = []
    audit = []
    for fred_id, name in FRED_SERIES.items():
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}&cosd={REQUESTED_START}"
        try:
            req = Request(url, headers={"User-Agent": "aurora-event-study-factory/1.0"})
            with urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            reader = csv.DictReader(text.splitlines())
            rows = []
            for row in reader:
                raw_date = row.get("observation_date")
                raw_value = row.get(fred_id)
                if not raw_date or raw_value in {None, ".", ""}:
                    continue
                rows.append({"date": raw_date, name: float(raw_value)})
            frame = pd.DataFrame(rows)
            if frame.empty:
                raise RuntimeError("empty FRED series")
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame.set_index("date").sort_index()
            frames.append(frame)
            audit.append(
                {
                    "series": fred_id,
                    "column": name,
                    "status": "ok",
                    "rows": int(len(frame)),
                    "first_date": str(frame.index.min().date()),
                    "last_date": str(frame.index.max().date()),
                    "source_url": url,
                }
            )
        except Exception as exc:
            audit.append(
                {
                    "series": fred_id,
                    "column": name,
                    "status": f"failed:{type(exc).__name__}:{exc}",
                    "rows": 0,
                    "first_date": "",
                    "last_date": "",
                    "source_url": url,
                }
            )
    panel = pd.concat(frames, axis=1).sort_index() if frames else pd.DataFrame()
    return panel, audit


def build_feature_frame(sp500: pd.DataFrame, fred: pd.DataFrame) -> pd.DataFrame:
    close = sp500["close"].astype(float)
    ret = close.pct_change(fill_method=None)
    frame = pd.DataFrame(index=sp500.index)
    frame["close"] = close
    for window in [1, 2, 3, 5, 10, 21, 42, 45, 63, 126, 252]:
        frame[f"ret_{window}d"] = close.pct_change(window, fill_method=None)
        frame[f"vol_{window}d"] = ret.rolling(window, min_periods=max(2, min(window, 10))).std()
        high = close.rolling(window, min_periods=max(2, min(window, 10))).max()
        low = close.rolling(window, min_periods=max(2, min(window, 10))).min()
        frame[f"drawdown_{window}d"] = close / high - 1.0
        frame[f"dist_low_{window}d"] = close / low - 1.0
        frame[f"range_pos_{window}d"] = (close - low) / (high - low).replace(0.0, np.nan)
    for window in [20, 50, 100, 200]:
        ma = close.rolling(window, min_periods=max(5, window // 4)).mean()
        frame[f"ma_gap_{window}d"] = close / ma - 1.0
    for window in [3, 5, 7, 9, 10]:
        signs = np.sign(ret)
        frame[f"up_count_{window}d"] = (signs > 0).rolling(window, min_periods=window).sum()
        frame[f"down_count_{window}d"] = (signs < 0).rolling(window, min_periods=window).sum()
    frame["month"] = frame.index.month
    frame["quarter"] = frame.index.quarter
    frame["day_of_month"] = frame.index.day
    frame["trading_day_of_year"] = pd.Series(1, index=frame.index).groupby(frame.index.year).cumsum()
    frame["first_100_trading_days"] = (frame["trading_day_of_year"] <= 100).astype(float)
    frame["last_21_trading_days"] = (
        frame["trading_day_of_year"]
        >= frame.groupby(frame.index.year)["trading_day_of_year"].transform("max") - 20
    ).astype(float)

    if not fred.empty:
        fred_daily = fred.reindex(frame.index, method="ffill")
        for column in fred_daily.columns:
            series = fred_daily[column].astype(float)
            frame[column] = series
            frame[f"{column}_change_1m"] = series.diff(21)
            frame[f"{column}_change_3m"] = series.diff(63)
            frame[f"{column}_z_3y"] = rolling_z(series, 756)
        if {"treasury_10y", "tbill_3m"}.issubset(fred_daily.columns):
            frame["yield_curve_10y_3m"] = fred_daily["treasury_10y"] - fred_daily["tbill_3m"]
            frame["yield_curve_10y_3m_change_3m"] = frame["yield_curve_10y_3m"].diff(63)
        if {"cpi"}.issubset(fred_daily.columns):
            frame["cpi_yoy"] = fred_daily["cpi"].pct_change(252, fill_method=None)
            frame["cpi_yoy_change_3m"] = frame["cpi_yoy"].diff(63)
    frame = frame.replace([np.inf, -np.inf], np.nan)
    return frame


def rolling_z(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(20, window // 5)).mean()
    std = series.rolling(window, min_periods=max(20, window // 5)).std()
    return (series - mean) / std.replace(0.0, np.nan)


def build_event_specs(frame: pd.DataFrame) -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    add_threshold_events(specs, frame, "ret", [1, 2, 3, 5, 10, 21, 42, 45, 63, 126, 252], "return")
    add_threshold_events(specs, frame, "vol", [5, 10, 21, 42, 63, 126], "volatility")
    add_threshold_events(specs, frame, "drawdown", [21, 42, 63, 126, 252], "drawdown")
    add_threshold_events(specs, frame, "dist_low", [21, 42, 63, 126, 252], "rebound")
    add_threshold_events(specs, frame, "ma_gap", [20, 50, 100, 200], "moving_average")
    for window in [3, 5, 7, 9, 10]:
        specs.append(make_spec("streak", f"up_count_{window}d", ">=", window, f"{window} positive days in last {window}d"))
        specs.append(make_spec("streak", f"down_count_{window}d", ">=", window, f"{window} negative days in last {window}d"))
    for month in range(1, 13):
        specs.append(make_spec("calendar", "month", "==", month, f"calendar month == {month}"))
    specs.append(make_spec("calendar", "first_100_trading_days", "==", 1.0, "within first 100 trading days of year"))
    specs.append(make_spec("calendar", "last_21_trading_days", "==", 1.0, "within last 21 trading days of year"))
    for column in [
        "nber_recession",
        "cpi_yoy",
        "cpi_yoy_change_3m",
        "unemployment_rate_change_3m",
        "industrial_production_change_3m",
        "fed_funds_change_3m",
        "yield_curve_10y_3m",
        "yield_curve_10y_3m_change_3m",
    ]:
        if column in frame.columns:
            add_quantile_events(specs, frame, column, "macro")
    return specs


def add_threshold_events(
    specs: list[dict[str, object]],
    frame: pd.DataFrame,
    prefix: str,
    windows: list[int],
    family: str,
) -> None:
    for window in windows:
        col = f"{prefix}_{window}d"
        if col not in frame:
            continue
        add_quantile_events(specs, frame, col, family)


def add_quantile_events(specs: list[dict[str, object]], frame: pd.DataFrame, column: str, family: str) -> None:
    series = frame[column].dropna()
    if len(series) < 500:
        return
    for q in [0.01, 0.02, 0.05, 0.10, 0.20, 0.80, 0.90, 0.95, 0.98, 0.99]:
        threshold = float(series.quantile(q))
        op = "<=" if q < 0.5 else ">="
        label = f"{column} {op} p{int(q * 100):02d} ({threshold:.6g})"
        specs.append(make_spec(family, column, op, threshold, label))


def make_spec(family: str, column: str, op: str, threshold: float, label: str) -> dict[str, object]:
    raw = f"{family}|{column}|{op}|{threshold:.12g}"
    return {
        "event_id": hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16],
        "family": family,
        "column": column,
        "operator": op,
        "threshold": float(threshold),
        "label": label,
    }


def spec_to_row(spec: dict[str, object]) -> dict[str, object]:
    return {
        "event_id": spec["event_id"],
        "family": spec["family"],
        "column": spec["column"],
        "operator": spec["operator"],
        "threshold": spec["threshold"],
        "label": spec["label"],
    }


def run_shard(output_dir: Path, *, stage: int, stages: int, max_events_per_stage: int) -> None:
    data_dir = output_dir / "data"
    feature_frame = pd.read_csv(data_dir / "event_feature_frame.csv", parse_dates=["date"]).set_index("date")
    specs = pd.read_csv(data_dir / "event_specs.csv").to_dict("records")
    assigned = [spec for i, spec in enumerate(specs) if i % stages == stage]
    assigned = assigned[:max_events_per_stage]
    rows = []
    years_rows = []
    for spec in assigned:
        result, per_year = evaluate_event(feature_frame, spec)
        rows.append(result)
        years_rows.extend(per_year)
    shard_dir = output_dir / "shards" / f"stage_{stage:04d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(shard_dir / "event_results.csv", index=False)
    pd.DataFrame(years_rows).to_csv(shard_dir / "event_years.csv", index=False)
    summary = {
        "stage": int(stage),
        "stages": int(stages),
        "events_assigned": int(len(assigned)),
        "results": int(len(rows)),
        "years_rows": int(len(years_rows)),
        "backtest_enabled": False,
    }
    (shard_dir / "shard_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def evaluate_event(feature_frame: pd.DataFrame, spec: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    event_mask = event_condition(feature_frame, spec)
    close = feature_frame["close"].astype(float)
    event_dates = feature_frame.index[event_mask.fillna(False)]
    result: dict[str, object] = {
        "event_id": spec["event_id"],
        "family": spec["family"],
        "label": spec["label"],
        "column": spec["column"],
        "operator": spec["operator"],
        "threshold": spec["threshold"],
        "cases_total": int(len(event_dates)),
        "cases_train": int((event_dates <= TRAIN_END).sum()),
        "cases_validation": int((event_dates >= VALIDATION_START).sum()),
        "first_event": str(event_dates.min().date()) if len(event_dates) else "",
        "last_event": str(event_dates.max().date()) if len(event_dates) else "",
    }
    years_rows: list[dict[str, object]] = []
    for horizon in HORIZONS:
        fwd = close.shift(-horizon) / close - 1.0
        values = fwd.loc[event_dates].dropna()
        train_values = values.loc[values.index <= TRAIN_END]
        validation_values = values.loc[values.index >= VALIDATION_START]
        baseline = fwd.dropna()
        baseline_train = baseline.loc[baseline.index <= TRAIN_END]
        baseline_validation = baseline.loc[baseline.index >= VALIDATION_START]
        add_horizon_metrics(result, f"{horizon}d_total", values, baseline)
        add_horizon_metrics(result, f"{horizon}d_train", train_values, baseline_train)
        add_horizon_metrics(result, f"{horizon}d_validation", validation_values, baseline_validation)
        for year, group in values.groupby(values.index.year):
            years_rows.append(
                {
                    "event_id": spec["event_id"],
                    "family": spec["family"],
                    "label": spec["label"],
                    "horizon_days": horizon,
                    "year": int(year),
                    "cases": int(len(group)),
                    "mean_return": float(group.mean()) if len(group) else np.nan,
                    "positive_pct": float((group > 0).mean()) if len(group) else np.nan,
                }
            )
    score_fields(result)
    return result, years_rows


def event_condition(feature_frame: pd.DataFrame, spec: dict[str, object]) -> pd.Series:
    column = str(spec["column"])
    values = feature_frame[column].astype(float)
    op = str(spec["operator"])
    threshold = float(spec["threshold"])
    if op == ">=":
        return values >= threshold
    if op == "<=":
        return values <= threshold
    if op == "==":
        return values == threshold
    raise ValueError(f"unsupported operator: {op}")


def add_horizon_metrics(out: dict[str, object], prefix: str, values: pd.Series, baseline: pd.Series) -> None:
    clean = values.replace([np.inf, -np.inf], np.nan).dropna()
    base = baseline.replace([np.inf, -np.inf], np.nan).dropna()
    out[f"{prefix}_cases"] = int(len(clean))
    out[f"{prefix}_mean_return"] = float(clean.mean()) if len(clean) else np.nan
    out[f"{prefix}_median_return"] = float(clean.median()) if len(clean) else np.nan
    out[f"{prefix}_positive_pct"] = float((clean > 0).mean()) if len(clean) else np.nan
    out[f"{prefix}_worst_return"] = float(clean.min()) if len(clean) else np.nan
    out[f"{prefix}_best_return"] = float(clean.max()) if len(clean) else np.nan
    out[f"{prefix}_excess_mean_vs_all_days"] = (
        float(clean.mean() - base.mean()) if len(clean) and len(base) else np.nan
    )


def score_fields(row: dict[str, object]) -> None:
    for horizon in HORIZONS:
        train_cases = int(row.get(f"{horizon}d_train_cases", 0) or 0)
        valid_cases = int(row.get(f"{horizon}d_validation_cases", 0) or 0)
        train_excess = safe_float(row.get(f"{horizon}d_train_excess_mean_vs_all_days"))
        valid_excess = safe_float(row.get(f"{horizon}d_validation_excess_mean_vs_all_days"))
        train_pos = safe_float(row.get(f"{horizon}d_train_positive_pct"))
        valid_pos = safe_float(row.get(f"{horizon}d_validation_positive_pct"))
        sample_penalty = 0.0 if train_cases >= MIN_CASES and valid_cases >= MIN_CASES else -999.0
        bullish_score = train_excess * 100.0 + valid_excess * 220.0 + (train_pos + valid_pos - 1.0) * 12.0 + sample_penalty
        bearish_score = -train_excess * 100.0 - valid_excess * 220.0 + ((1.0 - train_pos) + (1.0 - valid_pos) - 1.0) * 12.0 + sample_penalty
        row[f"{horizon}d_bullish_score"] = bullish_score
        row[f"{horizon}d_bearish_score"] = bearish_score
        row[f"{horizon}d_signal_type"] = "bullish" if bullish_score >= bearish_score else "bearish"
        row[f"{horizon}d_best_score"] = max(bullish_score, bearish_score)


def safe_float(value: object) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except Exception:
        return 0.0


def run_merge(output_dir: Path, *, stages: int) -> None:
    result_files = list((output_dir / "shards").glob("**/event_results.csv"))
    year_files = list((output_dir / "shards").glob("**/event_years.csv"))
    summary_files = list((output_dir / "shards").glob("**/shard_summary.json"))
    if not result_files:
        raise RuntimeError("No event result shards found.")
    results = pd.concat([pd.read_csv(path) for path in result_files], ignore_index=True)
    years = pd.concat([pd.read_csv(path) for path in year_files], ignore_index=True) if year_files else pd.DataFrame()
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in summary_files]

    results = results.drop_duplicates("event_id")
    leaderboards = []
    for horizon in HORIZONS:
        score_col = f"{horizon}d_best_score"
        type_col = f"{horizon}d_signal_type"
        frame = results.copy()
        frame["selected_horizon_days"] = horizon
        frame["signal_type"] = frame[type_col]
        frame["selected_score"] = frame[score_col]
        leaderboards.append(frame.sort_values(score_col, ascending=False).head(200))
    leaderboard = pd.concat(leaderboards, ignore_index=True).sort_values("selected_score", ascending=False)
    bullish = leaderboard.loc[leaderboard["signal_type"] == "bullish"].copy()
    bearish = leaderboard.loc[leaderboard["signal_type"] == "bearish"].copy()
    robust = leaderboard.loc[
        (leaderboard["cases_train"] >= MIN_CASES)
        & (leaderboard["cases_validation"] >= MIN_CASES)
        & (leaderboard["selected_score"] > 0)
    ].copy()
    rejected = results.loc[
        (results["cases_train"] < MIN_CASES) | (results["cases_validation"] < MIN_CASES)
    ].copy()

    active_today = active_events_today(results, output_dir / "data" / "event_feature_frame.csv")

    output_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(output_dir / "event_study_full_results.csv", index=False)
    leaderboard.to_csv(output_dir / "event_study_leaderboard.csv", index=False)
    bullish.to_csv(output_dir / "bullish_events.csv", index=False)
    bearish.to_csv(output_dir / "bearish_events.csv", index=False)
    robust.to_csv(output_dir / "event_study_robust.csv", index=False)
    rejected.to_csv(output_dir / "event_study_rejected.csv", index=False)
    active_today.to_csv(output_dir / "event_study_active_today.csv", index=False)
    years.to_csv(output_dir / "event_study_years.csv", index=False)
    pd.DataFrame(summaries).to_csv(output_dir / "event_study_shard_summaries.csv", index=False)

    summary = {
        "campaign_id": CAMPAIGN_ID,
        "universe": "core_1950",
        "data_scope": "SP500 daily since 1950 plus long-history FRED macro aligned causally",
        "stages_expected": int(stages),
        "stages_completed": int(len(summaries)),
        "partial": int(len(summaries)) != int(stages),
        "events_tested": int(len(results)),
        "leaderboard_rows": int(len(leaderboard)),
        "robust_rows": int(len(robust)),
        "bullish_rows": int(len(bullish)),
        "bearish_rows": int(len(bearish)),
        "active_today_rows": int(len(active_today)),
        "requested_start": REQUESTED_START,
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "horizons_trading_days": HORIZONS,
        "min_cases": MIN_CASES,
        "lookahead_guard": "forward returns are computed after event date; macro data is forward-filled only from published historical series",
        "backtest_enabled": False,
    }
    (output_dir / "event_study_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def active_events_today(results: pd.DataFrame, feature_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(feature_path, parse_dates=["date"]).set_index("date")
    latest = frame.iloc[[-1]]
    rows = []
    for row in results.to_dict("records"):
        spec = {
            "column": row["column"],
            "operator": row["operator"],
            "threshold": row["threshold"],
        }
        if bool(event_condition(latest, spec).iloc[0]):
            rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        out.insert(0, "active_date", str(frame.index.max().date()))
    return out


if __name__ == "__main__":
    main()
