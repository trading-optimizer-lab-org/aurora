"""Tests for R134 / R143 / R145 / R152 batch."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from aurora.core.snapshot_freshness import (
    audit_freshness,
    stale_snapshots,
)
from aurora.core.universe_gate import (
    affected_strategies,
    diff_universe,
)
from aurora.ml.ood_detector import OODDetector
from aurora.research.ancestry import (
    AncestryEdge,
    render_dot,
    render_text,
)


# --------------------------------------------------------------------------
# R143 snapshot freshness
# --------------------------------------------------------------------------


def test_freshness_flags_old_and_passes_recent():
    snapshots = [
        {"sha256": "old", "created_at": "2024-01-01T00:00:00"},
        {"sha256": "fresh", "created_at": datetime.utcnow().isoformat()},
    ]
    verdicts = audit_freshness(snapshots, cutoff=timedelta(days=30))
    by_id = {v.snapshot_id: v for v in verdicts}
    assert by_id["old"].is_fresh is False
    assert by_id["fresh"].is_fresh is True
    assert "old" in stale_snapshots(verdicts)
    assert "fresh" not in stale_snapshots(verdicts)


def test_freshness_handles_unparseable_timestamp():
    snapshots = [{"sha256": "bad", "created_at": "not-a-date"}]
    verdicts = audit_freshness(snapshots, cutoff=timedelta(days=30))
    assert verdicts[0].is_fresh is False


# --------------------------------------------------------------------------
# R134 universe gate
# --------------------------------------------------------------------------


def test_universe_diff_detects_added_and_removed():
    diff = diff_universe({"AAPL", "MSFT"}, {"MSFT", "GOOG"})
    assert diff.added == frozenset({"GOOG"})
    assert diff.removed == frozenset({"AAPL"})


def test_affected_strategies_lists_only_those_referencing_removed():
    diff = diff_universe({"AAPL", "MSFT", "GE"}, {"MSFT"})
    affected = affected_strategies(diff, {
        "alpha": {"AAPL", "MSFT"},
        "beta": {"MSFT"},
        "gamma": {"GE"},
    })
    assert "alpha" in affected
    assert "gamma" in affected
    assert "beta" not in affected


# --------------------------------------------------------------------------
# R145 OOD detector
# --------------------------------------------------------------------------


def test_ood_detects_drift_when_distribution_shifts():
    rng = np.random.default_rng(0)
    train = rng.normal(0.0, 1.0, size=(2000, 4))
    # KL on small comparison batches is noisy; rely primarily on
    # Mahalanobis for the in-vs-out decision in this test.
    det = OODDetector(reference=train, kl_threshold=1e9,
                      mahalanobis_threshold=2.5)
    in_dist = rng.normal(0.0, 1.0, size=(500, 4))
    out_dist = rng.normal(5.0, 1.0, size=(500, 4))
    rep_in = det.score(in_dist)
    rep_out = det.score(out_dist)
    assert rep_in.is_drift is False
    assert rep_out.is_drift is True


def test_ood_kl_flags_obvious_distribution_shift():
    rng = np.random.default_rng(0)
    train = rng.normal(0.0, 1.0, size=(2000, 4))
    det = OODDetector(reference=train, kl_threshold=0.5,
                      mahalanobis_threshold=1e9)
    out_dist = rng.normal(5.0, 1.0, size=(500, 4))
    rep = det.score(out_dist)
    assert rep.max_kl > det.kl_threshold


# --------------------------------------------------------------------------
# R152 ancestry
# --------------------------------------------------------------------------


def test_ancestry_text_renders_root_first():
    edges = [
        AncestryEdge(parent_id=None, child_id="alpha_v1", status="active"),
        AncestryEdge(parent_id="alpha_v1", child_id="alpha_v2",
                     status="active"),
        AncestryEdge(parent_id="alpha_v1", child_id="alpha_v3",
                     status="archived"),
    ]
    text = render_text(edges)
    assert "alpha_v1" in text
    assert "alpha_v2" in text
    assert "alpha_v3" in text
    # alpha_v1 listed before its children.
    assert text.index("alpha_v1") < text.index("alpha_v2")


def test_ancestry_dot_includes_every_edge():
    edges = [
        AncestryEdge(parent_id=None, child_id="root", status="active"),
        AncestryEdge(parent_id="root", child_id="leaf", status="active"),
    ]
    dot = render_dot(edges)
    assert "digraph ancestry" in dot
    assert '"root" -> "leaf"' in dot
