"""Tests for quantforge.compliance.mifid_reporting."""
from __future__ import annotations

import csv
from datetime import datetime, timezone

import pytest

from aurora.compliance.mifid_reporting import (
    RTS22_FIELDS,
    MiFIDConfig,
    MiFIDIIReporter,
)


@pytest.fixture
def reporter() -> MiFIDIIReporter:
    return MiFIDIIReporter(MiFIDConfig(
        executing_entity_lei="EXEC0000000000000001",
        submitting_entity_lei="SUBM0000000000000001",
    ))


@pytest.fixture
def sample_trades() -> list[dict]:
    return [
        {
            "trade_id": "T-001",
            "timestamp": datetime(2025, 4, 1, 14, 30, tzinfo=timezone.utc),
            "symbol": "AAPL",
            "isin": "US0378331005",
            "side": "BUY",
            "quantity": 100,
            "price": 175.50,
            "currency": "USD",
            "venue": "XNAS",
        },
        {
            "trade_id": "T-002",
            "timestamp": datetime(2025, 4, 1, 14, 31, tzinfo=timezone.utc),
            "symbol": "MSFT",
            "side": "SELL",
            "quantity": 50,
            "price": 410.10,
            "currency": "USD",
        },
    ]


def test_build_report_returns_all_fields(reporter, sample_trades):
    rows = reporter.build_report(sample_trades)
    assert len(rows) == 2
    for row in rows:
        assert set(row.keys()) == set(RTS22_FIELDS)


def test_build_report_sets_executing_entity(reporter, sample_trades):
    rows = reporter.build_report(sample_trades)
    assert all(r["executing_entity_id"] == "EXEC0000000000000001" for r in rows)


def test_buyer_seller_assignment_by_side(reporter, sample_trades):
    rows = reporter.build_report(sample_trades)
    buy_row = rows[0]
    sell_row = rows[1]
    assert buy_row["buyer_id"] == "EXEC0000000000000001"
    assert sell_row["seller_id"] == "EXEC0000000000000001"


def test_isin_uses_isin_id_type(reporter, sample_trades):
    rows = reporter.build_report(sample_trades)
    assert rows[0]["instrument_id_type"] == "ISIN"
    assert rows[0]["instrument_id"] == "US0378331005"
    assert rows[1]["instrument_id_type"] == "OTHR"


def test_export_csv_writes_header_and_rows(tmp_path, reporter, sample_trades):
    out = tmp_path / "mifid.csv"
    path = reporter.export_csv(sample_trades, out)
    assert path.exists()
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 2
    assert reader.fieldnames == list(RTS22_FIELDS)


def test_empty_trades_writes_header_only(tmp_path, reporter):
    out = tmp_path / "empty.csv"
    path = reporter.export_csv([], out)
    text = path.read_text(encoding="utf-8").splitlines()
    assert text[0] == ",".join(RTS22_FIELDS)
    assert len(text) == 1
