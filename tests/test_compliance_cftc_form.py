"""Tests for quantforge.compliance.cftc_form."""
from __future__ import annotations

import csv

import pytest

from aurora.compliance.cftc_form import (
    CTA_FIELDS,
    CTAFormConfig,
    CTAFormReporter,
)


@pytest.fixture
def reporter() -> CTAFormReporter:
    return CTAFormReporter(CTAFormConfig(
        filer_nfa_id="NFA-123456",
        report_period="2025-03-31",
        speculative_threshold_pct=10.0,
    ))


@pytest.fixture
def positions() -> list[dict]:
    return [
        {
            "account_id": "ACC-001",
            "contract_market": "CME",
            "contract_symbol": "ES",
            "contract_month": "JUN25",
            "long": 50,
            "short": 10,
            "open_interest": 200,
            "notional": 12500000.0,
            "currency": "USD",
        },
        {
            "account_id": "ACC-001",
            "contract_market": "CME",
            "contract_symbol": "CL",
            "contract_month": "JUL25",
            "long": 5,
            "short": 5,
            "open_interest": 1000,
            "notional": 0.0,
        },
    ]


def test_build_report_returns_all_fields(reporter, positions):
    rows = reporter.build_report(positions)
    assert len(rows) == 2
    for row in rows:
        assert set(row.keys()) == set(CTA_FIELDS)


def test_net_position_arithmetic(reporter, positions):
    rows = reporter.build_report(positions)
    assert rows[0]["net_position"] == 40
    assert rows[1]["net_position"] == 0


def test_speculative_flag_above_threshold(reporter, positions):
    rows = reporter.build_report(positions)
    # 40 / 200 = 20% >= 10% threshold -> speculative
    assert rows[0]["is_speculative"] == "Y"
    # 0 / 1000 = 0% < threshold -> not speculative
    assert rows[1]["is_speculative"] == "N"


def test_export_csv_round_trip(tmp_path, reporter, positions):
    out = tmp_path / "cta.csv"
    path = reporter.export_csv(positions, out)
    with path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["filer_nfa_id"] == "NFA-123456"


def test_empty_positions_writes_header_only(tmp_path, reporter):
    out = tmp_path / "empty.csv"
    path = reporter.export_csv([], out)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(CTA_FIELDS)
    assert len(lines) == 1


def test_now_utc_returns_aware_datetime(reporter):
    ts = reporter.now_utc()
    assert ts.tzinfo is not None
