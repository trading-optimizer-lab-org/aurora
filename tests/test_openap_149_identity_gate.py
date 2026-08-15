from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest


def _module():
    return importlib.import_module("aurora.research.openap_149.identity_gate")


def _valid_bridge() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "canonical_security_id": ["sec:a", "sec:b", "sec:c"],
            "permno": [10001, 10002, 10003],
            "valid_from": ["2023-01-01"] * 3,
            "valid_to": ["2024-12-31"] * 3,
            "share_class_id": ["A", "A", "A"],
            "evidence_url": ["https://example.org/direct"] * 3,
            "evidence_kind": ["direct_identifier_history"] * 3,
            "source_id": ["public_direct_history"] * 3,
            "source_retrieved_at": ["2026-08-15T00:00:00Z"] * 3,
            "source_sha256": ["a" * 64, "b" * 64, "c" * 64],
            "zero_cost_authorized": [True] * 3,
        }
    )


def _reference_spine() -> pd.DataFrame:
    rows = []
    for month in pd.period_range("2023-01", "2024-12", freq="M"):
        for permno in (10001, 10002, 10003, 10004):
            rows.append({"permno": permno, "yyyymm": month.strftime("%Y%m")})
    return pd.DataFrame(rows)


def test_bridge_rejects_ticker_only_and_target_derived_evidence() -> None:
    module = _module()
    with pytest.raises(module.IdentityGateError, match="canonical_security_id"):
        module.validate_bridge(pd.DataFrame({"ticker": ["AAA"], "permno": [10001]}))

    frame = _valid_bridge()
    frame["evidence_kind"] = "openap_characteristic_match"
    with pytest.raises(module.IdentityGateError, match="target-derived"):
        module.validate_bridge(frame)


def test_bridge_rejects_overlapping_many_to_one_intervals() -> None:
    module = _module()
    frame = pd.concat([_valid_bridge(), _valid_bridge().iloc[[0]]], ignore_index=True)
    frame.loc[3, "canonical_security_id"] = "sec:other"
    frame.loc[3, "source_sha256"] = "d" * 64

    with pytest.raises(module.IdentityGateError, match="overlap"):
        module.validate_bridge(frame)


def test_bridge_rejects_non_free_and_invalid_hash() -> None:
    module = _module()
    frame = _valid_bridge()
    frame.loc[0, "zero_cost_authorized"] = False
    with pytest.raises(module.IdentityGateError, match="zero-cost"):
        module.validate_bridge(frame)

    frame = _valid_bridge()
    frame.loc[0, "source_sha256"] = "not-a-hash"
    with pytest.raises(module.IdentityGateError, match="SHA-256"):
        module.validate_bridge(frame)


def test_freeze_is_stable_across_input_row_order(tmp_path: Path) -> None:
    module = _module()
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    manifest_a = module.freeze_bridge(_valid_bridge(), first)
    manifest_b = module.freeze_bridge(
        _valid_bridge().sample(frac=1.0, random_state=7), second
    )

    assert manifest_a.bridge_sha256 == manifest_b.bridge_sha256
    assert manifest_a.rows == 3
    assert manifest_a.frozen_before_reference_read is True
    assert first.read_bytes() == second.read_bytes()


def test_coverage_requires_every_month_and_seventy_percent(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "bridge.parquet"
    manifest = module.freeze_bridge(_valid_bridge(), output)
    frozen = pd.read_parquet(output)

    decision = module.evaluate_bridge_coverage(
        frozen, _reference_spine(), manifest=manifest
    )

    assert decision.minimum_monthly_coverage == pytest.approx(0.75)
    assert decision.median_monthly_coverage == pytest.approx(0.75)
    assert decision.ambiguous_links == 0
    assert decision.required_months == 24
    assert decision.status == "pass"


def test_coverage_fails_if_one_month_is_below_threshold(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "bridge.parquet"
    manifest = module.freeze_bridge(_valid_bridge(), output)
    reference = _reference_spine()
    extra = pd.DataFrame(
        {"permno": range(20000, 20020), "yyyymm": ["202401"] * 20}
    )

    decision = module.evaluate_bridge_coverage(
        pd.read_parquet(output),
        pd.concat([reference, extra], ignore_index=True),
        manifest=manifest,
    )

    assert decision.minimum_monthly_coverage < 0.70
    assert decision.status == "blocked_identity"


def test_coverage_rejects_unfrozen_bridge() -> None:
    module = _module()
    manifest = module.BridgeManifest(
        rows=3,
        min_valid_from="2023-01-01T00:00:00+00:00",
        max_valid_to="2024-12-31T00:00:00+00:00",
        bridge_sha256="a" * 64,
        frozen_before_reference_read=False,
    )

    with pytest.raises(module.IdentityGateError, match="frozen"):
        module.evaluate_bridge_coverage(
            _valid_bridge(), _reference_spine(), manifest=manifest
        )
