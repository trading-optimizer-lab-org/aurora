from __future__ import annotations

from scripts.run_sp500_atlas_controller import segment_dispatch_inputs


def test_controller_dispatch_is_bound_to_commit_and_segment_attempt() -> None:
    values = segment_dispatch_inputs(
        commit_sha="a" * 40,
        preflight_run_id="123",
        runtime_input_run_id="456",
        segment_index=3,
        controller_run_id="789",
        attempt=2,
    )
    assert values == {
        "commit_sha": "a" * 40,
        "preflight_run_id": "123",
        "runtime_input_run_id": "456",
        "segment_index": "3",
        "controller_run_id": "789",
        "attempt": "2",
    }
