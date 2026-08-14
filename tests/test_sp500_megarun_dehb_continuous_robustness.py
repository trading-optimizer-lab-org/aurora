from __future__ import annotations


def _row(replica, seed, *, position="a" * 64, archive=-0.2):
    return {
        "island_id": f"F001-R{replica}",
        "lane_id": "F001",
        "replicate": replica,
        "restart_seed": seed,
        "strategy_fingerprint": "b" * 64,
        "position_fingerprint": position,
        "archive_key": [archive, -0.6, -0.1],
        "full_fidelity": True,
        "train_feasible": True,
        "config": {"lookback": 21},
        "validation_opened": False,
        "locked_opened": False,
    }


def test_only_seed_consensus_champions_receive_expensive_local_reviews():
    from aurora.infra.sp500_megarun.dehb_continuous_robustness import (
        plan_candidate_local_reviews,
    )

    rows = [_row(1, 101), _row(2, 202), _row(3, 303, position="c" * 64)]
    requests = plan_candidate_local_reviews(rows)

    assert [(row.island_id, row.robustness_seed) for row in requests] == [
        ("F001-R1", 101),
        ("F001-R2", 202),
    ]


def test_distinct_robustness_seeds_are_never_deduplicated():
    from aurora.infra.sp500_megarun.dehb_continuous_robustness import (
        execute_candidate_local_reviews,
    )

    calls = []

    def reviewer(request):
        calls.append(request.robustness_seed)
        return {
            "candidate_local_passed": True,
            "validation_opened": False,
            "locked_opened": False,
        }

    class Cache:
        def __init__(self):
            self.rows = {}

        def get_robustness_evidence(self, **identity):
            return self.rows.get(tuple(identity.values()))

        def put_robustness_evidence(self, **values):
            identity = (
                values["stage"],
                values["strategy_fingerprint"],
                values["robustness_seed"],
            )
            self.rows[identity] = dict(values["evidence"])
            return dict(values["evidence"])

    cache = Cache()
    rows = [_row(1, 101), _row(2, 202)]
    first = execute_candidate_local_reviews(rows, store=cache, reviewer=reviewer)
    second = execute_candidate_local_reviews(rows, store=cache, reviewer=reviewer)

    assert calls == [101, 202]
    assert len(first) == len(second) == 2
    assert {row["robustness_seed"] for row in first} == {101, 202}
