"""Tests for R167 incremental data refresh + dataset diff."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.data_contracts.dataset_diff import (
    DatasetDiffSummary,
    RowDiff,
    StaleArtefact,
    SymbolDiff,
    content_hash,
    diff_dataset,
    diff_symbol,
    stale_artefact_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frame(start: str, n: int, base: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n, name="timestamp")
    return pd.DataFrame({
        "open": np.full(n, base + 0.5),
        "close": np.full(n, base),
    }, index=idx)


# ---------------------------------------------------------------------------
# Symbol-level
# ---------------------------------------------------------------------------


def test_identical_frames_have_no_diff():
    old = _frame("2024-01-02", 10)
    new = _frame("2024-01-02", 10)
    d = diff_symbol(symbol="SPY", old=old, new=new)
    assert d.new_rows == 0
    assert d.removed_rows == 0
    assert d.changed_rows == []
    assert d.is_changed is False


def test_extension_appears_as_new_rows():
    old = _frame("2024-01-02", 10)
    new = _frame("2024-01-02", 12)
    d = diff_symbol(symbol="SPY", old=old, new=new)
    assert d.new_rows == 2
    assert d.removed_rows == 0
    assert d.is_changed is True


def test_removed_row_detected():
    old = _frame("2024-01-02", 10)
    new = old.iloc[:-1]
    d = diff_symbol(symbol="SPY", old=old, new=new)
    assert d.removed_rows == 1


def test_changed_historical_row_detected():
    old = _frame("2024-01-02", 5)
    new = old.copy()
    new.iloc[2, new.columns.get_loc("close")] = 999.0
    d = diff_symbol(symbol="SPY", old=old, new=new)
    assert len(d.changed_rows) == 1
    rd = d.changed_rows[0]
    assert rd.column == "close"
    assert rd.new_value == 999.0


def test_metadata_changes_recorded():
    old = _frame("2024-01-02", 5)
    new = _frame("2024-01-02", 5)
    d = diff_symbol(
        symbol="SPY",
        old=old,
        new=new,
        old_metadata={"provider": "yahoo", "adjustment": "raw"},
        new_metadata={"provider": "yahoo", "adjustment": "split"},
    )
    assert "adjustment" in d.metadata_changes
    assert d.metadata_changes["adjustment"] == ("raw", "split")
    assert d.is_changed is True


def test_content_hash_is_stable_for_same_data():
    f = _frame("2024-01-02", 5)
    assert content_hash(f) == content_hash(f.copy())


def test_content_hash_changes_when_value_changes():
    a = _frame("2024-01-02", 5)
    b = a.copy()
    b.iloc[0, b.columns.get_loc("close")] = 999.0
    assert content_hash(a) != content_hash(b)


def test_diff_to_dict_round_trip():
    old = _frame("2024-01-02", 5)
    new = old.copy()
    new.iloc[0, new.columns.get_loc("close")] = 200.0
    d = diff_symbol(symbol="SPY", old=old, new=new)
    payload = d.to_dict()
    assert payload["symbol"] == "SPY"
    assert payload["changed_rows"][0]["column"] == "close"


# ---------------------------------------------------------------------------
# Dataset-level
# ---------------------------------------------------------------------------


def test_dataset_diff_classifies_added_removed_changed_unchanged():
    old = {
        "SPY": _frame("2024-01-02", 5),
        "IEF": _frame("2024-01-02", 5, base=80),
        "TLT": _frame("2024-01-02", 5, base=120),
    }
    new = dict(old)
    new["NEW"] = _frame("2024-01-02", 5, base=50)
    del new["TLT"]
    new["IEF"] = new["IEF"].copy()
    new["IEF"].iloc[0, new["IEF"].columns.get_loc("close")] = 999.0

    diff = diff_dataset(old_frames=old, new_frames=new)
    assert diff.symbols_added == ["NEW"]
    assert diff.symbols_removed == ["TLT"]
    assert diff.symbols_changed == ["IEF"]
    assert diff.symbols_unchanged == ["SPY"]


def test_dataset_diff_to_dict_serialises_rows():
    old = {"SPY": _frame("2024-01-02", 5)}
    new = {"SPY": _frame("2024-01-02", 5).copy()}
    new["SPY"].iloc[0, new["SPY"].columns.get_loc("close")] = 999.0
    diff = diff_dataset(old_frames=old, new_frames=new)
    payload = diff.to_dict()
    assert payload["symbols_changed"] == ["SPY"]
    assert payload["per_symbol"]["SPY"]["changed_rows"]


# ---------------------------------------------------------------------------
# Stale-report
# ---------------------------------------------------------------------------


def test_stale_artefact_report_picks_up_changed_symbols():
    diff = DatasetDiffSummary(
        symbols_added=[],
        symbols_removed=[],
        symbols_changed=["SPY", "IEF"],
        symbols_unchanged=["TLT"],
        per_symbol={},
    )
    deps = {
        "validation": {
            "validation_alpha": ["SPY"],
            "validation_beta": ["TLT"],
        },
        "snapshot": {
            "snap_2024_q1": ["IEF", "TLT"],
        },
    }
    out = stale_artefact_report(diff, deps)
    out_ids = {a.artefact_id for a in out}
    assert "validation_alpha" in out_ids
    assert "snap_2024_q1" in out_ids
    assert "validation_beta" not in out_ids


def test_stale_artefact_report_empty_when_nothing_changed():
    diff = DatasetDiffSummary(
        symbols_added=[],
        symbols_removed=[],
        symbols_changed=[],
        symbols_unchanged=["SPY"],
        per_symbol={},
    )
    out = stale_artefact_report(diff, {"snapshot": {"snap": ["SPY"]}})
    assert out == []
