from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CAMPAIGN_ID = "paper_aqr_factor_sharpe2_360stages"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_SHARPE = 2.0
PPY = 252

AQR_DATASETS = {
    "bab": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Betting-Against-Beta-Equity-Factors-Daily.xlsx",
        "paper": "Betting Against Beta",
        "authors": "Frazzini; Pedersen",
        "year": 2014,
        "rule": "Long low-beta equities and short high-beta equities as a self-financing BAB factor.",
        "type": "paper_factor_benchmark_proxy",
    },
    "qmj": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Daily.xlsx",
        "paper": "Quality Minus Junk",
        "authors": "Asness; Frazzini; Pedersen",
        "year": 2014,
        "rule": "Long high-quality equities and short junk equities as a self-financing QMJ factor.",
        "type": "paper_factor_benchmark_proxy",
    },
    "hml_devil": {
        "url": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/The-Devil-in-HMLs-Details-Factors-Daily.xlsx",
        "paper": "The Devil in HML's Details",
        "authors": "Asness; Frazzini",
        "year": 2013,
        "rule": "Value factor with HML Devil implementation details as a self-financing factor.",
        "type": "paper_factor_benchmark_proxy",
    },
}

REGIONS = ("USA", "Global", "Global Ex USA", "Europe", "North America", "Pacific")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    strategy_name: str
    source_papers: str
    strategy_type: str
    rule: str
    factor_columns: tuple[str, ...]
    transform: str
    lookback: int = 0
    max_scale: float = 1.0
    daily_vol_target: float = 0.006
    ridge: float | None = None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--total-stages", type=int, default=360)
    parser.add_argument("--top-per-stage", type=int, default=200)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(output_dir, args.stage, args.total_stages, args.top_per_stage)
    else:
        run_merge(output_dir, args.total_stages)


def run_data(output_dir: Path) -> None:
    frames: list[pd.DataFrame] = []
    source_rows: list[dict[str, Any]] = []
    raw_future_rows = 0
    for dataset_key, meta in AQR_DATASETS.items():
        df = download_aqr_daily_factor(meta["url"])
        raw_future_rows += int((df.index >= LOCKED_START).sum())
        for region in REGIONS:
            if region not in df.columns:
                continue
            col = f"{dataset_key}_{region.replace(' ', '_')}"
            frames.append(df[[region]].rename(columns={region: col}))
            source_rows.append(
                {
                    "factor_column": col,
                    "dataset_key": dataset_key,
                    "region": region,
                    **{k: v for k, v in meta.items() if k != "url"},
                    "url": meta["url"],
                }
            )
    if not frames:
        raise RuntimeError("No AQR factor data downloaded")
    panel = pd.concat(frames, axis=1).sort_index()
    panel = panel.loc[(panel.index >= TRAIN_START) & (panel.index <= VALIDATION_END)]
    if panel.index.max() >= LOCKED_START:
        raise RuntimeError("Locked rows reached AQR factor panel")
    panel.to_csv(output_dir / "aqr_factor_panel.csv", index_label="timestamp")
    pd.DataFrame(source_rows).to_csv(output_dir / "aqr_factor_sources.csv", index=False)
    candidates = build_candidates(panel.columns.tolist())
    pd.DataFrame([candidate_to_row(c) for c in candidates]).to_csv(
        output_dir / "candidate_manifest.csv",
        index=False,
    )
    (output_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "objective": "Find paper-sourced AQR factor strategies with Sharpe >= 2 in train and validation.",
                "train_start": str(TRAIN_START.date()),
                "train_end": str(TRAIN_END.date()),
                "validation_start": str(VALIDATION_START.date()),
                "validation_end": str(VALIDATION_END.date()),
                "locked_start": str(LOCKED_START.date()),
                "data_end_max": str(panel.index.max().date()),
                "locked_opened": False,
                "locked_rows_used": 0,
                "raw_source_rows_at_or_after_locked": raw_future_rows,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
                "paper_sourced_only": True,
                "frequency": "daily",
                "lag_periods_minimum": 1,
                "candidate_count": len(candidates),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def download_aqr_daily_factor(url: str) -> pd.DataFrame:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Aurora research"})
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read()
    return parse_aqr_daily_factor_xlsx(raw)


def parse_aqr_daily_factor_xlsx(raw: bytes) -> pd.DataFrame:
    excel = pd.ExcelFile(io.BytesIO(raw))
    sheet = excel.sheet_names[0]
    preview = pd.read_excel(excel, sheet_name=sheet, header=None, nrows=90)
    header_row = None
    for idx, row in preview.iterrows():
        values = [str(x).strip().upper() for x in row.tolist()]
        if "DATE" in values:
            header_row = int(idx)
            break
    if header_row is None:
        raise ValueError("AQR daily factor file DATE header not found")
    df = pd.read_excel(excel, sheet_name=sheet, header=header_row)
    date_col = next(c for c in df.columns if str(c).strip().upper() == "DATE")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_candidates(columns: list[str]) -> list[Candidate]:
    out: list[Candidate] = []
    for col in columns:
        dataset = col.split("_", 1)[0]
        meta = AQR_DATASETS.get(dataset, {})
        out.append(
            Candidate(
                candidate_id=stable_id("raw", (col,)),
                strategy_name=f"raw_{col}",
                source_papers=str(meta.get("paper", "")),
                strategy_type=str(meta.get("type", "paper_factor_benchmark_proxy")),
                rule=str(meta.get("rule", "")),
                factor_columns=(col,),
                transform="raw_factor",
            )
        )
        for lookback in (21, 63, 126):
            for max_scale in (1.0, 2.0, 3.0, 5.0):
                out.append(
                    Candidate(
                        candidate_id=stable_id("volmanaged", (col, str(lookback), str(max_scale))),
                        strategy_name=f"volmanaged_{lookback}_max{max_scale:g}_{col}",
                        source_papers=f"{meta.get('paper', '')}; Volatility-Managed Portfolios",
                        strategy_type="multi_paper_proxy",
                        rule=(
                            f"{meta.get('rule', '')} Scale next-day exposure using prior "
                            f"{lookback}-day realised volatility, following Moreira-Muir style volatility management."
                        ),
                        factor_columns=(col,),
                        transform="volmanaged",
                        lookback=lookback,
                        max_scale=max_scale,
                    )
                )
    for region in sorted({region_from_col(c) for c in columns}):
        region_cols = tuple(c for c in columns if region_from_col(c) == region)
        if len(region_cols) < 2:
            continue
        out.append(
            Candidate(
                candidate_id=stable_id("equal_factor_blend", region_cols),
                strategy_name=f"equal_factor_blend_{region}",
                source_papers="; ".join(sorted({paper_for_col(c) for c in region_cols})),
                strategy_type="multi_paper_proxy",
                rule="Equal-weight blend of AQR paper factors in the same region.",
                factor_columns=region_cols,
                transform="equal_factor_blend",
            )
        )
        for ridge in (0.0001, 0.001, 0.01):
            base = Candidate(
                candidate_id=stable_id("train_markowitz", (*region_cols, str(ridge))),
                strategy_name=f"train_markowitz_{region}_ridge_{ridge:g}",
                source_papers="; ".join(sorted({paper_for_col(c) for c in region_cols})),
                strategy_type="multi_paper_proxy",
                rule="Train-only mean-variance blend of AQR paper factors in the same region.",
                factor_columns=region_cols,
                transform="train_markowitz",
                ridge=ridge,
            )
            out.append(base)
            for lookback in (21, 63, 126):
                for max_scale in (1.0, 2.0, 3.0, 5.0):
                    out.append(
                        Candidate(
                            candidate_id=stable_id("volmanaged_markowitz", (*region_cols, str(ridge), str(lookback), str(max_scale))),
                            strategy_name=f"volmanaged_{lookback}_max{max_scale:g}_{base.strategy_name}",
                            source_papers=f"{base.source_papers}; Volatility-Managed Portfolios",
                            strategy_type="multi_paper_proxy",
                            rule=f"{base.rule} Exposure is scaled using prior {lookback}-day realised volatility.",
                            factor_columns=region_cols,
                            transform="volmanaged_train_markowitz",
                            lookback=lookback,
                            max_scale=max_scale,
                            ridge=ridge,
                        )
                    )
    return out


def stable_id(prefix: str, parts: tuple[str, ...]) -> str:
    import hashlib

    digest = hashlib.sha256("|".join((prefix, *parts)).encode("utf-8")).hexdigest()[:16]
    return f"aqr_{digest}"


def region_from_col(col: str) -> str:
    for prefix in ("bab_", "qmj_", "hml_devil_"):
        if col.startswith(prefix):
            return col[len(prefix) :]
    return col.rsplit("_", 1)[-1]


def paper_for_col(col: str) -> str:
    if col.startswith("bab_"):
        return str(AQR_DATASETS["bab"]["paper"])
    if col.startswith("qmj_"):
        return str(AQR_DATASETS["qmj"]["paper"])
    if col.startswith("hml_devil_"):
        return str(AQR_DATASETS["hml_devil"]["paper"])
    return ""


def candidate_to_row(candidate: Candidate) -> dict[str, Any]:
    row = candidate.__dict__.copy()
    row["factor_columns"] = ",".join(candidate.factor_columns)
    return row


def run_shard(output_dir: Path, stage: int, total_stages: int, top_per_stage: int) -> None:
    panel = read_panel(output_dir)
    candidates = build_candidates(panel.columns.tolist())
    selected = [candidate for idx, candidate in enumerate(candidates) if idx % total_stages == stage]
    rows: list[dict[str, Any]] = []
    for candidate in selected:
        try:
            returns, weights = build_candidate_returns(panel, candidate)
            row = evaluate_candidate(candidate, returns, weights)
        except Exception as exc:
            row = {
                **candidate_to_row(candidate),
                "status": "error",
                "error": str(exc),
                "locked_opened": False,
                "validation_used_for_selection": False,
            }
        rows.append(row)
    stage_dir = output_dir / "shards" / f"stage_{stage:03d}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if not frame.empty and "train_sharpe" in frame:
        frame = frame.sort_values(["train_sharpe", "candidate_id"], ascending=[False, True]).head(top_per_stage)
    frame.to_csv(stage_dir / "stage_results.csv", index=False)
    (stage_dir / "stage_summary.json").write_text(
        json.dumps(
            {
                "stage": stage,
                "total_stages": total_stages,
                "candidates_seen": len(selected),
                "rows_written": int(len(frame)),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def read_panel(output_dir: Path) -> pd.DataFrame:
    panel = pd.read_csv(output_dir / "aqr_factor_panel.csv", parse_dates=["timestamp"])
    panel = panel.set_index("timestamp").sort_index()
    panel = panel.loc[(panel.index >= TRAIN_START) & (panel.index <= VALIDATION_END)]
    if panel.index.max() >= LOCKED_START:
        raise RuntimeError("Locked rows reached shard panel")
    return panel


def build_candidate_returns(panel: pd.DataFrame, candidate: Candidate) -> tuple[pd.Series, pd.DataFrame]:
    cols = list(candidate.factor_columns)
    data = panel[cols].copy()
    if candidate.transform == "raw_factor":
        weights = pd.DataFrame({cols[0]: 1.0}, index=data.index)
        return data[cols[0]].rename("strategy_return"), weights
    if candidate.transform == "equal_factor_blend":
        weights = pd.DataFrame(1.0 / len(cols), index=data.index, columns=cols)
        return data.mean(axis=1).rename("strategy_return"), weights
    if candidate.transform in {"train_markowitz", "volmanaged_train_markowitz"}:
        base, weights = train_markowitz_returns(data, ridge=float(candidate.ridge or 0.0))
        if candidate.transform == "train_markowitz":
            return base, weights
        scaled, scale = volatility_managed(base, lookback=candidate.lookback, max_scale=candidate.max_scale, target=candidate.daily_vol_target)
        return scaled, weights.mul(scale, axis=0)
    if candidate.transform == "volmanaged":
        base = data[cols[0]].rename("strategy_return")
        scaled, scale = volatility_managed(base, lookback=candidate.lookback, max_scale=candidate.max_scale, target=candidate.daily_vol_target)
        weights = pd.DataFrame({cols[0]: scale}, index=data.index)
        return scaled, weights
    raise ValueError(f"Unknown transform: {candidate.transform}")


def train_markowitz_returns(data: pd.DataFrame, *, ridge: float) -> tuple[pd.Series, pd.DataFrame]:
    train = data.loc[(data.index >= TRAIN_START) & (data.index <= TRAIN_END)].dropna()
    if len(train) < 500:
        raise ValueError("Not enough train observations for train_markowitz")
    mu = train.mean().to_numpy()
    cov = train.cov().to_numpy() + np.eye(train.shape[1]) * ridge
    weights_vec = np.linalg.solve(cov, mu)
    denom = float(np.sum(np.abs(weights_vec)))
    if denom <= 0 or not np.isfinite(denom):
        raise ValueError("Invalid train_markowitz weights")
    weights_vec = weights_vec / denom
    weights = pd.DataFrame([weights_vec] * len(data), index=data.index, columns=data.columns)
    returns = (data.fillna(0.0) * weights).sum(axis=1).rename("strategy_return")
    return returns, weights


def volatility_managed(base: pd.Series, *, lookback: int, max_scale: float, target: float) -> tuple[pd.Series, pd.Series]:
    min_periods = min(lookback, max(5, lookback // 3))
    realised_vol = base.rolling(lookback, min_periods=min_periods).std(ddof=0)
    scale = (target / realised_vol.replace(0.0, np.nan)).clip(lower=0.0, upper=max_scale)
    scale = scale.shift(1).fillna(1.0).rename("scale")
    return (base * scale).rename("strategy_return"), scale


def evaluate_candidate(candidate: Candidate, returns: pd.Series, weights: pd.DataFrame) -> dict[str, Any]:
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    train = returns.loc[(returns.index >= TRAIN_START) & (returns.index <= TRAIN_END)]
    validation = returns.loc[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    train_m = metrics(train)
    validation_m = metrics(validation)
    accepted = bool(
        train_m["sharpe"] >= TARGET_SHARPE
        and validation_m["sharpe"] >= TARGET_SHARPE
    )
    return {
        **candidate_to_row(candidate),
        "status": "accepted" if accepted else "evaluated",
        "accepted": accepted,
        "train_start": str(TRAIN_START.date()),
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "validation_end": str(VALIDATION_END.date()),
        **{f"train_{k}": v for k, v in train_m.items()},
        **{f"validation_{k}": v for k, v in validation_m.items()},
        "max_abs_weight": float(weights.abs().sum(axis=1).max()) if not weights.empty else math.nan,
        "avg_abs_weight": float(weights.abs().sum(axis=1).mean()) if not weights.empty else math.nan,
        "lag_audit": "volatility scale uses rolling realised volatility shifted by 1 day; factor return series is the published self-financing paper factor.",
        "lookahead_audit": "No validation rows are used for train metrics, weights, volatility scale at t, or train-only Markowitz weights.",
        "proxy_audit": "AQR published paper factor benchmark/proxy. Not claimed as exact live replication of individual stock portfolio.",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    }


def metrics(returns: pd.Series) -> dict[str, float]:
    r = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return {
            "cagr_pct": math.nan,
            "sharpe": math.nan,
            "mdd_pct": math.nan,
            "calmar": math.nan,
            "positive_days_pct": math.nan,
            "positive_months_pct": math.nan,
            "positive_years_pct": math.nan,
            "observations": 0,
            "final_nav": math.nan,
        }
    nav = (1.0 + r).cumprod()
    years = len(r) / PPY
    cagr = nav.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 and nav.iloc[-1] > 0 else math.nan
    vol = float(r.std(ddof=0))
    sharpe = float(r.mean() / vol * math.sqrt(PPY)) if vol > 0 else math.nan
    mdd = float((nav / nav.cummax() - 1.0).min())
    monthly = (1.0 + r).resample("ME").prod() - 1.0
    yearly = (1.0 + r).resample("YE").prod() - 1.0
    return {
        "cagr_pct": cagr * 100.0,
        "sharpe": sharpe,
        "mdd_pct": mdd * 100.0,
        "calmar": cagr / abs(mdd) if mdd < 0 and np.isfinite(cagr) else math.inf,
        "positive_days_pct": float((r > 0).mean() * 100.0),
        "positive_months_pct": float((monthly > 0).mean() * 100.0),
        "positive_years_pct": float((yearly > 0).mean() * 100.0),
        "observations": int(len(r)),
        "final_nav": float(nav.iloc[-1]),
    }


def run_merge(output_dir: Path, total_stages: int) -> None:
    frames: list[pd.DataFrame] = []
    found_stages: set[int] = set()
    for path in (output_dir / "shards").glob("stage_*/stage_results.csv"):
        try:
            stage = int(path.parent.name.split("_")[-1])
        except Exception:
            stage = -1
        found_stages.add(stage)
        frames.append(pd.read_csv(path))
    if not frames:
        raise RuntimeError("No stage results found")
    all_results = pd.concat(frames, ignore_index=True)
    all_results = all_results.drop_duplicates(subset=["candidate_id"], keep="first")
    all_results = all_results.sort_values(["train_sharpe", "candidate_id"], ascending=[False, True])
    accepted = all_results[
        (all_results["train_sharpe"] >= TARGET_SHARPE)
        & (all_results["validation_sharpe"] >= TARGET_SHARPE)
        & (all_results["locked_opened"].astype(str).str.lower() == "false")
        & (all_results["validation_used_for_selection"].astype(str).str.lower() == "false")
    ].copy()
    accepted = accepted.sort_values(["train_sharpe", "validation_sharpe"], ascending=[False, False])
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    all_results.to_csv(final_dir / "paper_aqr_factor_leaderboard.csv", index=False)
    accepted.to_csv(final_dir / "paper_aqr_factor_accepted.csv", index=False)
    all_results.head(100).to_csv(final_dir / "paper_aqr_factor_train_top.csv", index=False)
    all_results.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(100).to_csv(
        final_dir / "paper_aqr_factor_validation_report.csv",
        index=False,
    )
    all_results[[
        "candidate_id",
        "strategy_name",
        "source_papers",
        "strategy_type",
        "rule",
        "factor_columns",
        "lag_audit",
        "lookahead_audit",
        "proxy_audit",
    ]].drop_duplicates().to_csv(final_dir / "paper_aqr_factor_audit.csv", index=False)
    policy = json.loads((output_dir / "policy_audit.json").read_text(encoding="utf-8"))
    summary = {
        **policy,
        "stages_expected": total_stages,
        "stages_found": len(found_stages),
        "partial": len(found_stages) != total_stages,
        "candidates_evaluated": int(len(all_results)),
        "accepted_count": int(len(accepted)),
        "best_train_sharpe": float(all_results["train_sharpe"].max()),
        "best_validation_sharpe": float(all_results["validation_sharpe"].max()),
        "best_min_train_validation_sharpe": float(all_results[["train_sharpe", "validation_sharpe"]].min(axis=1).max()),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    }
    (final_dir / "paper_aqr_factor_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if accepted.empty:
        print("No accepted AQR paper factor strategy found.")
    else:
        print(f"Accepted AQR paper factor strategies: {len(accepted)}")
        print(accepted[["candidate_id", "strategy_name", "train_sharpe", "validation_sharpe"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
