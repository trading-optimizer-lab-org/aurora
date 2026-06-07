from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CAMPAIGN_ID = "paper_spy_daily_event_sharpe2_360jobs"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_SHARPE = 2.0
PPY = 252

MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
MONTH_RE = "|".join(MONTHS)

PAPER_SOURCES: dict[str, dict[str, str]] = {
    "mcconnell_xu_turn_of_month": {
        "paper": "Equity Returns at the Turn of the Month",
        "authors": "McConnell, Xu",
        "year": "2008",
        "type": "template",
        "rule": "Equity returns concentrate around the turn of the month.",
    },
    "lucca_moench_pre_fomc": {
        "paper": "The Pre-FOMC Announcement Drift",
        "authors": "Lucca, Moench",
        "year": "2015",
        "type": "template",
        "rule": "Equities earn abnormal returns before scheduled FOMC announcements.",
    },
    "cieslak_fomc_cycle": {
        "paper": "Stock Returns over the FOMC Cycle",
        "authors": "Cieslak, Morse, Vissing-Jorgensen",
        "year": "2019",
        "type": "template",
        "rule": "Equity premium concentrates in alternating weeks of the FOMC cycle.",
    },
    "savor_wilson_macro": {
        "paper": "How Much Do Investors Care About Macroeconomic Risk?",
        "authors": "Savor, Wilson",
        "year": "2013",
        "type": "template",
        "rule": "Major scheduled macro announcement days carry equity risk premia.",
    },
    "giot_vix_extreme": {
        "paper": "Relationships Between Implied Volatility Indexes and Stock Index Returns",
        "authors": "Giot",
        "year": "2005",
        "type": "template",
        "rule": "Extreme implied volatility levels are linked to future stock-index returns.",
    },
    "simon_wiggins_sentiment": {
        "paper": "S&P Futures Returns and Contrary Sentiment Indicators",
        "authors": "Simon, Wiggins",
        "year": "2001",
        "type": "template",
        "rule": "Contrary sentiment indicators such as put-call ratios and VIX can predict S&P returns.",
    },
    "calendar_anomalies": {
        "paper": "Are Seasonal Anomalies Real? A Ninety-Year Perspective",
        "authors": "Sullivan, Timmermann, White",
        "year": "2001",
        "type": "template",
        "rule": "Calendar effects should be tested causally and out-of-sample, not accepted by data snooping.",
    },
    "option_expiration_effect": {
        "paper": "Stock Index Futures and Options Expiration-Day Effects",
        "authors": "Stoll, Whaley",
        "year": "1990",
        "type": "template",
        "rule": "Index option/futures expiration windows can change stock-index return behavior.",
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
    parser.add_argument("--configs-per-stage", type=int, default=20_000)
    parser.add_argument("--time-budget-minutes", type=float, default=35.0)
    parser.add_argument("--top-per-stage", type=int, default=150)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=args.stage,
            configs_per_stage=args.configs_per_stage,
            time_budget_minutes=args.time_budget_minutes,
            top_per_stage=args.top_per_stage,
        )
    else:
        run_merge(output_dir)


def run_data(output_dir: Path) -> None:
    cache_dir = output_dir / ".yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        yf.set_tz_cache_location(str(cache_dir))
    except Exception:
        pass
    raw = pd.DataFrame()
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            raw = yf.download(
                ["SPY", "^VIX"],
                start="1995-01-01",
                end="2021-01-01",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=False,
            )
            if not raw.empty:
                break
        except Exception as exc:
            last_error = exc
            time.sleep(2.0 + attempt)
    if raw.empty and last_error is not None:
        raise RuntimeError(f"SPY/VIX download failed after retries: {last_error}") from last_error
    prices = pd.DataFrame()
    for symbol in ["SPY", "^VIX"]:
        try:
            prices[symbol] = raw[symbol]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
        except Exception:
            continue
    if "SPY" not in prices or prices["SPY"].dropna().empty:
        raise RuntimeError("SPY data unavailable")
    prices = prices.sort_index()
    prices = prices[prices.index < LOCKED_START]
    if prices.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached data output")
    returns = prices[["SPY"]].pct_change(fill_method=None).dropna()
    returns = returns.loc[(returns.index >= TRAIN_START) & (returns.index < LOCKED_START)]

    fomc = fetch_fomc_dates(TRAIN_START, VALIDATION_END)
    event_frame = build_event_frame(returns.index, fomc)
    feature_frame = build_daily_features(prices, returns)
    common = returns.index.intersection(feature_frame.index).intersection(event_frame.index)
    returns = returns.reindex(common)
    feature_frame = feature_frame.reindex(common)
    event_frame = event_frame.reindex(common).fillna(0.0)

    returns.to_csv(output_dir / "daily_returns.csv", index_label="timestamp")
    prices.reindex(common).to_csv(output_dir / "daily_prices.csv", index_label="timestamp")
    event_frame.to_csv(output_dir / "event_frame.csv", index_label="timestamp")
    feature_frame.to_csv(output_dir / "daily_feature_frame.csv", index_label="timestamp")
    pd.DataFrame(PAPER_SOURCES.values()).assign(paper_key=list(PAPER_SOURCES)).to_csv(
        output_dir / "paper_sources.csv",
        index=False,
    )
    pd.DataFrame({"fomc_date": [str(x.date()) for x in fomc]}).to_csv(output_dir / "fomc_dates.csv", index=False)
    (output_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "objective": "Sharpe >= 2 in train and validation using paper-sourced SPY daily event/calendar signals",
                "train_start": str(TRAIN_START.date()),
                "train_end": str(TRAIN_END.date()),
                "validation_start": str(VALIDATION_START.date()),
                "validation_end": str(VALIDATION_END.date()),
                "locked_start": str(LOCKED_START.date()),
                "data_end_max": str(common.max().date()),
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
                "paper_sourced_only": True,
                "traded_asset": "SPY",
                "frequency": "daily",
                "cash_allowed": True,
                "lag_periods_minimum": 1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def fetch_fomc_dates(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for year in range(start.year, end.year + 1):
        url = f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Aurora research"})
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        dates.update(parse_fomc_dates_from_html(html, year))
    return sorted(x for x in dates if start <= x <= end)


def parse_fomc_dates_from_html(html: str, year: int) -> list[pd.Timestamp]:
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"\s+", " ", clean)
    pattern = re.compile(
        rf"(?P<m1>{MONTH_RE})\s+(?P<d1>\d{{1,2}})"
        rf"(?:\s*[-/]\s*(?:(?P<m2>{MONTH_RE})\s+)?(?P<d2>\d{{1,2}}))?"
        rf",\s+{year}"
    )
    out: list[pd.Timestamp] = []
    for match in pattern.finditer(clean):
        month = MONTHS[match.group("m2") or match.group("m1")]
        day = int(match.group("d2") or match.group("d1"))
        try:
            out.append(pd.Timestamp(year=year, month=month, day=day))
        except ValueError:
            continue
    return sorted(set(out))


def build_event_frame(index: pd.DatetimeIndex, fomc_dates: list[pd.Timestamp]) -> pd.DataFrame:
    out = pd.DataFrame(index=index)
    ordinal = pd.Series(np.arange(len(index)), index=index)
    out["turn_of_month_rank"] = turn_of_month_rank(index)
    out["month_bday_rank"] = month_business_day_rank(index, reverse=False)
    out["month_bday_from_end"] = month_business_day_rank(index, reverse=True)
    out["weekday"] = index.weekday.astype(float)
    out["third_friday_rank"] = third_friday_distance(index)
    out["pre_fomc_days"] = 999.0
    out["post_fomc_days"] = 999.0
    out["days_since_fomc"] = 999.0
    for date in fomc_dates:
        if date not in ordinal.index:
            loc = ordinal.index.searchsorted(date)
            if loc >= len(ordinal.index):
                continue
            event_idx = int(loc)
        else:
            event_idx = int(ordinal.loc[date])
        distances = np.arange(len(index)) - event_idx
        out["pre_fomc_days"] = np.minimum(out["pre_fomc_days"], np.where(distances <= 0, -distances, 999.0))
        out["post_fomc_days"] = np.minimum(out["post_fomc_days"], np.where(distances >= 0, distances, 999.0))
        out["days_since_fomc"] = np.minimum(out["days_since_fomc"], np.where(distances >= 0, distances, 999.0))
    out["fomc_event_day"] = (out["post_fomc_days"] == 0).astype(float)
    out["fomc_cycle_week"] = np.floor(out["days_since_fomc"] / 7.0).mod(8).where(out["days_since_fomc"] < 900, 99.0)
    return out


def turn_of_month_rank(index: pd.DatetimeIndex) -> pd.Series:
    values = pd.Series(index=index, dtype=float)
    for _, locs in pd.Series(range(len(index)), index=index).groupby([index.year, index.month]):
        positions = list(locs.values)
        n = len(positions)
        for rank, pos in enumerate(positions):
            from_start = rank
            from_end = rank - (n - 1)
            values.iloc[pos] = from_end if abs(from_end) <= abs(from_start) else from_start + 1
    return values


def month_business_day_rank(index: pd.DatetimeIndex, *, reverse: bool) -> pd.Series:
    values = pd.Series(index=index, dtype=float)
    for _, locs in pd.Series(range(len(index)), index=index).groupby([index.year, index.month]):
        positions = list(locs.values)
        n = len(positions)
        for rank, pos in enumerate(positions):
            values.iloc[pos] = float(n - rank if reverse else rank + 1)
    return values


def third_friday_distance(index: pd.DatetimeIndex) -> pd.Series:
    values = pd.Series(99.0, index=index)
    grouped = pd.Series(range(len(index)), index=index).groupby([index.year, index.month])
    for (_, _), locs in grouped:
        month_index = index[list(locs.values)]
        fridays = [d for d in month_index if d.weekday() == 4]
        if len(fridays) < 3:
            continue
        expiry = fridays[2]
        expiry_loc = int(np.where(index == expiry)[0][0])
        distances = np.arange(len(index)) - expiry_loc
        month_mask = (index.year == expiry.year) & (index.month == expiry.month)
        values.iloc[np.where(month_mask)[0]] = distances[month_mask]
    return values


def build_daily_features(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=returns.index)
    spy = prices["SPY"].reindex(out.index).ffill()
    spy_ret = returns["SPY"].reindex(out.index)
    if "^VIX" in prices:
        vix = prices["^VIX"].reindex(out.index).ffill()
        for lb in [21, 63, 126, 252]:
            out[f"vix_z_{lb}d"] = zscore(vix, lb).shift(1)
            out[f"vix_chg_{lb}d"] = vix.diff(lb).shift(1)
    for lb in [21, 63, 126, 252]:
        out[f"spy_mom_{lb}d"] = ((1.0 + spy_ret).rolling(lb).apply(np.prod, raw=True) - 1.0).shift(1)
        out[f"spy_realized_vol_{lb}d"] = spy_ret.rolling(lb).std().shift(1)
        out[f"spy_ma_gap_{lb}d"] = (spy / spy.rolling(lb).mean() - 1.0).shift(1)
    return out.replace([np.inf, -np.inf], np.nan).dropna(how="any").clip(-8.0, 8.0)


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std()
    return (series - mean) / std.replace(0.0, np.nan)


def run_shard(output_dir: Path, *, stage: int, configs_per_stage: int, time_budget_minutes: float, top_per_stage: int) -> None:
    returns = pd.read_csv(output_dir / "daily_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    events = pd.read_csv(output_dir / "event_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    features = pd.read_csv(output_dir / "daily_feature_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    common = returns.index.intersection(events.index).intersection(features.index)
    returns = returns.reindex(common)
    events = events.reindex(common)
    features = features.reindex(common)
    if common.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard")
    train_mask = (common >= TRAIN_START) & (common <= TRAIN_END)
    validation_mask = (common >= VALIDATION_START) & (common <= VALIDATION_END)
    spy_values = returns["SPY"].to_numpy(dtype=float)
    rng = np.random.default_rng(20260607 + int(stage) * 1_000_003)
    deadline = time.monotonic() + max(1.0, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    for config_index in range(int(configs_per_stage)):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        candidate = sample_candidate(rng, stage)
        positions = build_positions(candidate, events, features)
        strategy_returns = positions * spy_values
        train_metrics = daily_metrics(strategy_returns[train_mask])
        if not np.isfinite(train_metrics["sharpe"]):
            continue
        if train_metrics["sharpe"] < 0.25 and config_index % 251 != 0:
            continue
        validation_metrics = daily_metrics(strategy_returns[validation_mask])
        pass_train = bool(train_metrics["sharpe"] >= TARGET_SHARPE)
        pass_validation = bool(validation_metrics["sharpe"] >= TARGET_SHARPE)
        paper_key = paper_key_for_family(candidate.family)
        payload = {"family": candidate.family, "params": candidate.params, "paper_key": paper_key}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "strategy_id": f"paper_spy_daily_event_s{stage:03d}_{digest}",
                "stage": int(stage),
                "config_index": int(config_index),
                "train_pass": pass_train,
                "validation_pass_report_only": pass_validation,
                "final_verified_report_only": bool(pass_train and pass_validation),
                "validation_used_for_selection": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "paper_exact_replication_claimed": False,
                "paper_strategy_type": PAPER_SOURCES[paper_key]["type"],
                "paper_key": paper_key,
                "paper_title": PAPER_SOURCES[paper_key]["paper"],
                "paper_authors": PAPER_SOURCES[paper_key]["authors"],
                "source_rule_summary": PAPER_SOURCES[paper_key]["rule"],
                "traded_asset": "SPY",
                "frequency": "daily",
                "lag_periods": int(candidate.params.get("lag_periods", 1)),
                "cash_allowed": True,
                "family": candidate.family,
                "train_sharpe": float(train_metrics["sharpe"]),
                "validation_sharpe": float(validation_metrics["sharpe"]),
                "train_cagr": float(train_metrics["cagr"]),
                "validation_cagr": float(validation_metrics["cagr"]),
                "train_mdd": float(train_metrics["mdd"]),
                "validation_mdd": float(validation_metrics["mdd"]),
                "train_positive_days_pct": float(train_metrics["positive_days_pct"]),
                "validation_positive_days_pct": float(validation_metrics["positive_days_pct"]),
                "train_exposure_pct": float(np.mean(np.abs(positions[train_mask]) > 0.0)),
                "validation_exposure_pct": float(np.mean(np.abs(positions[validation_mask]) > 0.0)),
                "train_long_pct": float(np.mean(positions[train_mask] > 0.0)),
                "train_short_pct": float(np.mean(positions[train_mask] < 0.0)),
                "train_cash_pct": float(np.mean(np.isclose(positions[train_mask], 0.0))),
                "params_json": json.dumps(candidate.params, sort_keys=True),
                "train_score": float(train_metrics["sharpe"] + min(0.0, train_metrics["mdd"]) * 0.15),
            }
        )
    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["strategy_id", "train_score", "final_verified_report_only"])
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    diag = frame.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    verified = frame[frame.get("final_verified_report_only", pd.Series(dtype=bool)).astype(bool)]
    top.to_csv(shard_dir / "top_candidates.csv", index=False)
    diag.to_csv(shard_dir / "validation_ceiling_diagnostic.csv", index=False)
    verified.to_csv(shard_dir / "verified_candidates_report_only.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "configs_requested": int(configs_per_stage),
                "configs_evaluated": int(evaluated),
                "rows_kept": int(len(frame)),
                "top_rows_written": int(len(top)),
                "final_verified_report_only_rows": int(len(verified)),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def sample_candidate(rng: np.random.Generator, stage: int) -> Candidate:
    families = [
        "turn_of_month",
        "pre_fomc",
        "fomc_window",
        "fomc_cycle",
        "macro_monthly_rank",
        "macro_rank_weekday",
        "weekday_calendar",
        "option_expiration_window",
        "vix_extreme",
        "vix_momentum_filter",
    ]
    family = families[stage % len(families)] if rng.random() < 0.65 else str(rng.choice(families))
    if family == "turn_of_month":
        return Candidate(
            family,
            {
                "start_rank": int(rng.integers(-8, 3)),
                "end_rank": int(rng.integers(-1, 8)),
                "direction": int(rng.choice([-1, 1])),
                "outside_position": float(rng.choice([0.0, 0.0, 0.0, -1.0, 1.0])),
                "lag_periods": 1,
            },
        )
    if family in {"pre_fomc", "fomc_window"}:
        return Candidate(
            family,
            {
                "pre_days": int(rng.integers(1, 8)),
                "post_days": int(rng.integers(0, 4)),
                "direction": int(rng.choice([-1, 1])),
                "outside_position": float(rng.choice([0.0, 0.0, -1.0, 1.0])),
                "lag_periods": 1,
            },
        )
    if family == "fomc_cycle":
        mode = str(rng.choice(["even", "odd", "single", "pair"]))
        return Candidate(
            family,
            {
                "cycle_mode": mode,
                "week_a": int(rng.integers(0, 8)),
                "week_b": int(rng.integers(0, 8)),
                "direction": int(rng.choice([-1, 1])),
                "outside_position": float(rng.choice([0.0, 0.0, -1.0, 1.0])),
                "lag_periods": 1,
            },
        )
    if family == "macro_monthly_rank":
        return Candidate(
            family,
            {
                "rank_column": str(rng.choice(["month_bday_rank", "month_bday_from_end"])),
                "rank": int(rng.integers(1, 23)),
                "pre_days": int(rng.integers(0, 4)),
                "post_days": int(rng.integers(0, 4)),
                "direction": int(rng.choice([-1, 1])),
                "outside_position": float(rng.choice([0.0, 0.0, 0.0, -1.0, 1.0])),
                "lag_periods": 1,
            },
        )
    if family == "macro_rank_weekday":
        return Candidate(
            family,
            {
                "rank_column": str(rng.choice(["month_bday_rank", "month_bday_from_end"])),
                "rank": int(rng.integers(1, 16)),
                "pre_days": int(rng.integers(0, 3)),
                "post_days": int(rng.integers(0, 3)),
                "weekday": int(rng.integers(0, 5)),
                "direction": int(rng.choice([-1, 1])),
                "outside_position": float(rng.choice([0.0, 0.0, 0.0, -1.0, 1.0])),
                "lag_periods": 1,
            },
        )
    if family == "weekday_calendar":
        return Candidate(
            family,
            {
                "weekday": int(rng.integers(0, 5)),
                "direction": int(rng.choice([-1, 1])),
                "outside_position": float(rng.choice([0.0, 0.0, -1.0, 1.0])),
                "lag_periods": 1,
            },
        )
    if family == "option_expiration_window":
        return Candidate(
            family,
            {
                "start_distance": int(rng.integers(-5, 2)),
                "end_distance": int(rng.integers(0, 6)),
                "direction": int(rng.choice([-1, 1])),
                "outside_position": float(rng.choice([0.0, 0.0, -1.0, 1.0])),
                "lag_periods": 1,
            },
        )
    return Candidate(
        family,
        {
            "vix_feature": str(rng.choice(["vix_z_21d", "vix_z_63d", "vix_z_126d", "vix_chg_21d", "vix_chg_63d"])),
            "threshold": float(rng.uniform(-2.5, 2.5)),
            "direction": int(rng.choice([-1, 1])),
            "outside_position": float(rng.choice([0.0, 0.0, -1.0, 1.0])),
            "trend_filter": str(rng.choice(["none", "spy_mom_21d", "spy_mom_63d", "spy_ma_gap_126d"])),
            "trend_direction": int(rng.choice([-1, 1])),
            "lag_periods": 1,
        },
    )


def paper_key_for_family(family: str) -> str:
    if family == "turn_of_month":
        return "mcconnell_xu_turn_of_month"
    if family in {"pre_fomc", "fomc_window"}:
        return "lucca_moench_pre_fomc"
    if family == "fomc_cycle":
        return "cieslak_fomc_cycle"
    if family in {"macro_monthly_rank", "macro_rank_weekday"}:
        return "savor_wilson_macro"
    if family == "weekday_calendar":
        return "calendar_anomalies"
    if family == "option_expiration_window":
        return "option_expiration_effect"
    if family.startswith("vix"):
        return "giot_vix_extreme"
    return "savor_wilson_macro"


def build_positions(candidate: Candidate, events: pd.DataFrame, features: pd.DataFrame) -> np.ndarray:
    params = candidate.params
    positions = np.zeros(len(events), dtype=float)
    if candidate.family == "turn_of_month":
        rank = events["turn_of_month_rank"].to_numpy(dtype=float)
        inside = (rank >= float(params["start_rank"])) & (rank <= float(params["end_rank"]))
        positions[:] = float(params["outside_position"])
        positions[inside] = float(params["direction"])
        return positions
    if candidate.family in {"pre_fomc", "fomc_window"}:
        pre = events["pre_fomc_days"].to_numpy(dtype=float)
        post = events["post_fomc_days"].to_numpy(dtype=float)
        inside = (pre <= float(params["pre_days"])) | (post <= float(params["post_days"]))
        positions[:] = float(params["outside_position"])
        positions[inside] = float(params["direction"])
        return positions
    if candidate.family == "fomc_cycle":
        cycle = events["fomc_cycle_week"].to_numpy(dtype=float)
        mode = str(params["cycle_mode"])
        if mode == "even":
            inside = np.isin(cycle, [0.0, 2.0, 4.0, 6.0])
        elif mode == "odd":
            inside = np.isin(cycle, [1.0, 3.0, 5.0, 7.0])
        elif mode == "pair":
            inside = np.isin(cycle, [float(params["week_a"]), float(params["week_b"])])
        else:
            inside = cycle == float(params["week_a"])
        positions[:] = float(params["outside_position"])
        positions[inside] = float(params["direction"])
        return positions
    if candidate.family == "macro_monthly_rank":
        rank = events[str(params["rank_column"])].to_numpy(dtype=float)
        center = float(params["rank"])
        inside = (rank >= center - float(params["pre_days"])) & (rank <= center + float(params["post_days"]))
        positions[:] = float(params["outside_position"])
        positions[inside] = float(params["direction"])
        return positions
    if candidate.family == "macro_rank_weekday":
        rank = events[str(params["rank_column"])].to_numpy(dtype=float)
        weekday = events["weekday"].to_numpy(dtype=float)
        center = float(params["rank"])
        inside = (
            (rank >= center - float(params["pre_days"]))
            & (rank <= center + float(params["post_days"]))
            & (weekday == float(params["weekday"]))
        )
        positions[:] = float(params["outside_position"])
        positions[inside] = float(params["direction"])
        return positions
    if candidate.family == "weekday_calendar":
        weekday = events["weekday"].to_numpy(dtype=float)
        inside = weekday == float(params["weekday"])
        positions[:] = float(params["outside_position"])
        positions[inside] = float(params["direction"])
        return positions
    if candidate.family == "option_expiration_window":
        distance = events["third_friday_rank"].to_numpy(dtype=float)
        inside = (distance >= float(params["start_distance"])) & (distance <= float(params["end_distance"]))
        positions[:] = float(params["outside_position"])
        positions[inside] = float(params["direction"])
        return positions
    feature = params["vix_feature"]
    if feature not in features:
        return positions
    signal = features[feature].to_numpy(dtype=float)
    inside = signal >= float(params["threshold"])
    trend_filter = params.get("trend_filter", "none")
    if trend_filter != "none" and trend_filter in features:
        trend = features[trend_filter].to_numpy(dtype=float)
        inside &= (trend * float(params.get("trend_direction", 1))) >= 0.0
    positions[:] = float(params["outside_position"])
    positions[inside] = float(params["direction"])
    return positions


def daily_metrics(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return {"sharpe": np.nan, "cagr": np.nan, "mdd": np.nan, "positive_days_pct": np.nan}
    std = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values) / std * math.sqrt(PPY)) if std > 0 else np.nan
    nav = np.cumprod(1.0 + values)
    years = len(values) / PPY
    cagr = float(nav[-1] ** (1.0 / years) - 1.0) if years > 0 and nav[-1] > 0 else np.nan
    mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    return {
        "sharpe": sharpe,
        "cagr": cagr,
        "mdd": mdd,
        "positive_days_pct": float(np.mean(values > 0.0)),
    }


def run_merge(output_dir: Path) -> None:
    shard_root = output_dir / "shards"
    top_files = list(shard_root.glob("**/top_candidates.csv"))
    verified_files = list(shard_root.glob("**/verified_candidates_report_only.csv"))
    diag_files = list(shard_root.glob("**/validation_ceiling_diagnostic.csv"))
    summary_files = list(shard_root.glob("**/shard_summary.json"))
    top = pd.concat([pd.read_csv(path) for path in top_files], ignore_index=True) if top_files else pd.DataFrame()
    verified = pd.concat([pd.read_csv(path) for path in verified_files], ignore_index=True) if verified_files else pd.DataFrame()
    diagnostic = pd.concat([pd.read_csv(path) for path in diag_files], ignore_index=True) if diag_files else pd.DataFrame()
    for frame_name, frame in [("top", top), ("verified", verified), ("diagnostic", diagnostic)]:
        if not frame.empty and "params_json" in frame:
            frame["candidate_key"] = frame.apply(
                lambda r: hashlib.sha256(
                    json.dumps(
                        {"paper_key": r.get("paper_key"), "family": r.get("family"), "params_json": r.get("params_json")},
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()[:16],
                axis=1,
            )
            frame.drop_duplicates("candidate_key", inplace=True)
    if not top.empty:
        top = top.sort_values(["train_score", "train_sharpe"], ascending=[False, False])
    if not verified.empty:
        verified = verified.sort_values(["train_sharpe", "validation_sharpe"], ascending=[False, False])
    if not diagnostic.empty:
        diagnostic = diagnostic.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False])
    top.to_csv(output_dir / "paper_spy_daily_event_sharpe2_leaderboard.csv", index=False)
    verified.to_csv(output_dir / "paper_spy_daily_event_sharpe2_verified.csv", index=False)
    diagnostic.to_csv(output_dir / "paper_spy_daily_event_sharpe2_validation_ceiling_diagnostic.csv", index=False)
    fail_reasons = build_fail_reasons(top)
    fail_reasons.to_csv(output_dir / "paper_spy_daily_event_sharpe2_fail_reasons.csv", index=False)
    summaries = []
    for path in summary_files:
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    pd.DataFrame(summaries).to_csv(output_dir / "paper_spy_daily_event_sharpe2_shard_summaries.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "target_train_sharpe": TARGET_SHARPE,
        "target_validation_sharpe_report_only": TARGET_SHARPE,
        "verified_count_report_only": int(len(verified)),
        "top_candidate_rows": int(len(top)),
        "validation_diagnostic_rows": int(len(diagnostic)),
        "configs_evaluated": int(sum(item.get("configs_evaluated", 0) for item in summaries)),
        "best_train_sharpe": float(top["train_sharpe"].max()) if not top.empty else None,
        "best_validation_sharpe": float(top["validation_sharpe"].max()) if not top.empty else None,
        "best_min_train_validation_sharpe": float(top[["train_sharpe", "validation_sharpe"]].min(axis=1).max()) if not top.empty else None,
        "locked_opened": False,
        "locked_rows_accessed": 0,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "paper_sourced_only": True,
        "train_start": str(TRAIN_START.date()),
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "validation_end": str(VALIDATION_END.date()),
        "locked_start": str(LOCKED_START.date()),
    }
    (output_dir / "paper_spy_daily_event_sharpe2_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def build_fail_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in frame.iterrows():
        if bool(row.get("final_verified_report_only", False)):
            reasons.append("verified")
        elif float(row.get("train_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("train_sharpe_below_2")
        elif float(row.get("validation_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("validation_sharpe_below_2_report_only")
        else:
            reasons.append("other")
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


if __name__ == "__main__":
    main()
