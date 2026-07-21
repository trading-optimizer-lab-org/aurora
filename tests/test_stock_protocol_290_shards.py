"""Contracts for the historical and corrected 10 x 29 shard runners."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.run_stock_protocol_290_corrected_shard import (
    DATASET_CUTOFF,
    ENTRY_FEATURE_SCHEMA,
    PERIODS,
    build_entry_cohort,
    complete_entry_feature_schema,
    complete_ledger_contract,
    enrich_opportunities,
    load_corrected_entry_rows,
    reconciliation_by_combination,
    run_corrected_shard,
)
from scripts.run_stock_protocol_290_historical_shard import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    METRIC_TOLERANCES,
    _resolve_pack_root as resolve_historical_pack_root,
    load_entry_manifest_rows,
    reconcile_historical_rows,
)


def _manifest_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry_index in range(10):
        entry_spec = {
            "candidate_id": f"entry-{entry_index}",
            "signal_test_id": 2,
            "signal_variant": {"lookback": 126, "skip": 21},
            "selection": {"kind": "top_percent", "value": 20.0},
            "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
        }
        for exit_index in range(29):
            combination_id = f"combination-{entry_index}-{exit_index}"
            exit_spec = {
                "exit_test_id": 26,
                "exit_variant_index": exit_index,
                "exit": {
                    "kind": "none",
                    "holding_sessions": min(exit_index + 1, 252),
                },
            }
            full_spec = {
                **entry_spec,
                **exit_spec,
                "horizon_sessions": exit_spec["exit"]["holding_sessions"],
            }
            rows.append(
                {
                    "combination_id": combination_id,
                    "candidate_id": combination_id,
                    "entry_spec_id": f"entry-{entry_index}",
                    "exit_spec_id": f"exit-{exit_index}",
                    "entry_spec_json": json.dumps(entry_spec),
                    "exit_spec_json": json.dumps(exit_spec),
                    "spec_json": json.dumps(full_spec),
                    "corrected_track_applicability": (
                        "not_applicable" if exit_index == 0 else "applicable"
                    ),
                    "corrected_track_reason": (
                        "missing_breakout_level" if exit_index == 0 else ""
                    ),
                    "dataset_hash": "1" * 64,
                    "policy_hash": "2" * 64,
                    "source_snapshot_sha256": "3" * 64,
                    "status": "evaluated",
                    "cagr": "0.1",
                    "sharpe": "1.0",
                    "max_drawdown": "-0.2",
                    "trades": "10",
                }
            )
    return rows


def test_historical_pack_resolver_accepts_the_frozen_32_shard_artifact(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "downloaded-artifact" / "pre2021_full_daily_pack"
    nested.mkdir(parents=True)
    (nested / "shard-000.parquet").touch()
    (nested / "shard-031.parquet").touch()
    frozen_calendar = tmp_path / "downloaded-artifact" / "trading_calendar.parquet"
    frozen_calendar.write_bytes(b"frozen-calendar")

    assert resolve_historical_pack_root(tmp_path) == nested
    assert (nested / "trading_calendar.parquet").read_bytes() == b"frozen-calendar"


def _write_manifest(root: Path) -> pd.DataFrame:
    frame = pd.DataFrame(_manifest_rows())
    root.mkdir()
    frame.to_csv(root / "original_290_combination_manifest.csv", index=False)
    return frame


def test_historical_loader_assigns_exactly_one_complete_entry_axis(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manifest"
    _write_manifest(root)

    _, rows = load_entry_manifest_rows(root, 7)

    assert len(rows) == 29
    assert rows["entry_spec_id"].unique().tolist() == ["entry-7"]
    assert rows["exit_spec_id"].nunique() == 29
    assert DEVELOPMENT_START == "1995-01-01"
    assert DEVELOPMENT_END == "2015-12-31"
    assert METRIC_TOLERANCES == {
        "cagr": 0.0002,
        "sharpe": 0.005,
        "max_drawdown": 0.0002,
        "trades": 0.0,
    }


@pytest.mark.parametrize(
    "loader",
    [load_entry_manifest_rows, load_corrected_entry_rows],
)
def test_manifest_loaders_reject_duplicate_combination_ids(
    tmp_path: Path,
    loader,
) -> None:
    root = tmp_path / "manifest"
    manifest = _write_manifest(root)
    manifest.loc[1, "combination_id"] = manifest.loc[0, "combination_id"]
    manifest.to_csv(root / "original_290_combination_manifest.csv", index=False)

    with pytest.raises(ValueError, match="290 unique combination IDs"):
        loader(root, 0)


@pytest.mark.parametrize(
    "loader",
    [load_entry_manifest_rows, load_corrected_entry_rows],
)
def test_manifest_loaders_reject_non_uniform_hashes(
    tmp_path: Path,
    loader,
) -> None:
    root = tmp_path / "manifest"
    manifest = _write_manifest(root)
    manifest.loc[1, "policy_hash"] = "4" * 64
    manifest.to_csv(root / "original_290_combination_manifest.csv", index=False)

    with pytest.raises(ValueError, match="policy_hash must be one uniform sha256"):
        loader(root, 0)


@dataclass
class _HistoricalResult:
    candidate_id: str
    status: str = "evaluated"
    locked_opened: bool = False
    data_end: str = "2015-12-31"

    def result_row(self) -> dict[str, object]:
        return {
            "cagr": 0.1001,
            "sharpe": 1.004,
            "max_drawdown": -0.2001,
            "trades": 10,
        }


def test_historical_reconciliation_documents_every_tolerance() -> None:
    source = pd.DataFrame(_manifest_rows()).iloc[:29].copy()
    evaluations = tuple(
        SimpleNamespace(
            result=_HistoricalResult(str(row["combination_id"])),
            folds=(object(),),
        )
        for row in source.to_dict(orient="records")
    )

    result = reconcile_historical_rows(source, evaluations)

    assert len(result) == 29
    assert result["replication_passed"].all()
    for metric, tolerance in METRIC_TOLERANCES.items():
        assert result[f"{metric}_tolerance"].eq(tolerance).all()
        assert result[f"{metric}_passed"].all()


def test_corrected_manifest_preserves_semantic_not_applicable(tmp_path: Path) -> None:
    root = tmp_path / "manifest"
    _write_manifest(root)

    _, rows, entry_spec = load_corrected_entry_rows(root, 0)

    assert len(rows) == 29
    assert entry_spec["entry"]["kind"] == "immediate_next_open"
    assert rows.iloc[0]["corrected_track_applicability"] == "not_applicable"
    assert rows.iloc[0]["corrected_track_reason"] == "missing_breakout_level"


def test_periods_are_entry_date_bounded_with_warmup_and_follow_up() -> None:
    assert PERIODS["A"]["entry_start"] == "2008-01-01"
    assert PERIODS["A"]["entry_end"] == "2015-12-31"
    assert PERIODS["B"]["entry_start"] == "2016-01-01"
    assert PERIODS["B"]["entry_end"] == "2020-12-31"
    assert PERIODS["C"]["entry_start"] == "2021-01-01"
    assert PERIODS["C"]["entry_end"] == "2026-07-17"
    assert pd.Timestamp(str(PERIODS["B"]["load_start"])) < pd.Timestamp(
        str(PERIODS["B"]["entry_start"])
    )
    assert pd.Timestamp(str(PERIODS["B"]["load_end"])) > pd.Timestamp(
        str(PERIODS["B"]["entry_end"])
    )
    assert DATASET_CUTOFF == pd.Timestamp("2026-07-17")


def _panel_frame() -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=6, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "AAA",
            "open": [100.0, 101.0, 51.0, 52.0, 53.0, 54.0],
            "high": [101.0, 102.0, 52.0, 53.0, 54.0, 55.0],
            "low": [99.0, 100.0, 50.0, 51.0, 52.0, 53.0],
            "close": [100.0, 101.0, 51.0, 52.0, 53.0, 54.0],
            "adj_close": [50.0, 50.5, 51.0, 52.0, 53.0, 54.0],
            "volume": 1_000.0,
            "dividends": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
            "stock_splits": [0.0, 0.0, 2.0, 0.0, 0.0, 0.0],
        }
    )


def _base_feature_frame(panel_frame: pd.DataFrame) -> pd.DataFrame:
    frame = panel_frame[["date", "symbol", "adj_close"]].copy()
    factor = panel_frame["adj_close"].div(panel_frame["close"])
    frame["adj_high"] = panel_frame["high"].mul(factor)
    frame["adj_low"] = panel_frame["low"].mul(factor)
    frame["mom_12_1"] = 0.2
    frame["mom_6_1"] = 0.1
    frame["vol_12_1"] = 0.3
    frame["h52"] = 0.9
    frame["information_discreteness"] = 0.0
    frame["price_score"] = 0.8
    frame["rvol50"] = 1.5
    frame["atr20"] = 2.0
    return frame


def test_complete_entry_feature_schema_restores_real_ten_entry_inputs() -> None:
    periods = 270
    dates = pd.bdate_range("2019-01-02", periods=periods)
    close = pd.Series(100.0 + np.arange(periods), dtype=float)
    panel_frame = pd.DataFrame(
        {
            "date": dates,
            "symbol": "AAA",
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "adj_close": close,
            "volume": 1_000.0,
            "dividends": 0.0,
            "stock_splits": 0.0,
        }
    )
    base = _base_feature_frame(panel_frame)
    base["breakout_20"] = False
    base["breakout_level_20"] = np.nan

    result = complete_entry_feature_schema(SimpleNamespace(frame=panel_frame), base)

    assert set(ENTRY_FEATURE_SCHEMA) <= set(result.columns)
    assert {
        "breakout_50",
        "breakout_100",
        "breakout_150",
        "breakout_200",
        "breakout_252",
        "consolidation_20",
        "consolidation_40",
        "consolidation_60",
        "sma_150",
        "sma_200",
        "sma_250",
    } <= set(result.columns)
    assert result["breakout_level_252"].notna().any()
    assert result["consolidation_60"].notna().any()
    assert result["sma_250"].notna().any()


def test_complete_ledger_contract_records_cost_grid_without_financing_guess() -> None:
    frame = pd.DataFrame(
        {
            "status": ["completed", "right_censored"],
            "gross_return": [0.10, np.nan],
            "gross_return_basis": ["total_return_local", "not_realized"],
            "entry_day_volume": [1_000.0, 2_000.0],
            "entry_day_dollar_volume_local": [100_000.0, 200_000.0],
            "entry_adv20_local": [90_000.0, np.nan],
            "currency": ["GBP", "USD"],
            "return_usd": [np.nan, np.nan],
        }
    )

    result = complete_ledger_contract(frame)

    assert result.loc[0, "net_return_0bps"] == pytest.approx(0.10)
    assert result.loc[0, "net_return_200bps"] == pytest.approx(0.06)
    assert pd.isna(result.loc[1, "net_return_200bps"])
    assert json.loads(result.loc[0, "net_returns_by_cost_bps_json"])["25"] == (
        pytest.approx(0.095)
    )
    assert pd.isna(result.loc[0, "financed_in_old_portfolio"])
    assert result.loc[0, "financed_in_old_portfolio_source"] == (
        "not_available_in_independent_opportunity_protocol"
    )
    assert result.loc[0, "liquidity_status"] == "observed_local_notional"
    assert result.loc[0, "liquidity_currency"] == "GBP"
    assert result.loc[0, "fx_required"]
    assert not result.loc[0, "fx_available"]


def test_enrichment_accounts_for_splits_dividends_and_leaves_fx_empty() -> None:
    opportunity = pd.DataFrame(
        {
            "opportunity_id": ["one"],
            "combination_id": ["combination-0-0"],
            "symbol": ["AAA"],
            "status": ["completed"],
            "entry_date": ["2020-01-03"],
            "entry_price": [50.5],
            "exit_date": ["2020-01-08"],
            "exit_price": [52.0],
            "mtm_date": [None],
            "mtm_price": [np.nan],
            "gross_return": [52.0 / 50.5 - 1.0],
            "maximum_favourable_excursion": [0.25],
            "maximum_adverse_excursion": [-0.10],
            "intratrade_max_drawdown": [-0.12],
        }
    )
    panel = _panel_frame()
    panel.loc[panel.index[-1], ["high", "low", "close"]] = [1_000.0, 1.0, 500.0]
    panel.loc[panel.index[-1], ["dividends", "stock_splits"]] = [50.0, 3.0]

    result = enrich_opportunities(opportunity, panel).iloc[0]

    assert result["cumulative_split_factor"] == 2.0
    assert result["split_event_count"] == 1
    assert result["dividend_event_count"] == 1
    assert result["dividends_local"] == 2.0
    assert result["entry_value_local_per_initial_share"] == 101.0
    assert result["exit_value_local_per_initial_share"] == 104.0
    assert result["price_return_local"] == pytest.approx(104.0 / 101.0 - 1.0)
    assert result["total_return_local"] == pytest.approx(106.0 / 101.0 - 1.0)
    assert json.loads(result["dividend_payments_local_json"]) == [
        {
            "date": "2020-01-06",
            "declared_local_per_share": 1.0,
            "shares_held": 2.0,
            "cash_local_per_initial_share": 2.0,
        }
    ]
    assert result["gross_return"] == pytest.approx(result["total_return_local"])
    assert result["executor_gross_return"] == pytest.approx(52.0 / 50.5 - 1.0)
    assert result["gross_return_basis"] == "total_return_local"
    assert result["maximum_favourable_excursion"] == 0.25
    assert result["maximum_adverse_excursion"] == -0.10
    assert result["intratrade_max_drawdown"] == -0.12
    assert pd.isna(result["return_usd"])
    assert result["fx_merge_status"] == "not_available_in_entry_period_shard"
    assert not result["capital_rejected"]
    assert not result["overlap_discarded"]


def test_enrichment_uses_existing_causal_usd_total_return_for_statistics() -> None:
    opportunity = pd.DataFrame(
        {
            "opportunity_id": ["usd"],
            "combination_id": ["combination-0-0"],
            "symbol": ["AAA"],
            "status": ["completed"],
            "entry_date": ["2020-01-03"],
            "entry_price": [50.5],
            "exit_date": ["2020-01-08"],
            "exit_price": [52.0],
            "mtm_date": [None],
            "mtm_price": [np.nan],
            "gross_return": [0.0],
            "return_usd": [0.15],
        }
    )

    result = enrich_opportunities(opportunity, _panel_frame()).iloc[0]

    assert result["price_return_local"] == pytest.approx(104.0 / 101.0 - 1.0)
    assert result["total_return_local"] == pytest.approx(106.0 / 101.0 - 1.0)
    assert result["gross_return"] == 0.15
    assert result["gross_return_basis"] == "total_return_usd"
    assert result["fx_merge_status"] == "already_enriched"


def test_reconciliation_counts_censored_and_keeps_not_applicable_out_of_ranking() -> None:
    opportunities = pd.DataFrame(
        {
            "combination_id": ["c0", "c0", "c0"],
            "entry_spec_id": ["e0"] * 3,
            "exit_spec_id": ["x0"] * 3,
            "period": ["C"] * 3,
            "semantic_applicability": ["not_applicable"] * 3,
            "ranking_eligible": [False] * 3,
            "status": ["completed", "right_censored", "failed_due_to_data"],
        }
    )

    result = reconciliation_by_combination(opportunities).iloc[0]

    assert result["opportunities"] == 3
    assert result["completed"] == 1
    assert result["censored"] == 1
    assert result["failed_due_to_data"] == 1
    assert result["reconciled"]
    assert not opportunities["ranking_eligible"].any()
    assert "entry_not_triggered" not in set(opportunities["status"])


def test_empty_entry_cohort_still_reconciles_all_29_combinations() -> None:
    manifest = pd.DataFrame(_manifest_rows()).iloc[:29]
    empty = pd.DataFrame(columns=["combination_id", "status"])

    result = reconciliation_by_combination(empty, manifest, period="A")

    assert len(result) == 29
    assert result["opportunities"].eq(0).all()
    assert result["reconciled"].all()


def test_exit_slice_reconciles_only_its_requested_combinations() -> None:
    manifest = pd.DataFrame(_manifest_rows()).iloc[:5]
    empty = pd.DataFrame(columns=["combination_id", "status"])

    result = reconciliation_by_combination(empty, manifest, period="A")

    assert len(result) == 5
    assert result["combination_id"].tolist() == manifest["combination_id"].tolist()
    assert result["reconciled"].all()


def test_entry_coverage_retains_non_triggered_outside_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel_frame = _panel_frame()
    panel = SimpleNamespace(frame=panel_frame)
    candidates = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "available_at": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "symbol": ["AAA", "AAA"],
            "score": [1.0, 0.9],
        }
    )
    events = pd.DataFrame(
        {
            "selection_date": pd.to_datetime(["2020-01-02"]),
            "signal_date": pd.to_datetime(["2020-01-02"]),
            "available_at": pd.to_datetime(["2020-01-02"]),
            "symbol": ["AAA"],
            "entry_rule": ["immediate_next_open"],
        }
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard._candidates_for_spec",
        lambda *args, **kwargs: candidates,
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard.apply_entry_rule",
        lambda *args, **kwargs: events,
    )
    features = panel_frame[["date", "symbol"]].copy()
    spec = {
        "candidate_id": "entry-0",
        "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
    }

    _, cohort, coverage = build_entry_cohort(
        panel, features, spec, period="B", authorization=None
    )

    assert len(cohort) == 1
    assert coverage["selected"].sum() == 2
    assert coverage["triggered"].sum() == 1
    assert coverage["coverage_status"].eq("entry_not_triggered").sum() == 1
    assert "entry_not_triggered" not in set(cohort.get("status", pd.Series(dtype=str)))


def test_corrected_runner_reuses_prepared_executor_and_preserves_economic_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_root = tmp_path / "manifest"
    manifest = _write_manifest(manifest_root)
    ranking_projection = json.loads(manifest.loc[1, "exit_spec_json"])
    ranking_projection["exit"] = {
        "kind": "ranking_hysteresis",
        "holding_sessions": 20,
        "keep_percentile": 40.0,
    }
    manifest.loc[1, "exit_spec_json"] = json.dumps(ranking_projection)
    manifest.to_csv(
        manifest_root / "original_290_combination_manifest.csv", index=False
    )
    panel_frame = _panel_frame().copy()
    panel_frame["date"] = pd.date_range("2010-01-04", periods=6, freq="B")
    panel = SimpleNamespace(frame=panel_frame)
    features = _base_feature_frame(panel_frame)
    candidates = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2010-01-04"]),
            "available_at": pd.to_datetime(["2010-01-04"]),
            "symbol": ["AAA"],
            "score": [1.0],
        }
    )
    events = candidates.assign(
        selection_date=pd.to_datetime(["2010-01-04"]),
        entry_rule="immediate_next_open",
    )
    shared_executor_context = object()
    prepared_calls: list[object] = []
    ranking_inputs: dict[str, pd.DataFrame | None] = {}
    written: dict[str, pd.DataFrame] = {}

    def prepare_context(*, panel, cutoff, locked_authorization):
        prepared_calls.append(panel)
        assert cutoff == DATASET_CUTOFF
        assert locked_authorization is None
        return shared_executor_context

    def execute(
        signal_frame,
        panel,
        exit_rule,
        *,
        combination_id,
        ranking_keep,
        prepared_context,
        **kwargs,
    ):
        assert prepared_context is shared_executor_context
        ranking_inputs[combination_id] = ranking_keep
        return pd.DataFrame(
            {
                "opportunity_id": [f"opportunity-{combination_id}"],
                "combination_id": [combination_id],
                "symbol": ["AAA"],
                "status": ["completed"],
                "entry_date": ["2010-01-05"],
                "entry_price": [50.5],
                "exit_date": ["2010-01-08"],
                "exit_price": [52.0],
                "mtm_date": [None],
                "mtm_price": [np.nan],
                "gross_return": [52.0 / 50.5 - 1.0],
                "maximum_favourable_excursion": [0.20],
                "maximum_adverse_excursion": [-0.08],
                "intratrade_max_drawdown": [-0.09],
                "holding_sessions": [3],
            }
        )

    def capture_frame(root, stem, frame):
        written[stem] = frame.copy()
        return {"parquet": str(root / f"{stem}.parquet")}

    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard."
        "require_github_actions_or_explicit_local_permission",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard._resolve_pack_root",
        lambda root: root,
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard._period_frames",
        lambda **kwargs: (panel, features),
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard._candidates_for_spec",
        lambda *args, **kwargs: candidates,
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard.apply_entry_rule",
        lambda *args, **kwargs: events,
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard._write_frame_pair",
        capture_frame,
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard."
        "independent_opportunity_executor.prepare_opportunity_execution_context",
        prepare_context,
        raising=False,
    )
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard."
        "independent_opportunity_executor.execute_independent_opportunities",
        execute,
    )

    audit = run_corrected_shard(
        manifest_root=manifest_root,
        pack_root=tmp_path / "pack",
        entry_index=0,
        period="A",
        output_root=tmp_path / "output",
    )

    opportunities = written["corrected_290_opportunities"]
    assert len(opportunities) == 29
    assert len(prepared_calls) == 1
    assert audit["executor_prepared_context_reused"]
    assert ranking_inputs["combination-0-0"] is None
    assert ranking_inputs["combination-0-1"] is not None
    assert not opportunities.loc[
        opportunities["combination_id"].eq("combination-0-0"), "ranking_eligible"
    ].item()
    first = opportunities.iloc[0]
    assert first["gross_return"] == pytest.approx(106.0 / 101.0 - 1.0)
    assert first["gross_return_basis"] == "total_return_local"
    assert first["maximum_favourable_excursion"] == 0.20
    assert json.loads(first["dividend_payments_local_json"])[0]["date"] == "2010-01-06"
    assert pd.isna(first["return_usd"])
    assert first["fx_merge_status"] == "not_available_in_entry_period_shard"


def test_locked_period_rejects_unbound_data_before_loading_manifest_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "manifest"
    _write_manifest(root)
    monkeypatch.setattr(
        "scripts.run_stock_protocol_290_corrected_shard."
        "require_github_actions_or_explicit_local_permission",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(ValueError, match="requires locked shards"):
        run_corrected_shard(
            manifest_root=root,
            pack_root=tmp_path / "pack",
            locked_shards_root=None,
            frozen_manifest_path=None,
            frozen_manifest_sha256=None,
            implementation_commit=None,
            entry_index=0,
            period="C",
            output_root=tmp_path / "output",
        )
