"""Reproduce and later evaluate the one frozen stock-protocol strategy."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.stock_protocol.campaign import evaluate_spec
from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.exact_oos import (
    EXACT_CANDIDATE_ID,
    EXACT_DATASET_HASH,
    EXACT_POLICY_HASH,
    EXACT_SOURCE_ARTIFACT_DIGEST,
    EXACT_SOURCE_ARTIFACT_NAME,
    EXACT_SOURCE_RUN_ID,
    EXACT_SOURCE_TASK_ARTIFACT_DIGEST,
    EXACT_SOURCE_TASK_ARTIFACT_NAME,
    EXACT_SOURCE_TASK_RUN_ID,
    assert_exact_is_reproduction,
    exact_strategy_spec,
    load_frozen_manifest_authorization,
)
from aurora.research.stock_protocol.exact_oos_reporting import (
    classify_verdict,
    relative_metrics,
    spy_benchmark,
    statistical_validation,
    yearly_comparison,
)
from aurora.research.stock_protocol.locked_access import activate_locked_data_access
from aurora.research.stock_protocol.metrics import compute_portfolio_metrics
from aurora.research.stock_protocol.portfolio import simulate_daily_portfolio
from aurora.research.stock_protocol.scientific_evaluation import (
    evaluate_development_walk_forward_from_pack,
)
from aurora.research.stock_protocol.signals import compute_features


LOCKED_FEATURE_COLUMNS = (
    "date",
    "symbol",
    "adj_close",
    "adj_high",
    "adj_low",
    "mom_12_1",
    "mom_6_1",
    "vol_12_1",
    "h52",
    "information_discreteness",
    "price_score",
    "breakout_20",
    "breakout_level_20",
    "rvol50",
    "atr20",
)
DAILY_COLUMNS = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_authorization(
    manifest_path: Path,
    manifest_sha256: str,
    implementation_commit: str,
):
    return load_frozen_manifest_authorization(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        expected_implementation_commit=implementation_commit,
    )


def prepare_locked_symbols(
    *,
    pack_root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    implementation_commit: str,
    output_root: Path,
) -> dict[str, object]:
    """Bind the exact 4,828 symbols and original 32 shards to the manifest."""

    require_github_actions_or_explicit_local_permission("exact locked symbol freeze")
    _manifest_authorization(
        manifest_path, manifest_sha256, implementation_commit
    )
    pack_audit_path = pack_root / "pack_audit.json"
    pack_manifest_path = pack_root.parent / "data_shard_manifest.json"
    pack_audit = json.loads(pack_audit_path.read_text(encoding="utf-8"))
    pack_manifest = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    if pack_audit.get("dataset_hash") != EXACT_DATASET_HASH:
        raise ValueError("prelocked pack dataset hash differs from frozen source")
    if int(pack_audit.get("symbols", 0)) != 4828:
        raise ValueError("prelocked pack does not contain exactly 4,828 symbols")
    if int(pack_manifest.get("shards_expected", 0)) != 32:
        raise ValueError("prelocked pack must retain exactly 32 source shards")
    shards: dict[str, dict[str, object]] = {}
    all_symbols: list[str] = []
    for index in range(32):
        path = pack_root / f"shard-{index:03d}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"missing source shard {index}")
        symbols = sorted(
            pd.read_parquet(path, columns=["symbol"])["symbol"]
            .astype(str)
            .unique()
            .tolist()
        )
        if not symbols:
            raise ValueError(f"source shard {index} has no symbols")
        shards[str(index)] = {
            "symbols": symbols,
            "symbols_expected": len(symbols),
            "source_shard_sha256": _sha256(path),
        }
        all_symbols.extend(symbols)
    if len(all_symbols) != 4828 or len(set(all_symbols)) != 4828:
        raise ValueError("source shard symbols are incomplete or duplicated")
    payload = {
        "schema_version": 1,
        "candidate_id": EXACT_CANDIDATE_ID,
        "manifest_sha256": manifest_sha256,
        "implementation_commit": implementation_commit,
        "shard_count": 32,
        "symbols": 4828,
        "locked_start": "2021-01-01",
        "locked_end": json.loads(manifest_path.read_text(encoding="utf-8"))["periods"]["locked_end"],
        "survivorship_limited": True,
        "shards": shards,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / "locked_symbol_shards.json", payload)
    shutil.copy2(manifest_path, output_root / "frozen_oos_strategy_manifest.json")
    print(json.dumps({"symbols": 4828, "shards": 32, "locked_opened": False}))
    return payload


def _locked_shards(
    root: Path,
    *,
    manifest_sha256: str,
    implementation_commit: str,
) -> dict[int, tuple[Path, dict[str, object]]]:
    indexed: dict[int, tuple[Path, dict[str, object]]] = {}
    for audit_path in root.rglob("locked_download_audit.json"):
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        index = int(audit["shard_index"])
        expected = {
            "shard_count": 32,
            "manifest_sha256": manifest_sha256,
            "implementation_commit": implementation_commit,
            "locked_opened": True,
            "partial_session_included": False,
        }
        for key, value in expected.items():
            if audit.get(key) != value:
                raise ValueError(f"locked shard {index} has invalid {key}")
        price_path = audit_path.parent / "locked_prices.parquet"
        if _sha256(price_path) != audit["sha256"]:
            raise ValueError(f"locked shard {index} hash mismatch")
        if index in indexed:
            raise ValueError(f"duplicate locked shard {index}")
        indexed[index] = (audit_path.parent, audit)
    if set(indexed) != set(range(32)):
        raise ValueError("locked data shards are incomplete")
    return indexed


def _period_frames(
    *,
    pack_root: Path,
    locked: dict[int, tuple[Path, dict[str, object]]],
    start: str,
    end: str,
    include_locked: bool,
    authorization,
) -> tuple[ResearchPanel, pd.DataFrame]:
    panel_parts: list[pd.DataFrame] = []
    feature_parts: list[pd.DataFrame] = []
    start_date = pd.Timestamp(start).normalize()
    end_date = pd.Timestamp(end).normalize()
    for index in range(32):
        source_path = pack_root / f"shard-{index:03d}.parquet"
        source = pd.read_parquet(
            source_path,
            columns=list(DAILY_COLUMNS),
            filters=[("date", ">=", start_date.to_pydatetime()), ("date", "<=", pd.Timestamp("2020-12-31").to_pydatetime())],
        )
        source["date"] = pd.to_datetime(source["date"], errors="raise").dt.normalize()
        parts = [source]
        if include_locked:
            locked_frame = pd.read_parquet(
                locked[index][0] / "locked_prices.parquet",
                columns=list(DAILY_COLUMNS),
            )
            locked_frame["date"] = pd.to_datetime(
                locked_frame["date"], errors="raise"
            ).dt.normalize()
            locked_frame = locked_frame.loc[
                locked_frame["date"].between("2021-01-01", end_date)
            ].copy()
            parts.append(locked_frame)
        combined = pd.concat(parts, ignore_index=True)
        combined = combined.loc[combined["date"].between(start_date, end_date)]
        combined = combined.drop_duplicates(["date", "symbol"], keep="last")
        combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)
        audit = PackAudit(
            source_root="manifest_bound_exact_source_plus_yfinance",
            output_root="ephemeral_github_runner",
            data_start=combined["date"].min().date().isoformat(),
            data_end=end_date.date().isoformat(),
            rows=int(len(combined)),
            symbols=int(combined["symbol"].nunique()),
            locked_rows=int(combined["date"].ge("2021-01-01").sum()),
            survivorship_free=False,
            metadata_is_bitemporal=False,
            dataset_hash=EXACT_DATASET_HASH,
            locked_opened=include_locked,
        )
        shard_panel = ResearchPanel(combined, audit)
        features = compute_features(
            shard_panel,
            locked_authorization=authorization if include_locked else None,
        )
        missing = set(LOCKED_FEATURE_COLUMNS) - set(features.columns)
        if missing:
            raise ValueError(f"feature shard {index} lacks {sorted(missing)}")
        panel_parts.append(combined[list(DAILY_COLUMNS)])
        feature_parts.append(features[list(LOCKED_FEATURE_COLUMNS)])
    panel_frame = pd.concat(panel_parts, ignore_index=True).sort_values(["date", "symbol"])
    features = pd.concat(feature_parts, ignore_index=True)
    if panel_frame.duplicated(["date", "symbol"]).any():
        raise ValueError("combined OOS panel contains duplicate symbol-dates")
    features["date"] = pd.to_datetime(features["date"], errors="raise").dt.normalize()
    by_date = features.groupby("date", group_keys=False, sort=False)
    features["price_score"] = (
        by_date["mom_12_1"].rank(pct=True) * 0.5
        + by_date["h52"].rank(pct=True) * 0.3
        - by_date["information_discreteness"].rank(pct=True) * 0.2
    )
    features = features.sort_values(["date", "symbol"]).reset_index(drop=True)
    audit = PackAudit(
        source_root="manifest_bound_exact_source_plus_yfinance",
        output_root="ephemeral_github_runner",
        data_start=panel_frame["date"].min().date().isoformat(),
        data_end=end_date.date().isoformat(),
        rows=int(len(panel_frame)),
        symbols=int(panel_frame["symbol"].nunique()),
        locked_rows=int(panel_frame["date"].ge("2021-01-01").sum()),
        survivorship_free=False,
        metadata_is_bitemporal=False,
        dataset_hash=EXACT_DATASET_HASH,
        locked_opened=include_locked,
    )
    return ResearchPanel(panel_frame.reset_index(drop=True), audit), features


def _result_payload(result, role: str) -> dict[str, object]:
    return {
        "candidate_id": result.candidate_id,
        "role": role,
        "status": result.status,
        "metrics": result.metrics,
        "locked_opened": result.locked_opened,
        "data_end": result.data_end,
        "validation_used_for_selection": False,
    }


def _copy_is_outputs(is_root: Path, output_root: Path) -> None:
    required = (
        "exact_strategy_source_row.csv",
        "exact_strategy_parameters.json",
        "in_sample_replication.csv",
        "in_sample_trade_comparison.csv",
        "in_sample_equity_curve.csv",
        "is_reproduction.json",
    )
    for name in required:
        matches = list(is_root.rglob(name))
        if len(matches) != 1:
            raise ValueError(f"expected one IS artifact file {name}, found {len(matches)}")
        shutil.copy2(matches[0], output_root / name)


def _metric_table(
    strategy: dict[str, float], spy: dict[str, float]
) -> list[dict[str, object]]:
    names = (
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "annualized_volatility",
        "max_drawdown",
        "calmar",
        "worst_day",
        "worst_month",
    )
    return [
        {
            "metric": name,
            "strategy": strategy[name],
            "spy": spy[name],
            "difference": strategy[name] - spy[name],
        }
        for name in names
    ]


def evaluate_frozen_oos(
    *,
    pack_root: Path,
    locked_shards_root: Path,
    is_root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    implementation_commit: str,
    output_root: Path,
) -> dict[str, object]:
    """Run the reused diagnostic and the one immutable true locked evaluation."""

    require_github_actions_or_explicit_local_permission("single exact OOS evaluation")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    locked_end = str(manifest["periods"]["locked_end"])
    locked = _locked_shards(
        locked_shards_root,
        manifest_sha256=manifest_sha256,
        implementation_commit=implementation_commit,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    _copy_is_outputs(is_root, output_root)
    shutil.copy2(manifest_path, output_root / "frozen_oos_strategy_manifest.json")

    diagnostic_panel, diagnostic_features = _period_frames(
        pack_root=pack_root,
        locked=locked,
        start="2014-01-01",
        end="2020-12-31",
        include_locked=False,
        authorization=None,
    )
    diagnostic = evaluate_spec(
        diagnostic_panel,
        exact_strategy_spec(),
        start="2016-01-01",
        end="2020-12-31",
        features=diagnostic_features,
    )
    if diagnostic.status != "evaluated":
        raise ValueError(f"diagnostic evaluation failed: {diagnostic.status}")
    diagnostic_spy_curve, diagnostic_spy_metrics = spy_benchmark(
        diagnostic.equity_curve,
        diagnostic_panel.frame,
        authorization=None,
    )
    _write_json(
        output_root / "diagnostic_oos_2016_2020_metrics.json",
        _result_payload(diagnostic, "diagnostic_reused_holdout"),
    )
    diagnostic.equity_curve.to_csv(
        output_root / "diagnostic_oos_2016_2020_equity.csv", index=False
    )
    diagnostic.trade_ledger.to_csv(
        output_root / "diagnostic_oos_2016_2020_trades.csv", index=False
    )
    diagnostic.yearly.to_csv(
        output_root / "diagnostic_oos_2016_2020_yearly.csv", index=False
    )
    diagnostic_yearly = yearly_comparison(
        diagnostic.equity_curve,
        diagnostic_spy_curve,
        diagnostic.trade_ledger,
        period="diagnostic_reused_holdout",
    )
    del diagnostic_features
    gc.collect()

    data_authorization = _manifest_authorization(
        manifest_path, manifest_sha256, implementation_commit
    )
    activate_locked_data_access(data_authorization, end=pd.Timestamp(locked_end))
    locked_panel, locked_features = _period_frames(
        pack_root=pack_root,
        locked=locked,
        start="2020-01-01",
        end=locked_end,
        include_locked=True,
        authorization=data_authorization,
    )
    evaluation_authorization = _manifest_authorization(
        manifest_path, manifest_sha256, implementation_commit
    )
    true_oos = evaluate_spec(
        locked_panel,
        exact_strategy_spec(),
        start="2021-01-01",
        end=locked_end,
        features=locked_features,
        locked_authorization=evaluation_authorization,
    )
    if true_oos.status != "evaluated":
        raise ValueError(f"true OOS evaluation failed: {true_oos.status}")
    spy_curve, spy_metrics = spy_benchmark(
        true_oos.equity_curve,
        locked_panel.frame,
        authorization=evaluation_authorization,
    )
    relative = relative_metrics(true_oos.equity_curve, spy_curve)
    _write_json(
        output_root / "true_oos_2021_latest_metrics.json",
        _result_payload(true_oos, "true_locked_oos"),
    )
    true_oos.equity_curve.to_csv(
        output_root / "true_oos_2021_latest_equity.csv", index=False
    )
    true_oos.trade_ledger.to_csv(
        output_root / "true_oos_2021_latest_trades.csv", index=False
    )
    spy_curve.to_csv(output_root / "spy_benchmark_equity.csv", index=False)
    _write_json(
        output_root / "spy_benchmark_metrics.json",
        {
            "period_start": true_oos.equity_curve["date"].min(),
            "period_end": true_oos.equity_curve["date"].max(),
            "risk_free_rate": 0.0,
            "adjusted_for_dividends": True,
            "metrics": spy_metrics,
            "relative": relative,
            "comparison": _metric_table(true_oos.metrics, spy_metrics),
        },
    )
    true_yearly = yearly_comparison(
        true_oos.equity_curve,
        spy_curve,
        true_oos.trade_ledger,
        period="true_locked_oos",
    )
    pd.concat([diagnostic_yearly, true_yearly], ignore_index=True).to_csv(
        output_root / "exact_strategy_yearly_comparison.csv", index=False
    )

    cost_rows: list[dict[str, object]] = []
    for cost in (0, 5, 10, 25, 50):
        curve, _, ledger = simulate_daily_portfolio(
            true_oos.trade_ledger,
            locked_panel,
            initial_capital=100_000.0,
            cost_bps_per_side=float(cost),
            locked_authorization=evaluation_authorization,
        )
        metrics = compute_portfolio_metrics(
            curve,
            ledger,
            locked_authorization=evaluation_authorization,
        )
        cost_rows.append(
            {
                "cost_bps_per_side": cost,
                **metrics,
                "survived": bool(curve["equity"].min() > 0),
                "used_for_selection": False,
            }
        )
    pd.DataFrame(cost_rows).to_csv(
        output_root / "cost_sensitivity.csv", index=False
    )
    statistics, bootstrap = statistical_validation(
        true_oos.equity_curve, spy_curve
    )
    statistics.to_csv(output_root / "statistical_validation.csv", index=False)
    bootstrap.to_parquet(
        output_root / "statistical_bootstrap_records.parquet", index=False
    )

    status_parts = []
    audits = []
    for index in range(32):
        shard_root, audit = locked[index]
        status = pd.read_csv(shard_root / "locked_download_status.csv")
        status["shard_index"] = index
        status_parts.append(status)
        audits.append(audit)
    status = pd.concat(status_parts, ignore_index=True)
    status.to_csv(output_root / "locked_symbol_status.csv", index=False)
    locked_dates = locked_panel.frame.loc[
        locked_panel.frame["date"].ge("2021-01-01")
    ]
    symbols_by_date = (
        locked_dates.groupby("date")["symbol"].nunique().rename("symbols").reset_index()
    )
    symbols_by_date.to_csv(output_root / "locked_symbols_by_date.csv", index=False)
    locked_hash = hashlib.sha256(
        "".join(str(audit["sha256"]) for audit in audits).encode("ascii")
    ).hexdigest()
    locked_opened_at = min(str(audit["locked_opened_at"]) for audit in audits)
    data_audit = {
        "candidate_id": EXACT_CANDIDATE_ID,
        "manifest_sha256": manifest_sha256,
        "implementation_commit": implementation_commit,
        "locked_opened": True,
        "locked_opened_at": locked_opened_at,
        "locked_start": "2021-01-01",
        "locked_end": locked_end,
        "locked_strategy_count": 1,
        "symbols_initial": 4828,
        "symbols_downloaded": int(status.loc[status["status"].eq("downloaded"), "symbol"].nunique()),
        "symbols_missing_or_failed": int(status.loc[status["status"].ne("downloaded"), "symbol"].nunique()),
        "excluded_symbols": status.loc[status["status"].ne("downloaded"), "symbol"].astype(str).tolist(),
        "rows_downloaded": int(sum(int(audit["rows"]) for audit in audits)),
        "maximum_date": locked_dates["date"].max().date().isoformat(),
        "symbols_per_date_min": int(symbols_by_date["symbols"].min()),
        "symbols_per_date_median": float(symbols_by_date["symbols"].median()),
        "symbols_per_date_max": int(symbols_by_date["symbols"].max()),
        "acquired_or_delisted_symbols": "unknown_without_point_in_time_metadata",
        "delisting_returns_invented": False,
        "survivorship_limited": True,
        "survivorship_bias_effect": "Likely overstates historical opportunity and may improve returns because the universe is based on securities known later; missing and delisted names are not replaced or assigned artificial losses.",
        "partial_session_included": False,
        "combined_locked_data_sha256": locked_hash,
    }
    _write_json(output_root / "locked_data_audit.json", data_audit)

    verdict = classify_verdict(true_oos.metrics, spy_metrics, statistics)
    cost_frame = pd.DataFrame(cost_rows).set_index("cost_bps_per_side")
    reasons = true_oos.trade_ledger["exit_reason"].astype(str)
    stats_index = statistics.set_index("test")
    markdown = f"""# Final exact strategy verdict

Classification: `{verdict}`

1. Exact 1995-2015 reproduction: **yes**, including all source ledger rows and the exact operation count.
2. Diagnostic 2016-2020: CAGR {diagnostic.metrics['cagr']:.6f}, Sharpe {diagnostic.metrics['sharpe']:.6f}, max drawdown {diagnostic.metrics['max_drawdown']:.6f}.
3. True locked 2021-{locked_end}: CAGR {true_oos.metrics['cagr']:.6f}, Sharpe {true_oos.metrics['sharpe']:.6f}, max drawdown {true_oos.metrics['max_drawdown']:.6f}.
4. Beat SPY CAGR: **{true_oos.metrics['cagr'] > spy_metrics['cagr']}**.
5. Beat SPY Sharpe: **{true_oos.metrics['sharpe'] > spy_metrics['sharpe']}**.
6. Beat SPY Sortino: **{true_oos.metrics['sortino'] > spy_metrics['sortino']}**.
7. Lower drawdown than SPY: **{true_oos.metrics['max_drawdown'] > spy_metrics['max_drawdown']}**.
8. Remained solvent at 5/10/25/50 bps: **{bool(cost_frame.loc[[5, 10, 25, 50], 'survived'].all())}**. These scenarios were not used for selection.
9. Closed operations: **{int(true_oos.metrics['trades'])}**.
10. Reached +50% target: **{int(reasons.isin(['take_profit', 'gap_through_target']).sum())}**.
11. Exited after 252 sessions: **{int(reasons.eq('time_exit').sum())}**.
12. Year-by-year outcomes are in `exact_strategy_yearly_comparison.csv`; no year was excluded.
13. Statistically distinguishable from zero: **{float(stats_index.loc['block_bootstrap_sharpe', 'lower_95']) > 0}** by the frozen block-bootstrap rule.
14. Statistically superior to SPY: **{float(stats_index.loc['paired_daily_return_ttest', 'estimate']) > 0 and float(stats_index.loc['paired_daily_return_ttest', 'p_value']) <= 0.05}** by paired daily returns.
15. Operable: **{verdict == 'validated_out_of_sample'}** under the predeclared strict verdict; otherwise research-only.
16. Survivorship limitation: **material and unresolved**. The current-universe backfill is not point-in-time membership and can overstate performance.

The true OOS sample is only about five to six years, so statistical power remains limited. No parameter, signal, universe rule, cost, or period was changed after the manifest was frozen.
"""
    (output_root / "final_exact_strategy_verdict.md").write_text(
        markdown, encoding="utf-8"
    )
    artifact_files = sorted(
        path for path in output_root.iterdir() if path.is_file()
    )
    artifact_manifest = {
        "candidate_id": EXACT_CANDIDATE_ID,
        "classification": verdict,
        "locked_opened": True,
        "locked_opened_at": locked_opened_at,
        "locked_strategy_count": 1,
        "optimization_allowed": False,
        "parameter_search_allowed": False,
        "validation_used_for_selection": False,
        "survivorship_limited": True,
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in artifact_files
        },
    }
    _write_json(output_root / "final_artifact_manifest.json", artifact_manifest)
    summary = {
        "candidate_id": EXACT_CANDIDATE_ID,
        "classification": verdict,
        "diagnostic_metrics": diagnostic.metrics,
        "true_oos_metrics": true_oos.metrics,
        "spy_metrics": spy_metrics,
        "locked_opened": True,
        "locked_opened_at": locked_opened_at,
        "locked_strategy_count": 1,
        "validation_used_for_selection": False,
        "survivorship_limited": True,
    }
    _write_json(output_root / "exact_oos_summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return summary


def reproduce_is(
    *,
    pack_root: Path,
    source_result_path: Path,
    source_trade_ledger_path: Path,
    source_selection_path: Path,
    output_root: Path,
    implementation_commit: str,
) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission("exact IS reproduction")
    source_result = json.loads(source_result_path.read_text(encoding="utf-8-sig"))
    selection = pd.read_csv(source_selection_path)
    if len(selection) != 290:
        raise ValueError(f"source selection row count mismatch: {len(selection)}")
    best_cagr = selection.loc[pd.to_numeric(selection["cagr"]).idxmax()]
    best_sharpe = selection.loc[pd.to_numeric(selection["sharpe"]).idxmax()]
    if (
        best_cagr["candidate_id"] != EXACT_CANDIDATE_ID
        or best_sharpe["candidate_id"] != EXACT_CANDIDATE_ID
    ):
        raise ValueError("frozen candidate is not both source maxima")
    if json.loads(best_cagr["spec_json"]) != exact_strategy_spec():
        raise ValueError("source selection spec differs from frozen exact spec")
    if source_result.get("dataset_hash") != EXACT_DATASET_HASH:
        raise ValueError("source result dataset hash mismatch")
    if source_result.get("policy_hash") != EXACT_POLICY_HASH:
        raise ValueError("source result policy hash mismatch")
    source_ledger = pd.read_csv(source_trade_ledger_path)
    evaluation = evaluate_development_walk_forward_from_pack(
        pack_root,
        exact_strategy_spec(),
        start="1995-01-01",
        end="2015-12-31",
        initial_capital=100_000.0,
        mode="expanding",
    )
    report = assert_exact_is_reproduction(
        evaluation.result,
        source_result=source_result,
        source_trade_ledger=source_ledger,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    best_source_row = selection.loc[
        selection["candidate_id"].eq(EXACT_CANDIDATE_ID)
    ].copy()
    best_source_row.to_csv(output_root / "exact_strategy_source_row.csv", index=False)
    _write_json(
        output_root / "exact_strategy_parameters.json",
        {
            "candidate_id": EXACT_CANDIDATE_ID,
            "upstream_candidate_id": exact_strategy_spec()["upstream_candidate_id"],
            "strategy_spec": exact_strategy_spec(),
            "dataset_hash": EXACT_DATASET_HASH,
            "policy_hash": EXACT_POLICY_HASH,
            "universe": "current_universe_backfill",
            "symbols": 4828,
            "survivorship_limited": True,
        },
    )
    evaluation.result.trade_ledger.to_csv(
        output_root / "is_reproduced_trade_ledger.csv", index=False
    )
    evaluation.result.position_ledger.to_parquet(
        output_root / "is_reproduced_position_ledger.parquet", index=False
    )
    evaluation.result.equity_curve.to_parquet(
        output_root / "is_reproduced_daily_equity.parquet", index=False
    )
    evaluation.result.equity_curve.to_csv(
        output_root / "in_sample_equity_curve.csv", index=False
    )
    evaluation.result.yearly.to_csv(
        output_root / "is_reproduced_yearly.csv", index=False
    )
    evaluation.fold_results.to_csv(
        output_root / "is_reproduced_folds.csv", index=False
    )
    _write_json(output_root / "strategy_spec.json", exact_strategy_spec())
    _write_json(
        output_root / "is_reproduction.json",
        {
            **report,
            "implementation_commit": implementation_commit,
            "source_run_id": EXACT_SOURCE_RUN_ID,
            "source_artifact_name": EXACT_SOURCE_ARTIFACT_NAME,
            "source_artifact_digest": EXACT_SOURCE_ARTIFACT_DIGEST,
            "source_task_run_id": EXACT_SOURCE_TASK_RUN_ID,
            "source_task_artifact_name": EXACT_SOURCE_TASK_ARTIFACT_NAME,
            "source_task_artifact_digest": EXACT_SOURCE_TASK_ARTIFACT_DIGEST,
            "dataset_hash": EXACT_DATASET_HASH,
            "policy_hash": EXACT_POLICY_HASH,
            "development_start": "1995-01-01",
            "development_end": "2015-12-31",
            "validation_used_for_selection": False,
            "locked_opened": False,
            "survivorship_limited": True,
        },
    )
    metric_rows = []
    for name, values in report["metric_comparison"].items():
        metric_rows.append({"metric": name, **values})
    pd.DataFrame(metric_rows).to_csv(
        output_root / "is_reproduction_metrics.csv", index=False
    )
    replication_row = {
        "candidate_id": EXACT_CANDIDATE_ID,
        "exact_reproduction": True,
        "operations_expected": int(float(source_result["trades"])),
        "operations_observed": int(float(evaluation.result.metrics["trades"])),
        "ledger_rows_expected": len(source_ledger),
        "ledger_rows_observed": len(evaluation.result.trade_ledger),
    }
    for name, values in report["metric_comparison"].items():
        replication_row[f"{name}_expected"] = values["expected"]
        replication_row[f"{name}_observed"] = values["observed"]
        replication_row[f"{name}_difference"] = values["difference"]
    pd.DataFrame([replication_row]).to_csv(
        output_root / "in_sample_replication.csv", index=False
    )
    comparison_columns = [
        "symbol",
        "signal_date",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "exit_reason",
        "status",
        "fold_id",
        "trade_id",
    ]
    expected = source_ledger[comparison_columns].reset_index(drop=True).add_suffix("_expected")
    observed = evaluation.result.trade_ledger[comparison_columns].reset_index(drop=True).add_suffix("_observed")
    trade_comparison = pd.concat([expected, observed], axis=1)
    trade_comparison["exact_match"] = True
    trade_comparison.to_csv(
        output_root / "in_sample_trade_comparison.csv", index=False
    )
    summary = {
        "candidate_id": EXACT_CANDIDATE_ID,
        "exact_reproduction": True,
        "closed_operations": report["closed_operations"],
        "ledger_rows": report["ledger_rows"],
        "locked_opened": False,
        "output_root": str(output_root),
    }
    print(json.dumps(summary, sort_keys=True))
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    reproduce = subparsers.add_parser("reproduce-is")
    reproduce.add_argument("--pack-root", type=Path, required=True)
    reproduce.add_argument("--source-result", dest="source_result_path", type=Path, required=True)
    reproduce.add_argument(
        "--source-trade-ledger",
        dest="source_trade_ledger_path",
        type=Path,
        required=True,
    )
    reproduce.add_argument(
        "--source-selection",
        dest="source_selection_path",
        type=Path,
        required=True,
    )
    reproduce.add_argument("--output-root", type=Path, required=True)
    reproduce.add_argument("--implementation-commit", required=True)
    symbols = subparsers.add_parser("prepare-locked-symbols")
    symbols.add_argument("--pack-root", type=Path, required=True)
    symbols.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    symbols.add_argument("--manifest-sha256", required=True)
    symbols.add_argument("--implementation-commit", required=True)
    symbols.add_argument("--output-root", type=Path, required=True)
    evaluate = subparsers.add_parser("evaluate-frozen-oos")
    evaluate.add_argument("--pack-root", type=Path, required=True)
    evaluate.add_argument("--locked-shards-root", type=Path, required=True)
    evaluate.add_argument("--is-root", type=Path, required=True)
    evaluate.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    evaluate.add_argument("--manifest-sha256", required=True)
    evaluate.add_argument("--implementation-commit", required=True)
    evaluate.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    args = vars(_parser().parse_args())
    command = args.pop("command")
    if command == "reproduce-is":
        reproduce_is(**args)
    elif command == "prepare-locked-symbols":
        prepare_locked_symbols(**args)
    elif command == "evaluate-frozen-oos":
        evaluate_frozen_oos(**args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
