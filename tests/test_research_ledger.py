"""Tests for the Phase 2 research-honesty ledger.

Covers the contract from ``docs/roadmap/ROADMAP_PENDING.md`` Phase 2
(Candidate B): append-only behaviour, retry safety, manual-override
authorship, pressure-score thresholds and pressure-warning formatting.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantforge.research.ledger import (
    ResearchChoice,
    ResearchLedger,
    VALID_KINDS,
)
from quantforge.research.pressure import (
    ResearchPressureScore,
    compute_pressure,
)
from quantforge.validation.research_pressure import (
    RESEARCH_PRESSURE_THRESHOLDS,
    format_pressure_warning,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "research_ledger.jsonl"


@pytest.fixture
def ledger(ledger_path: Path) -> ResearchLedger:
    return ResearchLedger(path=ledger_path)


def _choice(
    run_id: str = "r1",
    kind: str = "parameters",
    payload: dict | None = None,
    author: str | None = None,
    reason: str | None = None,
    timestamp_iso: str = "2026-05-09T08:00:00+00:00",
) -> ResearchChoice:
    return ResearchChoice(
        run_id=run_id,
        timestamp_iso=timestamp_iso,
        kind=kind,
        payload=payload or {},
        author=author,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Append-only behaviour
# ---------------------------------------------------------------------------


def test_ledger_is_append_only(ledger: ResearchLedger, ledger_path: Path) -> None:
    """Two writes produce two distinct records; the second never
    overwrites the first."""
    ledger.record(_choice(payload={"sma": 10}))
    ledger.record(_choice(payload={"sma": 20}))

    rows = ledger.read()
    assert len(rows) == 2
    assert rows[0].payload == {"sma": 10}
    assert rows[1].payload == {"sma": 20}

    # File-level assertion: two physical lines, no truncation.
    raw_lines = [
        line for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(raw_lines) == 2


def test_retry_does_not_overwrite_previous_records(
    ledger: ResearchLedger,
) -> None:
    """Recording the same run_id twice yields two entries, not one."""
    ledger.record(_choice(run_id="run-A", payload={"attempt": 1}))
    ledger.record(_choice(run_id="run-A", payload={"attempt": 2}))

    rows = ledger.read(run_id="run-A")
    assert len(rows) == 2
    payloads = [r.payload for r in rows]
    assert {"attempt": 1} in payloads
    assert {"attempt": 2} in payloads


def test_rejected_candidate_is_recorded(ledger: ResearchLedger) -> None:
    """``rejection_reason`` is a first-class kind on the ledger."""
    ledger.record(
        _choice(
            run_id="run-B",
            kind="rejection_reason",
            payload={"stage": "OOS_DEV", "reason": "sharpe<0.5"},
        )
    )
    rows = ledger.read(run_id="run-B")
    assert len(rows) == 1
    assert rows[0].kind == "rejection_reason"
    assert rows[0].payload["stage"] == "OOS_DEV"


# ---------------------------------------------------------------------------
# Manual override authorship
# ---------------------------------------------------------------------------


def test_manual_override_requires_author_and_reason(
    ledger: ResearchLedger,
) -> None:
    """Manual overrides without an author MUST raise."""
    bad_no_author = _choice(
        kind="manual_override",
        payload={"override": "force_promote"},
        author=None,
        reason="emergency",
    )
    with pytest.raises(ValueError, match="manual_override"):
        ledger.record(bad_no_author)

    bad_no_reason = _choice(
        kind="manual_override",
        payload={"override": "force_promote"},
        author="dgomez",
        reason=None,
    )
    with pytest.raises(ValueError, match="manual_override"):
        ledger.record(bad_no_reason)

    # Happy path: both present.
    ok = _choice(
        kind="manual_override",
        payload={"override": "force_promote"},
        author="dgomez",
        reason="release deadline",
    )
    ledger.record(ok)
    rows = ledger.read()
    assert len(rows) == 1
    assert rows[0].author == "dgomez"
    assert rows[0].reason == "release deadline"


def test_unknown_kind_raises(ledger: ResearchLedger) -> None:
    bad = _choice(kind="not_a_real_kind")
    with pytest.raises(ValueError, match="Unknown research-choice kind"):
        ledger.record(bad)


def test_empty_run_id_raises(ledger: ResearchLedger) -> None:
    bad = _choice(run_id="")
    with pytest.raises(ValueError, match="run_id"):
        ledger.record(bad)


# ---------------------------------------------------------------------------
# Read filtering
# ---------------------------------------------------------------------------


def test_read_filtered_by_run_id_returns_only_that_run(
    ledger: ResearchLedger,
) -> None:
    ledger.record(_choice(run_id="A", payload={"x": 1}))
    ledger.record(_choice(run_id="B", payload={"x": 2}))
    ledger.record(_choice(run_id="A", payload={"x": 3}))
    ledger.record(_choice(run_id="C", payload={"x": 4}))

    rows_a = ledger.read(run_id="A")
    assert {r.payload["x"] for r in rows_a} == {1, 3}

    rows_b = ledger.read(run_id="B")
    assert {r.payload["x"] for r in rows_b} == {2}

    rows_all = ledger.read()
    assert len(rows_all) == 4


def test_read_missing_file_returns_empty(tmp_path: Path) -> None:
    ledger = ResearchLedger(path=tmp_path / "does_not_exist.jsonl")
    assert ledger.read() == []


def test_read_skips_blank_and_corrupt_lines(
    ledger: ResearchLedger, ledger_path: Path
) -> None:
    ledger.record(_choice(payload={"good": 1}))
    # Inject a blank line and a junk line; reader should keep going.
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write("not-json\n")
    ledger.record(_choice(payload={"good": 2}))

    rows = ledger.read()
    assert len(rows) == 2
    assert {r.payload["good"] for r in rows} == {1, 2}


# ---------------------------------------------------------------------------
# Pressure score thresholds
# ---------------------------------------------------------------------------


def test_pressure_low_label() -> None:
    score = ResearchPressureScore(
        n_variants=1,
        n_parameters=1,
        data_length_bars=10_000,
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    assert score.pressure_ratio == pytest.approx(1 / 10_000)
    assert score.risk_label() == "low"


def test_pressure_medium_label() -> None:
    # ratio = 200 / 10_000 = 0.02 -> medium (>0.01 and <=0.05)
    score = ResearchPressureScore(
        n_variants=20,
        n_parameters=10,
        data_length_bars=15_000,  # 200/15000 ~= 0.0133
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    assert 0.01 < score.pressure_ratio <= 0.05
    assert score.risk_label() == "medium"


def test_pressure_high_label() -> None:
    # ratio between 0.05 and 0.20
    score = ResearchPressureScore(
        n_variants=50,
        n_parameters=10,
        data_length_bars=5_000,  # 500/5000 = 0.1
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    assert 0.05 < score.pressure_ratio <= 0.20
    assert score.risk_label() == "high"


def test_pressure_extreme_label() -> None:
    score = ResearchPressureScore(
        n_variants=1000,
        n_parameters=10,
        data_length_bars=1_000,  # ratio = 10
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    assert score.pressure_ratio > 0.20
    assert score.risk_label() == "extreme"


def test_pressure_zero_data_is_extreme() -> None:
    score = ResearchPressureScore(
        n_variants=1,
        n_parameters=1,
        data_length_bars=0,
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    assert score.pressure_ratio == float("inf")
    assert score.risk_label() == "extreme"


# ---------------------------------------------------------------------------
# compute_pressure() reads the ledger correctly
# ---------------------------------------------------------------------------


def test_compute_pressure_aggregates_ledger(ledger: ResearchLedger) -> None:
    run = "swept-run"
    # 3 distinct strategy hashes -> 3 variants
    for h in ("h1", "h2", "h3"):
        ledger.record(
            _choice(run_id=run, kind="strategy_hash", payload={"hash": h})
        )
    # 5 parameter choices
    for i in range(5):
        ledger.record(
            _choice(run_id=run, kind="parameters", payload={"window": i})
        )
    # 1 manual override
    ledger.record(
        _choice(
            run_id=run,
            kind="manual_override",
            payload={"override": "extend_window"},
            author="dgomez",
            reason="market regime change",
        )
    )
    # 2 OOS touches via validation_window payload mentioning oos
    ledger.record(
        _choice(
            run_id=run,
            kind="validation_window",
            payload={"oos_dev": [10, 20]},
        )
    )
    ledger.record(
        _choice(
            run_id=run,
            kind="validation_window",
            payload={"tier": "OOS_LOCKED"},
        )
    )
    # Unrelated run -- must NOT bleed into the score.
    ledger.record(_choice(run_id="other", kind="parameters", payload={}))

    score = compute_pressure(ledger, run_id=run, data_length_bars=2_000)

    assert score.n_variants == 3
    assert score.n_parameters == 5
    assert score.n_manual_interventions == 1
    assert score.n_oos_touches == 2
    assert score.data_length_bars == 2_000


# ---------------------------------------------------------------------------
# Pressure warning text
# ---------------------------------------------------------------------------


def test_format_pressure_warning_mentions_label() -> None:
    score = ResearchPressureScore(
        n_variants=50,
        n_parameters=10,
        data_length_bars=5_000,
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    text = format_pressure_warning(score)
    assert score.risk_label().upper() in text
    assert "variants=50" in text
    assert "parameters=10" in text


def test_format_pressure_warning_extreme_blocks_promotion_message() -> None:
    score = ResearchPressureScore(
        n_variants=1000,
        n_parameters=10,
        data_length_bars=100,
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    text = format_pressure_warning(score)
    assert "EXTREME" in text
    assert "override" in text.lower() or "block" in text.lower()


def test_thresholds_match_pressure_module() -> None:
    """The validation report's thresholds and the score's bucketing
    must agree on cut-points."""
    just_low = ResearchPressureScore(
        n_variants=1,
        n_parameters=1,
        data_length_bars=int(1 / RESEARCH_PRESSURE_THRESHOLDS["low"]),
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    assert just_low.risk_label() == "low"

    just_medium = ResearchPressureScore(
        n_variants=1,
        n_parameters=1,
        data_length_bars=int(1 / RESEARCH_PRESSURE_THRESHOLDS["medium"]),
        n_manual_interventions=0,
        n_oos_touches=0,
    )
    assert just_medium.risk_label() == "medium"


# ---------------------------------------------------------------------------
# Large parameter sweep (vectorbt-style)
# ---------------------------------------------------------------------------


def test_large_parameter_sweep_does_not_corrupt_jsonl(
    ledger: ResearchLedger, ledger_path: Path
) -> None:
    """1000 parameter choices write 1000 well-formed JSONL lines."""
    run = "sweep"
    for i in range(1000):
        ledger.record(
            _choice(
                run_id=run,
                kind="parameters",
                payload={"sma": i, "rsi": i % 10},
            )
        )

    # Read back via the API.
    rows = ledger.read(run_id=run)
    assert len(rows) == 1000

    # And verify the raw file: every line parses as JSON.
    raw_lines = [
        line for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(raw_lines) == 1000
    for line in raw_lines:
        parsed = json.loads(line)
        assert parsed["run_id"] == run
        assert parsed["kind"] == "parameters"


# ---------------------------------------------------------------------------
# Sanity: every kind in VALID_KINDS round-trips
# ---------------------------------------------------------------------------


def test_all_valid_kinds_round_trip(ledger: ResearchLedger) -> None:
    for kind in sorted(VALID_KINDS):
        if kind == "manual_override":
            choice = _choice(
                kind=kind,
                author="dgomez",
                reason="test override",
            )
        else:
            choice = _choice(kind=kind)
        ledger.record(choice)

    rows = ledger.read()
    assert {r.kind for r in rows} == VALID_KINDS
