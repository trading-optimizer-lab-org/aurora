"""R163 - tests for the liquidity operator report."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.data_contracts.liquidity import (
    compute_liquidity_features,
    LiquidityRecord,
)
from aurora.reporting.liquidity_report import (
    LiquidityReport,
    render_liquidity_report,
)


@pytest.fixture
def liquid_record() -> LiquidityRecord:
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    df = pd.DataFrame(
        {"close": np.full(40, 100.0), "volume": np.full(40, 1_000_000.0)},
        index=idx,
    )
    return compute_liquidity_features(
        df, symbol="AAA", asof=idx[-1], window=20, source="provider:test"
    )


@pytest.fixture
def thin_record() -> LiquidityRecord:
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    df = pd.DataFrame(
        {"close": np.full(40, 5.0), "volume": np.full(40, 2_000.0)},
        index=idx,
    )
    return compute_liquidity_features(
        df,
        symbol="THIN",
        asof=idx[-1],
        window=20,
        low_volume_floor=1.0e6,
    )


def test_report_carries_policy_hash_placeholder(liquid_record):
    report = render_liquidity_report([liquid_record])
    # Default placeholder kicks in when caller does not pass a hash.
    assert report.policy_hash == "policy-hash-pending"


def test_report_propagates_supplied_policy_hash(liquid_record):
    report = render_liquidity_report(
        [liquid_record], policy_hash="abc123def456"
    )
    assert report.policy_hash == "abc123def456"
    assert "abc123def456" in report.to_markdown()


def test_report_renders_deterministically(liquid_record, thin_record):
    """Same input -> identical markdown across calls."""
    r1 = render_liquidity_report(
        [liquid_record, thin_record],
        policy_hash="deadbeef",
        min_dollar_volume=1.0e6,
        min_adv=1.0e6,
    )
    r2 = render_liquidity_report(
        [thin_record, liquid_record],  # different order
        policy_hash="deadbeef",
        min_dollar_volume=1.0e6,
        min_adv=1.0e6,
    )
    assert r1.to_markdown() == r2.to_markdown()


def test_report_markdown_lists_low_volume_symbols(liquid_record, thin_record):
    report = render_liquidity_report(
        [liquid_record, thin_record],
        policy_hash="deadbeef",
        min_dollar_volume=1.0e6,
        min_adv=1.0e6,
    )
    md = report.to_markdown()
    assert "## Low-volume symbols" in md
    assert "- THIN" in md
    # The liquid symbol should NOT appear in low-volume section
    section = md.split("## Low-volume symbols", 1)[1].split("##", 1)[0]
    assert "AAA" not in section


def test_report_markdown_lists_thin_symbols_section(liquid_record, thin_record):
    report = render_liquidity_report(
        [liquid_record, thin_record],
        policy_hash="deadbeef",
        min_dollar_volume=1.0e6,
        min_adv=1.0e6,
    )
    md = report.to_markdown()
    assert "## Thin symbols (failed floor)" in md
    section = md.split("## Thin symbols", 1)[1]
    assert "THIN" in section


def test_report_to_dict_round_trips_records(liquid_record):
    report = render_liquidity_report([liquid_record], policy_hash="x")
    d = report.to_dict()
    assert d["policy_hash"] == "x"
    assert len(d["records"]) == 1
    assert d["records"][0]["symbol"] == "AAA"
    assert d["records"][0]["observed_or_estimated"] == "estimated"


def test_report_validates_floors(liquid_record):
    with pytest.raises(ValueError):
        render_liquidity_report([liquid_record], min_dollar_volume=-1.0)
    with pytest.raises(ValueError):
        render_liquidity_report([liquid_record], min_adv=-1.0)
