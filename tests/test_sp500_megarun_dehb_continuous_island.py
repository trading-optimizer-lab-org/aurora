from __future__ import annotations

import hashlib
import os

import pytest


class FakeOptimizer:
    def __init__(self):
        self.asked = 0
        self.told = []

    def ask(self, n_configs=1):
        assert n_configs == 1
        index = self.asked
        self.asked += 1
        return {"config": {"index": index}, "fidelity": 27, "config_id": index}

    def tell(self, job, result):
        self.told.append((int(job["config_id"]), float(result["fitness"])))


def result(index):
    return {
        "fitness": float(index),
        "cost": 1.0,
        "info": {
            "archive_key": [0.0, -0.2, -0.6, -0.1 + index / 1000],
            "validation_opened": False,
            "locked_opened": False,
        },
    }


def state(optimizer=None):
    from aurora.infra.sp500_megarun.dehb_continuous_island import ContinuousIslandState

    return ContinuousIslandState(
        island_id="F067-R0",
        optimizer=optimizer or FakeOptimizer(),
        full_fidelity=27,
        plateau_minimum_completed=128,
        plateau_completed_without_improvement=512,
        checkpoint_serializer=lambda optimizer: (
            ",".join(str(item[0]) for item in optimizer.told).encode("ascii")
        ),
    )


def test_out_of_order_arrival_is_told_in_canonical_slot_order():
    optimizer = FakeOptimizer()
    island = state(optimizer)
    batch = island.ask_batch()

    advance = island.tell_batch(
        batch,
        {3: result(3), 1: result(1), 0: result(0), 2: result(2)},
    )

    assert optimizer.told == [(0, 0.0), (1, 1.0), (2, 2.0), (3, 3.0)]
    assert len(advance.consumed_result_sha256s) == 4
    assert advance.checkpoint_bytes == b"0,1,2,3"
    assert advance.checkpoint_sha256 == hashlib.sha256(b"0,1,2,3").hexdigest()


def test_island_exposes_only_one_unresolved_batch():
    from aurora.infra.sp500_megarun.dehb_continuous_island import ContinuousIslandError

    island = state()
    island.ask_batch()

    with pytest.raises(ContinuousIslandError, match="CONTINUOUS_ISLAND_BATCH_ALREADY_OPEN"):
        island.ask_batch()


def test_missing_or_wrong_batch_result_fails_without_telling_optimizer():
    from aurora.infra.sp500_megarun.dehb_continuous_island import ContinuousIslandError

    optimizer = FakeOptimizer()
    island = state(optimizer)
    batch = island.ask_batch()

    with pytest.raises(ContinuousIslandError, match="CONTINUOUS_ISLAND_BATCH_RESULTS_INCOMPLETE"):
        island.tell_batch(batch, {0: result(0), 1: result(1), 2: result(2)})
    assert optimizer.told == []


def test_three_batches_match_the_existing_synchronous_trajectory():
    from aurora.infra.sp500_megarun.dehb_island_runner import _ask_valid_batch

    baseline = FakeOptimizer()
    for _ in range(3):
        jobs, rejected = _ask_valid_batch(baseline, n_configs=4, rejection_limit=100)
        assert rejected == 0
        for job in jobs:
            baseline.tell(job, result(int(job["config_id"])))

    continuous_optimizer = FakeOptimizer()
    island = state(continuous_optimizer)
    prior_checkpoint = None
    for _ in range(3):
        batch = island.ask_batch()
        results = {
            slot: result(int(job["config_id"]))
            for slot, job in reversed(tuple(enumerate(batch.jobs)))
        }
        advance = island.tell_batch(batch, results)
        assert advance.prior_checkpoint_sha256 == prior_checkpoint
        prior_checkpoint = advance.checkpoint_sha256

    assert continuous_optimizer.told == baseline.told
    assert island.evaluations == 12
    assert island.next_batch_sequence == 4


def test_result_that_opened_validation_is_rejected_before_tell():
    from aurora.infra.sp500_megarun.dehb_continuous_island import ContinuousIslandError

    optimizer = FakeOptimizer()
    island = state(optimizer)
    batch = island.ask_batch()
    invalid = result(0)
    invalid["info"]["validation_opened"] = True

    with pytest.raises(ContinuousIslandError, match="CONTINUOUS_ISLAND_OPENED_VALIDATION"):
        island.tell_batch(
            batch,
            {0: invalid, 1: result(1), 2: result(2), 3: result(3)},
        )
    assert optimizer.told == []


def test_native_checkpoint_codec_is_deterministic_and_rejects_tampering(tmp_path):
    from aurora.infra.sp500_megarun.dehb_continuous_island import (
        ContinuousIslandError,
        pack_checkpoint_directory,
        restore_checkpoint_directory,
    )

    source = tmp_path / "source"
    source.mkdir()
    (source / "state.json").write_text('{"asked":4}', encoding="utf-8")
    nested = source / "history"
    nested.mkdir()
    (nested / "rows.bin").write_bytes(b"official-dehb-history")

    first = pack_checkpoint_directory(source)
    os.utime(source / "state.json", (2_000_000_000, 2_000_000_000))
    second = pack_checkpoint_directory(source)
    destination = tmp_path / "restored"
    expected_checkpoint_sha256 = hashlib.sha256(first).hexdigest()
    receipt = restore_checkpoint_directory(
        first,
        destination,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
    )

    assert first == second
    assert (destination / "state.json").read_text("utf-8") == '{"asked":4}'
    assert (destination / "history" / "rows.bin").read_bytes() == b"official-dehb-history"
    assert receipt.file_count == 2
    assert receipt.checkpoint_sha256 == expected_checkpoint_sha256

    tampered = first[:-1] + bytes([first[-1] ^ 1])
    with pytest.raises(ContinuousIslandError, match="CONTINUOUS_CHECKPOINT_HASH_MISMATCH"):
        restore_checkpoint_directory(
            tampered,
            tmp_path / "tampered",
            expected_checkpoint_sha256=expected_checkpoint_sha256,
        )
