from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from aurora.infra.sp500_long_short_daily.contracts import (
    EXPECTED_CANDIDATES,
    EXPECTED_FAMILIES,
    EXPECTED_FEATURES,
    CampaignPackage,
    LockedBoundaryError,
    canonical_json_hash,
    candidate_canonical_payload,
)
from aurora.infra.sp500_long_short_daily.ledger import (
    apply_positions,
    build_total_return_ledger,
)
from aurora.infra.sp500_long_short_daily.data import (
    DataGateError,
    PreparedMarketData,
    _align_initial_releases,
    _parse_yahoo_chart,
    _reconcile_spy_sources,
    _repo_campaign_root,
    download_alfred_initial_series,
    load_sec_distribution_totals,
    load_state_street_distributions,
    reconcile_official_distribution_audit,
    reconcile_sponsor_distributions,
    write_fixture_snapshot,
    load_market_snapshot,
)
from aurora.infra.sp500_long_short_daily.signals import (
    CandidateRejected,
    EXPLICIT_FAMILY_REJECTIONS,
    IMPLEMENTED_FAMILIES,
    _frozen_component_ids,
    benchmark_decisions,
    candidate_decisions,
)
from aurora.infra.sp500_long_short_daily.workload import (
    PILOT_WORKLOAD,
    SMOKE_WORKLOAD,
    TRAIN_WORKLOAD,
)
from aurora.infra.sp500_long_short_daily.statistics import (
    _benjamini_hochberg,
    _stationary_bootstrap_indices,
    effective_independent_trials,
    reality_check_and_spa,
)
from aurora.infra.sp500_long_short_daily.validation import (
    VALIDATION_ACK,
    ValidationGateError,
    combine_phase_snapshots,
    run_validation_once,
    verify_train_freeze,
)
from aurora.infra.github_performance.contracts import RunSpec
from aurora.infra.github_performance.preflight import validate_run_spec


REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = REPO_ROOT / "campaigns" / "sp500_long_short_daily"


def _campaign() -> CampaignPackage:
    return CampaignPackage.load(
        CAMPAIGN_ROOT / "research_input",
        CAMPAIGN_ROOT / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip",
    )


def test_campaign_root_prefers_explicit_github_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = tmp_path / "campaigns" / "sp500_long_short_daily"
    (expected / "official_inputs").mkdir(parents=True)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    assert _repo_campaign_root() == expected.resolve()


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-12-23", "2020-12-24", "2020-12-28", "2020-12-29"]),
            "open": [100.0, 101.0, 50.0, 51.0],
            "high": [102.0, 102.0, 51.0, 52.0],
            "low": [99.0, 100.0, 49.0, 50.0],
            "close": [101.0, 101.5, 50.5, 51.5],
            "volume": [10, 11, 22, 23],
        }
    )


def test_exact_package_contract_and_counts() -> None:
    package = _campaign()
    assert len(package.candidates) == EXPECTED_CANDIDATES
    assert len(package.features) == EXPECTED_FEATURES
    assert len({row["family"] for row in package.candidates}) == EXPECTED_FAMILIES
    assert len(package.spec["benchmarks"]) == 5
    assert all(row["position_values"] == [-1, 1] for row in package.candidates)


def test_candidate_hashes_are_exact_and_unique() -> None:
    package = _campaign()
    observed = []
    for candidate in package.candidates:
        expected = canonical_json_hash(candidate_canonical_payload(candidate))
        assert candidate["canonical_hash"] == expected
        observed.append(expected)
    assert len(observed) == len(set(observed)) == 168


def test_all_positions_and_costs_are_frozen() -> None:
    package = _campaign()
    costs = {
        "commission_bps",
        "slippage_bps",
        "borrow_cost_bps",
        "financing_bps",
        "switching_cost_bps",
        "market_impact_bps",
    }
    for candidate in package.candidates:
        assert candidate["position_values"] == [-1, 1]
        assert candidate["absolute_exposure"] == 1.0
        assert all(candidate[key] == 0 for key in costs)


def test_dividend_and_split_open_to_open_hand_calculation() -> None:
    distributions = pd.DataFrame({"date": [pd.Timestamp("2020-12-24")], "distribution": [1.0]})
    splits = pd.DataFrame({"date": [pd.Timestamp("2020-12-28")], "split_ratio": [2.0]})
    ledger, audit = build_total_return_ledger(_prices(), distributions, splits)
    assert audit.distribution_count == 1
    assert audit.split_count == 1
    assert audit.long_short_max_abs_error == 0.0
    expected_first = ((101.0 / 2.0) + (1.0 / 2.0) - (100.0 / 2.0)) / (100.0 / 2.0)
    assert ledger.loc["2020-12-23", "long_return"] == pytest.approx(expected_first)
    assert np.allclose(
        ledger["short_return"].dropna(),
        -ledger["long_return"].dropna(),
        rtol=0,
        atol=0,
    )
    assert ledger["tr_open"].iloc[0] == 1.0
    assert ledger["tr_open"].iloc[1] == pytest.approx(1.0 + expected_first)


def test_adjusted_close_is_never_used_as_an_open_price() -> None:
    prices = _prices().assign(adj_close=[1.0, 2.0, 3.0, 4.0])
    plain, _ = build_total_return_ledger(_prices())
    adjusted_column_present, _ = build_total_return_ledger(prices)
    pd.testing.assert_series_equal(plain["long_return"], adjusted_column_present["long_return"])


def test_yahoo_chart_parser_preserves_raw_prices_events_and_bounds() -> None:
    timestamps = [
        int(pd.Timestamp("2009-03-19", tz="UTC").timestamp()),
        int(pd.Timestamp("2009-03-20", tz="UTC").timestamp()),
    ]
    payload = json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {
                            "regularMarketTime": int(
                                pd.Timestamp("2026-08-04", tz="UTC").timestamp()
                            ),
                            "regularMarketPrice": 999.0,
                        },
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": [80.0, 81.0],
                                    "high": [82.0, 83.0],
                                    "low": [79.0, 80.0],
                                    "close": [81.0, 82.0],
                                    "volume": [1000, 1200],
                                }
                            ],
                            "adjclose": [{"adjclose": [75.0, 76.0]}],
                        },
                        "events": {
                            "dividends": {
                                str(timestamps[1]): {
                                    "date": timestamps[1],
                                    "amount": 0.56172,
                                }
                            },
                            "splits": {
                                str(timestamps[0]): {
                                    "date": timestamps[0],
                                    "numerator": 2.0,
                                    "denominator": 1.0,
                                }
                            },
                        },
                    }
                ],
            }
        }
    ).encode()

    prices, dividends, splits, bounded = _parse_yahoo_chart(
        payload,
        start=pd.Timestamp("2009-03-19"),
        end=pd.Timestamp("2009-03-20"),
    )

    assert prices["close"].tolist() == [81.0, 82.0]
    assert prices["adj_close"].tolist() == [75.0, 76.0]
    assert dividends.to_dict(orient="records") == [
        {"date": pd.Timestamp("2009-03-20"), "distribution": 0.56172}
    ]
    assert splits.to_dict(orient="records") == [
        {"date": pd.Timestamp("2009-03-19"), "split_ratio": 2.0}
    ]
    bounded_document = json.loads(bounded)
    assert "meta" not in bounded_document
    assert bounded_document["prices"][-1]["date"] == "2009-03-20"
    assert "2026" not in bounded.decode()


def test_yahoo_chart_parser_rejects_observations_outside_requested_period() -> None:
    timestamp = int(pd.Timestamp("2011-01-03", tz="UTC").timestamp())
    payload = json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "timestamp": [timestamp],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0],
                                    "high": [101.0],
                                    "low": [99.0],
                                    "close": [100.5],
                                    "volume": [1000],
                                }
                            ],
                            "adjclose": [{"adjclose": [100.5]}],
                        },
                    }
                ],
            }
        }
    ).encode()
    with pytest.raises(DataGateError, match="UNBOUNDED_SOURCE_RESPONSE:yahoo_history"):
        _parse_yahoo_chart(
            payload,
            start=pd.Timestamp("2010-01-01"),
            end=pd.Timestamp("2010-12-31"),
        )


def test_next_session_open_crosses_nyse_holiday_without_calendar_day_fill() -> None:
    ledger, _ = build_total_return_ledger(_prices())
    assert ledger.index[1] == pd.Timestamp("2020-12-24")
    assert ledger.index[2] == pd.Timestamp("2020-12-28")
    expected = (50.0 - 101.0) / 101.0
    assert ledger.loc["2020-12-24", "long_return"] == pytest.approx(expected)


def test_official_sponsor_snapshot_and_yahoo_events_must_match(tmp_path: Path) -> None:
    path = tmp_path / "state-street.csv"
    path.write_text(
        "ex_date,distribution\n2009-03-20,0.56172\n2010-03-19,0.48073\n",
        encoding="utf-8",
    )
    sponsor, receipt = load_state_street_distributions(
        path, "2009-01-01", "2010-12-31", split="train"
    )
    assert receipt.dataset_id == "DS001"
    assert receipt.status == "loaded_official_frozen_snapshot"
    audit = reconcile_sponsor_distributions(sponsor, sponsor.copy())
    assert audit["event_count"] == 2
    mismatched = sponsor.copy()
    mismatched.loc[0, "distribution"] += 0.01
    with pytest.raises(DataGateError, match="SPONSOR_DISTRIBUTION_AMOUNT_MISMATCH"):
        reconcile_sponsor_distributions(sponsor, mismatched)


def test_layered_official_distribution_audit_covers_every_operational_event(
    tmp_path: Path,
) -> None:
    exact_path = tmp_path / "exact.csv"
    exact_path.write_text(
        "ex_date,distribution\n2006-06-16,0.55\n2006-09-15,0.58\n",
        encoding="utf-8",
    )
    totals_path = tmp_path / "totals.csv"
    totals_path.write_text(
        "period_start,period_end,distribution_total\n2005-10-01,2006-09-30,1.13\n",
        encoding="utf-8",
    )
    exact, _ = load_state_street_distributions(
        exact_path, "2005-10-01", "2010-12-31", split="train"
    )
    totals, _ = load_sec_distribution_totals(totals_path, "2005-10-01", "2010-12-31", split="train")
    audit = reconcile_official_distribution_audit(exact, totals, exact.copy())
    assert audit["operational_event_count"] == 2
    assert audit["uncovered_event_count"] == 0

    uncovered = pd.concat(
        [
            exact,
            pd.DataFrame({"date": pd.to_datetime(["2005-09-16"]), "distribution": [0.10]}),
        ],
        ignore_index=True,
    )
    with pytest.raises(
        DataGateError,
        match="OPERATIONAL_DISTRIBUTION_EVENT_WITHOUT_OFFICIAL_COVERAGE",
    ):
        reconcile_official_distribution_audit(exact, totals, uncovered)


def test_sec_totals_can_cover_window_before_exact_event_export() -> None:
    exact = pd.DataFrame(columns=["date", "distribution"])
    totals = pd.DataFrame(
        {
            "period_start": [pd.Timestamp("1994-01-01")],
            "period_end": [pd.Timestamp("1994-12-31")],
            "distribution_total": [1.23],
        }
    )
    operational = pd.DataFrame(
        {
            "date": pd.to_datetime(["1994-03-18", "1994-06-17", "1994-09-16", "1994-12-16"]),
            "distribution": [0.27, 0.30, 0.31, 0.35],
        }
    )
    audit = reconcile_official_distribution_audit(exact, totals, operational)
    assert audit["exact_event_audit"]["event_count"] == 0
    assert audit["fiscal_period_audit"][0]["event_count"] == 4
    assert audit["uncovered_event_count"] == 0


def test_layered_official_distribution_audit_rejects_fiscal_total_mismatch(
    tmp_path: Path,
) -> None:
    exact_path = tmp_path / "exact.csv"
    exact_path.write_text(
        "ex_date,distribution\n2006-06-16,0.55\n2006-09-15,0.58\n",
        encoding="utf-8",
    )
    totals_path = tmp_path / "totals.csv"
    totals_path.write_text(
        "period_start,period_end,distribution_total\n2005-10-01,2006-09-30,9.99\n",
        encoding="utf-8",
    )
    exact, _ = load_state_street_distributions(
        exact_path, "2005-10-01", "2010-12-31", split="train"
    )
    totals, _ = load_sec_distribution_totals(totals_path, "2005-10-01", "2010-12-31", split="train")
    with pytest.raises(DataGateError, match="SEC_DISTRIBUTION_FISCAL_TOTAL_MISMATCH"):
        reconcile_official_distribution_audit(exact, totals, exact.copy())


def test_sponsor_snapshot_cannot_cross_train_or_locked_boundary(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "ex_date,distribution\n2010-12-17,0.65\n2021-03-19,1.38\n",
        encoding="utf-8",
    )
    with pytest.raises(
        (DataGateError, LockedBoundaryError),
        match="STATE_STREET_SNAPSHOT_EXCEEDS_PHASE_BOUNDARY|LOCKED_BREACH",
    ):
        load_state_street_distributions(path, "1993-01-22", "2010-12-31", split="train")


def test_spy_reconciliation_requires_99_5_percent_and_explains_outliers() -> None:
    dates = pd.bdate_range("2000-01-03", periods=1001)
    close = 100.0 * np.cumprod(np.full(len(dates), 1.0001))
    yahoo = pd.DataFrame({"date": dates, "close": close})
    stooq = yahoo.copy()
    distributions = pd.DataFrame(columns=["date", "distribution"])
    splits = pd.DataFrame(columns=["date", "split_ratio"])
    report = _reconcile_spy_sources(yahoo, stooq, distributions, splits, minimum_overlap=1000)
    assert report["within_5_bps_fraction"] == 1.0
    broken = stooq.copy()
    broken.loc[500, "close"] *= 1.01
    with pytest.raises(DataGateError, match="SPY_UNRECONCILED_RETURN_OUTLIERS"):
        _reconcile_spy_sources(yahoo, broken, distributions, splits, minimum_overlap=1000)


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.content = payload

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.params = None

    def get(self, url, *, params=None, timeout=None):
        del url, timeout
        self.params = params
        return _FakeResponse(self.payload)


def test_alfred_uses_initial_release_dates_and_never_latest_revised_values() -> None:
    payload = json.dumps(
        {
            "observations": [
                {
                    "date": "2000-01-01",
                    "realtime_start": "2000-02-15",
                    "realtime_end": "2000-02-15",
                    "value": "100.0",
                },
                {
                    "date": "2000-02-01",
                    "realtime_start": "2000-03-15",
                    "realtime_end": "2000-03-15",
                    "value": "101.0",
                },
            ]
        }
    ).encode()
    session = _FakeSession(payload)
    releases, receipt = download_alfred_initial_series(
        "CPIAUCSL",
        "DS033",
        "2000-01-01",
        "2000-12-31",
        split="train",
        session=session,
        api_key="test-key",
    )
    assert session.params is not None
    assert session.params["output_type"] == 4
    assert receipt.status == "downloaded_initial_releases_only"
    sessions = pd.DatetimeIndex(["2000-02-15", "2000-02-16", "2000-03-15", "2000-03-16"])
    aligned = _align_initial_releases(releases, sessions)
    assert pd.isna(aligned.loc["2000-02-15"])
    assert aligned.loc["2000-02-16"] == 100.0
    assert aligned.loc["2000-03-16"] == 101.0


def test_alfred_rejects_release_after_phase_end_without_persisting_it(
    tmp_path: Path,
) -> None:
    payload = json.dumps(
        {
            "observations": [
                {
                    "date": "2010-12-01",
                    "realtime_start": "2011-01-15",
                    "realtime_end": "2011-01-15",
                    "value": "100.0",
                }
            ]
        }
    ).encode()
    with pytest.raises(DataGateError, match="POST_PHASE_RELEASE_IN_RESPONSE"):
        download_alfred_initial_series(
            "CPIAUCSL",
            "DS033",
            "2010-01-01",
            "2010-12-31",
            split="train",
            session=_FakeSession(payload),
            api_key="test-key",
            raw_dir=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []


def test_close_decision_executes_at_next_open_and_ties_persist() -> None:
    ledger, _ = build_total_return_ledger(_prices())
    decisions = pd.Series([1.0, -1.0, np.nan, 1.0], index=ledger.index, dtype=float)
    result = apply_positions(ledger, decisions)
    assert result["position"].tolist() == [1, 1, -1, -1]


def test_locked_firewall_fails_without_value_disclosure() -> None:
    prices = _prices()
    prices.loc[len(prices)] = [
        pd.Timestamp("2021-01-04"),
        52.0,
        53.0,
        51.0,
        52.5,
        24,
    ]
    with pytest.raises(LockedBoundaryError, match="TECHNICAL_FAILURE_LOCKED_BREACH"):
        build_total_return_ledger(prices)


def _long_fixture() -> PreparedMarketData:
    dates = pd.bdate_range("1993-01-22", "2010-12-31")
    phase = np.linspace(0.0, 20.0 * np.pi, len(dates))
    close = 100.0 * np.exp(np.cumsum(0.0002 + 0.002 * np.sin(phase)))
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.linspace(1_000_000, 2_000_000, len(dates)),
        }
    )
    ledger, _ = build_total_return_ledger(prices)
    return PreparedMarketData(
        ledger=ledger,
        series={},
        available_dataset_ids=frozenset({"DS001", "DS002"}),
        rejected_datasets={},
        receipts=(),
        split="train",
    )


def test_repository_official_distribution_inputs_are_bounded_and_complete() -> None:
    official = CAMPAIGN_ROOT / "official_inputs"
    events, _ = load_state_street_distributions(
        official / "state_street_spy_distribution_events_2006_2010.csv",
        "1993-01-22",
        "2010-12-31",
        split="train",
    )
    totals, _ = load_sec_distribution_totals(
        official / "sec_spy_distribution_fiscal_totals_1993_2009.csv",
        "1993-01-22",
        "2010-12-31",
        split="train",
    )
    audit = json.loads((official / "official_source_audit.json").read_text("utf-8"))
    assert len(events) == 19
    assert len(totals) == 17
    assert events["date"].max() == pd.Timestamp("2010-12-17")
    assert totals["period_end"].max() == pd.Timestamp("2009-09-30")
    assert audit["locked_opened"] is False
    assert audit["validation_boundary_incident"]["response_used"] is False


def test_price_candidate_and_benchmarks_are_exact_long_short_states() -> None:
    data = _long_fixture()
    package = _campaign()
    candidate = package.candidate_by_id()["STRAT0004"]
    signal = candidate_decisions(candidate, data)
    assert signal.first_evaluable_date is not None
    assert set(signal.decisions.unique()) <= {-1, 1}
    always_long = benchmark_decisions("always_long", data).decisions
    buy_hold = benchmark_decisions("buy_and_hold_spy_total_return", data).decisions
    always_short = benchmark_decisions("always_short", data).decisions
    assert always_long.equals(buy_hold)
    assert np.array_equal(always_short.to_numpy(), -always_long.to_numpy())


def test_warmup_is_not_misreported_as_missing_causal_coverage() -> None:
    data = _long_fixture()
    candidate = _campaign().candidate_by_id()["STRAT0004"]
    signal = candidate_decisions(candidate, data)
    assert signal.missing_fraction == pytest.approx(0.0)


def test_missing_candidate_dataset_is_explicit_rejection() -> None:
    data = _long_fixture()
    candidate = _campaign().candidate_by_id()["STRAT0019"]
    with pytest.raises(CandidateRejected, match="DATA_GATE_REJECTED"):
        candidate_decisions(candidate, data)


def test_monetary_candidate_uses_calendar_yoy_and_exact_long_short_states() -> None:
    base = _long_fixture()
    index = base.ledger.index
    data = PreparedMarketData(
        ledger=base.ledger,
        series={
            "DFF": pd.Series(4.0, index=index),
            "CPI": pd.Series(
                100.0 * np.exp(np.arange(len(index)) * 0.02 / 252.0),
                index=index,
            ),
        },
        available_dataset_ids=frozenset({"DS001", "DS002", "DS021", "DS033"}),
        rejected_datasets={},
        receipts=(),
        split="train",
    )
    candidate = _campaign().candidate_by_id()["STRAT0121"]
    signal = candidate_decisions(candidate, data)
    assert signal.first_evaluable_date is not None
    assert set(signal.decisions.unique()) <= {-1, 1}
    assert (signal.decisions.loc[signal.first_evaluable_date :] == -1).all()


def test_nfci_change_uses_four_calendar_weeks_not_four_daily_sessions() -> None:
    base = _long_fixture()
    index = base.ledger.index
    nfci = pd.Series(np.arange(len(index), dtype=float), index=index)
    data = PreparedMarketData(
        ledger=base.ledger,
        series={"NFCI": nfci},
        available_dataset_ids=frozenset({"DS001", "DS002", "DS025"}),
        rejected_datasets={},
        receipts=(),
        split="train",
    )
    candidate = _campaign().candidate_by_id()["STRAT0092"]
    signal = candidate_decisions(candidate, data)
    first = pd.Timestamp(signal.first_evaluable_date)
    assert first >= index[20]
    assert signal.decisions.loc[first] == -1


def test_financial_conditions_vote_uses_component_signs() -> None:
    base = _long_fixture()
    index = base.ledger.index
    data = PreparedMarketData(
        ledger=base.ledger,
        series={
            "NFCI": pd.Series(100.0, index=index),
            "ANFCI": pd.Series(-1.0, index=index),
            "OFR_FSI": pd.Series(-1.0, index=index),
        },
        available_dataset_ids=frozenset({"DS001", "DS002"}),
        rejected_datasets={},
        receipts=(),
        split="train",
    )
    candidate = _campaign().candidate_by_id()["STRAT0096"]
    signal = candidate_decisions(candidate, data)
    assert (signal.decisions == 1).all()


def test_under_specified_monetary_vote_is_rejected_precisely() -> None:
    base = _long_fixture()
    candidate = _campaign().candidate_by_id()["STRAT0126"]
    data = PreparedMarketData(
        ledger=base.ledger,
        series={
            name: pd.Series(1.0, index=base.ledger.index)
            for name in ("DFF", "CPI", "T10YIE", "WALCL", "M2")
        },
        available_dataset_ids=frozenset(candidate["required_datasets"]),
        rejected_datasets={},
        receipts=(),
        split="train",
    )
    with pytest.raises(
        CandidateRejected,
        match="INCOMPLETE_FROZEN_RULE_SPEC:INFLATION_ACCELERATION_HORIZON",
    ):
        candidate_decisions(candidate, data)


def test_preholiday_rule_does_not_treat_an_ordinary_weekend_as_a_holiday() -> None:
    data = _long_fixture()
    candidate = _campaign().candidate_by_id()["STRAT0143"]
    signal = candidate_decisions(candidate, data)
    index = data.ledger.index
    close = data.ledger["tr_close"]
    trend = close - close.rolling(200, min_periods=200).mean()
    next_dates = pd.Series(index, index=index).shift(-1)
    following_dates = next_dates.shift(-1)
    ordinary_friday = (
        (next_dates.dt.dayofweek == 4) & (following_dates.dt.dayofweek == 0) & (trend < 0)
    )
    assert ordinary_friday.any()
    assert (signal.decisions.loc[ordinary_friday] == -1).all()


def test_ensemble_uses_exact_frozen_component_ids_without_aliases() -> None:
    package = _campaign()
    candidate = package.candidate_by_id()["STRAT0027"]
    assert _frozen_component_ids(candidate) == (
        "STRAT0004",
        "STRAT0046",
        "STRAT0079",
        "STRAT0086",
    )
    assert candidate["parameters"]["components"] == [
        "SMA200",
        "BREAKOUT126",
        "CURVE",
        "CREDIT",
    ]


def test_ensemble_requires_registry_and_never_substitutes_aliases() -> None:
    base = _long_fixture()
    data = PreparedMarketData(
        ledger=base.ledger,
        series=base.series,
        available_dataset_ids=frozenset({"DS001", "DS002", "DS004", "DS009"}),
        rejected_datasets={},
        receipts=(),
        split="train",
    )
    candidate = _campaign().candidate_by_id()["STRAT0025"]
    with pytest.raises(
        CandidateRejected,
        match="ENSEMBLE_REQUIRES_FROZEN_CANDIDATE_REGISTRY",
    ):
        candidate_decisions(candidate, data)


def test_train_workload_evaluates_or_rejects_without_silent_drop() -> None:
    data = _long_fixture()
    package = _campaign()
    evaluated, records = TRAIN_WORKLOAD._evaluate(
        data,
        "STRAT0004",
        package.candidate_by_id()["STRAT0004"],
        "test-attempt",
    )
    rejected, rejected_records = TRAIN_WORKLOAD._evaluate(
        data,
        "STRAT0019",
        package.candidate_by_id()["STRAT0019"],
        "test-attempt",
    )
    assert evaluated["status"] == "evaluated"
    assert len(records) == 1
    assert evaluated["train_period_count"] >= 1000
    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"].startswith("DATA_GATE_REJECTED")
    assert rejected_records == ()


def test_campaign_partial_merge_waits_for_exact_coverage_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    data = _long_fixture()
    candidate = _campaign().candidate_by_id()["STRAT0004"]
    row, _ = TRAIN_WORKLOAD._evaluate(data, "STRAT0004", candidate, "merge-attempt-a")
    first = tmp_path / "first"
    first.mkdir()
    pq.write_table(
        pa.Table.from_pylist([row], schema=TRAIN_WORKLOAD.result_schema),
        first / TRAIN_WORKLOAD.result_filename,
    )
    partial = tmp_path / "partial"
    TRAIN_WORKLOAD.merge_group((first,), partial)
    assert (partial / TRAIN_WORKLOAD.result_filename).is_file()
    assert not (partial / "train_selection_freeze.json").exists()

    conflicting = dict(row)
    conflicting["source_attempt_id"] = "merge-attempt-b"
    conflicting["unit_output_sha256"] = "0" * 64
    second = tmp_path / "second"
    second.mkdir()
    pq.write_table(
        pa.Table.from_pylist([conflicting], schema=TRAIN_WORKLOAD.result_schema),
        second / TRAIN_WORKLOAD.result_filename,
    )
    with pytest.raises(ValueError, match="conflicting result for STRAT0004"):
        TRAIN_WORKLOAD.merge_group((first, second), tmp_path / "conflict")


def test_fixture_snapshot_round_trip_preserves_boundaries(tmp_path: Path) -> None:
    data = _long_fixture()
    write_fixture_snapshot(tmp_path, data.ledger)
    loaded = load_market_snapshot(tmp_path)
    assert loaded.split == "train"
    assert loaded.ledger.index.max() == pd.Timestamp("2010-12-31")
    assert loaded.available_dataset_ids == frozenset({"DS001", "DS002"})


def test_github_train_spec_passes_universal_preflight() -> None:
    report = validate_run_spec(REPO_ROOT / "config" / "sp500_long_short_daily_train_v3.yaml")
    assert report.valid, [item.model_dump() for item in report.violations]


def test_phase_workloads_are_bounded_and_have_exact_unit_counts() -> None:
    assert SMOKE_WORKLOAD.data_end == "1995-12-29"
    assert PILOT_WORKLOAD.data_end == "2010-12-31"
    assert TRAIN_WORKLOAD.data_end == "2010-12-31"
    assert len(SMOKE_WORKLOAD._unit_definitions()) == 7
    assert len(PILOT_WORKLOAD._unit_definitions()) == 23
    assert len(TRAIN_WORKLOAD._unit_definitions()) == 173
    assert {
        payload["family"]
        for _, payload, _ in PILOT_WORKLOAD._unit_definitions()
        if payload.get("unit_type") != "benchmark"
    } == set(PILOT_WORKLOAD.representative_families)


def test_every_frozen_family_is_implemented_or_has_a_precise_rejection() -> None:
    package_families = {row["family"] for row in _campaign().candidates}
    assert IMPLEMENTED_FAMILIES.isdisjoint(EXPLICIT_FAMILY_REJECTIONS)
    assert package_families == IMPLEMENTED_FAMILIES | set(EXPLICIT_FAMILY_REJECTIONS)


def test_effective_trial_count_collapses_identical_strategies() -> None:
    values = np.linspace(-0.01, 0.01, 200)
    identical = pd.DataFrame({"a": values, "b": values, "c": values})
    independent = pd.DataFrame(
        np.random.default_rng(20260803).normal(size=(2000, 3)),
        columns=["a", "b", "c"],
    )
    assert effective_independent_trials(identical) == pytest.approx(1.0)
    assert effective_independent_trials(independent) > 2.8


def test_stationary_bootstrap_and_fdr_are_deterministic_and_bounded() -> None:
    left = _stationary_bootstrap_indices(np.random.default_rng(7), 200, 10)
    right = _stationary_bootstrap_indices(np.random.default_rng(7), 200, 10)
    assert np.array_equal(left, right)
    assert int(left.min()) >= 0
    assert int(left.max()) < 200
    qvalues = _benjamini_hochberg({"a": 0.01, "b": 0.04, "c": 0.03})
    assert qvalues == pytest.approx({"a": 0.03, "c": 0.04, "b": 0.04})


def test_reality_check_uses_stationary_bootstrap_and_reports_ci_and_fdr() -> None:
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {
            "a": rng.normal(0.001, 0.01, 220),
            "b": rng.normal(0.0002, 0.01, 220),
        }
    )
    result = reality_check_and_spa(frame, seed=13, samples=80, block_lengths=(5,))
    assert result["bootstrap_method"] == "politis_romano_stationary_circular"
    assert set(result["candidate_fdr_qvalues"]) == {"a", "b"}
    assert set(result["candidate_mean_differential_ci_95"]) == {"a", "b"}
    assert all(len(bounds) == 2 for bounds in result["candidate_mean_differential_ci_95"].values())


def test_train_freeze_hash_and_code_are_verified(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1",
        "selection_closed": True,
        "validation_opened": False,
        "locked_opened": False,
        "train_end": "2010-12-31",
        "locked_start": "2021-01-01",
        "code_sha": "abc123",
        "finalists": [],
    }
    payload["freeze_sha256"] = canonical_json_hash(payload)
    path = tmp_path / "train_selection_freeze.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert verify_train_freeze(path, code_sha="abc123")["selection_closed"] is True
    with pytest.raises(ValidationGateError, match="CODE_SHA_MISMATCH"):
        verify_train_freeze(path, code_sha="different")
    payload["selection_closed"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationGateError, match="HASH_MISMATCH"):
        verify_train_freeze(path, code_sha="abc123")


def test_validation_ack_is_required_before_any_artifact_read(tmp_path: Path) -> None:
    with pytest.raises(ValidationGateError, match="VALIDATION_ACK_MISMATCH"):
        run_validation_once(
            train_results_dir=tmp_path / "missing-results",
            train_prepared_dir=tmp_path / "missing-train",
            validation_prepared_dir=tmp_path / "missing-validation",
            output_dir=tmp_path / "output",
            validation_ack=VALIDATION_ACK + "_WRONG",
        )


def test_phase_snapshots_combine_without_opening_locked() -> None:
    train = _long_fixture()
    validation_dates = pd.bdate_range("2011-01-03", "2020-12-31")
    close = 100.0 * np.exp(np.arange(len(validation_dates)) * 0.0001)
    prices = pd.DataFrame(
        {
            "date": validation_dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
        }
    )
    validation_ledger, _ = build_total_return_ledger(prices)
    validation = PreparedMarketData(
        ledger=validation_ledger,
        series={},
        available_dataset_ids=frozenset({"DS001", "DS002"}),
        rejected_datasets={},
        receipts=(),
        split="validation",
    )
    combined = combine_phase_snapshots(train, validation)
    assert combined.ledger.index.min() == train.ledger.index.min()
    assert combined.ledger.index.max() == pd.Timestamp("2020-12-31")
    assert combined.ledger.index.max() < pd.Timestamp("2021-01-01")


def test_one_shot_validation_outputs_only_frozen_candidate_and_2011_2020(
    tmp_path: Path,
) -> None:
    package = _campaign()
    candidate = package.candidate_by_id()["STRAT0004"]
    train_data = _long_fixture()
    train_root = tmp_path / "train-prepared"
    write_fixture_snapshot(train_root, train_data.ledger)

    dates = pd.bdate_range("2011-01-03", "2020-12-31")
    close = 100.0 * np.exp(np.arange(len(dates)) * 0.0002)
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
        }
    )
    validation_ledger, _ = build_total_return_ledger(prices)
    validation_root = tmp_path / "validation-prepared"
    write_fixture_snapshot(validation_root, validation_ledger, split="validation")

    freeze = {
        "schema_version": "1",
        "selection_closed": True,
        "validation_opened": False,
        "locked_opened": False,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "code_sha": "LOCAL_TEST_ONLY",
        "finalists": [
            {
                "strategy_id": candidate["strategy_id"],
                "canonical_hash": candidate["canonical_hash"],
                "diagnostic_only": False,
                "train_metrics": {"sharpe": 0.5, "calmar": 0.5},
            }
        ],
    }
    freeze["freeze_sha256"] = canonical_json_hash(freeze)
    train_results = tmp_path / "train-results"
    train_results.mkdir()
    (train_results / "train_selection_freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
    output = tmp_path / "validation-output"
    summary = run_validation_once(
        train_results_dir=train_results,
        train_prepared_dir=train_root,
        validation_prepared_dir=validation_root,
        output_dir=output,
        validation_ack=VALIDATION_ACK,
        code_sha="LOCAL_TEST_ONLY",
    )
    metrics = pd.read_csv(output / "validation_candidate_and_benchmark_metrics.csv")
    daily = pd.read_parquet(output / "validation_daily_returns.parquet")
    assert len(metrics) == 6
    assert set(metrics.loc[metrics["unit_type"] == "candidate", "strategy_id"]) == {"STRAT0004"}
    assert pd.to_datetime(daily["date"]).min() >= pd.Timestamp("2011-01-01")
    assert pd.to_datetime(daily["date"]).max() <= pd.Timestamp("2020-12-31")
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    assert (output / "final_manifest.json").is_file()


def test_workflow_exposes_fail_closed_one_shot_validation() -> None:
    path = REPO_ROOT / ".github" / "workflows" / "sp500-long-short-daily-campaign.yml"
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    assert parsed
    assert "validation_once" in text
    assert "OPEN_VALIDATION_2011_2020_ONCE" in text
    assert "train_selection_freeze.json" not in text or "train-results" in text
    assert "2021-01-01" not in text
    assert "C:\\" not in text
    assert "self-hosted" not in text
    assert "ubuntu-24.04" in text


def test_smoke_manifest_advertises_only_opened_train_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = yaml.safe_load(
        (REPO_ROOT / "config" / "sp500_long_short_daily_train_v3.yaml").read_text(encoding="utf-8")
    )
    payload["policy"]["policy_hash"] = "a" * 64
    spec = RunSpec.model_validate(payload)
    monkeypatch.setattr(
        SMOKE_WORKLOAD,
        "_prepare_dataset",
        lambda root: (("market_data_manifest.json",), "b" * 64),
    )
    prepared = SMOKE_WORKLOAD.prepare_shared_inputs(spec, tmp_path)
    manifest = pd.read_json(prepared.manifest_path, typ="series")
    assert manifest["campaign_phase"] == "smoke"
    assert manifest["max_date"] == "1995-12-29"
    assert manifest["validation_opened"] is False
    assert manifest["locked_opened"] is False


def test_smoke_reduction_cannot_create_train_freeze(tmp_path: Path) -> None:
    rows = []
    for key, payload, _ in SMOKE_WORKLOAD._unit_definitions():
        row = SMOKE_WORKLOAD._base_row(key, payload, "test-smoke")
        row["status"] = "rejected"
        row["rejection_reason"] = "TEST_REJECTION"
        from aurora.infra.github_performance.contracts import canonical_sha256

        row["unit_output_sha256"] = canonical_sha256(
            {name: value for name, value in row.items() if name != "source_attempt_id"}
        )
        rows.append(row)
    SMOKE_WORKLOAD._write_reduction(rows, tmp_path)
    summary = pd.read_json(tmp_path / "sp500_long_short_daily_smoke_summary.json", typ="series")
    assert summary["expected_units"] == 7
    assert summary["maximum_date"] == "1995-12-29"
    assert summary["validation_opened"] is False
    assert not (tmp_path / "train_selection_freeze.json").exists()


def test_full_coverage_reduction_keeps_every_terminal_unit(tmp_path: Path, monkeypatch) -> None:
    data = _long_fixture()
    write_fixture_snapshot(tmp_path, data.ledger)
    monkeypatch.setenv("AURORA_PREPARED_ROOT", str(tmp_path))
    definitions = TRAIN_WORKLOAD._unit_definitions()
    rows = []
    evaluated_keys = {
        "STRAT0001",
        *(key for key, _, _ in definitions if key.startswith("BENCHMARK::")),
    }
    for key, payload, _ in definitions:
        if key in evaluated_keys:
            row, _ = TRAIN_WORKLOAD._evaluate(data, key, payload, "test-reduction")
        else:
            row = TRAIN_WORKLOAD._base_row(key, payload, "test-reduction")
            row["status"] = "rejected"
            row["rejection_reason"] = "TEST_DISCLOSED_REJECTION"
            from aurora.infra.github_performance.contracts import canonical_sha256

            row["unit_output_sha256"] = canonical_sha256(
                {name: value for name, value in row.items() if name != "source_attempt_id"}
            )
        rows.append(row)
    output = tmp_path / "reduction"
    TRAIN_WORKLOAD._write_reduction(rows, output)
    summary = pd.read_json(output / "sp500_long_short_daily_train_summary.json", typ="series")
    eligibility = pd.read_csv(output / "eligibility_and_rejections.csv")
    assert len(eligibility) == 173
    assert int(summary["expected_candidates"]) == 168
    assert int(summary["expected_benchmarks"]) == 5
    assert (output / "train_selection_freeze.json").is_file()
    assert (output / "multiple_testing.json").is_file()
    required = {
        "RESULT_STATUS.md",
        "final_manifest.json",
        "candidate_and_benchmark_metrics.csv",
        "annual_returns.csv",
        "rolling_metrics.csv",
        "regime_metrics.csv",
        "fold_metrics.csv",
        "multiple_testing_results.json",
        "data_lineage.jsonl",
        "raw_manifest.jsonl",
        "scheduler_plan.json",
        "environment_lock.txt",
        "implementation_mapping.md",
        "official_source_audit.json",
    }
    assert required <= {path.name for path in output.iterdir()}
    final_manifest = json.loads((output / "final_manifest.json").read_text("utf-8"))
    assert final_manifest["validation_opened"] is False
    assert final_manifest["locked_opened"] is False
    assert set(final_manifest["files"]) >= required - {"final_manifest.json"}
    metrics = pd.read_csv(output / "candidate_and_benchmark_metrics.csv")
    assert len(metrics) == 173
    assert metrics["strategy_id"].nunique() == 173
    folds = pd.read_csv(output / "fold_metrics.csv")
    assert {
        "outer_fold_id",
        "outer_train_end",
        "outer_test_start",
        "outer_test_end",
        "embargo_sessions",
        "fit_mode",
        "out_of_fold",
    } <= set(folds.columns)
    assert set(folds["fit_mode"]) == {"static_rule_no_fit"}
    regimes = pd.read_csv(output / "regime_metrics.csv")
    assert set(regimes["status"]) == {"calculated"}
    assert set(regimes["regime"]) <= {
        "spy_above_sma200",
        "spy_at_or_below_sma200",
    }
    freeze = json.loads((output / "train_selection_freeze.json").read_text("utf-8"))
    assert freeze["position_contract"]["allowed_values"] == [-1, 1]
    assert freeze["costs"] == {
        "commission_bps": 0,
        "spread_bps": 0,
        "slippage_bps": 0,
        "market_impact_bps": 0,
        "borrow_bps": 0,
        "financing_bps": 0,
    }
