from __future__ import annotations

import json

import numpy as np
import pandas as pd
import aurora.infra.sp500_search_method_benchmark.benchmark as benchmark_module
from aurora.infra.sp500_search_method_benchmark.benchmark import (
    METHODS,
    SEEDS,
    _genome_canonical,
    _warm_start,
    canonical_hash,
    parse_causal_dates,
    run_unit,
)
from aurora.infra.sp500_long_short_daily.data import write_fixture_snapshot
from aurora.infra.sp500_long_short_daily.ledger import build_total_return_ledger


def test_numeric_dates_require_explicit_unit_and_preserve_expected_boundary():
    expected = pd.DatetimeIndex(["2004-05-03", "2010-12-30"])
    seconds = [int(pd.Timestamp(value, tz="UTC").timestamp()) for value in expected]
    assert parse_causal_dates(seconds, numeric_unit="s").equals(expected)
    try:
        parse_causal_dates(seconds)
    except ValueError as exc:
        assert str(exc) == "NUMERIC_DATE_REQUIRES_EXPLICIT_UNIT"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("numeric dates must not be guessed")


def test_prepare_uses_explicit_fast_source_path_and_date_firewall(monkeypatch, tmp_path):
    calls = {}

    def fake_prepare_market_snapshot(root, package, **kwargs):
        calls.update(kwargs)
        index = pd.bdate_range("1993-01-22", "2010-12-31")
        close = pd.Series(100.0, index=index)
        prices = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 100_000.0,
            },
            index=index,
        )
        ledger, _ = build_total_return_ledger(prices)
        write_fixture_snapshot(root, ledger, split="train")
        return {
            "minimum_date": "1993-01-22",
            "maximum_date": "2010-12-31",
            "locked_opened": False,
            "receipts": [],
        }

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(benchmark_module, "prepare_market_snapshot", fake_prepare_market_snapshot)
    benchmark_module.prepare_benchmark_data(tmp_path / "prepared")

    manifest = json.loads((tmp_path / "prepared" / "benchmark_dataset_manifest.json").read_text())
    assert calls["skip_independent_price_sources"] is True
    assert manifest["date_parser"] == "strict_explicit_numeric_unit_seconds"
    assert manifest["locked_start_unopened"] == "2021-01-01"
    assert manifest["loaded_last_date"] == "2010-12-31"


def test_common_warm_start_is_identical_for_all_methods():
    warm = _warm_start(SEEDS[0])
    assert warm.shape == (32, 15)
    assert all(np.array_equal(warm, _warm_start(SEEDS[0])) for _ in METHODS)


def test_methods_share_the_same_representable_space():
    left = _genome_canonical(np.linspace(0.01, 0.99, 15))
    right = _genome_canonical(np.linspace(0.99, 0.01, 15))
    assert set(left) == set(right)
    assert left["root"] in {"boolean", "hysteresis"}
    assert left["active_nodes"] <= 15
    assert canonical_hash(left) == canonical_hash(json.loads(json.dumps(left, sort_keys=True)))


def test_search_space_has_exact_methods_and_seeds():
    assert METHODS == (
        "M0_RANDOM",
        "M1_SCRAMBLED_SOBOL",
        "M2_TPE",
        "M3_SMAC_RF_SMBO",
        "M4_DIFFERENTIAL_EVOLUTION",
        "M5_STRONGLY_TYPED_GENETIC_PROGRAMMING",
        "M6_GP_TO_TPE_HYBRID",
    )
    assert SEEDS == (104729, 209759, 314159, 419431, 524287, 630529, 735731)


def test_synthetic_unit_has_exact_budget_and_never_reads_future(tmp_path):
    index = pd.bdate_range("1993-01-22", "2010-12-31")
    rng = np.random.default_rng(11)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0001, 0.008, len(index))))
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 100_000.0,
        },
        index=index,
    )
    ledger, _ = build_total_return_ledger(frame)
    write_fixture_snapshot(tmp_path / "data", ledger, split="train")
    result = run_unit("M0_RANDOM", 104729, tmp_path / "data", tmp_path / "unit")
    assert len(result["records"]) == 256
    assert result["unique_evaluations"] <= 256
    assert result["date_access"]["validation_rows"] == 0
    assert result["date_access"]["locked_rows"] == 0
    assert max(row["search_annual"][-1]["year"] for row in result["records"] if row["search_annual"]) <= 2005
