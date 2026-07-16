"""Governance, implementation status, PIT universe and locked contracts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.stock_protocol.dataset import PackAudit, ResearchPanel
from aurora.research.stock_protocol.governance import (
    ALLOWED_IMPLEMENTATION_STATES,
    implementation_matrix,
    unsupported_data_requirements,
)
from aurora.research.stock_protocol.manifest import load_protocol_manifest
from aurora.research.stock_protocol.signals import compute_features
from aurora.research.stock_protocol.universe import (
    CurrentUniverseBackfillProvider,
    HistoricalPointInTimeUniverseProvider,
    UniverseSnapshot,
)


MANIFEST = Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"


def _locked_panel() -> ResearchPanel:
    frame = pd.DataFrame(
        {
            "date": [pd.Timestamp("2021-01-01")],
            "symbol": ["AAA"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "adj_close": [100.0],
            "volume": [1000.0],
            "dividends": [0.0],
            "stock_splits": [0.0],
        }
    )
    audit = PackAudit(
        "source", "pack", "2021-01-01", "2020-12-31", 1, 1, 1,
        False, False, "hash"
    )
    return ResearchPanel(frame, audit)


def test_implementation_matrix_has_exactly_36_honest_rows():
    manifest = load_protocol_manifest(MANIFEST)
    matrix = implementation_matrix(manifest)
    assert matrix["test_id"].tolist() == list(range(1, 37))
    assert len(matrix) == 36
    assert set(matrix["implementation_status"]) <= ALLOWED_IMPLEMENTATION_STATES
    assert matrix["implementation_status"].ne("executable").all()
    assert matrix["code_path"].notna().all()
    assert matrix["limitation"].notna().all()


def test_unsupported_tests_have_exact_loader_contracts():
    manifest = load_protocol_manifest(MANIFEST)
    requirements = unsupported_data_requirements(manifest)
    assert len(requirements) == 11
    assert set(requirements["test_id"]) == set(manifest.unsupported_tests()[i].test_id for i in range(11))
    assert requirements["dataset"].str.len().gt(0).all()
    assert requirements["required_columns"].str.len().gt(0).all()
    assert requirements["frequency"].str.len().gt(0).all()
    assert requirements["available_at_field"].str.len().gt(0).all()
    assert requirements["provider_examples"].str.len().gt(0).all()
    assert requirements["loader_interface"].eq("PointInTimeResearchDataProvider").all()


def test_current_universe_is_explicitly_survivorship_limited():
    provider = CurrentUniverseBackfillProvider(["BBB", "AAA", "AAA"])
    snapshot = provider.snapshot_as_of(pd.Timestamp("2000-01-03"))
    assert snapshot.symbols == ("AAA", "BBB")
    assert snapshot.mode == "current_universe_backfill"
    assert snapshot.survivorship_limited is True
    assert snapshot.point_in_time is False
    assert snapshot.as_of == pd.Timestamp("2000-01-03")


def test_historical_pit_interface_requires_as_of_membership():
    class ExamplePIT(HistoricalPointInTimeUniverseProvider):
        def snapshot_as_of(self, as_of: pd.Timestamp) -> UniverseSnapshot:
            return UniverseSnapshot(
                as_of=as_of,
                symbols=("OLD",),
                mode="historical_point_in_time_universe",
                point_in_time=True,
                survivorship_limited=False,
                source="test",
            )

    snapshot = ExamplePIT().snapshot_as_of(pd.Timestamp("1999-12-31"))
    assert snapshot.symbols == ("OLD",)
    assert snapshot.point_in_time is True
    assert snapshot.survivorship_limited is False


def test_features_fail_on_exact_locked_boundary():
    with pytest.raises(ValueError, match="locked"):
        compute_features(_locked_panel())

