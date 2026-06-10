from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aurora.core.metrics import compute_metrics

paper = importlib.import_module("scripts.run_paper_operable_ensemble_sharpe2")
btc = importlib.import_module("scripts.run_btc_5m_pf105_statistical_robustness")
from aurora.research.btc_5m_trainonly_search import (
    BTC5mSearchConfig,
    _method_offset,
    _scores_for_spec,
    candidate_id_from_spec,
    load_dataset,
    positions_from_scores,
    WAVE_SEED_STRIDE,
)

DEFAULT_OUTPUT = Path("outputs/calmar_gt1_pvalue_bootstrap_173495")
DEFAULT_SOURCE = Path("outputs/robustness_calmar_gt1_soft_gate_173495/soft_robust_results.csv")
PPY_MONTHLY = 12
PPY_DAILY = 365


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["prepare", "prepare-from-artifacts", "prepare-data", "chunk", "merge"], required=True)
    parser.add_argument("--source-csv", default=str(DEFAULT_SOURCE))
    parser.add_argument("--source-root", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--total-chunks", type=int, default=360)
    parser.add_argument("--n-bootstrap", type=int, default=80)
    parser.add_argument("--bootstrap-block", type=int, default=6)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--allow-unsupported", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--family-filter", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare":
        prepare_manifest(Path(args.source_csv), output_dir)
    elif args.mode == "prepare-from-artifacts":
        prepare_manifest_from_artifacts(Path(args.source_root), output_dir)
    elif args.mode == "prepare-data":
        prepare_data(output_dir)
    elif args.mode == "chunk":
        run_chunk(
            output_dir,
            chunk_index=args.chunk_index,
            total_chunks=args.total_chunks,
            n_bootstrap=args.n_bootstrap,
            bootstrap_block=args.bootstrap_block,
            alpha=args.alpha,
            limit=args.limit,
            family_filter=args.family_filter,
        )
    else:
        merge(output_dir, total_chunks=args.total_chunks, allow_unsupported=args.allow_unsupported)
    return 0


def prepare_manifest_from_artifacts(source_root: Path, output_dir: Path) -> None:
    if not source_root.exists():
        raise FileNotFoundError(f"source root not found: {source_root}")
    rows: dict[str, dict[str, Any]] = {}
    scanned_files = 0
    source_csvs = []
    for path in source_root.rglob("*.csv"):
        name = path.name.lower()
        if not any(token in name for token in ("leaderboard", "supported", "accepted", "verified")):
            continue
        source_csvs.append(path)
    for path in sorted(source_csvs):
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                first = handle.readline()
                if not first:
                    continue
                header = next(csv.reader([first]))
        except Exception:
            continue
        lows = [h.strip().lower() for h in header]
        if "candidate_id" not in lows:
            continue
        train_calmar_col = _header_pick(header, lows, ["train_calmar", "train_1x_calmar"])
        validation_calmar_col = _header_pick(header, lows, ["validation_calmar", "valid_calmar", "validation_1x_calmar"])
        if not train_calmar_col or not validation_calmar_col:
            continue
        scanned_files += 1
        candidate_col = header[lows.index("candidate_id")]
        usecols = list(
            dict.fromkeys(
                [
                    candidate_col,
                    train_calmar_col,
                    validation_calmar_col,
                    *_existing(header, lows, [
                        "train_sharpe",
                        "validation_sharpe",
                        "train_1x_sharpe",
                        "validation_1x_sharpe",
                        "config_json",
                        "rule",
                        "source_method",
                        "method",
                        "wave",
                        "stage",
                        "total_stages",
                        "position_size",
                    ]),
                ]
            )
        )
        for chunk in pd.read_csv(path, usecols=usecols, dtype=str, chunksize=100_000, low_memory=True):
            train_calmar = pd.to_numeric(chunk[train_calmar_col], errors="coerce")
            validation_calmar = pd.to_numeric(chunk[validation_calmar_col], errors="coerce")
            sub = chunk[(train_calmar > 1.0) & (validation_calmar > 1.0)].copy()
            for _, raw in sub.iterrows():
                cid = str(raw[candidate_col]).strip()
                if not cid or cid.lower() in {"nan", "none", "null"}:
                    continue
                row = raw.to_dict()
                family = _family_from_row({"source_file": str(path)}, row)
                item = {
                    "candidate_id": cid,
                    "strategy_key": f"candidate_id:{cid}",
                    "source_run": _source_run_from_artifact_path(path),
                    "source_file": str(path.relative_to(source_root)),
                    "family": family,
                    "config_json": row.get("config_json", ""),
                    "rule": row.get("rule", ""),
                    "source_method": row.get("source_method", row.get("method", "")),
                    "wave": row.get("wave", ""),
                    "stage": row.get("stage", ""),
                    "total_stages": row.get("total_stages", ""),
                    "position_size": row.get("position_size", "1.0"),
                    "train_sharpe": row.get("train_sharpe", row.get("train_1x_sharpe", "")),
                    "validation_sharpe": row.get("validation_sharpe", row.get("validation_1x_sharpe", "")),
                    "train_calmar": row.get(train_calmar_col, ""),
                    "validation_calmar": row.get(validation_calmar_col, ""),
                    "reconstruction_status": "pending",
                }
                previous = rows.get(cid)
                quality = int(bool(item["config_json"])) + int(bool(item["rule"]))
                previous_quality = int(bool(previous and previous.get("config_json"))) + int(bool(previous and previous.get("rule")))
                if previous is None or quality >= previous_quality:
                    rows[cid] = item

    manifest = pd.DataFrame(rows.values()).sort_values(["family", "candidate_id"]) if rows else pd.DataFrame()
    manifest.to_csv(output_dir / "calmar_gt1_pvalue_bootstrap_manifest.csv", index=False)
    summary = {
        "source_root": str(source_root),
        "source_csvs_found": len(source_csvs),
        "source_csvs_used": scanned_files,
        "manifest_rows": int(len(manifest)),
        "by_family": manifest["family"].value_counts(dropna=False).to_dict() if not manifest.empty else {},
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (output_dir / "prepare_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def _header_pick(header: list[str], lows: list[str], names: list[str]) -> str | None:
    for name in names:
        if name in lows:
            return header[lows.index(name)]
    return None


def _existing(header: list[str], lows: list[str], names: list[str]) -> list[str]:
    out = []
    for name in names:
        if name in lows:
            out.append(header[lows.index(name)])
    return out


def _source_run_from_artifact_path(path: Path) -> str:
    parts = [part for part in path.parts]
    for part in parts:
        if part.startswith("run_"):
            return part.removeprefix("run_")
    return ""


def prepare_manifest(source_csv: Path, output_dir: Path) -> None:
    source = pd.read_csv(source_csv, dtype=str)
    source = source.drop_duplicates("strategy_key", keep="first")
    wanted_by_file: dict[str, set[str]] = {}
    for row in source.itertuples(index=False):
        wanted_by_file.setdefault(str(row.source_file), set()).add(str(row.id_value))

    rows: list[dict[str, Any]] = []
    source_by_id = source.set_index("id_value", drop=False)
    for source_file, wanted in sorted(wanted_by_file.items()):
        path = Path("outputs") / source_file
        if not path.exists():
            for cid in sorted(wanted):
                rows.append(_unsupported_row(source_by_id.loc[cid], "source_file_missing"))
            continue
        id_col = "candidate_id"
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                header = next(csv.reader([handle.readline()]))
            if "candidate_id" not in header:
                for candidate in ("strategy_id", "signature_hash"):
                    if candidate in header:
                        id_col = candidate
                        break
        except Exception:
            for cid in sorted(wanted):
                rows.append(_unsupported_row(source_by_id.loc[cid], "source_file_header_error"))
            continue

        matched: set[str] = set()
        for chunk in pd.read_csv(path, dtype=str, chunksize=100_000, low_memory=True):
            if id_col not in chunk.columns:
                break
            sub = chunk[chunk[id_col].astype(str).isin(wanted)].copy()
            if sub.empty:
                continue
            for _, raw in sub.iterrows():
                cid = str(raw[id_col])
                matched.add(cid)
                base = source_by_id.loc[cid].to_dict()
                family = _family_from_row(base, raw.to_dict())
                rows.append(
                    {
                        "candidate_id": cid,
                        "strategy_key": base.get("strategy_key", f"candidate_id:{cid}"),
                        "source_run": base.get("source_run", ""),
                        "source_file": source_file,
                        "family": family,
                        "config_json": raw.get("config_json", ""),
                        "rule": raw.get("rule", ""),
                        "source_method": raw.get("source_method", raw.get("method", "")),
                        "wave": raw.get("wave", ""),
                        "stage": raw.get("stage", ""),
                        "total_stages": raw.get("total_stages", ""),
                        "position_size": raw.get("position_size", "1.0"),
                        "train_sharpe": base.get("train_sharpe", ""),
                        "validation_sharpe": base.get("validation_sharpe", ""),
                        "train_calmar": base.get("train_calmar", ""),
                        "validation_calmar": base.get("validation_calmar", ""),
                        "reconstruction_status": "pending",
                    }
                )
        for cid in sorted(wanted - matched):
            rows.append(_unsupported_row(source_by_id.loc[cid], "candidate_not_found_in_source_file"))

    manifest = pd.DataFrame(rows)
    manifest.to_csv(output_dir / "calmar_gt1_pvalue_bootstrap_manifest.csv", index=False)
    summary = {
        "input_candidates": int(source.shape[0]),
        "manifest_rows": int(len(manifest)),
        "by_family": manifest["family"].value_counts(dropna=False).to_dict() if not manifest.empty else {},
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (output_dir / "prepare_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def _unsupported_row(row: pd.Series | dict[str, Any], reason: str) -> dict[str, Any]:
    item = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    return {
        "candidate_id": item.get("id_value", ""),
        "strategy_key": item.get("strategy_key", ""),
        "source_run": item.get("source_run", ""),
        "source_file": item.get("source_file", ""),
        "family": "unsupported",
        "config_json": "",
        "rule": "",
        "source_method": "",
        "wave": "",
        "stage": "",
        "total_stages": "",
        "position_size": "1.0",
        "train_sharpe": item.get("train_sharpe", ""),
        "validation_sharpe": item.get("validation_sharpe", ""),
        "train_calmar": item.get("train_calmar", ""),
        "validation_calmar": item.get("validation_calmar", ""),
        "reconstruction_status": reason,
    }


def _family_from_row(base: dict[str, Any], raw: dict[str, Any]) -> str:
    cid = str(raw.get("candidate_id") or base.get("id_value") or "")
    source_file = str(base.get("source_file") or "")
    if cid.startswith("operable_paper_") and "config_json" in raw:
        return "paper_operable_ensemble"
    if cid.startswith("btc_5m_"):
        return "btc_5m"
    if cid.startswith("aqr_"):
        return "unsupported_aqr_factor_no_return_rebuilder"
    if cid.startswith("lit_"):
        return "unsupported_literature_no_return_rebuilder"
    if "paper_operable_ensemble" in source_file:
        return "paper_operable_ensemble"
    return "unsupported_no_return_rebuilder"


def prepare_data(output_dir: Path) -> None:
    paper_dir = output_dir / "paper_data"
    paper_dir.mkdir(parents=True, exist_ok=True)
    if not (paper_dir / "operable_paper_strategy_returns.csv").exists():
        paper.run_data(paper_dir)
    summary = {
        "paper_data": str(paper_dir / "operable_paper_strategy_returns.csv"),
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (output_dir / "data_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def run_chunk(
    output_dir: Path,
    *,
    chunk_index: int,
    total_chunks: int,
    n_bootstrap: int,
    bootstrap_block: int,
    alpha: float,
    limit: int,
    family_filter: str,
) -> None:
    manifest_path = output_dir / "calmar_gt1_pvalue_bootstrap_manifest.csv"
    manifest = pd.read_csv(manifest_path, dtype=str).fillna("")
    chunk = manifest.iloc[[i for i in range(len(manifest)) if i % total_chunks == chunk_index]].copy()
    if family_filter:
        allowed = {item.strip() for item in family_filter.split(",") if item.strip()}
        chunk = chunk[chunk["family"].astype(str).isin(allowed)].copy()
    if limit > 0:
        chunk = chunk.head(limit)
    paper_returns: pd.DataFrame | None = None
    btc_dataset: dict[str, Any] | None = None
    btc_ml_cache: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}

    rows: list[dict[str, Any]] = []
    for row in chunk.to_dict("records"):
        try:
            family = str(row.get("family", ""))
            if family == "paper_operable_ensemble":
                if paper_returns is None:
                    paper_returns = pd.read_csv(
                        output_dir / "paper_data" / "operable_paper_strategy_returns.csv",
                        parse_dates=["date"],
                    ).set_index("date").sort_index()
                train, validation = _paper_candidate_returns(row, paper_returns)
                rows.append(_result_row(row, train, validation, PPY_MONTHLY, n_bootstrap, bootstrap_block, alpha))
            elif family == "btc_5m":
                if btc_dataset is None:
                    cfg = BTC5mSearchConfig(run_id="btc_5m_all_features_5methods_trainonly_9h_max500_real180")
                    btc_dataset, _audit = load_dataset(cfg)
                train, validation = _btc_candidate_returns(row, btc_dataset, btc_ml_cache)
                train_daily = btc._daily_from_5m(train, btc_dataset["train_index"])
                valid_daily = btc._daily_from_5m(validation, btc_dataset["valid_index"])
                rows.append(_result_row(row, train_daily, valid_daily, PPY_DAILY, n_bootstrap, 5, alpha))
            else:
                rows.append(_error_row(row, str(row.get("reconstruction_status") or family or "unsupported")))
        except Exception as exc:
            rows.append(_error_row(row, f"error:{str(exc)[:240]}"))

    out_dir = output_dir / "chunks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"chunk_{chunk_index:04d}.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    summary = {
        "chunk_index": int(chunk_index),
        "total_chunks": int(total_chunks),
        "rows": int(len(rows)),
        "pass_pvalue_bootstrap": int(sum(bool(r.get("pvalue_bootstrap_pass")) for r in rows)),
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (out_dir / f"chunk_{chunk_index:04d}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def _paper_candidate_returns(row: dict[str, Any], returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    config = json.loads(str(row["config_json"]))
    ids = list(config["ids"])
    weights = paper.train_only_weights(config, returns)
    series = returns[ids].dot(weights)
    if "vol_lookback" in config:
        series = series * paper.volatility_scale(
            series,
            lookback=int(config["vol_lookback"]),
            target=float(config["vol_target_monthly"]),
            max_scale=float(config["max_scale"]),
        )
    train = series.loc[paper.TRAIN_START:paper.TRAIN_END].dropna().to_numpy(dtype=float)
    validation = series.loc[paper.VALID_START:paper.VALID_END].dropna().to_numpy(dtype=float)
    return train, validation


def _btc_candidate_returns(
    row: dict[str, Any],
    dataset: dict[str, Any],
    ml_cache: dict[tuple[int, int], dict[str, dict[str, Any]]],
) -> tuple[np.ndarray, np.ndarray]:
    method = str(row.get("source_method") or "")
    if method == "github_ml":
        wave = int(float(row.get("wave") or 0))
        stage = int(float(row.get("stage") or 0))
        key = (wave, stage)
        if key not in ml_cache:
            cfg = BTC5mSearchConfig(run_id="btc_5m_all_features_5methods_trainonly_9h_max500_real180")
            target_row = {k: str(v) for k, v in row.items()}
            ml_cache[key] = btc._replay_ml_specs(
                dataset,
                cfg,
                [target_row],
                wave=wave,
                stage=stage,
                total_stages=int(float(row.get("total_stages") or 36)),
            )
        spec = ml_cache[key].get(str(row.get("candidate_id")))
        if spec is None:
            raise ValueError("github_ml spec could not be reconstructed")
    else:
        spec = json.loads(str(row["rule"]))
    fit_payload = spec.get("_fit_payload")
    train_scores = _scores_for_spec(dataset["train_x"], dataset["train_returns"], spec, fit_payload=fit_payload)
    valid_scores = _scores_for_spec(dataset["valid_x"], dataset["valid_returns"], spec, fit_payload=fit_payload)
    train_positions = positions_from_scores(train_scores, threshold=float(spec["threshold"]))
    valid_positions = positions_from_scores(valid_scores, threshold=float(spec["threshold"]))
    size = float(row.get("position_size") or 1.0)
    return (
        train_positions * size * np.asarray(dataset["train_returns"], dtype=float),
        valid_positions * size * np.asarray(dataset["valid_returns"], dtype=float),
    )


def _result_row(
    row: dict[str, Any],
    train: np.ndarray,
    validation: np.ndarray,
    ppy: int,
    n_bootstrap: int,
    bootstrap_block: int,
    alpha: float,
) -> dict[str, Any]:
    train_stats = _period_tests(train, ppy=ppy, n_bootstrap=n_bootstrap, block=bootstrap_block, seed=_seed(row, "train"))
    valid_stats = _period_tests(validation, ppy=ppy, n_bootstrap=n_bootstrap, block=bootstrap_block, seed=_seed(row, "valid"))
    checks = {
        "train_pvalue": train_stats["mean_return_pvalue"] <= alpha,
        "validation_pvalue": valid_stats["mean_return_pvalue"] <= alpha,
        "train_bootstrap_cagr": train_stats["bootstrap_cagr_p05"] >= 0.0,
        "validation_bootstrap_cagr": valid_stats["bootstrap_cagr_p05"] >= 0.0,
        "train_bootstrap_sharpe": train_stats["bootstrap_sharpe_p05"] >= 0.0,
        "validation_bootstrap_sharpe": valid_stats["bootstrap_sharpe_p05"] >= 0.0,
        "train_bootstrap_calmar": train_stats["bootstrap_calmar_p05"] >= 0.0,
        "validation_bootstrap_calmar": valid_stats["bootstrap_calmar_p05"] >= 0.0,
    }
    fail_reasons = ";".join(name for name, passed in checks.items() if not passed)
    out = {
        "candidate_id": row.get("candidate_id"),
        "strategy_key": row.get("strategy_key"),
        "family": row.get("family"),
        "source_run": row.get("source_run"),
        "source_file": row.get("source_file"),
        "ppy": int(ppy),
        "pvalue_bootstrap_pass": bool(all(checks.values())),
        "fail_reasons": fail_reasons,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    out.update({f"train_{k}": v for k, v in train_stats.items()})
    out.update({f"validation_{k}": v for k, v in valid_stats.items()})
    return out


def _period_tests(values: np.ndarray, *, ppy: int, n_bootstrap: int, block: int, seed: int) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 8:
        return {
            "periods": float(len(arr)),
            "cagr": float("nan"),
            "sharpe": float("nan"),
            "calmar": float("nan"),
            "mdd": float("nan"),
            "mean_return_pvalue": 1.0,
            "bootstrap_cagr_p05": float("nan"),
            "bootstrap_sharpe_p05": float("nan"),
            "bootstrap_calmar_p05": float("nan"),
        }
    metrics = compute_metrics(arr, ppy=ppy)
    if len(arr) > 3 and float(np.std(arr, ddof=1)) > 1e-12:
        pvalue = float(stats.ttest_1samp(arr, 0.0, alternative="greater").pvalue)
    else:
        pvalue = 1.0
    rng = np.random.default_rng(seed)
    cagr = np.empty(n_bootstrap)
    sharpe = np.empty(n_bootstrap)
    calmar = np.empty(n_bootstrap)
    for idx in range(n_bootstrap):
        sample = _block_indices(len(arr), block, rng)
        boot = compute_metrics(arr[sample], ppy=ppy)
        cagr[idx] = float(boot.cagr)
        sharpe[idx] = float(boot.sharpe)
        calmar[idx] = float(boot.calmar)
    return {
        "periods": float(len(arr)),
        "cagr": float(metrics.cagr),
        "sharpe": float(metrics.sharpe),
        "calmar": float(metrics.calmar),
        "mdd": float(metrics.mdd),
        "mean_return_pvalue": pvalue,
        "bootstrap_cagr_p05": float(np.nanpercentile(cagr, 5)),
        "bootstrap_sharpe_p05": float(np.nanpercentile(sharpe, 5)),
        "bootstrap_calmar_p05": float(np.nanpercentile(calmar, 5)),
    }


def _block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    pieces: list[np.ndarray] = []
    total = 0
    block = max(1, int(block))
    while total < n:
        start = int(rng.integers(0, n))
        take = min(block, n - total)
        pieces.append((start + np.arange(take)) % n)
        total += take
    return np.concatenate(pieces)


def _seed(row: dict[str, Any], suffix: str) -> int:
    payload = f"{row.get('candidate_id')}|{suffix}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)


def _error_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "candidate_id": row.get("candidate_id"),
        "strategy_key": row.get("strategy_key"),
        "family": row.get("family"),
        "source_run": row.get("source_run"),
        "source_file": row.get("source_file"),
        "pvalue_bootstrap_pass": False,
        "fail_reasons": reason,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }


def merge(output_dir: Path, *, total_chunks: int, allow_unsupported: bool) -> None:
    files = sorted((output_dir / "chunks").glob("chunk_*.csv"))
    frames = [pd.read_csv(path) for path in files if path.stat().st_size > 0]
    results = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not results.empty:
        results = results.drop_duplicates("candidate_id", keep="first")
    pass_df = results[results["pvalue_bootstrap_pass"].astype(str).str.lower().isin(["true", "1"])] if not results.empty else pd.DataFrame()
    fail_df = results[~results["pvalue_bootstrap_pass"].astype(str).str.lower().isin(["true", "1"])] if not results.empty else pd.DataFrame()
    final = output_dir / "final"
    final.mkdir(parents=True, exist_ok=True)
    results.to_csv(final / "pvalue_bootstrap_results.csv", index=False)
    pass_df.to_csv(final / "pvalue_bootstrap_pass.csv", index=False)
    fail_df[["candidate_id", "family", "source_run", "fail_reasons"]].to_csv(final / "pvalue_bootstrap_fail_reasons.csv", index=False)
    found_chunks = {int(path.stem.split("_")[1]) for path in files}
    summary = {
        "input_candidates_expected": 173495,
        "chunks_expected": int(total_chunks),
        "chunks_found": int(len(found_chunks)),
        "partial": len(found_chunks) != int(total_chunks),
        "rows": int(len(results)),
        "pass_count": int(len(pass_df)),
        "fail_count": int(len(fail_df)),
        "unsupported_or_errors": int(fail_df["fail_reasons"].astype(str).str.contains("unsupported|error|missing|not_found", case=False, na=False).sum()) if not fail_df.empty else 0,
        "by_family": results["family"].value_counts(dropna=False).to_dict() if not results.empty else {},
        "pass_by_family": pass_df["family"].value_counts(dropna=False).to_dict() if not pass_df.empty else {},
        "locked_opened": False,
        "validation_used_for_selection": False,
        "test_definition": "mean_return_pvalue <= 0.05 and bootstrap cagr/sharpe/calmar p05 >= 0 in both train and validation",
    }
    (final / "pvalue_bootstrap_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["partial"]:
        raise RuntimeError(f"Partial merge: {summary['chunks_found']}/{summary['chunks_expected']} chunks")
    if summary["unsupported_or_errors"] and not allow_unsupported:
        raise RuntimeError(f"Unsupported/errors present: {summary['unsupported_or_errors']}")


if __name__ == "__main__":
    raise SystemExit(main())
