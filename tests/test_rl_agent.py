"""Tests for aurora.ml.rl_agent.

All tests skip when gymnasium or stable_baselines3 is not installed.

Run with optional deps:
    uv run --with gymnasium --with stable-baselines3 \
        pytest aurora/tests/test_rl_agent.py -v
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pandas as pd
import pytest

# Skip the entire module if optional deps are missing.
gym = pytest.importorskip("gymnasium")
sb3 = pytest.importorskip("stable_baselines3")

from aurora.ml.rl_agent import (  # noqa: E402
    GYM_AVAILABLE,
    SB3_AVAILABLE,
    RLAgent,
    RLAgentConfig,
    TradingEnv,
    TradingEnvConfig,
    evaluate_policy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_prices() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 200
    rets = rng.normal(0.0005, 0.01, n)
    close = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(
        {
            "close": close,
            "feat1": rets,
            "feat2": np.cumsum(rets),
        },
        index=idx,
    )


@pytest.fixture
def env(synthetic_prices) -> TradingEnv:
    cfg = TradingEnvConfig(
        max_position=1,
        cost_bps=1.0,
        window=10,
        feature_columns=["close", "feat1", "feat2"],
    )
    return TradingEnv(synthetic_prices, cfg)


# ---------------------------------------------------------------------------
# Module flags
# ---------------------------------------------------------------------------

def test_module_flags_true_when_imported():
    assert GYM_AVAILABLE is True
    assert SB3_AVAILABLE is True


# ---------------------------------------------------------------------------
# Env basics
# ---------------------------------------------------------------------------

def test_env_reset(env):
    obs, info = env.reset(seed=0)
    assert isinstance(obs, np.ndarray)
    assert env.observation_space.contains(obs)
    assert isinstance(info, dict)
    assert "position" in info
    assert info["position"] == 0


def test_observation_space(synthetic_prices):
    cfg = TradingEnvConfig(
        window=15,
        feature_columns=["close", "feat1", "feat2"],
    )
    env_local = TradingEnv(synthetic_prices, cfg)
    expected = cfg.window * 3 + 1
    assert env_local.observation_space.shape == (expected,)


def test_action_space(env):
    # max_position=1 => Discrete(3)
    assert env.action_space.n == 3


def test_env_step_action_long(env):
    env.reset(seed=0)
    # Action index 2 = long (target_position = 2 - 1 = +1)
    obs, reward, terminated, truncated, info = env.step(2)
    assert info["position"] == 1
    assert info["prev_position"] == 0
    assert info["position_change"] == 1
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)


def test_env_step_cost(env):
    env.reset(seed=0)
    # Going from 0 -> +1 costs cost_bps/10000 * 1 = 0.0001 (with reward_scale=1).
    _obs, reward, _t, _tr, info = env.step(2)
    assert info["position_change"] == 1
    assert info["cost"] == pytest.approx(1.0 / 10_000.0)
    # Reward = prev_position(0) * pct_ret - cost
    assert reward == pytest.approx(-info["cost"])


def test_env_terminated(synthetic_prices):
    cfg = TradingEnvConfig(window=5, feature_columns=["close", "feat1", "feat2"])
    env_local = TradingEnv(synthetic_prices, cfg)
    env_local.reset(seed=0)
    terminated = False
    truncated = False
    steps = 0
    max_steps = len(synthetic_prices) + 5
    while not (terminated or truncated) and steps < max_steps:
        _obs, _r, terminated, truncated, _info = env_local.step(1)  # flat
        steps += 1
    assert terminated is True
    # Should terminate near the last bar.
    assert steps <= len(synthetic_prices)


# ---------------------------------------------------------------------------
# RLAgent
# ---------------------------------------------------------------------------

def test_rl_agent_train_short(env):
    cfg = RLAgentConfig(algo="PPO", total_timesteps=100, learning_rate=3e-4, seed=0)
    agent = RLAgent(env, cfg)
    info = agent.train()
    assert isinstance(info, dict)
    assert info["algo"] == "PPO"
    assert info["total_timesteps"] == 100


def test_rl_agent_predict(env):
    cfg = RLAgentConfig(algo="PPO", total_timesteps=64, learning_rate=3e-4, seed=0)
    agent = RLAgent(env, cfg)
    agent.train()
    obs, _info = env.reset(seed=1)
    action = agent.predict(obs)
    assert isinstance(action, int)
    assert 0 <= action < env.action_space.n


def test_save_load(env):
    cfg = RLAgentConfig(algo="PPO", total_timesteps=64, learning_rate=3e-4, seed=0)
    agent = RLAgent(env, cfg)
    agent.train()
    obs, _info = env.reset(seed=2)
    action_before = agent.predict(obs)

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ppo_model")
        agent.save(path)

        # Brand-new agent reloads weights.
        agent2 = RLAgent(env, cfg)
        agent2.load(path, env)
        action_after = agent2.predict(obs)

    assert action_after == action_before


def test_evaluate_policy(env):
    cfg = RLAgentConfig(algo="PPO", total_timesteps=64, learning_rate=3e-4, seed=0)
    agent = RLAgent(env, cfg)
    agent.train()
    metrics = evaluate_policy(agent, env, n_episodes=1)
    assert isinstance(metrics, dict)
    for key in ("total_return", "sharpe", "max_drawdown", "n_trades"):
        assert key in metrics
    assert isinstance(metrics["n_trades"], int)
    assert metrics["n_episodes"] == 1


# ---------------------------------------------------------------------------
# Audit fix: equity curve must reflect compound returns + cost as separate
# cash debit (issue #10), and Sharpe must accept a bars_per_year param (#11).
# ---------------------------------------------------------------------------


def test_rl_env_equity_curves_correctly(synthetic_prices):
    """Hold a +1 long for the entire episode with zero costs.

    With zero cost and a constant +1 position, equity should equal initial
    cash compounded by the realized log-returns of the close price across
    bars [window..N-1]. Use cost_bps=0 to isolate the compounding logic.
    """
    cfg = TradingEnvConfig(
        max_position=1,
        cost_bps=0.0,
        window=10,
        feature_columns=["close", "feat1", "feat2"],
        initial_cash=1.0,
    )
    e = TradingEnv(synthetic_prices, cfg)
    e.reset(seed=0)
    terminated = False
    truncated = False
    while not (terminated or truncated):
        # action 2 -> position +1
        _obs, _r, terminated, truncated, _info = e.step(2)
    # Ground truth: compound log-returns over the full traversed window.
    p = synthetic_prices["close"].to_numpy(dtype=float)
    # Env loops from index = window..N-2 stepping forward; final cash should
    # equal cumulative product of price-ratios across that span.
    start_idx = cfg.window
    end_idx = len(p) - 1
    expected_log_total = float(np.sum(np.log(p[start_idx + 1: end_idx + 1] / p[start_idx: end_idx])))
    expected_cash = cfg.initial_cash * float(np.exp(expected_log_total))
    # Allow a small numerical tolerance.
    assert e._cash == pytest.approx(expected_cash, rel=1e-6, abs=1e-9)


def test_rl_env_cost_debited_separately(synthetic_prices):
    """With zero price drift (constant prices) but nonzero cost_bps, equity
    after a single trade must equal initial_cash * (1 - cost) and never
    swap signs through compounding the cost.
    """
    n = 30
    flat = pd.DataFrame(
        {
            "close": np.full(n, 100.0),
            "feat1": np.zeros(n),
            "feat2": np.zeros(n),
        },
        index=pd.date_range("2022-01-03", periods=n, freq="B"),
    )
    cfg = TradingEnvConfig(
        max_position=1,
        cost_bps=10.0,  # 0.001 fractional
        window=5,
        feature_columns=["close", "feat1", "feat2"],
        initial_cash=1_000.0,
    )
    e = TradingEnv(flat, cfg)
    e.reset(seed=0)
    # Open a long position at the very first action; thereafter hold flat.
    _obs, _r, terminated, truncated, _info = e.step(2)
    expected_after_open = 1_000.0 * (1.0 - 10.0 / 10_000.0)
    assert e._cash == pytest.approx(expected_after_open, rel=1e-9)
    # Now go flat. Another single-unit cost is debited.
    if not (terminated or truncated):
        _obs, _r, terminated, truncated, _info = e.step(1)
        expected_after_close = expected_after_open * (1.0 - 10.0 / 10_000.0)
        assert e._cash == pytest.approx(expected_after_close, rel=1e-9)


def test_rl_env_leverage_uses_linear_compounding(synthetic_prices):
    """Audit fix: when ``max_position > 1``, equity bookkeeping must use
    linear ``(1 + position * simple_return)`` compounding, not exp() of the
    leveraged log-return (which systematically misprices leveraged PnL).
    """
    cfg = TradingEnvConfig(
        max_position=2,
        cost_bps=0.0,
        window=5,
        feature_columns=["close", "feat1", "feat2"],
        initial_cash=1.0,
    )
    e = TradingEnv(synthetic_prices, cfg)
    e.reset(seed=0)
    # action_to_position(action) = action - max_position. action=4 => +2.
    long_action = cfg.max_position * 2  # max long
    cash_path = [e._cash]
    terminated = False
    truncated = False
    while not (terminated or truncated):
        _obs, _r, terminated, truncated, _info = e.step(long_action)
        cash_path.append(e._cash)
    # Expected linear compounding under +2 position.
    p = synthetic_prices["close"].to_numpy(dtype=float)
    start_idx = cfg.window
    end_idx = len(p) - 1
    simple_rets = p[start_idx + 1: end_idx + 1] / p[start_idx: end_idx] - 1.0
    expected_cash = 1.0
    for r in simple_rets:
        expected_cash *= (1.0 + 2.0 * r)
    assert e._cash == pytest.approx(expected_cash, rel=1e-6, abs=1e-9)


def test_rl_env_terminal_step_reuses_last_obs(synthetic_prices):
    """Audit fix: stepping past the last bar must not index past the end of
    the price/feature arrays. The env returns the last valid observation
    when ``_step_idx`` advances past the data.
    """
    cfg = TradingEnvConfig(
        max_position=1,
        cost_bps=0.0,
        window=5,
        feature_columns=["close", "feat1", "feat2"],
    )
    e = TradingEnv(synthetic_prices, cfg)
    e.reset(seed=0)
    last_obs = None
    while True:
        obs, _r, terminated, truncated, _info = e.step(1)  # flat
        last_obs = obs
        if terminated or truncated:
            break
    # The terminal observation must be a valid finite vector (no IndexError,
    # no NaN explosion from reading past-end of the feature array).
    assert isinstance(last_obs, np.ndarray)
    assert last_obs.shape == e.observation_space.shape
    assert np.all(np.isfinite(last_obs))


def test_rl_evaluate_policy_bars_per_year_param(env):
    """Sharpe must scale with sqrt(bars_per_year) override."""
    cfg = RLAgentConfig(algo="PPO", total_timesteps=64, learning_rate=3e-4, seed=0)
    agent = RLAgent(env, cfg)
    agent.train()
    m_daily = evaluate_policy(agent, env, n_episodes=1, bars_per_year=252)
    m_intraday = evaluate_policy(agent, env, n_episodes=1, bars_per_year=252 * 78)
    # When sharpe is non-zero the intraday-annualized number should be sqrt(78)x.
    if m_daily["sharpe"] != 0.0:
        ratio = m_intraday["sharpe"] / m_daily["sharpe"]
        assert ratio == pytest.approx(np.sqrt(78.0), rel=1e-3)
