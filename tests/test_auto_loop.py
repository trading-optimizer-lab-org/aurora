"""Tests for research.auto_loop (R10)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from quantforge.research.auto_loop import (
    AutoLoopConfig,
    AutoResearchLoop,
    CycleSummary,
)
from quantforge.research.factory.outcomes import (
    CandidateRun,
    RejectionReason,
    ResearchOutcome,
    ResearchStage,
)
from quantforge.research.factory.spec import StrategySpec

# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class _FakeGenerator:
    """Deterministic generator returning N spec stubs."""

    name = "fake-gen"

    def __init__(self, n_to_return: int = 3, fail: bool = False):
        self.n_to_return = n_to_return
        self.fail = fail
        self.calls: list[tuple[int, int]] = []

    def generate(self, n: int, seed: int) -> list[StrategySpec]:
        self.calls.append((n, seed))
        if self.fail:
            raise RuntimeError("boom")
        return [
            StrategySpec.make(
                name="MACross",
                hypothesis="auto-loop test stub",
                strategy_class="quantforge.strategies.library.MACross",
                params={"fast": 5 + i, "slow": 50 + i},
                expected_edge_bps=10.0,
                regime_dependence=["trending"],
                failure_modes=["whipsaw"],
                universe=["SPY"],
                rebalance="1d",
                generator=self.name,
            )
            for i in range(self.n_to_return)
        ]


class _FakeFactory:
    """Fake factory: returns alternating promoted/archived outcomes.

    Records the submitted specs for later assertions.
    """

    def __init__(
        self,
        review_queue_size: int = 0,
        submit_raises: bool = False,
        promote_pattern: tuple[bool, ...] = (True, False),
    ):
        self.review_queue_size = review_queue_size
        self.submit_raises = submit_raises
        self.promote_pattern = promote_pattern
        self.submitted: list[StrategySpec] = []

    def list_review_queue(self) -> list[object]:
        return [object()] * self.review_queue_size

    def submit(self, spec: StrategySpec) -> ResearchOutcome:
        if self.submit_raises:
            raise RuntimeError("simulated factory failure")
        idx = len(self.submitted)
        self.submitted.append(spec)
        promoted = self.promote_pattern[idx % len(self.promote_pattern)]
        cand = CandidateRun(
            candidate_id=f"cand_{idx}",
            spec=spec,
            stage=ResearchStage.REVIEW_QUEUE if promoted else ResearchStage.ARCHIVED,
            is_metrics=None,
            wf_metrics=None,
            oos_dev_metrics=None,
            auditor_report_hash=None,
            rejection=None if promoted else RejectionReason.IS_SHARPE_TOO_LOW,
            rejection_detail=None if promoted else "stub failure",
            started_at=pd.Timestamp("2026-05-08T10:00:00"),
            finished_at=pd.Timestamp("2026-05-08T10:00:01"),
            cost_seconds=0.01,
        )
        return ResearchOutcome(
            promising=promoted,
            candidate=cand,
            summary="ok" if promoted else "rejected",
        )


# --------------------------------------------------------------------------
# Cycle behaviour
# --------------------------------------------------------------------------


def test_cycle_runs_and_logs(tmp_path: Path):
    factory = _FakeFactory()
    gen = _FakeGenerator(n_to_return=4)
    log = tmp_path / "auto_loop.jsonl"
    loop = AutoResearchLoop(
        factory=factory,
        generator=gen,
        config=AutoLoopConfig(n_specs_per_cycle=4),
        log_path=log,
    )
    summary = loop.run_cycle()
    assert isinstance(summary, CycleSummary)
    assert summary.n_generated == 4
    assert summary.n_submitted == 4
    # promote_pattern (True, False) -> 2 promoted, 2 archived
    assert summary.n_promoted == 2
    assert summary.n_archived == 2
    assert log.exists()
    assert log.read_text(encoding="utf-8").strip().count("\n") == 0  # one record


def test_cycle_dry_run_does_not_submit(tmp_path: Path):
    factory = _FakeFactory()
    gen = _FakeGenerator(n_to_return=3)
    log = tmp_path / "auto_loop.jsonl"
    loop = AutoResearchLoop(
        factory=factory,
        generator=gen,
        config=AutoLoopConfig(n_specs_per_cycle=3, dry_run=True),
        log_path=log,
    )
    summary = loop.run_cycle()
    assert summary.dry_run is True
    assert summary.n_generated == 3
    assert summary.n_submitted == 0
    assert factory.submitted == []
    assert any("dry_run" in n for n in summary.notes)


def test_cycle_skips_when_queue_cap_exceeded(tmp_path: Path):
    factory = _FakeFactory(review_queue_size=100)
    gen = _FakeGenerator(n_to_return=3)
    log = tmp_path / "auto_loop.jsonl"
    loop = AutoResearchLoop(
        factory=factory,
        generator=gen,
        config=AutoLoopConfig(n_specs_per_cycle=3, review_queue_cap=10),
        log_path=log,
    )
    summary = loop.run_cycle()
    assert summary.n_generated == 0
    assert summary.n_submitted == 0
    assert any("queue_cap_exceeded" in n for n in summary.notes)


def test_cycle_records_submit_exceptions(tmp_path: Path):
    factory = _FakeFactory(submit_raises=True)
    gen = _FakeGenerator(n_to_return=2)
    log = tmp_path / "auto_loop.jsonl"
    loop = AutoResearchLoop(
        factory=factory,
        generator=gen,
        config=AutoLoopConfig(n_specs_per_cycle=2),
        log_path=log,
    )
    summary = loop.run_cycle()
    assert summary.n_failed_with_exception == 2
    assert summary.n_submitted == 0
    assert any("submit_exception" in n for n in summary.notes)


def test_cycle_handles_generator_failure(tmp_path: Path):
    factory = _FakeFactory()
    gen = _FakeGenerator(n_to_return=3, fail=True)
    log = tmp_path / "auto_loop.jsonl"
    loop = AutoResearchLoop(
        factory=factory,
        generator=gen,
        config=AutoLoopConfig(n_specs_per_cycle=3),
        log_path=log,
    )
    summary = loop.run_cycle()
    assert summary.n_generated == 0
    assert any("generator_failed" in n for n in summary.notes)


def test_seed_increments_per_cycle(tmp_path: Path):
    factory = _FakeFactory()
    gen = _FakeGenerator(n_to_return=1)
    log = tmp_path / "auto_loop.jsonl"
    loop = AutoResearchLoop(
        factory=factory,
        generator=gen,
        config=AutoLoopConfig(n_specs_per_cycle=1, seed_base=10_000),
        log_path=log,
    )
    s0 = loop.run_cycle()
    s1 = loop.run_cycle()
    assert s0.seed == 10_000
    assert s1.seed == 10_001
    # Generator received both seeds.
    seeds_seen = [c[1] for c in gen.calls]
    assert seeds_seen == [10_000, 10_001]


def test_log_appends_one_line_per_cycle(tmp_path: Path):
    factory = _FakeFactory()
    gen = _FakeGenerator(n_to_return=1)
    log = tmp_path / "auto_loop.jsonl"
    loop = AutoResearchLoop(
        factory=factory,
        generator=gen,
        config=AutoLoopConfig(n_specs_per_cycle=1),
        log_path=log,
    )
    loop.run_cycle()
    loop.run_cycle()
    loop.run_cycle()
    lines = [
        line for line in log.read_text(encoding="utf-8").splitlines() if line
    ]
    assert len(lines) == 3
    # Each line is valid JSON with cycle_id.
    for line in lines:
        d = json.loads(line)
        assert "cycle_id" in d
        assert "timestamp_iso" in d
