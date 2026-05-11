"""Tests for :mod:`aurora.data_contracts.lineage_producer`."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from aurora.core.snapshots import SnapshotStore
from aurora.data_contracts import (
    DataLineage,
    SnapshotStoreLineageWrapper,
    producer_for_snapshot_store,
    record_pipeline_step,
)


# --------------------------------------------------------------------------
# 1. record_pipeline_step appends a chain entry
# --------------------------------------------------------------------------


def test_record_pipeline_step_appends_to_chain() -> None:
    prior = DataLineage(
        input_dataset_hash="raw_hash",
        transformation_chain=("ingest",),
        code_version="1.0.0",
        contract_version="1.0.0",
        snapshot_hash="raw_hash",
        validator_version="1.0.0",
        decision_outcome="accepted",
        contract_hash="contract123",
        policy_hash="policy123",
    )
    nxt = record_pipeline_step(
        prior,
        "adjust_splits",
        output_hash="adj_hash",
        params={"factor": 2.0},
    )
    assert nxt.transformation_chain == ("ingest", "adjust_splits(factor=2.0)")
    assert nxt.input_dataset_hash == "raw_hash"
    assert nxt.snapshot_hash == "adj_hash"
    # propagated fields stay sticky
    assert nxt.contract_hash == "contract123"
    assert nxt.policy_hash == "policy123"
    assert nxt.contract_version == "1.0.0"


# --------------------------------------------------------------------------
# 2. empty prior lineage initialises a fresh chain
# --------------------------------------------------------------------------


def test_empty_prior_initializes_chain() -> None:
    nxt = record_pipeline_step(
        None,
        "ingest_raw",
        output_hash="raw_hash_v1",
    )
    assert nxt.transformation_chain == ("ingest_raw",)
    assert nxt.input_dataset_hash == "raw_hash_v1"
    assert nxt.snapshot_hash == "raw_hash_v1"
    assert nxt.decision_outcome == "pipeline_step:ingest_raw"


# --------------------------------------------------------------------------
# 3. SnapshotStore wrapper preserves lineage end-to-end (raw -> snapshot)
# --------------------------------------------------------------------------


def test_snapshot_store_wrapper_records_lineage(tmp_path) -> None:
    store = SnapshotStore(root_dir=str(tmp_path))
    wrapper = producer_for_snapshot_store(
        store,
        code_version="1.4.0",
        contract_hash="contract_abc",
        contract_version="1.0.0",
        validator_version="1.0.0",
    )
    assert isinstance(wrapper, SnapshotStoreLineageWrapper)

    idx = pd.DatetimeIndex(
        [pd.Timestamp(datetime(2024, 1, d, tzinfo=timezone.utc)) for d in range(1, 6)]
    )
    prices = pd.Series([100.0 + i for i in range(5)], index=idx, name="Close")

    snap = wrapper.freeze(prices, "AAPL", provenance="unit-test")
    assert wrapper.last_lineage is not None
    assert wrapper.last_lineage.transformation_chain[-1].startswith("snapshot_freeze")
    assert wrapper.last_lineage.snapshot_hash == snap.sha256
    assert wrapper.last_lineage.contract_hash == "contract_abc"

    # second op (load) extends the chain in-place
    _, snap2 = wrapper.load(snap.sha256)
    assert snap2.sha256 == snap.sha256
    assert len(wrapper.chain) == 2
    assert wrapper.chain[-1].transformation_chain == (
        wrapper.chain[0].transformation_chain[0],
        f"snapshot_load(sha256='{snap.sha256}')",
    )


# --------------------------------------------------------------------------
# 4. raw -> adjusted -> snapshot -> strategy lineage chain end-to-end
# --------------------------------------------------------------------------


def test_full_pipeline_chain_grows() -> None:
    """Simulate the playbook's raw -> adjusted -> snapshot -> strategy
    flow purely with :func:`record_pipeline_step` (no SnapshotStore
    needed).
    """
    raw = record_pipeline_step(
        None, "ingest_raw", output_hash="raw_hash"
    )
    adj = record_pipeline_step(
        raw, "adjust_splits", output_hash="adj_hash", params={"factor": 2.0}
    )
    snap = record_pipeline_step(
        adj, "snapshot_freeze", output_hash="snap_hash"
    )
    strat = record_pipeline_step(
        snap, "strategy_consume", output_hash="snap_hash",
        decision_outcome="accepted",
    )
    assert strat.transformation_chain == (
        "ingest_raw",
        "adjust_splits(factor=2.0)",
        "snapshot_freeze",
        "strategy_consume",
    )
    assert strat.input_dataset_hash == "raw_hash"
    assert strat.snapshot_hash == "snap_hash"
    assert strat.decision_outcome == "accepted"
