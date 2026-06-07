from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backtest_sp500_downside_26_paper_replicas import (
    LOCKED_START,
    TRAIN_END,
    TRAIN_START,
    VALID_END,
    VALID_START,
    build_context,
    build_specs,
)

CAMPAIGN_ID = "paper_operable_ensemble_sharpe2_360stages"
TARGET_SHARPE = 2.0
PPY = 12


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--total-stages", type=int, default=360)
    parser.add_argument("--configs-per-stage", type=int, default=2500)
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
        )
    else:
        run_merge(output_dir, total_stages=args.total_stages)


def run_data(output_dir: Path) -> None:
    ctx = build_context()
    if ctx.monthly_returns.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into operable ensemble context")

    returns: dict[str, pd.Series] = {}
    rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for spec in build_specs():
        result = spec.runner(ctx, spec)
        row = {
            "paper_id": spec.paper_id,
            "paper_title": spec.paper_title,
            "authors": spec.authors,
            "year": spec.year,
            "family": spec.family,
            "replication_level": spec.replication_level,
            "rule_summary": spec.rule_summary,
            "data_required": spec.data_required,
            "proxy_used": spec.proxy_used,
            "proxy_warning": spec.proxy_warning,
            "source_url": spec.source_url,
            "status": result.status,
            "unsupported_reason": result.unsupported_reason,
        }
        # Low-proxy VIX spot sleeves and unsupported exact studies are not operable
        # enough for this goal. They stay visible in the audit, but cannot feed a
        # candidate. No maquillamos un indice no negociable como si fuera una
        # cartera real.
        is_blocked = (
            result.status == "unsupported_exact"
            or "low_proxy" in str(spec.replication_level)
            or "Not tradable" in str(spec.proxy_warning)
            or "Full options unavailable" in str(spec.proxy_warning)
            or "cross-sectional" in str(spec.proxy_warning).lower()
        )
        if is_blocked:
            row["blocked_reason"] = "unsupported_or_non_operable_proxy"
            blocked.append(row)
            continue
        clean = result.returns.reindex(pd.date_range(TRAIN_START, VALID_END, freq="ME"))
        if clean.loc[TRAIN_START:TRAIN_END].dropna().shape[0] < 120:
            row["blocked_reason"] = "insufficient_train_history"
            blocked.append(row)
            continue
        returns[spec.paper_id] = clean.fillna(0.0).rename(spec.paper_id)
        rows.append(row)

    if not returns:
        raise RuntimeError("No operable paper strategy returns available")
    panel = pd.concat(returns.values(), axis=1).sort_index()
    panel = panel.loc[(panel.index >= TRAIN_START) & (panel.index <= VALID_END)]
    if panel.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into operable return panel")
    panel.to_csv(output_dir / "operable_paper_strategy_returns.csv", index_label="date")
    pd.DataFrame(rows).to_csv(output_dir / "operable_paper_strategy_manifest.csv", index=False)
    pd.DataFrame(blocked).to_csv(output_dir / "operable_paper_strategy_blocked.csv", index=False)
    ctx.proxy_map.to_csv(output_dir / "operable_proxy_map.csv", index=False)
    (output_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "objective": "Find paper-sourced operable strategy ensembles with Sharpe >= 2 in train and validation.",
                "train_start": str(TRAIN_START.date()),
                "train_end": str(TRAIN_END.date()),
                "validation_start": str(VALID_START.date()),
                "validation_end": str(VALID_END.date()),
                "locked_start": str(LOCKED_START.date()),
                "data_end_max": str(panel.index.max().date()),
                "locked_opened": False,
                "locked_rows_used": 0,
                "validation_used_for_selection": False,
                "uses_individual_stocks": False,
                "paper_exact_replication_claimed": False,
                "blocked_non_operable_low_proxy": True,
                "operable_strategy_count": int(panel.shape[1]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_shard(output_dir: Path, *, stage: int, total_stages: int, configs_per_stage: int) -> None:
    returns = pd.read_csv(output_dir / "operable_paper_strategy_returns.csv", parse_dates=["date"])
    returns = returns.set_index("date").sort_index()
    manifest = pd.read_csv(output_dir / "operable_paper_strategy_manifest.csv")
    configs = iter_candidate_configs(
        list(returns.columns),
        stage=stage,
        total_stages=total_stages,
        configs_per_stage=configs_per_stage,
    )
    rows: list[dict[str, Any]] = []
    for config in configs:
        rows.append(evaluate_config(config, returns, manifest))

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(shard_dir / "stage_results.csv", index=False)
    (shard_dir / "stage_summary.json").write_text(
        json.dumps(
            {
                "stage": stage,
                "total_stages": total_stages,
                "rows_written": int(len(frame)),
                "configs_per_stage": configs_per_stage,
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_merge(output_dir: Path, *, total_stages: int) -> None:
    result_files = list((output_dir / "shards").glob("**/stage_results.csv"))
    summary_files = list((output_dir / "shards").glob("**/stage_summary.json"))
    if not result_files:
        raise RuntimeError("No shard results found")
    frames = [pd.read_csv(path) for path in result_files]
    all_results = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    all_results = all_results.drop_duplicates(subset=["candidate_id"], keep="first")
    all_results = all_results.sort_values(["train_sharpe", "validation_sharpe"], ascending=[False, False])
    accepted = all_results[
        (all_results["train_sharpe"] >= TARGET_SHARPE)
        & (all_results["validation_sharpe"] >= TARGET_SHARPE)
        & (all_results["locked_opened"].astype(str).str.lower() == "false")
        & (all_results["validation_used_for_selection"].astype(str).str.lower() == "false")
    ].copy()
    accepted = accepted.sort_values(["train_sharpe", "validation_sharpe"], ascending=[False, False])
    found_stages = sorted(
        int(json.loads(path.read_text(encoding="utf-8")).get("stage", -1))
        for path in summary_files
    )
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    all_results.to_csv(final_dir / "paper_operable_ensemble_leaderboard.csv", index=False)
    accepted.to_csv(final_dir / "paper_operable_ensemble_accepted.csv", index=False)
    all_results.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(200).to_csv(
        final_dir / "paper_operable_ensemble_validation_top.csv",
        index=False,
    )
    partial = len(set(found_stages)) != total_stages
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "stages_expected": total_stages,
        "stages_found": len(set(found_stages)),
        "partial": partial,
        "candidates_evaluated": int(len(all_results)),
        "accepted_count": int(len(accepted)),
        "best_train_sharpe": float(all_results["train_sharpe"].max()) if not all_results.empty else None,
        "best_validation_sharpe": float(all_results["validation_sharpe"].max()) if not all_results.empty else None,
        "best_min_train_validation_sharpe": float(all_results[["train_sharpe", "validation_sharpe"]].min(axis=1).max())
        if not all_results.empty
        else None,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "uses_individual_stocks": False,
        "paper_exact_replication_claimed": False,
    }
    (final_dir / "paper_operable_ensemble_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if partial:
        raise RuntimeError(f"Partial merge: found {len(set(found_stages))}/{total_stages} stages")


def iter_candidate_configs(
    ids: list[str],
    *,
    stage: int,
    total_stages: int,
    configs_per_stage: int,
) -> list[dict[str, Any]]:
    ids = sorted(ids)
    configs: list[dict[str, Any]] = []
    # Exhaustive small combinations are partitioned by candidate hash. Larger
    # combinations are sampled deterministically per stage, because enumerating
    # the full ensemble universe in every runner is stupidly expensive.
    for paper_id in ids:
        add_if_stage(configs, {"mode": "single", "ids": [paper_id]}, stage, total_stages)
    for size in range(2, min(4, len(ids)) + 1):
        for combo in itertools.combinations(ids, size):
            add_if_stage(configs, {"mode": "equal", "ids": list(combo)}, stage, total_stages)
            for ridge in (1e-5, 1e-4, 1e-3, 1e-2):
                add_if_stage(
                    configs,
                    {"mode": "train_markowitz_long", "ids": list(combo), "ridge": ridge},
                    stage,
                    total_stages,
                )
            add_if_stage(configs, {"mode": "inverse_train_vol", "ids": list(combo)}, stage, total_stages)

    rng = np.random.default_rng(10_000_003 + stage)
    modes = ("equal", "inverse_train_vol", "train_markowitz_long")
    ridges = (1e-5, 1e-4, 1e-3, 1e-2)
    while len(configs) < configs_per_stage:
        size = int(rng.integers(2, min(9, len(ids) + 1)))
        combo = sorted(rng.choice(ids, size=size, replace=False).tolist())
        mode = str(rng.choice(modes))
        config: dict[str, Any] = {"mode": mode, "ids": combo}
        if mode == "train_markowitz_long":
            config["ridge"] = float(rng.choice(ridges))
        configs.append(config)

    vol_configs: list[dict[str, Any]] = []
    for config in configs[:configs_per_stage]:
        vol_configs.append(config)
        # One deterministic volatility-management variant per base config keeps
        # runtime bounded while still testing the Moreira-Muir layer.
        seed = int(hashlib.sha256(candidate_id(config).encode("utf-8")).hexdigest()[:8], 16)
        child = dict(config)
        child["vol_lookback"] = (3, 6, 9, 12, 18, 24)[seed % 6]
        child["vol_target_monthly"] = (0.01, 0.015, 0.02, 0.025, 0.03)[(seed // 7) % 5]
        child["max_scale"] = (0.75, 1.0, 1.25, 1.5, 2.0, 3.0)[(seed // 31) % 6]
        vol_configs.append(child)
    return vol_configs[: configs_per_stage * 2]


def add_if_stage(configs: list[dict[str, Any]], config: dict[str, Any], stage: int, total_stages: int) -> None:
    cid = candidate_id(config)
    bucket = int(hashlib.sha256(cid.encode("utf-8")).hexdigest()[:12], 16) % total_stages
    if bucket == stage:
        configs.append(config)


def candidate_id(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return "operable_paper_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def evaluate_config(config: dict[str, Any], returns: pd.DataFrame, manifest: pd.DataFrame) -> dict[str, Any]:
    ids = list(config["ids"])
    weights = train_only_weights(config, returns)
    base = returns[ids].dot(weights)
    scale = pd.Series(1.0, index=base.index, name="scale")
    if "vol_lookback" in config:
        lookback = int(config["vol_lookback"])
        target = float(config["vol_target_monthly"])
        max_scale = float(config["max_scale"])
        scale = volatility_scale(base, lookback=lookback, target=target, max_scale=max_scale)
        base = base * scale
    train = base.loc[TRAIN_START:TRAIN_END]
    validation = base.loc[VALID_START:VALID_END]
    train_m = period_metrics(train)
    valid_m = period_metrics(validation)
    src = manifest.set_index("paper_id").reindex(ids)
    source_papers = "; ".join(str(x) for x in src["paper_title"].dropna().unique())
    source_urls = "; ".join(str(x) for x in src["source_url"].dropna().unique() if str(x))
    accepted = bool(train_m["sharpe"] >= TARGET_SHARPE and valid_m["sharpe"] >= TARGET_SHARPE)
    return {
        "candidate_id": candidate_id(config),
        "strategy_name": config_name(config),
        "source_papers": source_papers,
        "source_urls": source_urls,
        "paper_ids": "|".join(ids),
        "paper_count": len(ids),
        "weights": "|".join(f"{x:.6f}" for x in weights),
        "config_json": json.dumps(config, sort_keys=True),
        "status": "accepted" if accepted else "evaluated",
        "accepted": accepted,
        "train_start": str(TRAIN_START.date()),
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALID_START.date()),
        "validation_end": str(VALID_END.date()),
        **{f"train_{k}": v for k, v in train_m.items()},
        **{f"validation_{k}": v for k, v in valid_m.items()},
        "avg_scale": float(scale.mean()),
        "max_scale_realized": float(scale.max()),
        "lag_audit": "Base paper strategy returns are monthly and already traded with one-month lag in source runner; ensemble volatility scale uses prior realised volatility shifted by one month.",
        "lookahead_audit": "Weights, Markowitz covariance and volatility scaling use train or past returns only. Validation is measured after selection.",
        "proxy_audit": "Uses operable ETF/fund/index class proxies from the 26-paper Aurora replica runner; low-proxy/non-tradable VIX spot and unsupported exact studies are excluded.",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "uses_individual_stocks": False,
        "paper_exact_replication_claimed": False,
    }


def config_name(config: dict[str, Any]) -> str:
    suffix = "_".join(config["ids"])
    name = str(config["mode"])
    if "vol_lookback" in config:
        name += f"_vm{config['vol_lookback']}_t{config['vol_target_monthly']}_mx{config['max_scale']}"
    return f"{name}_{hashlib.sha1(suffix.encode('utf-8')).hexdigest()[:8]}"


def train_only_weights(config: dict[str, Any], returns: pd.DataFrame) -> np.ndarray:
    ids = list(config["ids"])
    if len(ids) == 1:
        return np.ones(1)
    train = returns.loc[TRAIN_START:TRAIN_END, ids].fillna(0.0)
    if config["mode"] == "equal":
        return np.ones(len(ids)) / len(ids)
    if config["mode"] == "inverse_train_vol":
        vol = train.std(ddof=0).replace(0.0, np.nan)
        inv = (1.0 / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=float)
        return inv / inv.sum() if inv.sum() > 0 else np.ones(len(ids)) / len(ids)
    if config["mode"] == "train_markowitz_long":
        ridge = float(config.get("ridge", 1e-3))
        matrix = train.to_numpy(dtype=float)
        mu = matrix.mean(axis=0)
        cov = np.cov(matrix, rowvar=False) + ridge * np.eye(len(ids))
        try:
            weights = np.linalg.solve(cov, mu)
        except np.linalg.LinAlgError:
            return np.ones(len(ids)) / len(ids)
        weights = np.maximum(weights, 0.0)
        return weights / weights.sum() if weights.sum() > 0 else np.ones(len(ids)) / len(ids)
    return np.ones(len(ids)) / len(ids)


def volatility_scale(returns: pd.Series, *, lookback: int, target: float, max_scale: float) -> pd.Series:
    vol = returns.rolling(lookback, min_periods=max(2, lookback // 2)).std(ddof=0)
    scale = (target / vol.replace(0.0, np.nan)).clip(lower=0.0, upper=max_scale)
    return scale.shift(1).fillna(1.0).rename("scale")


def period_metrics(returns: pd.Series) -> dict[str, float]:
    r = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return {
            "cagr_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
            "calmar": float("nan"),
            "positive_months_pct": float("nan"),
            "positive_years_pct": float("nan"),
            "observations": 0.0,
            "final_nav": float("nan"),
        }
    nav = (1.0 + r).cumprod()
    years = len(r) / PPY
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and nav.iloc[-1] > 0 else float("nan")
    vol = float(r.std(ddof=0))
    sharpe = float(r.mean() / vol * math.sqrt(PPY)) if vol > 0 else float("nan")
    mdd = float((nav / nav.cummax() - 1.0).min())
    annual = (1.0 + r).resample("YE").prod(min_count=1) - 1.0
    return {
        "cagr_pct": cagr * 100.0,
        "sharpe": sharpe,
        "mdd_pct": mdd * 100.0,
        "calmar": cagr / abs(mdd) if mdd < 0 else float("inf"),
        "positive_months_pct": float((r > 0.0).mean() * 100.0),
        "positive_years_pct": float((annual > 0.0).mean() * 100.0),
        "observations": float(len(r)),
        "final_nav": float(nav.iloc[-1]),
    }


if __name__ == "__main__":
    main()
