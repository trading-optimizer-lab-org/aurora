from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json

import numpy as np
import pandas as pd
import pytest

from aurora.research.openap_181.recovered_current_features import (
    RECOVERED_CURRENT_FEATURE_FORMULA_SHA256,
    RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID,
    RECOVERED_CURRENT_FEATURE_TARGETS,
    build_recovered_current_feature_observations,
    validate_recovered_current_feature_members,
)


SOURCE_AS_OF = "2026-08-08T16:00:00+00:00"
SEC_AVAILABLE_AT = "2026-07-31T20:00:00+00:00"
MARKET_RETRIEVED_AT = "2026-08-08T12:00:00+00:00"


EXISTING_TARGET_DEPENDENCIES = {
    "AM": (("assets", 0),),
    "BM": (("equity", 0),),
    "CashProd": (("assets", 0), ("cash", 0)),
    "CF": (("net_income", 0), ("depreciation", 0)),
    "cfp": (("operating_cash_flow", 0),),
    "EP": (("net_income", 0),),
    "Leverage": (("liabilities", 0),),
    "NetDebtPrice": (
        ("debt_current", 0),
        ("debt_long", 0),
        ("cash", 0),
    ),
    "NetPayoutYield": (
        ("dividends", 0),
        ("repurchases", 0),
        ("share_issuance", 0),
    ),
    "PayoutYield": (("dividends", 0), ("repurchases", 0)),
    "RD": (("rd", 0),),
    "SP": (("revenue", 0),),
    "AdExp": (("advertising", 0),),
}

NEXT_TARGET_DEPENDENCIES = {
    "AccrualsBM": (
        ("net_income", 0),
        ("operating_cash_flow", 0),
        ("assets", 1),
        ("equity", 0),
    ),
    "BMdec": (("equity", 0),),
    "EntMult": (
        ("operating_income", 0),
        ("depreciation", 0),
        ("cash", 0),
        ("debt_current", 0),
        ("debt_long", 0),
    ),
    "PS": (
        ("equity", 0),
        ("assets", 0),
        ("assets", 1),
        ("net_income", 0),
        ("net_income", 1),
        ("operating_cash_flow", 0),
        ("debt_long", 0),
        ("debt_long", 1),
        ("current_assets", 0),
        ("current_assets", 1),
        ("current_liabilities", 0),
        ("current_liabilities", 1),
        ("tax", 0),
        ("interest", 0),
        ("revenue", 0),
        ("revenue", 1),
        ("shares", 0),
        ("shares", 1),
    ),
}

SOURCE_TARGET_DEPENDENCIES = {
    **EXISTING_TARGET_DEPENDENCIES,
    **NEXT_TARGET_DEPENDENCIES,
}

NEXT_TARGET_FORMULA_SHA256 = {
    "AccrualsBM": "3d2504ee7c6da044cfb9cbe5da5abc6d2e126a917b22b65333bcd28cde08c1fa",
    "BMdec": "111bb8df1db87d92fb55ec4c070dc157281655afe80d9f54796ee4572f533d06",
    "EntMult": "3959786d1f35735633a840c626f3241384cc913f5d026435a02c85c0b44161d9",
    "PS": "2c47a2cefe19e28b8cae289b2f57fa14dd3baf9cd960ba74f75321b99d30ac56",
}

EXPECTED_TARGETS_AFTER_NEXT_SLICE = frozenset(SOURCE_TARGET_DEPENDENCIES)


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def _security_master() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_id": ["sec-aaa", "sec-bbb"],
            "symbol": ["AAA", "BBB"],
            "cik": [1, 2],
            "exchange_sec": ["Nasdaq", "NYSE"],
            "eligible_common_stock": [True, True],
            "issuer_primary_security": [True, True],
            "issuer_share_class_count": [1, 1],
            "ranking_eligible": [True, True],
            "source_sec": ["sec_company_tickers_exchange"] * 2,
            "retrieved_at_sec": ["2026-08-08T11:00:00Z"] * 2,
            "marketCap": [1_000_000_000.0, 2_000_000_000.0],
            "issuer_market_cap": [1_000_000_000.0, 2_000_000_000.0],
            "issuer_market_cap_source": [
                "yfinance_single_share_class_market_cap",
                "yfinance_single_share_class_market_cap",
            ],
            "retrieved_at_yahoo": [
                MARKET_RETRIEVED_AT,
                "2026-08-09T12:00:00Z",
            ],
        }
    )


def _feature_frame() -> pd.DataFrame:
    fillers = [
        f"Filler{index:03d}"
        for index in range(185 - len(SOURCE_TARGET_DEPENDENCIES))
    ]
    signals = list(SOURCE_TARGET_DEPENDENCIES) + fillers
    rows = []
    for symbol in ("AAA", "BBB"):
        for signal_index, signal in enumerate(signals):
            is_target = signal in SOURCE_TARGET_DEPENDENCIES
            rows.append(
                {
                    "as_of": "2026-08-08",
                    "symbol": symbol,
                    "signalname": signal,
                    "raw_value": (
                        float(signal_index + 1) / 100.0 if is_target else np.nan
                    ),
                    "status": "proxy" if is_target else "unavailable",
                    "implementation_status": (
                        "proxy" if is_target else "unavailable"
                    ),
                    "value_status": "available" if is_target else "missing",
                    "source": "sec_edgar" if is_target else "formula_not_implemented",
                    "formula_id": (
                        f"formula_{signal}" if is_target else ""
                    ),
                    "note": "current SEC reconstruction" if is_target else "",
                    "source_available_at": (
                        SEC_AVAILABLE_AT if is_target else pd.NaT
                    ),
                    "official_filter_pass": True,
                    "official_filter_status": "implemented",
                }
            )
    return pd.DataFrame(rows)


def _concept_inputs() -> pd.DataFrame:
    dependencies = sorted(
        {
            dependency
            for values in SOURCE_TARGET_DEPENDENCIES.values()
            for dependency in values
        }
    )
    rows = []
    for symbol, cik in (("AAA", 1), ("BBB", 2)):
        for index, (concept, lag) in enumerate(dependencies):
            period_year = 2025 - lag
            filed_year = 2026 - lag
            available_at = (
                SEC_AVAILABLE_AT
                if lag == 0
                else f"{filed_year}-07-31T20:00:00+00:00"
            )
            rows.append(
                {
                    "symbol": symbol,
                    "cik": cik,
                    "concept": concept,
                    "concept_lag": lag,
                    "tag": f"Tag{concept}",
                    "taxonomy": "us-gaap",
                    "unit": "USD",
                    "value": float(index + 1),
                    "period_start": f"{period_year}-01-01",
                    "period_end": f"{period_year}-12-31",
                    "fy": period_year,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": f"{filed_year}-07-31",
                    "accession_number": f"0000000000-26-{index:06d}",
                    "available_at": available_at,
                    "available_at_quality": "accepted_timestamp",
                    "source": "sec_companyfacts",
                    "source_mode": "sec_official_live",
                }
            )
    return pd.DataFrame(rows)


def _coverage(features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for signal, group in features.groupby("signalname", sort=True):
        proxy_rows = int(
            (group["raw_value"].notna() & group["status"].eq("proxy")).sum()
        )
        exact_rows = int(
            (group["raw_value"].notna() & group["status"].eq("exact")).sum()
        )
        rows.append(
            {
                "signalname": signal,
                "data_family": "Accounting",
                "economic_family": "Value",
                "coverage_status": "proxy" if proxy_rows else "unavailable",
                "symbols_with_value": exact_rows + proxy_rows,
                "total_symbols": 2,
                "coverage_pct": 50.0 * (exact_rows + proxy_rows),
                "exact_rows": exact_rows,
                "proxy_rows": proxy_rows,
                "unavailable_rows": 2 - exact_rows - proxy_rows,
                "value_sources": "sec_edgar" if proxy_rows else "",
                "unavailable_reasons": "" if proxy_rows else "formula_not_implemented",
                "notes": "current SEC reconstruction" if proxy_rows else "",
                "formula_ids": (
                    f"formula_{signal}" if proxy_rows else ""
                ),
            }
        )
    return pd.DataFrame(rows)


def _members(
    *,
    features: pd.DataFrame | None = None,
    concepts: pd.DataFrame | None = None,
    security_master: pd.DataFrame | None = None,
) -> dict[str, bytes]:
    feature_frame = features if features is not None else _feature_frame()
    concept_frame = concepts if concepts is not None else _concept_inputs()
    security_frame = (
        security_master if security_master is not None else _security_master()
    )
    summary = {
        "as_of": SOURCE_AS_OF,
        "input_predictors": 185,
        "eligible_symbols": 2,
        "security_master_rows": 2,
        "coverage_rows": 185,
        "features_rows": 370,
        "sec_concept_input_rows": len(concept_frame),
        "all_facts_have_available_at": True,
        "concept_inputs_without_available_at": 0,
        "future_concept_inputs": 0,
        "concept_inputs_before_period_end": 0,
        "concept_inputs_before_filed": 0,
        "invalid_concept_units": 0,
        "inconsistent_feature_status": 0,
        "unsupported_official_filters": 0,
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": False,
        "database_contract_violations": 0,
    }
    payloads = {
        "security_master.parquet": _parquet_bytes(security_frame),
        "execution_summary.json": (
            json.dumps(summary, sort_keys=True).encode("utf-8")
        ),
        "openap_features_current.parquet": _parquet_bytes(feature_frame),
        "coverage_185.csv": _coverage(feature_frame).to_csv(index=False).encode(
            "utf-8"
        ),
        "sec_concept_inputs_current.parquet": _parquet_bytes(concept_frame),
    }
    manifest = pd.DataFrame(
        [
            {
                "file": name,
                "bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
            }
            for name, payload in payloads.items()
        ]
    )
    return {
        **payloads,
        "output_manifest.csv": manifest.to_csv(index=False).encode("utf-8"),
    }


def test_recovered_feature_bundle_is_hash_grid_and_coverage_bound() -> None:
    bundle = validate_recovered_current_feature_members(_members())

    assert bundle.evidence["input_predictors"] == 185
    assert bundle.evidence["eligible_symbols"] == 2
    assert bundle.evidence["features_rows"] == 370
    assert bundle.evidence["coverage_rows"] == 185
    assert bundle.evidence["target_signal_count"] == 17
    assert set(RECOVERED_CURRENT_FEATURE_FORMULA_SHA256) == set(
        RECOVERED_CURRENT_FEATURE_TARGETS
    )
    assert all(
        len(value) == 64
        for value in RECOVERED_CURRENT_FEATURE_FORMULA_SHA256.values()
    )
    assert set(bundle.features["signalname"]) == set(bundle.coverage["signalname"])


def test_next_accounting_slice_is_explicit_and_preserves_proxy_fidelity() -> None:
    bundle = validate_recovered_current_feature_members(_members())
    observations = build_recovered_current_feature_observations(bundle)

    assert bundle.evidence["target_signal_count"] == 17
    assert set(bundle.evidence["target_signals"]) == EXPECTED_TARGETS_AFTER_NEXT_SLICE
    assert len(observations) == 34
    assert set(observations["signal"]) == EXPECTED_TARGETS_AFTER_NEXT_SLICE
    assert {
        signal: RECOVERED_CURRENT_FEATURE_FORMULA_SHA256.get(signal)
        for signal in NEXT_TARGET_FORMULA_SHA256
    } == NEXT_TARGET_FORMULA_SHA256

    aaa = observations.loc[observations["ticker"].eq("AAA")].set_index("signal")
    assert aaa.loc["AccrualsBM", "fidelity_class"] == "unvalidated_proxy"
    assert aaa.loc["BMdec", "fidelity_class"] == "unvalidated_proxy"
    assert aaa.loc["EntMult", "fidelity_class"] == "reconstructed"
    assert aaa.loc["PS", "fidelity_class"] == "reconstructed"
    assert aaa.loc[
        list(NEXT_TARGET_DEPENDENCIES), "current_usable"
    ].eq(True).all()  # noqa: E712
    assert aaa.loc[
        list(NEXT_TARGET_DEPENDENCIES), "strict_score_eligible"
    ].eq(False).all()  # noqa: E712


def test_next_accounting_slice_requires_every_lagged_sec_dependency() -> None:
    concepts = _concept_inputs()
    concepts = concepts.loc[
        ~(
            concepts["symbol"].eq("AAA")
            & concepts["concept"].eq("assets")
            & concepts["concept_lag"].eq(1)
        )
    ].copy()

    with pytest.raises(ValueError, match="required SEC dependency"):
        validate_recovered_current_feature_members(_members(concepts=concepts))


def test_next_accounting_slice_rejects_dependency_availability_drift() -> None:
    concepts = _concept_inputs()
    concepts.loc[
        concepts["symbol"].eq("AAA")
        & concepts["concept"].eq("shares")
        & concepts["concept_lag"].eq(1),
        "available_at",
    ] = "2026-08-01T20:00:00+00:00"

    with pytest.raises(ValueError, match="SEC dependency timestamp"):
        validate_recovered_current_feature_members(_members(concepts=concepts))


def test_recovered_feature_bundle_rejects_tampering_and_incomplete_grid() -> None:
    tampered = _members()
    tampered["openap_features_current.parquet"] += b"tampered"
    with pytest.raises(ValueError, match="output manifest.*SHA-256"):
        validate_recovered_current_feature_members(tampered)

    incomplete = _feature_frame().iloc[:-1].copy()
    with pytest.raises(ValueError, match="feature grid"):
        validate_recovered_current_feature_members(_members(features=incomplete))


def test_recovered_feature_bundle_rejects_dependency_timestamp_drift() -> None:
    concepts = _concept_inputs()
    concepts.loc[
        concepts["symbol"].eq("AAA") & concepts["concept"].eq("assets"),
        "available_at",
    ] = "2026-08-01T20:00:00Z"

    with pytest.raises(ValueError, match="SEC dependency timestamp"):
        validate_recovered_current_feature_members(_members(concepts=concepts))


def test_current_feature_observations_keep_source_as_of_and_fail_closed() -> None:
    bundle = validate_recovered_current_feature_members(_members())
    observations = build_recovered_current_feature_observations(bundle)

    assert len(observations) == 34
    assert set(observations["signal"]) == set(
        RECOVERED_CURRENT_FEATURE_TARGETS
    )
    assert observations["formation_at"].eq(pd.Timestamp(SOURCE_AS_OF)).all()
    assert observations["strict_score_eligible"].eq(False).all()  # noqa: E712
    assert observations["historical_ticker_interval_verified"].eq(False).all()  # noqa: E712
    assert observations["source_run_id"].eq(
        RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID
    ).all()

    aaa = observations.loc[observations["ticker"].eq("AAA")]
    assert len(aaa) == 17
    assert aaa["current_usable"].eq(True).all()  # noqa: E712
    assert aaa["value"].notna().all()
    assert pd.to_datetime(aaa["available_at"], utc=True).eq(
        pd.Timestamp(MARKET_RETRIEVED_AT)
    ).all()
    assert aaa.loc[
        ~aaa["signal"].isin({"AccrualsBM", "BMdec"}), "fidelity_class"
    ].eq("reconstructed").all()
    assert aaa.loc[
        aaa["signal"].isin({"AccrualsBM", "BMdec"}), "fidelity_class"
    ].eq("unvalidated_proxy").all()
    assert aaa["official_formula_sha256"].str.fullmatch(
        r"[0-9a-f]{64}"
    ).all()
    assert aaa["source_id"].str.contains(
        "recovered_openap_features_31270341796", regex=False
    ).all()

    bbb = observations.loc[observations["ticker"].eq("BBB")]
    assert len(bbb) == 17
    assert bbb["current_usable"].eq(False).all()  # noqa: E712
    assert bbb["value"].isna().all()
    assert bbb["reason_if_missing"].eq("market_cap_lookahead").all()


def test_official_filter_exclusion_never_survives_as_a_current_value() -> None:
    features = _feature_frame()
    mask = features["symbol"].eq("AAA") & features["signalname"].eq("EP")
    features.loc[mask, "official_filter_pass"] = False
    features.loc[mask, "status"] = "unavailable"
    features.loc[mask, "value_status"] = "official_filter_excluded"
    bundle = validate_recovered_current_feature_members(_members(features=features))

    observations = build_recovered_current_feature_observations(bundle)
    ep = observations.loc[
        observations["ticker"].eq("AAA") & observations["signal"].eq("EP")
    ].iloc[0]

    assert pd.isna(ep["value"])
    assert ep["current_usable"] is False or ep["current_usable"] == False  # noqa: E712
    assert ep["reason_if_missing"] == "official_filter_excluded"


def test_mixed_accounting_periods_fail_closed_without_rejecting_other_rows() -> None:
    concepts = _concept_inputs()
    mismatch = concepts["symbol"].eq("AAA") & concepts["concept"].eq(
        "depreciation"
    )
    concepts.loc[mismatch, "period_end"] = "2024-12-31"
    bundle = validate_recovered_current_feature_members(_members(concepts=concepts))

    observations = build_recovered_current_feature_observations(bundle)
    cf = observations.loc[
        observations["ticker"].eq("AAA") & observations["signal"].eq("CF")
    ].iloc[0]
    am = observations.loc[
        observations["ticker"].eq("AAA") & observations["signal"].eq("AM")
    ].iloc[0]

    assert pd.isna(cf["value"])
    assert cf["reason_if_missing"] == "sec_dependency_period_mismatch"
    assert am["current_usable"] is True or am["current_usable"] == True  # noqa: E712
