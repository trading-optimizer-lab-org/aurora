"""Tests for R165 research ledger enforcement."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora.research.ledger import (
    LedgerEnforcementError,
    LedgerEvent,
    LedgerEventType,
    LedgerIntegrityError,
    ResearchLedger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_full_chain(ledger: ResearchLedger, project_id: str = "P1") -> None:
    seq = [
        (LedgerEventType.PROTOCOL_DECLARED, {
            "objective": "demo",
            "metric": "calmar",
            "allowed_selection_phases": ["train", "validation"],
            "locked_phases": ["locked"],
        }),
        (LedgerEventType.UNIVERSE_SELECTED, {"name": "etfs"}),
        (LedgerEventType.PROVIDER_SET, {"providers": ["yahoo"]}),
        (LedgerEventType.DATE_RANGE_SET, {"start": "2020", "end": "2026"}),
        (LedgerEventType.FEATURE_SET, {"features": ["sma", "rsi"]}),
        (LedgerEventType.SEED_SET, {"seed": 42}),
        (LedgerEventType.PARAMETER_GRID, {"n_choices": 8}),
        (LedgerEventType.CANDIDATE_GENERATED, {"candidate": "c1"}),
    ]
    for et, payload in seq:
        ledger.append(et, project_id=project_id, actor="op", payload=payload)


# ---------------------------------------------------------------------------
# Append + chain
# ---------------------------------------------------------------------------


def test_append_creates_chain(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    e1 = ledger.append(
        LedgerEventType.UNIVERSE_SELECTED,
        project_id="P1", actor="op", payload={"name": "etfs"},
    )
    e2 = ledger.append(
        LedgerEventType.PROVIDER_SET,
        project_id="P1", actor="op", payload={"providers": ["yahoo"]},
    )
    assert e2.parent_hash == e1.event_hash
    ledger.verify_chain()


def test_verify_chain_detects_tampered_payload(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEventType.UNIVERSE_SELECTED,
        project_id="P1", actor="op", payload={"name": "etfs"},
    )
    ledger.append(
        LedgerEventType.PROVIDER_SET,
        project_id="P1", actor="op", payload={"providers": ["yahoo"]},
    )
    raw = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    # Mutate the second line's payload but keep the parent_hash.
    payload = json.loads(raw[1])
    payload["payload"]["providers"].append("EVIL")
    raw[1] = json.dumps(payload, sort_keys=True)
    (tmp_path / "ledger.jsonl").write_text(
        "\n".join(raw) + "\n", encoding="utf-8",
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()


def test_verify_chain_detects_missing_event(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEventType.UNIVERSE_SELECTED,
        project_id="P1", actor="op", payload={"name": "etfs"},
    )
    ledger.append(
        LedgerEventType.PROVIDER_SET,
        project_id="P1", actor="op", payload={"providers": ["yahoo"]},
    )
    ledger.append(
        LedgerEventType.DATE_RANGE_SET,
        project_id="P1", actor="op", payload={"start": "2020", "end": "2026"},
    )
    # Remove the middle event and rewrite the file.
    raw = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    raw = [raw[0], raw[2]]
    (tmp_path / "ledger.jsonl").write_text(
        "\n".join(raw) + "\n", encoding="utf-8",
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def test_assert_ready_for_validation_blocks_when_missing(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEventType.UNIVERSE_SELECTED,
        project_id="P1", actor="op", payload={},
    )
    with pytest.raises(LedgerEnforcementError) as exc:
        ledger.assert_ready_for_validation("P1")
    msg = str(exc.value)
    assert "protocol_declared" in msg
    assert "provider_set" in msg
    assert "feature_set" in msg


def test_assert_ready_for_validation_passes_with_full_chain(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    ledger.assert_ready_for_validation("P1")


def test_assert_ready_for_promotion_requires_robustness_and_validation_run(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    with pytest.raises(LedgerEnforcementError) as exc:
        ledger.assert_ready_for_promotion("P1")
    assert "selection_run" in str(exc.value)
    assert "robustness_run" in str(exc.value)
    assert "validation_run" in str(exc.value)
    ledger.append(
        LedgerEventType.SELECTION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )
    ledger.append(
        LedgerEventType.ROBUSTNESS_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1", "passed": True},
    )
    ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id="P1", actor="op", payload={"validation_id": "v1"},
    )
    ledger.assert_ready_for_promotion("P1")


def test_assert_ready_for_promotion_rejects_failed_latest_robustness(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    ledger.append(
        LedgerEventType.SELECTION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )
    ledger.append(
        LedgerEventType.ROBUSTNESS_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1", "passed": True},
    )
    ledger.append(
        LedgerEventType.ROBUSTNESS_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1", "passed": False},
    )
    ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )

    with pytest.raises(LedgerEnforcementError, match="latest robustness_run did not pass"):
        ledger.assert_ready_for_promotion("P1")


def test_assert_ready_for_promotion_rejects_candidate_mismatch(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    ledger.append(
        LedgerEventType.SELECTION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )
    ledger.append(
        LedgerEventType.ROBUSTNESS_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1", "passed": True},
    )
    ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c2"},
    )

    with pytest.raises(LedgerEnforcementError, match="different candidates"):
        ledger.assert_ready_for_promotion("P1")


def test_assert_ready_for_promotion_rejects_failed_validation(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    ledger.append(
        LedgerEventType.SELECTION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )
    ledger.append(
        LedgerEventType.ROBUSTNESS_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1", "passed": True},
    )
    ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id="P1", actor="op",
        payload={"candidate_id": "c1", "metrics": {"overall_passed": False}},
    )

    with pytest.raises(LedgerEnforcementError, match="validation_run did not pass"):
        ledger.assert_ready_for_promotion("P1")


def test_assert_ready_for_promotion_rejects_selection_validation_mismatch(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    ledger.append(
        LedgerEventType.SELECTION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )
    ledger.append(
        LedgerEventType.ROBUSTNESS_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c2", "passed": True},
    )
    ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c2"},
    )

    with pytest.raises(LedgerEnforcementError, match="selection_run and validation_run"):
        ledger.assert_ready_for_promotion("P1")


def test_assert_ready_for_promotion_rejects_out_of_order_events(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    ledger.append(
        LedgerEventType.ROBUSTNESS_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1", "passed": True},
    )
    ledger.append(
        LedgerEventType.SELECTION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )
    ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id="P1", actor="op", payload={"candidate_id": "c1"},
    )

    with pytest.raises(LedgerEnforcementError, match="selection_run -> robustness_run"):
        ledger.assert_ready_for_promotion("P1")


def test_events_filter_by_project(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger, project_id="P1")
    _seed_full_chain(ledger, project_id="P2")
    p1 = ledger.events(project_id="P1")
    p2 = ledger.events(project_id="P2")
    assert all(e.project_id == "P1" for e in p1)
    assert all(e.project_id == "P2" for e in p2)


# ---------------------------------------------------------------------------
# Trial pressure
# ---------------------------------------------------------------------------


def test_trial_pressure_aggregates_counts(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    for i in range(3):
        ledger.append(
            LedgerEventType.CANDIDATE_REJECTED,
            project_id="P1", actor="op", payload={"candidate": f"c{i}"},
        )
    ledger.append(
        LedgerEventType.CANDIDATE_MODIFIED,
        project_id="P1", actor="op", payload={"candidate": "c1"},
    )
    ledger.append(
        LedgerEventType.OVERRIDE,
        project_id="P1", actor="op", payload={"reason": "force"},
    )
    score = ledger.trial_pressure("P1")
    # 1 generated + 3 rejected + 1 modified + 8 grid + 5*1 override = 18
    assert score.candidates_generated == 1
    assert score.candidates_rejected == 3
    assert score.candidates_modified == 1
    assert score.parameter_choices == 8
    assert score.overrides == 1
    assert score.score == pytest.approx(1 + 3 + 1 + 8 + 5)


def test_trial_pressure_zero_when_no_events(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    score = ledger.trial_pressure("P1")
    assert score.candidates_generated == 0
    assert score.score == 0.0


def test_trial_pressure_includes_oos_unlocks(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    ledger.append(
        LedgerEventType.OOS_UNLOCK,
        project_id="P1", actor="op",
        payload={"phase": "explicit_unlock_oos_locked"},
    )
    score = ledger.trial_pressure("P1")
    assert score.oos_unlocks == 1
    assert score.score >= 10  # 10 * unlock weight


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_events_round_trip_through_disk(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    _seed_full_chain(ledger)
    fresh = ResearchLedger(tmp_path / "ledger.jsonl")
    events = fresh.events(project_id="P1")
    assert events
    assert events[0].event_type is LedgerEventType.PROTOCOL_DECLARED


def test_event_id_uniqueness_across_appends(tmp_path: Path):
    ledger = ResearchLedger(tmp_path / "ledger.jsonl")
    ev1 = ledger.append(
        LedgerEventType.CANDIDATE_GENERATED,
        project_id="P1", actor="op", payload={"candidate": "c1"},
    )
    ev2 = ledger.append(
        LedgerEventType.CANDIDATE_GENERATED,
        project_id="P1", actor="op", payload={"candidate": "c2"},
    )
    assert ev1.event_id != ev2.event_id
