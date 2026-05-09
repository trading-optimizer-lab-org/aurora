"""Tests for ``quantforge.research.factory`` (P1.C).

The factory is the automated hypothesis -> review-queue pipeline: agents
propose StrategySpecs, the factory runs IS / WF / OOS_DEV gates, and
either archives the candidate with a categorical RejectionReason or
promotes it to the human review queue.

These tests pin every gate in isolation by injecting fake ``backtest_fn``
/ ``walk_forward_fn`` / ``data_loader`` callables. The real engine is
separately tested in ``test_engine.py`` etc.; here we are testing the
factory's gating + persistence + lineage logic.
"""
from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.protocol_policy import ProtocolPolicy
from aurora.research.factory import (
    CandidateRun,
    GAHypothesisGenerator,
    LLMHypothesisGenerator,
    LineageGraph,
    RejectionReason,
    ResearchFactory,
    ResearchOutcome,
    ResearchPipelineConfig,
    ResearchStage,
    StrategySpec,
    TemplateHypothesisGenerator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def policy() -> ProtocolPolicy:
    return ProtocolPolicy.default()


@pytest.fixture
def synthetic_prices() -> pd.Series:
    idx = pd.date_range("2010-01-01", periods=400, freq="B")
    import numpy as np
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0005, 0.01, 400)
    return pd.Series(100.0 * np.exp(np.cumsum(rets)), index=idx, name="SPY")


@pytest.fixture
def factory(tmp_path: Path, policy: ProtocolPolicy, synthetic_prices: pd.Series):
    """Construct a fresh factory with isolated archive paths.

    The fake registry implements only the methods the factory calls.
    """

    class _StubRegistry:
        def __init__(self):
            self.started: list[dict] = []
            self.finished: list[dict] = []

        def start_experiment(self, **kw):
            xid = f"exp{len(self.started)}"
            self.started.append({"id": xid, **kw})
            return xid

        def finish_experiment(self, experiment_id, **kw):
            self.finished.append({"id": experiment_id, **kw})

    cfg = ResearchPipelineConfig(
        archive_path=tmp_path / "archive.jsonl",
        review_queue_path=tmp_path / "review.jsonl",
    )

    # Default fakes promote everything; individual tests override per-test.
    def _backtest(strategy_class, params, prices):
        return {"sharpe": 1.0, "calmar": 1.0, "cagr": 0.10, "mdd": -0.10}

    def _wf(strategy_class, params, prices):
        return {
            "n_pass": 4, "n_total": 4,
            "fold_sharpes": [0.8, 0.9, 0.95, 0.85],
            "oos_sharpe_mean": 0.875,
            "oos_sharpe_std": 0.05,
            "windows": [],
        }

    def _loader(symbol, max_tier="OOS_DEV"):
        return synthetic_prices

    f = ResearchFactory(
        cfg, policy, _StubRegistry(),
        backtest_fn=_backtest,
        walk_forward_fn=_wf,
        data_loader=_loader,
    )
    return f


@pytest.fixture
def good_spec(policy: ProtocolPolicy) -> StrategySpec:
    return StrategySpec.make(
        name="ma_cross_baseline",
        hypothesis="20/100 MA cross has positive long-term edge in equities.",
        expected_edge_bps=50.0,
        regime_dependence=["trending"],
        failure_modes=["high_vol_chop"],
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 20, "slow": 100, "allow_short": False},
        universe=["SPY"],
        rebalance="1d",
    )


# ---------------------------------------------------------------------------
# StrategySpec validate / hash
# ---------------------------------------------------------------------------


def test_strategy_spec_validate_empty_hypothesis():
    s = StrategySpec.make(
        name="x",
        hypothesis="   ",
        strategy_class="pkg.mod.X",
        params={"a": 1},
        universe=["SPY"],
    )
    errs = s.validate()
    assert any("hypothesis" in e.lower() for e in errs)


def test_strategy_spec_hash_deterministic():
    a = StrategySpec.make(
        name="n", hypothesis="h",
        strategy_class="pkg.mod.X",
        params={"k": 1, "j": 2},
        universe=["SPY"],
    )
    b = StrategySpec.make(
        name="n", hypothesis="h",
        strategy_class="pkg.mod.X",
        params={"j": 2, "k": 1},
        universe=["SPY"],
    )
    # Different spec_ids but identical canonical content -> same spec_hash
    assert a.spec_id != b.spec_id
    assert a.spec_hash == b.spec_hash
    assert a.verify_hash()


def test_strategy_spec_policy_hash_binding(factory, good_spec):
    """Generators MUST NOT set policy_hash; the factory binds it."""
    # Submit a spec that claims a fake policy_hash. The factory should
    # overwrite it with the active policy's hash before executing the
    # gates.
    forged = good_spec
    object.__setattr__(forged, "policy_hash", "deadbeef" * 8)
    out = factory.submit(forged)
    assert out.candidate.spec.policy_hash == factory.policy.policy_hash
    assert out.candidate.spec.policy_hash != "deadbeef" * 8


# ---------------------------------------------------------------------------
# CandidateRun + Config defaults
# ---------------------------------------------------------------------------


def test_candidate_run_immutable(good_spec):
    cand = CandidateRun(
        candidate_id="abc",
        spec=good_spec,
        stage=ResearchStage.PROPOSED,
    )
    with pytest.raises(FrozenInstanceError):
        cand.candidate_id = "other"


def test_research_pipeline_config_defaults():
    cfg = ResearchPipelineConfig()
    assert cfg.is_sharpe_min == 0.5
    assert cfg.is_max_drawdown == -0.30
    assert cfg.wf_degradation_max == 0.50
    assert cfg.wf_instability_max == 0.40
    assert cfg.oos_dev_sharpe_min == 0.3
    assert cfg.skip_oos_dev_if_wf_fails is True
    assert cfg.parallel_workers == 1
    assert str(cfg.archive_path).endswith("research_archive.jsonl")
    assert str(cfg.review_queue_path).endswith("research_review_queue.jsonl")


# ---------------------------------------------------------------------------
# Factory: happy path + per-gate rejection paths
# ---------------------------------------------------------------------------


def test_factory_submits_valid_spec(factory, good_spec):
    out = factory.submit(good_spec)
    assert out.promising is True
    assert out.candidate.stage == ResearchStage.REVIEW_QUEUE
    assert out.candidate.rejection is None
    queue = factory.list_review_queue()
    assert len(queue) == 1
    assert queue[0].candidate_id == out.candidate.candidate_id


def test_factory_rejects_invalid_spec(factory, policy):
    bad = StrategySpec.make(
        name="x", hypothesis="ok",
        strategy_class="not-a-fully-qualified-path",
        params={}, universe=[],  # empty universe also triggers a validation error
    )
    out = factory.submit(bad)
    assert out.promising is False
    assert out.candidate.rejection == RejectionReason.SPEC_INVALID
    archive = factory.list_archived()
    assert len(archive) == 1
    assert archive[0].rejection == RejectionReason.SPEC_INVALID


def test_factory_rejects_is_sharpe_too_low(factory, good_spec):
    factory._backtest_fn = lambda *_: {
        "sharpe": 0.1, "calmar": 0.1, "cagr": 0.01, "mdd": -0.05,
    }
    out = factory.submit(good_spec)
    assert out.promising is False
    assert out.candidate.rejection == RejectionReason.IS_SHARPE_TOO_LOW


def test_factory_rejects_is_drawdown_too_high(factory, good_spec):
    factory._backtest_fn = lambda *_: {
        "sharpe": 1.0, "calmar": 0.5, "cagr": 0.1, "mdd": -0.45,
    }
    out = factory.submit(good_spec)
    assert out.promising is False
    assert out.candidate.rejection == RejectionReason.IS_DRAWDOWN_TOO_HIGH


def test_factory_rejects_wf_degradation(factory, good_spec):
    # IS sharpe is 1.0 (default), oos_sharpe_mean=0.4 -> ratio 0.4 < 0.5
    factory._walk_forward_fn = lambda *_: {
        "n_pass": 1, "n_total": 4,
        "fold_sharpes": [0.4, 0.4, 0.4, 0.4],
        "oos_sharpe_mean": 0.4,
        "oos_sharpe_std": 0.0,
        "windows": [],
    }
    out = factory.submit(good_spec)
    assert out.promising is False
    assert out.candidate.rejection == RejectionReason.WF_DEGRADATION


def test_factory_rejects_wf_instability(factory, good_spec):
    # ratio 1.0/1.0 = 1.0, but std/|mean| = 0.6/0.6 = 1.0 > 0.4
    factory._walk_forward_fn = lambda *_: {
        "n_pass": 2, "n_total": 4,
        "fold_sharpes": [0.0, 1.2, -0.6, 1.2],
        "oos_sharpe_mean": 0.6,
        "oos_sharpe_std": 0.6,
        "windows": [],
    }
    out = factory.submit(good_spec)
    assert out.promising is False
    assert out.candidate.rejection == RejectionReason.WF_INSTABILITY


def test_factory_rejects_oos_dev_failure(factory, good_spec):
    """OOS_DEV gate trips when wf_sharpe < oos_dev_sharpe_min after WF passes.

    Tighten the OOS_DEV bar in the config so we can isolate that gate
    without colliding with the IS sharpe floor (0.5) and the WF
    degradation rule (oos/is >= 0.5).
    """
    # IS=0.6, WF=0.31 -> ratio 0.516 (passes 0.5), but the OOS_DEV bar
    # is now 0.4 so 0.31 < 0.4 -> OOS_DEV_FAILURE.
    factory.config.oos_dev_sharpe_min = 0.4
    factory._walk_forward_fn = lambda *_: {
        "n_pass": 2, "n_total": 4,
        "fold_sharpes": [0.31, 0.32, 0.30, 0.31],
        "oos_sharpe_mean": 0.31,
        "oos_sharpe_std": 0.01,
        "windows": [],
    }
    factory._backtest_fn = lambda *_: {
        "sharpe": 0.6, "calmar": 0.4, "cagr": 0.05, "mdd": -0.15,
    }
    out = factory.submit(good_spec)
    assert out.promising is False
    assert out.candidate.rejection == RejectionReason.OOS_DEV_FAILURE


def test_factory_rejects_auditor_hard_fail(factory, good_spec):
    """Auditor injection: HARD_FAIL routes to ARCHIVED."""

    class _FakeAuditor:
        def audit(self, candidate):
            class _Report:
                hard_fail = True
                report_hash = "abc123"
            return _Report()

    factory.auditor = _FakeAuditor()
    out = factory.submit(good_spec)
    assert out.promising is False
    assert out.candidate.rejection == RejectionReason.AUDITOR_HARD_FAIL
    assert out.candidate.auditor_report_hash == "abc123"


def test_factory_deduplicates_same_spec_hash(factory, good_spec):
    out1 = factory.submit(good_spec)
    assert out1.promising is True
    out2 = factory.submit(good_spec)
    assert out2.promising is False
    assert out2.candidate.rejection == RejectionReason.DUPLICATE_OF_EXISTING


def test_factory_promotes_promising_candidate_to_review_queue(factory, good_spec):
    factory.submit(good_spec)
    queue = factory.list_review_queue()
    assert len(queue) == 1
    assert queue[0].stage == ResearchStage.REVIEW_QUEUE
    assert queue[0].rejection is None


# ---------------------------------------------------------------------------
# Critical: factory NEVER touches OOS_LOCKED
# ---------------------------------------------------------------------------


def test_factory_never_touches_oos_locked(tmp_path, policy, synthetic_prices):
    """The factory's data loader MUST refuse to load OOS_LOCKED.

    We replace the loader with one that records every requested tier.
    The factory's _MAX_TIER is OOS_DEV; any internal call asking for a
    higher tier is a contract violation.
    """
    seen: list[str] = []

    def _loader(symbol, max_tier="OOS_DEV"):
        seen.append(max_tier)
        # The factory should never ask above OOS_DEV.
        if max_tier in ("OOS_LOCKED", "FORWARD"):
            raise AssertionError(
                f"factory tried to load tier {max_tier}; this is a "
                "contract violation."
            )
        return synthetic_prices

    cfg = ResearchPipelineConfig(
        archive_path=tmp_path / "archive.jsonl",
        review_queue_path=tmp_path / "review.jsonl",
    )

    class _Reg:
        def start_experiment(self, **kw):
            return "x"

        def finish_experiment(self, *a, **kw):
            return None

    f = ResearchFactory(
        cfg, policy, _Reg(),
        backtest_fn=lambda *_: {"sharpe": 1.0, "mdd": -0.1, "calmar": 1.0, "cagr": 0.1},
        walk_forward_fn=lambda *_: {
            "n_pass": 4, "n_total": 4, "fold_sharpes": [0.9, 0.9, 0.9, 0.9],
            "oos_sharpe_mean": 0.9, "oos_sharpe_std": 0.0, "windows": [],
        },
        data_loader=_loader,
    )

    spec = StrategySpec.make(
        name="ok", hypothesis="ok",
        strategy_class="pkg.mod.X", params={}, universe=["SPY"],
    )
    f.submit(spec)
    assert seen == ["OOS_DEV"]
    # Direct call on the default loader for OOS_LOCKED must refuse.
    with pytest.raises(RuntimeError, match="OOS_DEV|OOS_LOCKED"):
        f._default_data_loader("SPY", max_tier="OOS_LOCKED")
    with pytest.raises(RuntimeError, match="OOS_DEV|FORWARD"):
        f._default_data_loader("SPY", max_tier="FORWARD")


# ---------------------------------------------------------------------------
# Persistence (JSONL append-only)
# ---------------------------------------------------------------------------


def test_factory_archive_is_jsonl_append_only(factory, good_spec, tmp_path):
    # Bad spec -> archive grows by 1
    bad = StrategySpec.make(
        name="x", hypothesis="ok",
        strategy_class="bad-no-dot",
        params={}, universe=[],
    )
    factory.submit(bad)
    factory._backtest_fn = lambda *_: {
        "sharpe": 0.0, "calmar": 0.0, "cagr": 0.0, "mdd": 0.0,
    }
    factory.submit(good_spec)
    arch = factory.config.archive_path
    assert arch.exists()
    lines = [ln for ln in arch.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        rec = json.loads(ln)
        assert "candidate_id" in rec
        assert rec["stage"] == "archived"


def test_factory_review_queue_is_jsonl(factory, good_spec):
    factory.submit(good_spec)
    rq = factory.config.review_queue_path
    assert rq.exists()
    lines = [ln for ln in rq.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["stage"] == "review_queue"
    assert rec["spec"]["name"] == "ma_cross_baseline"


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


def test_lineage_parent_child_traversal(factory):
    parent = StrategySpec.make(
        name="root", hypothesis="root",
        strategy_class="pkg.mod.X",
        params={"a": 1}, universe=["SPY"],
    )
    child = StrategySpec.make(
        name="child", hypothesis="child",
        strategy_class="pkg.mod.X",
        params={"a": 2}, universe=["SPY"],
        parent_spec_id=parent.spec_id,
    )
    factory.submit(parent)
    factory.submit(child)
    chain = factory.get_lineage(child.spec_id)
    # chain is root-first then the requested spec_id.
    assert [c.spec.spec_id for c in chain] == [parent.spec_id, child.spec_id]


def test_lineage_circular_detection():
    """A malformed JSONL with a cycle must not loop forever."""
    g = LineageGraph()
    a = StrategySpec.make(
        name="a", hypothesis="a",
        strategy_class="pkg.mod.X",
        params={"a": 1}, universe=["SPY"],
        parent_spec_id="bid",
    )
    b = StrategySpec.make(
        spec_id="bid",
        name="b", hypothesis="b",
        strategy_class="pkg.mod.X",
        params={"a": 2}, universe=["SPY"],
        parent_spec_id=a.spec_id,
    )
    cand_a = CandidateRun(
        candidate_id="ca", spec=a, stage=ResearchStage.REVIEW_QUEUE,
    )
    cand_b = CandidateRun(
        candidate_id="cb", spec=b, stage=ResearchStage.REVIEW_QUEUE,
    )
    g.add(cand_a)
    g.add(cand_b)
    # Should not loop forever: the visited set bounds the traversal.
    descendants = g.query_descendants(a.spec_id)
    ancestors = g.query_ancestors(a.spec_id)
    assert all(isinstance(c, CandidateRun) for c in descendants + ancestors)
    # Both nodes are reachable in the graph; we just want determinism.
    assert len(descendants) <= 2
    assert len(ancestors) <= 2


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


def test_ga_hypothesis_generator_emits_valid_specs():
    pareto = [
        ({"fast": 10, "slow": 50}, (0.05, 0.6, 1.2, -0.10)),
        ({"fast": 20, "slow": 100}, (0.04, 0.7, 1.3, -0.12)),
    ]
    gen = GAHypothesisGenerator(
        "aurora.strategies.library.ma_cross.MACross",
        pareto,
        universe=["SPY"],
    )
    specs = gen.generate(n=2, seed=1)
    assert len(specs) == 2
    for s in specs:
        assert s.generator == "ga"
        assert s.validate() == []


def test_template_hypothesis_generator_emits_valid_specs():
    templates = [
        (
            "macross_demo",
            "aurora.strategies.library.ma_cross.MACross",
            {"fast": 20, "slow": 100, "allow_short": False},
            {"fast": (0.5, 1.5), "slow": (0.8, 1.5)},
        ),
    ]
    gen = TemplateHypothesisGenerator(templates, universe=["SPY"])
    specs = gen.generate(n=3, seed=42)
    assert len(specs) == 3
    for s in specs:
        assert s.generator == "template"
        assert s.validate() == []
        # Jitter respected
        assert isinstance(s.params["fast"], int)


def test_llm_hypothesis_generator_fails_gracefully_without_client():
    gen = LLMHypothesisGenerator(client=None)
    with pytest.raises(RuntimeError, match="no client injected"):
        gen.generate(n=1, seed=0)


# ---------------------------------------------------------------------------
# CLI promote: ceremony enforcement
# ---------------------------------------------------------------------------


def test_research_promote_requires_ceremony_flag(factory, good_spec, capsys, monkeypatch):
    """Without --i-understand-..., promote returns 1 with a useful message."""
    from aurora.cli import forge as forge_cli
    factory.submit(good_spec)
    # Patch the loader so the CLI command picks up our isolated factory.
    monkeypatch.setattr(
        forge_cli, "_load_research_factory", lambda args: factory,
    )

    # Pull the candidate id from the queue
    cid = factory.list_review_queue()[0].candidate_id

    class _Args:
        candidate_id = cid
        i_understand = False
        config_path = None

    rc = forge_cli.cmd_research_promote(_Args())
    assert rc == 1
    err = capsys.readouterr().err
    assert "i-understand-promote-to-oos-locked" in err


def test_research_promote_without_oos_guard_refuses(
    factory, good_spec, capsys, monkeypatch,
):
    """With ceremony flag but no active OOSGuard, the CLI refuses."""
    from aurora.cli import forge as forge_cli
    from aurora.core.data_layer import OOSGuard

    factory.submit(good_spec)
    monkeypatch.setattr(
        forge_cli, "_load_research_factory", lambda args: factory,
    )
    cid = factory.list_review_queue()[0].candidate_id

    class _Args:
        candidate_id = cid
        i_understand = True
        config_path = None

    # Make sure there's no active OOSGuard.
    assert OOSGuard.active() is None
    rc = forge_cli.cmd_research_promote(_Args())
    assert rc == 1
    err = capsys.readouterr().err
    assert "OOSGuard" in err


def test_research_promote_with_ceremony_and_guard_succeeds(
    factory, good_spec, capsys, monkeypatch, tmp_path,
):
    """With both ceremony flag AND OOSGuard active, promote returns 0."""
    from aurora.cli import forge as forge_cli
    from aurora.core.data_layer import OOSGuard

    factory.submit(good_spec)
    monkeypatch.setattr(
        forge_cli, "_load_research_factory", lambda args: factory,
    )
    cid = factory.list_review_queue()[0].candidate_id

    class _Args:
        candidate_id = cid
        i_understand = True
        config_path = None

    lock_path = str(tmp_path / "oos_lock.json")
    with OOSGuard("explicit_unlock_oos_locked", lock_path=lock_path):
        rc = forge_cli.cmd_research_promote(_Args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "PROMOTED" in out
    assert "oos_locked" in out
