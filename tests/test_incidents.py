"""Tests for R180 incident notes + postmortems."""
from __future__ import annotations

from pathlib import Path

import pytest

from aurora.monitoring.incidents import (
    IncidentImmutable,
    IncidentKind,
    IncidentLedger,
    IncidentSeverity,
    IncidentStatus,
)


# ---------------------------------------------------------------------------
# Open / append / close
# ---------------------------------------------------------------------------


def test_open_incident_persists(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec = ledger.open_incident(
        kind=IncidentKind.STALE_DATA,
        severity=IncidentSeverity.WARN,
        title="Yahoo prices stale",
        actor="op",
        affected_strategies=["alpha"],
        affected_symbols=["SPY"],
        initial_note="Detected by daily ops at 15:30 UTC",
    )
    assert rec.status is IncidentStatus.OPEN
    fetched = ledger.latest(rec.incident_id)
    assert fetched is not None
    assert fetched.title == "Yahoo prices stale"
    assert len(fetched.timeline) == 1


def test_open_incident_requires_title(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    with pytest.raises(ValueError):
        ledger.open_incident(
            kind=IncidentKind.STALE_DATA,
            severity=IncidentSeverity.WARN,
            title="",
            actor="op",
        )


def test_append_note_grows_timeline(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec = ledger.open_incident(
        kind=IncidentKind.BAD_TICK,
        severity=IncidentSeverity.WARN,
        title="bad tick on SPY",
        actor="op",
    )
    ledger.append_note(rec.incident_id, text="reproduced", actor="op")
    ledger.append_note(rec.incident_id, text="fix queued", actor="op")
    latest = ledger.latest(rec.incident_id)
    assert latest is not None
    assert len(latest.timeline) == 2


def test_close_incident_records_root_cause_and_status(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec = ledger.open_incident(
        kind=IncidentKind.RECONCILIATION_MISMATCH,
        severity=IncidentSeverity.ERROR,
        title="recon mismatch",
        actor="op",
    )
    closed = ledger.close(
        rec.incident_id,
        actor="op",
        impact="2 missed fills",
        root_cause="paper adapter dropped websocket",
        action_items=["reconnect logic", "regression test"],
    )
    assert closed.status is IncidentStatus.CLOSED
    assert closed.root_cause == "paper adapter dropped websocket"
    assert "reconnect logic" in closed.action_items


def test_close_incident_is_immutable(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec = ledger.open_incident(
        kind=IncidentKind.MARGIN_WARNING,
        severity=IncidentSeverity.WARN,
        title="margin",
        actor="op",
    )
    ledger.close(
        rec.incident_id, actor="op",
        impact="none", root_cause="cause",
    )
    with pytest.raises(IncidentImmutable):
        ledger.close(
            rec.incident_id, actor="op",
            impact="none", root_cause="cause",
        )


def test_append_note_after_close_still_works(tmp_path: Path):
    """Closed incidents accept audited append-only notes."""
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec = ledger.open_incident(
        kind=IncidentKind.STALE_DATA,
        severity=IncidentSeverity.INFO,
        title="x", actor="op",
    )
    ledger.close(rec.incident_id, actor="op", impact="none", root_cause="x")
    ledger.append_note(rec.incident_id, text="follow-up", actor="op")
    latest = ledger.latest(rec.incident_id)
    assert latest is not None
    assert latest.status is IncidentStatus.CLOSED
    # Timeline carries the closing note + the follow-up note.
    assert any("follow-up" == n.text for n in latest.timeline)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_open_incidents_filters(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec_open = ledger.open_incident(
        kind=IncidentKind.STALE_DATA,
        severity=IncidentSeverity.WARN,
        title="open one", actor="op",
    )
    rec_closed = ledger.open_incident(
        kind=IncidentKind.BAD_TICK,
        severity=IncidentSeverity.WARN,
        title="closed one", actor="op",
    )
    ledger.close(
        rec_closed.incident_id, actor="op",
        impact="x", root_cause="x",
    )
    open_only = ledger.open_incidents()
    assert [r.incident_id for r in open_only] == [rec_open.incident_id]


def test_all_incidents_unique_per_id(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec = ledger.open_incident(
        kind=IncidentKind.OOS_LEAK_ATTEMPT,
        severity=IncidentSeverity.CRITICAL,
        title="leak attempt", actor="op",
    )
    ledger.append_note(rec.incident_id, text="more info", actor="op")
    ledger.append_note(rec.incident_id, text="even more info", actor="op")
    out = ledger.all_incidents()
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Postmortem
# ---------------------------------------------------------------------------


def test_postmortem_includes_timeline_and_action_items(tmp_path: Path):
    ledger = IncidentLedger(tmp_path / "incidents.jsonl")
    rec = ledger.open_incident(
        kind=IncidentKind.KILL_SWITCH_FIRED,
        severity=IncidentSeverity.CRITICAL,
        title="kill fired",
        actor="op",
        initial_note="kill switch fired due to drawdown",
    )
    ledger.close(
        rec.incident_id, actor="op",
        impact="halted alpha", root_cause="drawdown breach",
        action_items=["lower max_dd_limit"],
    )
    pm = ledger.latest(rec.incident_id).to_postmortem()
    assert "Timeline" in pm
    assert "drawdown" in pm.lower()
    assert "lower max_dd_limit" in pm
