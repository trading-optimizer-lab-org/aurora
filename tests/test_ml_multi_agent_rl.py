"""Tests for aurora.ml.multi_agent_rl."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.ml.multi_agent_rl import (
    ACTIONS,
    MultiAgentEnvConfig,
    MultiAgentTradingEnv,
    flat_policy,
    long_only_policy,
    momentum_policy,
)


@pytest.fixture
def upward_prices():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.001, 0.005, 100)
    return 100.0 * np.cumprod(1.0 + rets)


def test_env_initializes_correctly(upward_prices):
    env = MultiAgentTradingEnv(upward_prices, MultiAgentEnvConfig(n_agents=3))
    assert env.n_agents == 3
    assert env.n_steps == len(upward_prices) - 1
    obs = env.reset()
    assert "last_return" in obs
    assert obs["positions"].shape == (3,)
    assert (obs["positions"] == 0).all()


def test_step_validates_action_count(upward_prices):
    env = MultiAgentTradingEnv(upward_prices, MultiAgentEnvConfig(n_agents=2))
    env.reset()
    with pytest.raises(ValueError):
        env.step([1, 0, -1])  # too many actions
    with pytest.raises(ValueError):
        env.step([2, 0])  # invalid action value


def test_long_only_beats_flat_on_uptrend(upward_prices):
    env = MultiAgentTradingEnv(
        upward_prices, MultiAgentEnvConfig(n_agents=2, impact_coef=0.0)
    )
    out = env.rollout([long_only_policy, flat_policy])
    cum = out["cumulative"]
    # Agent 0 (long_only) should beat agent 1 (flat) on average uptrend.
    assert cum[0] > cum[1]


def test_impact_penalizes_competition(upward_prices):
    env_low = MultiAgentTradingEnv(
        upward_prices, MultiAgentEnvConfig(n_agents=3, impact_coef=0.0)
    )
    env_high = MultiAgentTradingEnv(
        upward_prices, MultiAgentEnvConfig(n_agents=3, impact_coef=0.01)
    )
    policies = [long_only_policy, long_only_policy, long_only_policy]
    cum_low = env_low.rollout(policies)["cumulative"]
    cum_high = env_high.rollout(policies)["cumulative"]
    # With high impact, all agents should earn less per step
    assert cum_high.sum() < cum_low.sum()


def test_rollout_handles_done_correctly(upward_prices):
    env = MultiAgentTradingEnv(upward_prices, MultiAgentEnvConfig(n_agents=1))
    out = env.rollout([flat_policy])
    assert out["n_steps_played"] == env.n_steps
    assert out["rewards_per_step"].shape == (env.n_steps, 1)


def test_invalid_input_raises():
    with pytest.raises(TypeError):
        MultiAgentTradingEnv([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        MultiAgentTradingEnv(np.array([[1.0, 2.0]]))
    with pytest.raises(ValueError):
        MultiAgentTradingEnv(np.array([1.0, 2.0]))  # too short


def test_actions_constant():
    assert ACTIONS == (-1, 0, 1)


def test_momentum_policy_obeys_obs():
    obs = {"last_return": np.array([0.01]), "positions": np.array([0])}
    assert momentum_policy(obs) == 1
    obs = {"last_return": np.array([-0.01]), "positions": np.array([0])}
    assert momentum_policy(obs) == -1
    obs = {"last_return": np.array([0.0]), "positions": np.array([0])}
    assert momentum_policy(obs) == 0
