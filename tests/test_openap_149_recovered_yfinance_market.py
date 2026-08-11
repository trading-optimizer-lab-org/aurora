from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research.openap_181.recovered_yfinance_market import (
    RECOVERED_YFINANCE_PRICE_COLUMNS,
    RECOVERED_YFINANCE_SOURCE_RUN_ID,
    build_recovered_yfinance_bars,
    validate_recovered_yfinance_price_shard,
    validate_recovered_yfinance_source,
    validate_yfinance_source_manifest,
)
from aurora.research.openap_181.recovered_yfinance_extended_signals import (
    RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS,
    calculate_recovered_yfinance_extended_signals,
    parse_pastor_stambaugh_liquidity,
)
from aurora.research.openap_181.twelve_data_market_signals import (
    calculate_twelve_data_direct_signals,
)
from aurora.research.openap_181.twelve_data_factor_signals import (
    calculate_twelve_data_factor_signals,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_HEAD_SHA = "af8c622fc8f0c3789bda539dd14e0b3a52f37187"
FORMATION_AT = "2026-08-09T23:59:59Z"
RETRIEVED_AT = "2026-08-08T12:09:28.273707+00:00"
SOURCE_ID = f"recovered_yfinance_artifacts_{RECOVERED_YFINANCE_SOURCE_RUN_ID}"
SOURCE_URL = (
    "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
    f"{RECOVERED_YFINANCE_SOURCE_RUN_ID}"
)


def _source_run() -> dict[str, object]:
    return {
        "id": RECOVERED_YFINANCE_SOURCE_RUN_ID,
        "status": "completed",
        "conclusion": "failure",
        "head_sha": SOURCE_HEAD_SHA,
        "path": ".github/workflows/openap-yfinance-sec-current-score.yml",
    }


def _source_jobs() -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = [
        {
            "name": "prepare",
            "conclusion": "success",
            "steps": [
                {"name": "Validate prepare outputs", "conclusion": "success"},
            ],
        }
    ]
    for chunk in range(48):
        jobs.append(
            {
                "name": f"yfinance ({chunk})",
                "conclusion": "success",
                "steps": [
                    {
                        "name": "Download YFinance history and current snapshots",
                        "conclusion": "success",
                    },
                    {
                        "name": "Run actions/upload-artifact@pinned",
                        "conclusion": "success",
                    },
                ],
            }
        )
    jobs.append({"name": "full_pipeline", "conclusion": "failure", "steps": []})
    return jobs


def _artifacts() -> list[dict[str, object]]:
    return [
        {
            "id": 9_021_577_506 + chunk,
            "name": f"openap-yfinance-{chunk}",
            "size_in_bytes": 12_000_000 + chunk,
            "expired": False,
        }
        for chunk in range(48)
    ]


def _price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-08-06", "2026-08-07", "2026-08-06", "2026-08-07"]
            ),
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "open": [10.0, 11.0, 20.0, 21.0],
            "high": [11.0, 12.0, 21.0, 22.0],
            "low": [9.0, 10.0, 19.0, 20.0],
            "close": [10.0, 11.0, 20.0, 21.0],
            "adj_close": [8.0, 8.8, 20.0, 21.0],
            "volume": [100.0, 110.0, 200.0, 210.0],
            "dividends": [0.0, 0.2, 0.0, 0.0],
            "stock_splits": [0.0, 0.0, 0.0, 0.0],
            "source": ["yfinance"] * 4,
            "retrieved_at": [RETRIEVED_AT] * 4,
        }
    )


def _price_payload(frame: pd.DataFrame | None = None) -> bytes:
    buffer = BytesIO()
    (frame if frame is not None else _price_frame()).to_parquet(buffer, index=False)
    return buffer.getvalue()


def _manifest_frame(payload: bytes) -> pd.DataFrame:
    rows = []
    for chunk in range(48):
        rows.append(
            {
                "chunk_index": chunk,
                "total_chunks": 48,
                "symbols_expected": 2,
                "symbols_with_prices": 2,
                "price_rows": 4,
                "metadata_rows": 2,
                "analyst_snapshots": 0,
                "option_rows": 0,
                "retrieved_at": RETRIEVED_AT,
                "prices_sha256": sha256(payload).hexdigest(),
                "metadata_sha256": "1" * 64,
                "options_sha256": "2" * 64,
                "analyst_sha256": "3" * 64,
                "status_sha256": "4" * 64,
                "summary_sha256": "5" * 64,
            }
        )
    return pd.DataFrame(rows)


def _accepted_universe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_id": ["sec-aaa", "sec-bbb"],
            "ticker": ["AAA", "BBB"],
            "cik": ["0000000001", "0000000002"],
        }
    )


def test_recovered_source_requires_exact_successful_48_shard_evidence() -> None:
    verified = validate_recovered_yfinance_source(
        _source_run(),
        _source_jobs(),
        _artifacts(),
    )

    assert verified["source_run_id"] == RECOVERED_YFINANCE_SOURCE_RUN_ID
    assert verified["source_head_sha"] == SOURCE_HEAD_SHA
    assert verified["artifact_count"] == 48
    assert [row["chunk_index"] for row in verified["artifacts"]] == list(range(48))

    missing_artifact = _artifacts()[:-1]
    with pytest.raises(ValueError, match="exactly 48"):
        validate_recovered_yfinance_source(
            _source_run(), _source_jobs(), missing_artifact
        )

    bad_jobs = _source_jobs()
    bad_jobs[10] = {**bad_jobs[10], "conclusion": "failure"}
    with pytest.raises(ValueError, match="successful yfinance jobs"):
        validate_recovered_yfinance_source(_source_run(), bad_jobs, _artifacts())


def test_source_manifest_and_price_shard_are_hash_and_row_bound() -> None:
    payload = _price_payload()
    manifest = validate_yfinance_source_manifest(
        _manifest_frame(payload).to_csv(index=False).encode("utf-8")
    )
    artifact = _artifacts()[0]

    frame, evidence = validate_recovered_yfinance_price_shard(
        artifact,
        payload,
        manifest.iloc[0],
    )

    assert tuple(frame.columns) == RECOVERED_YFINANCE_PRICE_COLUMNS
    assert evidence["chunk_index"] == 0
    assert evidence["price_rows"] == 4
    assert evidence["symbols_with_prices"] == 2
    assert evidence["prices_sha256"] == sha256(payload).hexdigest()

    tampered = _price_frame()
    tampered.loc[0, "close"] = 99.0
    with pytest.raises(ValueError, match="SHA-256"):
        validate_recovered_yfinance_price_shard(
            artifact,
            _price_payload(tampered),
            manifest.iloc[0],
        )

    quarantined = _price_frame()
    quarantined.loc[0, "high"] = np.nan
    quarantined_payload = _price_payload(quarantined)
    quarantined_manifest = validate_yfinance_source_manifest(
        _manifest_frame(quarantined_payload).to_csv(index=False).encode("utf-8")
    )
    cleaned, quarantine_evidence = validate_recovered_yfinance_price_shard(
        artifact,
        quarantined_payload,
        quarantined_manifest.iloc[0],
    )
    assert len(cleaned) == 3
    assert quarantine_evidence["accepted_price_rows"] == 3
    assert quarantine_evidence["quarantined_price_rows"] == 1


def test_recovered_prices_build_two_causal_non_strict_adjustment_modes() -> None:
    bars, rejected = build_recovered_yfinance_bars(
        [_price_frame()],
        _accepted_universe(),
        formation_at=FORMATION_AT,
        source_run_id=RECOVERED_YFINANCE_SOURCE_RUN_ID,
    )

    assert rejected.empty
    assert set(bars["adjust"]) == {"all", "none"}
    assert len(bars) == 8
    assert bars["source_id"].eq(SOURCE_ID).all()
    assert bars["strict_score_eligible"].eq(False).all()  # noqa: E712
    assert bars["historical_ticker_interval_verified"].eq(False).all()  # noqa: E712
    assert pd.to_datetime(bars["available_at"], utc=True).le(
        pd.Timestamp(FORMATION_AT)
    ).all()

    aaa_latest = bars.loc[
        bars["security_id"].eq("sec-aaa")
        & bars["date"].eq(pd.Timestamp("2026-08-07"))
    ].set_index("adjust")
    assert aaa_latest.loc["none", "close"] == pytest.approx(11.0)
    assert aaa_latest.loc["all", "close"] == pytest.approx(8.8)
    assert aaa_latest.loc["all", "high"] == pytest.approx(9.6)
    assert aaa_latest.loc["all", "low"] == pytest.approx(8.0)
    assert aaa_latest.loc["all", "volume"] == pytest.approx(110.0)


def test_recovered_prices_reject_current_universe_members_without_history() -> None:
    universe = pd.concat(
        [
            _accepted_universe(),
            pd.DataFrame(
                {
                    "security_id": ["sec-ccc"],
                    "ticker": ["CCC"],
                    "cik": ["0000000003"],
                }
            ),
        ],
        ignore_index=True,
    )

    bars, rejected = build_recovered_yfinance_bars(
        [_price_frame()],
        universe,
        formation_at=FORMATION_AT,
        source_run_id=RECOVERED_YFINANCE_SOURCE_RUN_ID,
    )

    assert set(bars["security_id"]) == {"sec-aaa", "sec-bbb"}
    assert rejected.to_dict("records") == [
        {
            "symbol": "CCC",
            "reason": "no_recovered_price_history",
            "strict_score_eligible": False,
        }
    ]


def test_direct_calculator_preserves_recovered_provider_provenance() -> None:
    dates = pd.bdate_range("2025-06-02", "2026-08-07")
    prices = pd.DataFrame(
        {
            "date": dates,
            "symbol": "AAA",
            "open": np.linspace(10.0, 20.0, len(dates)),
            "high": np.linspace(10.5, 20.5, len(dates)),
            "low": np.linspace(9.5, 19.5, len(dates)),
            "close": np.linspace(10.0, 20.0, len(dates)),
            "adj_close": np.linspace(9.0, 19.0, len(dates)),
            "volume": np.linspace(1000.0, 2000.0, len(dates)),
            "dividends": 0.0,
            "stock_splits": 0.0,
            "source": "yfinance",
            "retrieved_at": RETRIEVED_AT,
        }
    )
    bars, _ = build_recovered_yfinance_bars(
        [prices],
        _accepted_universe().iloc[[0]],
        formation_at=FORMATION_AT,
        source_run_id=RECOVERED_YFINANCE_SOURCE_RUN_ID,
    )

    values = calculate_twelve_data_direct_signals(
        bars,
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
        source_label="recovered yfinance artifact",
    )

    assert not values.empty
    assert values["source_id"].eq(SOURCE_ID).all()
    assert values["source_url"].eq(SOURCE_URL).all()
    assert values["caveat"].str.contains("recovered yfinance artifact").all()
    assert values["strict_score_eligible"].eq(False).all()  # noqa: E712

    ff3_daily = pd.DataFrame(
        {
            "date": dates,
            "mktrf": np.linspace(-0.01, 0.01, len(dates)),
            "smb": np.sin(np.arange(len(dates)) / 7.0) / 100.0,
            "hml": np.cos(np.arange(len(dates)) / 8.0) / 100.0,
            "rf": 0.0001,
        }
    )
    months = pd.period_range("2025-06", "2026-07", freq="M")
    ff3_monthly = pd.DataFrame(
        {
            "date": months.to_timestamp("M"),
            "mktrf": np.linspace(-0.03, 0.04, len(months)),
            "smb": np.sin(np.arange(len(months)) / 3.0) / 100.0,
            "hml": np.cos(np.arange(len(months)) / 4.0) / 100.0,
            "rf": 0.001,
        }
    )
    factor_values = calculate_twelve_data_factor_signals(
        bars,
        ff3_daily,
        ff3_monthly,
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
        source_label="recovered yfinance artifact",
    )
    assert not factor_values.empty
    assert factor_values["source_id"].eq(f"{SOURCE_ID}|kenneth_french").all()
    assert factor_values["source_url"].str.startswith(SOURCE_URL, na=False).all()
    assert factor_values["caveat"].str.contains(
        "recovered yfinance artifact", regex=False
    ).all()
    assert factor_values["strict_score_eligible"].eq(False).all()  # noqa: E712


def test_manual_workflow_reuses_artifacts_without_new_yahoo_or_twelve_calls() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-recovered-yfinance-market.yml"
    ).read_text(encoding="utf-8")
    runner = (
        ROOT / "scripts" / "run_openap_149_recovered_yfinance_market.py"
    ).read_text(encoding="utf-8")
    recovery = (
        ROOT / "scripts" / "recover_openap_yfinance_price_shards.py"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert 'default: "31256096194"' in workflow
    assert 'default: "31388342037"' in workflow
    assert "github.event.repository.private" in workflow
    assert "QF_DATA_DIR" in workflow
    assert "TWELVE_DATA_API_KEY" not in workflow
    assert "query1.finance.yahoo.com" not in workflow
    assert "download.finance.yahoo.com" not in workflow
    assert "openap-yfinance-*" in recovery
    assert "prices_{chunk_index:03d}.parquet" in recovery
    assert "calculate_twelve_data_direct_signals" in runner
    assert "calculate_twelve_data_factor_signals" in runner
    assert "calculate_recovered_yfinance_extended_signals" in runner
    assert '"covered_security_rows"' in runner
    assert "strict_score_eligible" in runner


def test_official_pastor_stambaugh_text_parser_is_causal_and_frozen() -> None:
    payload = b"""% LIQUIDITY FACTORS OF PASTOR AND STAMBAUGH
202509  0.01000000  -0.02000000  0.03000000
202510  0.02000000   0.01000000  0.04000000
202511 -0.01000000   0.03000000  0.05000000
"""

    parsed = parse_pastor_stambaugh_liquidity(
        payload,
        formation_at="2025-12-31T23:59:59Z",
    )

    assert list(parsed.columns) == [
        "month",
        "aggregate_liquidity",
        "ps_innov",
        "traded_liquidity",
    ]
    assert len(parsed) == 3
    assert parsed["month"].max() == pd.Period("2025-11", freq="M")
    october = parsed.loc[
        parsed["month"].eq(pd.Period("2025-10", freq="M")),
        "ps_innov",
    ].iloc[0]
    assert october == pytest.approx(0.01)


def test_extended_recovered_panel_emits_all_eight_non_strict_targets() -> None:
    dates = pd.bdate_range("2021-01-04", "2025-11-28")
    synthetic_retrieved_at = "2025-12-01T05:00:00Z"
    bar_parts = []
    context_rows = []
    for index in range(15):
        ticker = f"T{index:02d}"
        security_id = f"sec-{ticker.lower()}"
        base = 10.0 + index + np.linspace(0.0, 8.0, len(dates))
        close = base * (1.0 + 0.01 * np.sin(np.arange(len(dates)) / (9.0 + index)))
        bar_parts.append(
            pd.DataFrame(
                {
                    "security_id": security_id,
                    "ticker": ticker,
                    "cik": f"{index + 1:010d}",
                    "adjust": "all",
                    "date": dates,
                    "open": close * 0.995,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000.0 + index * 20_000.0,
                    "available_at": pd.Timestamp("2025-12-01T05:00:00Z"),
                    "retrieved_at": pd.Timestamp(synthetic_retrieved_at),
                    "source_id": SOURCE_ID,
                    "historical_ticker_interval_verified": False,
                    "strict_score_eligible": False,
                }
            )
        )
        context_rows.append(
            {
                "security_id": security_id,
                "ticker": ticker,
                "cik": f"{index + 1:010d}",
                "exchange_sec": "Nasdaq" if index else "NYSE",
                "industry": f"industry-{index % 3}",
                "issuer_market_cap": 500_000_000.0 * (index + 1),
                "sharesOutstanding": 50_000_000.0 + index * 1_000_000.0,
                "first_price_date": dates.min(),
            }
        )
    adjusted_bars = pd.concat(bar_parts, ignore_index=True)
    nominal_bars = adjusted_bars.copy()
    nominal_bars["adjust"] = "none"
    bars = pd.concat([adjusted_bars, nominal_bars], ignore_index=True)
    context = pd.DataFrame(context_rows)
    factor_months = pd.period_range("2021-01", "2025-11", freq="M")
    ff3 = pd.DataFrame(
        {
            "date": factor_months.to_timestamp("M"),
            "mktrf": np.linspace(-0.03, 0.04, len(factor_months)),
            "smb": np.sin(np.arange(len(factor_months)) / 5.0) / 100.0,
            "hml": np.cos(np.arange(len(factor_months)) / 6.0) / 100.0,
            "rf": 0.001,
        }
    )
    liquidity = pd.DataFrame(
        {
            "month": factor_months,
            "aggregate_liquidity": 0.0,
            "ps_innov": np.sin(np.arange(len(factor_months)) / 4.0) / 100.0,
            "traded_liquidity": 0.0,
        }
    )

    values = calculate_recovered_yfinance_extended_signals(
        bars,
        context,
        ff3,
        liquidity,
        formation_at="2025-12-31T23:59:59Z",
        retrieved_at=synthetic_retrieved_at,
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
    )

    assert len(values) == len(context) * len(RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS)
    assert set(values["signal"]) == set(RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS)
    assert values["strict_score_eligible"].eq(False).all()  # noqa: E712
    assert values["source_id"].str.contains(SOURCE_ID, regex=False).all()
    latest_nominal_close = (
        bars.loc[
            bars["security_id"].eq("sec-t00") & bars["adjust"].eq("none")
        ]
        .sort_values("date")["close"]
        .iloc[-1]
    )
    expected_size = np.log(
        context.loc[0, "sharesOutstanding"] * latest_nominal_close
    )
    actual_size = values.loc[
        values["security_id"].eq("sec-t00") & values["signal"].eq("Size"),
        "value",
    ].iloc[0]
    assert actual_size == pytest.approx(expected_size)
