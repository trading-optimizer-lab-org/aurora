from __future__ import annotations


class _SnapshotStore:
    def __init__(self, rows):
        self.rows = list(rows)
        self.persisted = {}
        self.state = "searching"

    def result_rows(self, cutoff_sequence):
        return [row for row in self.rows if row["created_sequence"] <= cutoff_sequence]

    def persist_reducer_snapshot(self, snapshot):
        self.persisted[snapshot.snapshot_sha256] = snapshot
        return len(self.persisted)

    def freeze_campaign(self, snapshot_sha256, winner):
        self.state = "frozen"
        self.winner = dict(winner)


def _champion(*, replica, annualized_return, sequence=1, robust=True):
    fingerprint = "a" * 64
    return {
        "created_sequence": sequence,
        "island_id": f"F001-R{replica}",
        "lane_id": "F001",
        "replicate": replica,
        "strategy_fingerprint": "b" * 64,
        "position_fingerprint": fingerprint,
        "archive_key": [-annualized_return, -0.61, -0.08],
        "annualized_strategy_return": annualized_return,
        "weekly_spy_beat_rate": 0.61,
        "full_fidelity": True,
        "train_feasible": True,
        "candidate_local_robustness_passed": robust,
        "global_robustness_passed": True,
        "all_60_train_gates_passed": True,
        "validation_opened": False,
        "locked_opened": False,
    }


def test_snapshot_is_repeatable_at_exact_sequence_cutoff():
    from aurora.infra.sp500_megarun.dehb_continuous_reducer import ContinuousReducer

    store = _SnapshotStore([_champion(replica=1, annualized_return=0.24)])
    reducer = ContinuousReducer(store)
    first = reducer.build_snapshot(1)
    store.rows.append(_champion(replica=2, annualized_return=0.24, sequence=2))

    assert reducer.build_snapshot(1).snapshot_sha256 == first.snapshot_sha256
    assert reducer.build_snapshot(2).snapshot_sha256 != first.snapshot_sha256


def test_freeze_requires_two_seed_consensus_and_all_robustness_gates():
    from aurora.infra.sp500_megarun.dehb_continuous_reducer import ContinuousReducer

    store = _SnapshotStore(
        [
            _champion(replica=1, annualized_return=0.24),
            _champion(replica=2, annualized_return=0.24),
        ]
    )
    reducer = ContinuousReducer(store)
    decision = reducer.attempt_train_freeze(reducer.build_snapshot(1))

    assert decision.action == "frozen"
    assert store.state == "frozen"
    assert decision.winner["annualized_strategy_return"] == 0.24
    assert decision.winner["seed_consensus"] == 2


def test_no_robust_consensus_keeps_searching_without_terminal_failure():
    from aurora.infra.sp500_megarun.dehb_continuous_reducer import ContinuousReducer

    store = _SnapshotStore([_champion(replica=1, annualized_return=0.50, robust=False)])
    decision = ContinuousReducer(store).attempt_train_freeze(
        ContinuousReducer(store).build_snapshot(1)
    )

    assert decision.action == "searching"
    assert store.state == "searching"
    assert decision.winner is None
