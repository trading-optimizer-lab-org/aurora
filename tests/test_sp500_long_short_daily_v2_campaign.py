from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.infra.sp500_long_short_daily.data import PreparedMarketData
from aurora.infra.sp500_long_short_daily.ledger import apply_positions
from aurora.infra.sp500_long_short_daily_v2.contracts import (
    CampaignPackage,
    EXPECTED_CANDIDATES,
    EXPECTED_CUMULATIVE_TRIALS,
    EXPECTED_V1_RESULTS_SHA256,
    VALIDATION_ACK,
    LockedBoundaryError,
    assert_frame_before_locked,
    canonical_json_hash,
)
from aurora.infra.sp500_long_short_daily_v2.data import FIXED_SYMBOLS, split_normalize_ohlcv
from aurora.infra.sp500_long_short_daily_v2.signals import (
    FeatureStore,
    candidate_decisions,
    candidate_decisions_reference,
    newey_west_slope_tstat,
    variance_ratio,
)
from aurora.infra.sp500_long_short_daily_v2.statistics import load_v1_evidence
from aurora.infra.sp500_long_short_daily_v2.validation import (
    ValidationGateError,
    verify_train_freeze,
)
from aurora.infra.sp500_long_short_daily_v2.workload import (
    BENCHMARK_IDS,
    SMOKE_WORKLOAD,
    TRAIN_WORKLOAD,
)


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns" / "sp500_long_short_daily_v2"


@pytest.fixture(scope="module")
def package() -> CampaignPackage:
    return CampaignPackage.load_zip(
        CAMPAIGN / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_V2_NEW_STRATEGIES.zip"
    )


@pytest.fixture(scope="module")
def synthetic_data() -> PreparedMarketData:
    index = pd.bdate_range("2003-01-02", periods=1800)
    x = np.arange(len(index), dtype=float)
    close = pd.Series(100.0 * np.exp(0.00015 * x + 0.02 * np.sin(x / 17.0)), index=index)
    open_ = close.shift(1).fillna(close.iloc[0]) * (1.0 + 0.002 * np.sin(x / 7.0))
    high = pd.concat([open_, close], axis=1).max(axis=1) * 1.006
    low = pd.concat([open_, close], axis=1).min(axis=1) * 0.994
    volume = pd.Series(1_000_000.0 + 100_000.0 * (1 + np.sin(x / 11.0)), index=index)
    long_return = open_.shift(-1) / open_ - 1.0
    ledger = pd.DataFrame(
        {
            "long_return": long_return,
            "short_return": -long_return,
            "tr_open": (1.0 + long_return.fillna(0.0)).cumprod().shift(1).fillna(1.0),
            "tr_close": close / close.iloc[0],
        },
        index=index,
    )
    series = {}
    for symbol_index, symbol in enumerate(FIXED_SYMBOLS):
        multiplier = 1.0 + 0.00003 * symbol_index * x + 0.003 * np.sin(x / (13 + symbol_index))
        qclose = close * multiplier
        series[f"{symbol}::open"] = open_ * multiplier
        series[f"{symbol}::high"] = high * multiplier
        series[f"{symbol}::low"] = low * multiplier
        series[f"{symbol}::close"] = qclose
        series[f"{symbol}::volume"] = volume * (1 + symbol_index / 20)
    return PreparedMarketData(
        ledger=ledger,
        series=series,
        available_dataset_ids=frozenset(f"V2DS{i:03d}" for i in range(1, 10)),
        rejected_datasets={"V2DS010": "SECONDARY_ONLY"},
        receipts=(),
        split="train",
    )


def test_package_cardinality_and_contract(package: CampaignPackage) -> None:
    assert len(package.candidates) == EXPECTED_CANDIDATES
    assert len({row["family"] for row in package.candidates}) == 24
    assert {sum(row["family"] == family for row in package.candidates) for family in {row["family"] for row in package.candidates}} == {6}
    assert len(package.features) == 144
    assert len(BENCHMARK_IDS) == 5
    assert len(TRAIN_WORKLOAD._unit_definitions()) == 149
    assert all(row["position_values"] == [-1, 1] for row in package.candidates)
    assert all(all(float(row[name]) == 0 for name in ("commission_bps", "slippage_bps", "borrow_cost_bps", "financing_bps", "switching_cost_bps", "market_impact_bps")) for row in package.candidates)
    assert all(row["locked_opened"] is False for row in package.candidates)


def test_smoke_uses_complete_audited_distribution_periods() -> None:
    assert SMOKE_WORKLOAD.data_start == "2005-10-01"
    assert SMOKE_WORKLOAD.data_end == "2009-09-30"
    assert SMOKE_WORKLOAD.evaluation_start == "2006-10-01"


def test_embedded_v1_has_exact_65_streams_and_312_trial_ledger(package: CampaignPackage) -> None:
    daily, eligibility, _ = load_v1_evidence(CAMPAIGN / "prior_campaign" / "sp500-ls-train-yahoo-fallback-r8-results.zip")
    candidates = daily.loc[~daily["unit_key"].astype(str).str.startswith("BENCHMARK::")]
    declared = eligibility.loc[~eligibility["unit_key"].astype(str).str.startswith("BENCHMARK::")]
    assert candidates["unit_key"].nunique() == 65
    assert len(declared) == 168
    assert len(declared) + len(package.candidates) == EXPECTED_CUMULATIVE_TRIALS


def test_split_normalization_prices_and_inverse_volume() -> None:
    prices = pd.DataFrame({"date": pd.to_datetime(["2000-01-03", "2000-01-04"]), "open": [100, 52], "high": [102, 53], "low": [98, 51], "close": [100, 52], "adj_close": [50, 52], "volume": [10, 22]})
    splits = pd.DataFrame({"date": pd.to_datetime(["2000-01-04"]), "split_ratio": [2.0]})
    result = split_normalize_ohlcv(prices, splits, source_already_split_normalized=False)
    assert result.loc[0, "close"] == 50
    assert result.loc[0, "volume"] == 20
    assert result.loc[1, "close"] == 52


def test_next_open_and_long_short_identity(synthetic_data: PreparedMarketData) -> None:
    index = synthetic_data.ledger.index[:4]
    decisions = pd.Series([-1, 1, -1, 1], index=index, dtype=np.int8)
    applied = apply_positions(synthetic_data.ledger.loc[index], decisions)
    assert applied["position"].tolist() == [1, -1, 1, -1]
    assert np.allclose(synthetic_data.ledger["long_return"], -synthetic_data.ledger["short_return"], equal_nan=True)


def test_reference_and_optimized_match_each_family(package: CampaignPackage, synthetic_data: PreparedMarketData) -> None:
    representatives = [next(row for row in package.candidates if row["family"] == family) for family in sorted({row["family"] for row in package.candidates})]
    store = FeatureStore.build(synthetic_data)
    for candidate in representatives:
        optimized = candidate_decisions(candidate, synthetic_data, feature_store=store)
        reference = candidate_decisions_reference(candidate, synthetic_data)
        pd.testing.assert_series_equal(optimized.decisions, reference.decisions)
        assert optimized.first_evaluable_date == reference.first_evaluable_date


def test_variance_ratio_and_newey_west_fixtures() -> None:
    trend = np.linspace(-0.01, 0.02, 126)
    assert np.isfinite(variance_ratio(trend, 5))
    assert newey_west_slope_tstat(np.log(np.linspace(100, 130, 63))) > 0


def test_locked_firewall() -> None:
    with pytest.raises(LockedBoundaryError, match="TECHNICAL_FAILURE_LOCKED_BREACH"):
        assert_frame_before_locked(pd.DataFrame({"value": [1]}, index=pd.to_datetime(["2021-01-01"])), label="test")


def test_workflow_is_github_only_and_has_exact_ack() -> None:
    path = ROOT / ".github" / "workflows" / "sp500-long-short-daily-v2-campaign.yml"
    text = path.read_text("utf-8")
    assert "C:\\" not in text
    assert "self-hosted" not in text
    assert "ubuntu-24.04" in text
    assert "OPEN_VALIDATION_2011_2020_ONCE_V2" in text
    assert "aurora.infra.sp500_long_short_daily_v2.workload" in text


def test_v2_module_is_in_distribution_package_map() -> None:
    text = (ROOT / "pyproject.toml").read_text("utf-8")
    assert '"aurora.infra.sp500_long_short_daily_v2"' in text
    assert '"aurora.infra.sp500_long_short_daily_v2" = "infra/sp500_long_short_daily_v2"' in text
    lock = (ROOT / "requirements" / "github-performance.lock").read_text("utf-8")
    assert "scikit-learn==1.9.0" in lock
    assert "joblib==1.5.3" in lock
    assert "narwhals==2.24.0" in lock
    assert "threadpoolctl==3.6.0" in lock


def test_no_post_2020_boundary_in_spec() -> None:
    text = (ROOT / "config" / "sp500_long_short_daily_v2_train_v3.yaml").read_text("utf-8")
    assert 'train_end: "2010-12-31"' in text
    assert 'validation_end: "2020-12-31"' in text
    assert 'locked_start: "2021-01-01"' in text


def _valid_freeze(package: CampaignPackage) -> dict[str, object]:
    candidate = next(row for row in package.candidates if row["evidence_track"] == "pre_2011_evidence")
    freeze: dict[str, object] = {
        "schema_version": "2",
        "campaign_id": "sp500_long_short_daily_zero_cost_v2_new_strategies",
        "selection_closed": True,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "validation_opened": False,
        "locked_opened": False,
        "validation_authorization_required": VALIDATION_ACK,
        "v1_results_sha256": EXPECTED_V1_RESULTS_SHA256,
        "cumulative_declared_trials": 312,
        "code_sha": "LOCAL_TEST_ONLY",
        "finalists": [
            {
                "strategy_id": candidate["strategy_id"],
                "canonical_hash": candidate["canonical_hash"],
                "candidate_rules": candidate,
                "eligible_for_validation": True,
            }
        ],
    }
    freeze["freeze_sha256"] = canonical_json_hash(freeze)
    return freeze


def test_validation_freeze_is_fail_closed_and_pre_2011_only(
    tmp_path: Path, package: CampaignPackage
) -> None:
    path = tmp_path / "v2_train_selection_freeze.json"
    valid = _valid_freeze(package)
    path.write_text(json.dumps(valid), encoding="utf-8")
    verified = verify_train_freeze(path, code_sha="LOCAL_TEST_ONLY")
    assert verified["validation_opened"] is False
    assert verified["locked_opened"] is False

    invalid = dict(valid)
    invalid["locked_start"] = "2022-01-01"
    invalid.pop("freeze_sha256", None)
    invalid["freeze_sha256"] = canonical_json_hash(invalid)
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValidationGateError, match="TRAIN_FREEZE_DATES_INVALID"):
        verify_train_freeze(path, code_sha="LOCAL_TEST_ONLY")


def test_validation_freeze_rejects_empty_or_post_2010_finalist(
    tmp_path: Path, package: CampaignPackage
) -> None:
    path = tmp_path / "v2_train_selection_freeze.json"
    empty = _valid_freeze(package)
    empty["finalists"] = []
    empty.pop("freeze_sha256", None)
    empty["freeze_sha256"] = canonical_json_hash(empty)
    path.write_text(json.dumps(empty), encoding="utf-8")
    with pytest.raises(ValidationGateError, match="NO_FROZEN_FINALISTS"):
        verify_train_freeze(path, code_sha="LOCAL_TEST_ONLY")

    post = _valid_freeze(package)
    finalist = dict(post["finalists"][0])
    rules = dict(finalist["candidate_rules"])
    rules["evidence_track"] = "post_2010_research"
    finalist["candidate_rules"] = rules
    post["finalists"] = [finalist]
    post.pop("freeze_sha256", None)
    post["freeze_sha256"] = canonical_json_hash(post)
    path.write_text(json.dumps(post), encoding="utf-8")
    with pytest.raises(ValidationGateError, match="POST_2010_FINALIST_PROHIBITED"):
        verify_train_freeze(path, code_sha="LOCAL_TEST_ONLY")
