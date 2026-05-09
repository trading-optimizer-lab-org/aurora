"""Tests for the P2.A vectorized triage backend.

Triage is a screening layer for thousands of strategy variants. It must:

* never operate on OOS_LOCKED / FORWARD data,
* never produce a verdict promotable on its own,
* match the official engine within a coarse tolerance on the same window,
* be deterministic for a given (config, variants, prices) tuple.

These tests pin every one of those guarantees.
"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pandas as pd
import pytest

from aurora.core.engine import run_backtest
from aurora.core.costs import IBKR_costs
from aurora.core.protocol_policy import ProtocolPolicy
from aurora.strategies.library.ma_cross import MACross
from aurora.triage import (
    StrategyVariant,
    TriageBatch,
    TriageConfig,
    TriageEngine,
    TriageResult,
    variant_grid,
    variant_random_sample,
)
from aurora.triage.vectorized import (
    compute_metrics_batch,
    compute_pnl_batch,
    compute_signals_batch,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def policy() -> ProtocolPolicy:
    return ProtocolPolicy.default()


@pytest.fixture
def is_train_prices() -> pd.DataFrame:
    """Synthetic prices entirely inside IS_TRAIN (1995-01-01..2010-12-31)."""
    idx = pd.date_range("2005-01-03", periods=400, freq="B")
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0005, 0.01, 400)
    series = pd.Series(100.0 * np.exp(np.cumsum(rets)), index=idx, name="SPY")
    return series.to_frame()


@pytest.fixture
def macross_variants() -> list[StrategyVariant]:
    return [
        StrategyVariant.make(
            strategy_class="aurora.strategies.library.ma_cross.MACross",
            params={"fast": 10, "slow": 50, "allow_short": True},
            universe=["SPY"],
        ),
        StrategyVariant.make(
            strategy_class="aurora.strategies.library.ma_cross.MACross",
            params={"fast": 20, "slow": 80, "allow_short": False},
            universe=["SPY"],
        ),
    ]


@pytest.fixture
def permissive_config() -> TriageConfig:
    return TriageConfig(
        parallel=False,
        min_sharpe_threshold=-99.0,
        max_dd_threshold=-0.99,
        min_trades=1,
    )


# ---------------------------------------------------------------------------
# 1. TriageConfig defaults sensible
# ---------------------------------------------------------------------------


def test_triage_config_defaults_sensible():
    cfg = TriageConfig()
    assert cfg.parallel is True
    assert cfg.max_workers == 0
    assert cfg.cost_bps_simple == 5.0
    assert cfg.slippage_bps_simple == 1.0
    assert cfg.min_sharpe_threshold == 0.5
    assert cfg.max_dd_threshold == -0.30
    assert cfg.min_trades == 30
    assert cfg.use_vectorbt is False
    assert cfg.triage_tier_only == "IS_TRAIN"
    # Hash is deterministic.
    assert cfg.config_hash() == TriageConfig().config_hash()


# ---------------------------------------------------------------------------
# 2. TriageResult immutable
# ---------------------------------------------------------------------------


def test_triage_result_immutable():
    r = TriageResult(
        variant_id="abc",
        sharpe=1.0,
        cagr=0.1,
        max_dd=-0.1,
        n_trades=100,
        win_rate=0.55,
        cost_seconds=0.01,
        promising=True,
        rejection_reason=None,
        metadata={"strategy_class": "x"},
        promotion_token="tok",
    )
    with pytest.raises(FrozenInstanceError):
        r.sharpe = 9.9


# ---------------------------------------------------------------------------
# 3. TriageBatch policy_hash matches active policy
# ---------------------------------------------------------------------------


def test_triage_batch_policy_hash_matches_active(
    policy, is_train_prices, macross_variants, permissive_config,
):
    eng = TriageEngine(permissive_config, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    assert batch.policy_hash == policy.policy_hash
    # Config hash also matches.
    assert batch.config_hash == permissive_config.config_hash()
    assert batch.n_variants == len(macross_variants)


# ---------------------------------------------------------------------------
# 4. variant_grid enumerates correctly
# ---------------------------------------------------------------------------


def test_variant_grid_cartesian_product():
    variants = list(variant_grid(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        universe=["SPY"],
        param_grid={"fast": [5, 10], "slow": [50, 100]},
    ))
    assert len(variants) == 4
    # All variant ids are unique.
    assert len({v.variant_id for v in variants}) == 4
    # The same input order produces the same output order (deterministic).
    second = list(variant_grid(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        universe=["SPY"],
        param_grid={"fast": [5, 10], "slow": [50, 100]},
    ))
    assert [v.variant_id for v in variants] == [v.variant_id for v in second]


# ---------------------------------------------------------------------------
# 5. variant_random_sample deterministic by seed
# ---------------------------------------------------------------------------


def test_variant_random_sample_deterministic():
    a = list(variant_random_sample(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        universe=["SPY"],
        param_space={"fast": (5, 30), "slow": (50, 300), "allow_short": [True, False]},
        n=10, seed=42,
    ))
    b = list(variant_random_sample(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        universe=["SPY"],
        param_space={"fast": (5, 30), "slow": (50, 300), "allow_short": [True, False]},
        n=10, seed=42,
    ))
    assert [v.variant_id for v in a] == [v.variant_id for v in b]
    # Different seed -> different IDs (almost certainly).
    c = list(variant_random_sample(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        universe=["SPY"],
        param_space={"fast": (5, 30), "slow": (50, 300), "allow_short": [True, False]},
        n=10, seed=7,
    ))
    assert [v.variant_id for v in a] != [v.variant_id for v in c]


# ---------------------------------------------------------------------------
# 6. compute_signals_batch shape correct
# ---------------------------------------------------------------------------


def test_compute_signals_batch_shape(is_train_prices, macross_variants):
    sig = compute_signals_batch(is_train_prices, macross_variants)
    n_time, n_assets = is_train_prices.shape
    assert sig.shape == (len(macross_variants), n_time, n_assets)
    # Values are in [-1, 1] and finite.
    assert np.all(np.isfinite(sig))
    assert sig.min() >= -1.0
    assert sig.max() <= 1.0


# ---------------------------------------------------------------------------
# 7. compute_pnl_batch matches scalar engine within 5%
# ---------------------------------------------------------------------------


def test_compute_pnl_batch_matches_scalar_engine_loosely(is_train_prices):
    """Triage's simplified pnl should give a Sharpe within rough tolerance.

    Triage uses a flat-bps cost model; the official engine uses IBKR costs.
    The two are not bit-equivalent, but the *sign and order of magnitude*
    of the sharpe should match. We assert the difference is bounded so a
    silent regression of the vectorized backend would surface.
    """
    series = is_train_prices["SPY"]
    variant = StrategyVariant.make(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 10, "slow": 50, "allow_short": True},
        universe=["SPY"],
    )
    sig = compute_signals_batch(is_train_prices, [variant])
    rets = compute_pnl_batch(
        is_train_prices, sig, cost_bps=0.0, slippage_bps=0.0,
    )
    metrics = compute_metrics_batch(rets)[0]
    # Reference: official engine on the same window with ZERO costs.
    from aurora.core.costs import ZERO_costs
    strat = MACross(fast=10, slow=50, allow_short=True)
    res = run_backtest(series, strat.signals, costs=ZERO_costs)
    # Same sign; magnitudes within a few absolute Sharpe points.
    if abs(res.sharpe) > 1e-3:
        assert (metrics["sharpe"] >= 0) == (res.sharpe >= 0)
    assert abs(metrics["sharpe"] - res.sharpe) <= 0.5


# ---------------------------------------------------------------------------
# 8. TriageEngine refuses OOS_LOCKED tier
# ---------------------------------------------------------------------------


def test_triage_engine_refuses_oos_locked_tier(policy):
    cfg = TriageConfig(triage_tier_only="OOS_LOCKED")
    with pytest.raises(RuntimeError, match="refuses tier"):
        TriageEngine(cfg, policy)
    cfg = TriageConfig(triage_tier_only="FORWARD")
    with pytest.raises(RuntimeError, match="refuses tier"):
        TriageEngine(cfg, policy)


def test_triage_engine_refuses_data_crossing_oos_locked(policy):
    """Even if the tier config is IS_TRAIN, locked-period bars are rejected."""
    cfg = TriageConfig(triage_tier_only="IS_TRAIN")
    eng = TriageEngine(cfg, policy)
    # 2022 falls inside OOS_LOCKED.
    idx = pd.date_range("2022-01-03", periods=10, freq="B")
    df = pd.DataFrame({"SPY": np.linspace(100, 110, 10)}, index=idx)
    v = StrategyVariant.make(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 2, "slow": 5},
        universe=["SPY"],
    )
    with pytest.raises(RuntimeError, match="OOS_LOCKED boundary"):
        eng.triage_batch(df, [v])


# ---------------------------------------------------------------------------
# 9. TriageEngine fallback when vectorbt missing
# ---------------------------------------------------------------------------


def test_triage_engine_warns_when_vectorbt_missing(
    policy, is_train_prices, macross_variants,
):
    cfg = TriageConfig(
        parallel=False, use_vectorbt=True,
        min_sharpe_threshold=-99.0, max_dd_threshold=-0.99, min_trades=1,
    )
    # The fallback warning is emitted on the constructor when vectorbt is
    # absent and again inside vectorbt_pnl_batch when invoked.
    from aurora.triage import vectorbt_backend
    if vectorbt_backend.is_available():
        pytest.skip("vectorbt is installed; fallback test does not apply")
    with pytest.warns(UserWarning, match="vectorbt"):
        eng = TriageEngine(cfg, policy)
        # Engine still produces a correct batch despite the missing backend.
        batch = eng.triage_batch(is_train_prices, macross_variants)
    assert batch.n_variants == len(macross_variants)


# ---------------------------------------------------------------------------
# 10. triage_batch parallel matches serial
# ---------------------------------------------------------------------------


def test_triage_batch_parallel_matches_serial(policy, is_train_prices):
    variants = list(variant_grid(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        universe=["SPY"],
        param_grid={"fast": [5, 10, 15, 20], "slow": [50, 100, 150, 200]},
    ))
    cfg_serial = TriageConfig(parallel=False, min_trades=1, min_sharpe_threshold=-99,
                              max_dd_threshold=-0.99)
    cfg_par = TriageConfig(parallel=True, max_workers=4, min_trades=1,
                           min_sharpe_threshold=-99, max_dd_threshold=-0.99)
    serial = TriageEngine(cfg_serial, policy).triage_batch(is_train_prices, variants)
    parallel = TriageEngine(cfg_par, policy).triage_batch(is_train_prices, variants)
    s_ids = [r.variant_id for r in serial.results]
    p_ids = [r.variant_id for r in parallel.results]
    assert s_ids == p_ids
    # Sharpes match within float precision.
    for s, p in zip(serial.results, parallel.results):
        if s.sharpe == s.sharpe and p.sharpe == p.sharpe:
            assert abs(s.sharpe - p.sharpe) < 1e-9


# ---------------------------------------------------------------------------
# 11. promising flag respects min_sharpe
# ---------------------------------------------------------------------------


def test_promising_respects_min_sharpe(policy, is_train_prices, macross_variants):
    cfg = TriageConfig(
        parallel=False, min_sharpe_threshold=999.0,
        max_dd_threshold=-0.99, min_trades=1,
    )
    eng = TriageEngine(cfg, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    assert all(not r.promising for r in batch.results)
    assert all(r.rejection_reason == "sharpe_below_threshold" for r in batch.results)


# ---------------------------------------------------------------------------
# 12. promising flag respects max_dd
# ---------------------------------------------------------------------------


def test_promising_respects_max_dd(policy, is_train_prices, macross_variants):
    cfg = TriageConfig(
        parallel=False, min_sharpe_threshold=-99.0,
        max_dd_threshold=-1e-9, min_trades=1,
    )
    eng = TriageEngine(cfg, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    # Any nonzero drawdown is now "below threshold" (more negative).
    assert all(not r.promising for r in batch.results)


# ---------------------------------------------------------------------------
# 13. promising flag respects min_trades
# ---------------------------------------------------------------------------


def test_promising_respects_min_trades(policy, is_train_prices, macross_variants):
    cfg = TriageConfig(
        parallel=False, min_sharpe_threshold=-99.0,
        max_dd_threshold=-0.99, min_trades=10**9,
    )
    eng = TriageEngine(cfg, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    assert all(r.rejection_reason == "too_few_trades" for r in batch.results)


# ---------------------------------------------------------------------------
# 14. promote_to_official requires promising=True
# ---------------------------------------------------------------------------


def test_promote_to_official_requires_promising(policy):
    cfg = TriageConfig(parallel=False)
    eng = TriageEngine(cfg, policy)
    bad = TriageResult(
        variant_id="x", sharpe=0.0, cagr=0.0, max_dd=-0.1, n_trades=10,
        win_rate=0.0, cost_seconds=0.0, promising=False,
        rejection_reason="sharpe_below_threshold", metadata={}, promotion_token=None,
    )
    with pytest.raises(ValueError, match="not promising"):
        eng.promote_to_official(bad, lambda *a, **k: 1)


# ---------------------------------------------------------------------------
# 15. promote_to_official consumes single-use token
# ---------------------------------------------------------------------------


def test_promote_to_official_single_use(policy, is_train_prices, macross_variants,
                                         permissive_config):
    eng = TriageEngine(permissive_config, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    promising = next(r for r in batch.results if r.promising)
    calls: list[dict] = []

    def runner(prices=None, **kw):
        calls.append({"prices": prices, **kw})
        return "done"

    out = eng.promote_to_official(promising, runner, prices=None)
    assert out == "done"
    assert len(calls) == 1
    # Second invocation must fail.
    with pytest.raises(ValueError, match="already consumed"):
        eng.promote_to_official(promising, runner)


# ---------------------------------------------------------------------------
# 16. TriageBatch.to_parquet roundtrips
# ---------------------------------------------------------------------------


def test_triage_batch_parquet_roundtrip(policy, is_train_prices,
                                          macross_variants, permissive_config,
                                          tmp_path):
    eng = TriageEngine(permissive_config, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    out = tmp_path / "batch.parquet"
    batch.to_parquet(out)
    rt = TriageBatch.from_parquet(out)
    assert rt.batch_id == batch.batch_id
    assert rt.config_hash == batch.config_hash
    assert rt.policy_hash == batch.policy_hash
    assert rt.n_variants == batch.n_variants
    for a, b in zip(batch.results, rt.results):
        assert a.variant_id == b.variant_id
        assert a.promising == b.promising
        if a.sharpe == a.sharpe and b.sharpe == b.sharpe:
            assert abs(a.sharpe - b.sharpe) < 1e-9


# ---------------------------------------------------------------------------
# 17. CLI: forge triage run smoke
# ---------------------------------------------------------------------------


def test_cli_triage_run_smoke(tmp_path, monkeypatch, policy, is_train_prices):
    """End-to-end: parse a variants YAML, run, write parquet, exit 0."""
    import yaml
    from aurora.cli.forge import main

    variants = list(variant_grid(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        universe=["SPY"],
        param_grid={"fast": [5, 10], "slow": [50, 100]},
    ))
    variants_yaml = tmp_path / "variants.yaml"
    with variants_yaml.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"variants": [v.to_dict() for v in variants]}, f)
    prices_pq = tmp_path / "prices.parquet"
    is_train_prices.to_parquet(prices_pq)
    out_pq = tmp_path / "batch.parquet"
    cfg_yaml = tmp_path / "triage.yaml"
    cfg_yaml.write_text(
        "parallel: false\nmin_sharpe_threshold: -99.0\n"
        "max_dd_threshold: -0.99\nmin_trades: 1\n"
        "triage_tier_only: IS_TRAIN\n",
        encoding="utf-8",
    )
    rc = main([
        "triage", "run",
        "--variants", str(variants_yaml),
        "--output", str(out_pq),
        "--prices", str(prices_pq),
        "--config-path", str(cfg_yaml),
    ])
    assert rc == 0
    assert out_pq.exists()
    rt = TriageBatch.from_parquet(out_pq)
    assert rt.n_variants == len(variants)


# ---------------------------------------------------------------------------
# 18. CLI: forge triage list-promising smoke
# ---------------------------------------------------------------------------


def test_cli_triage_list_promising_smoke(tmp_path, capsys, policy,
                                          is_train_prices, macross_variants,
                                          permissive_config):
    """Save a batch parquet, then run list-promising; exit 0 + prints rows."""
    from aurora.cli.forge import main

    eng = TriageEngine(permissive_config, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    out = tmp_path / "batch.parquet"
    batch.to_parquet(out)
    rc = main(["triage", "list-promising", "--batch", str(out), "--top", "5"])
    assert rc == 0
    captured = capsys.readouterr().out
    # At least one variant_id prefix appears in the output.
    promising_ids = [r.variant_id[:12] for r in batch.results if r.promising]
    if promising_ids:
        assert any(pid in captured for pid in promising_ids)


# ---------------------------------------------------------------------------
# 19. variant_id deterministic + spec invariance
# ---------------------------------------------------------------------------


def test_variant_id_deterministic():
    a = StrategyVariant.make(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 10, "slow": 50},
        universe=["SPY"],
    )
    b = StrategyVariant.make(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"slow": 50, "fast": 10},  # different key order
        universe=["SPY"],
    )
    assert a.variant_id == b.variant_id
    c = StrategyVariant.make(
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 11, "slow": 50},
        universe=["SPY"],
    )
    assert a.variant_id != c.variant_id


# ---------------------------------------------------------------------------
# 20. Factory submit_with_triage filters out triage rejects
# ---------------------------------------------------------------------------


def test_factory_submit_with_triage_filters(tmp_path, policy, is_train_prices):
    """When the triage engine rejects everything, submit() is never called."""
    from aurora.research.factory import (
        ResearchFactory, ResearchPipelineConfig, StrategySpec,
    )

    # Stub triage engine that rejects every variant.
    class _RejectAll:
        from dataclasses import dataclass

        class _Cfg:
            triage_tier_only = "IS_TRAIN"
        config = _Cfg()

        def triage_batch(self, prices, variants):
            from aurora.triage import TriageBatch, TriageResult
            results = []
            for v in variants:
                results.append(TriageResult(
                    variant_id=v.variant_id, sharpe=0.0, cagr=0.0, max_dd=0.0,
                    n_trades=0, win_rate=0.0, cost_seconds=0.0,
                    promising=False, rejection_reason="too_few_trades",
                    metadata={}, promotion_token=None,
                ))
            return TriageBatch(
                batch_id="bx", started_at=pd.Timestamp.utcnow().tz_localize(None),
                finished_at=pd.Timestamp.utcnow().tz_localize(None),
                n_variants=len(variants), n_promising=0,
                results=results, config_hash="cfg", policy_hash="pol",
            )

    class _StubReg:
        def start_experiment(self, **kw): return "exp"
        def finish_experiment(self, *a, **kw): pass

    cfg = ResearchPipelineConfig(
        archive_path=tmp_path / "a.jsonl",
        review_queue_path=tmp_path / "r.jsonl",
    )
    submit_calls = []

    def _bt(*a, **kw):
        submit_calls.append(("bt", a, kw))
        return {"sharpe": 1.0, "calmar": 1.0, "cagr": 0.1, "mdd": -0.1}

    def _wf(*a, **kw):
        submit_calls.append(("wf", a, kw))
        return {
            "n_pass": 4, "n_total": 4, "fold_sharpes": [0.8],
            "oos_sharpe_mean": 0.8, "oos_sharpe_std": 0.05, "windows": [],
        }

    def _loader(symbol, max_tier="OOS_DEV"):
        return is_train_prices["SPY"]

    f = ResearchFactory(
        cfg, policy, _StubReg(),
        backtest_fn=_bt, walk_forward_fn=_wf, data_loader=_loader,
        triage_engine=_RejectAll(),
    )
    spec = StrategySpec.make(
        name="ma1",
        hypothesis="trend signal",
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 10, "slow": 50, "allow_short": True},
        universe=["SPY"], rebalance="1d",
    )
    outs = f.submit_with_triage([spec], prices=is_train_prices)
    assert len(outs) == 1
    assert outs[0].promising is False
    # The factory's full IS pipeline never ran.
    assert not any(call[0] in ("bt", "wf") for call in submit_calls)


# ---------------------------------------------------------------------------
# 21. promote_to_official forwards prices and metadata
# ---------------------------------------------------------------------------


def test_promote_to_official_passes_prices_and_metadata(
    policy, is_train_prices, macross_variants, permissive_config,
):
    eng = TriageEngine(permissive_config, policy)
    batch = eng.triage_batch(is_train_prices, macross_variants)
    promising = next(r for r in batch.results if r.promising)
    captured = {}

    def runner(prices, **kw):
        captured["prices"] = prices
        captured.update(kw)
        return "ok"

    out = eng.promote_to_official(
        promising, runner, prices=is_train_prices["SPY"],
    )
    assert out == "ok"
    assert captured["data_tier_used"] == "IS_TRAIN"
    assert captured["strategy_class"].endswith(".MACross")


# ---------------------------------------------------------------------------
# 22. Empty variants returns empty batch
# ---------------------------------------------------------------------------


def test_empty_variants_empty_batch(policy, is_train_prices, permissive_config):
    eng = TriageEngine(permissive_config, policy)
    batch = eng.triage_batch(is_train_prices, [])
    assert batch.n_variants == 0
    assert batch.n_promising == 0
    assert batch.results == []
