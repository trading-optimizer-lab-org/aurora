"""Multi-agent trading environment.

N agents trade the same single asset over a shared price path. Each agent
chooses one of {short, flat, long} and receives a reward equal to the bar's
return * own position. A simple market-impact term subtracts a fraction of
the *total* gross position from each agent's reward, creating cooperation /
competition pressure: when several agents pile into the same direction, all
of them pay a per-bar friction.

This is intentionally a tabular environment that does not require gymnasium,
so importing the module is dep-free. Tabular policies are also provided so
tests pass without stable_baselines3. SB3 wrappers are exposed when the
optional dep is available.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import gymnasium as gym  # type: ignore
    from gymnasium import spaces  # type: ignore
    GYM_AVAILABLE = True
except ImportError:  # pragma: no cover
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    GYM_AVAILABLE = False

try:
    import stable_baselines3 as sb3  # type: ignore
    SB3_AVAILABLE = True
except ImportError:  # pragma: no cover
    sb3 = None  # type: ignore[assignment]
    SB3_AVAILABLE = False


ACTIONS = (-1, 0, 1)  # short, flat, long


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class MultiAgentEnvConfig:
    n_agents: int = 3
    impact_coef: float = 1e-4  # per-bar penalty multiplier on total gross position
    seed: int = 42


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


class MultiAgentTradingEnv:
    """Self-contained multi-agent trading environment.

    Public API mirrors gymnasium semantics but does not require it:

      env = MultiAgentTradingEnv(price_series, MultiAgentEnvConfig(n_agents=3))
      obs = env.reset()
      while not done:
          actions = [agent_policy(obs) for agent_policy in policies]
          obs, rewards, done, info = env.step(actions)
    """

    def __init__(self, prices: np.ndarray, config: Optional[MultiAgentEnvConfig] = None):
        if not isinstance(prices, np.ndarray):
            raise TypeError("prices must be a numpy array")
        if prices.ndim != 1:
            raise ValueError("prices must be 1D")
        if len(prices) < 5:
            raise ValueError("prices must have >= 5 bars")
        self.prices = prices.astype(float)
        self.config = config if config is not None else MultiAgentEnvConfig()
        if self.config.n_agents < 1:
            raise ValueError("n_agents must be >= 1")
        self._returns = np.diff(np.log(self.prices))
        self._t: int = 0
        self.positions: np.ndarray = np.zeros(self.config.n_agents, dtype=int)
        self.cumulative_rewards: np.ndarray = np.zeros(self.config.n_agents, dtype=float)

    @property
    def n_agents(self) -> int:
        return self.config.n_agents

    @property
    def n_steps(self) -> int:
        return len(self._returns)

    def reset(self) -> Dict[str, np.ndarray]:
        """Reset env and return initial observation dict."""
        self._t = 0
        self.positions[:] = 0
        self.cumulative_rewards[:] = 0.0
        return self._observe()

    def _observe(self) -> Dict[str, np.ndarray]:
        # Observation: last log return + each agent's own position
        last_ret = self._returns[max(self._t - 1, 0)] if self._t > 0 else 0.0
        return {
            "last_return": np.array([last_ret], dtype=float),
            "positions": self.positions.copy(),
            "t": self._t,
        }

    def step(
        self, actions: Sequence[int]
    ) -> Tuple[Dict[str, np.ndarray], np.ndarray, bool, Dict[str, Any]]:
        """Apply one bar of trading.

        Each action must be in {-1, 0, +1}.
        Returns (obs, rewards, done, info).
        """
        if len(actions) != self.config.n_agents:
            raise ValueError(
                f"actions must have len {self.config.n_agents}; got {len(actions)}"
            )
        for a in actions:
            if int(a) not in ACTIONS:
                raise ValueError(f"action must be in {ACTIONS}; got {a}")
        self.positions[:] = np.array(actions, dtype=int)

        if self._t >= self.n_steps:
            # Terminal: zero rewards
            return self._observe(), np.zeros(self.config.n_agents), True, {}

        bar_ret = self._returns[self._t]
        # Per-agent base reward = position * return.
        base = self.positions.astype(float) * bar_ret
        # Market-impact penalty: subtract impact_coef * total_gross_position
        # from each agent's reward (creates competition).
        gross = float(np.sum(np.abs(self.positions)))
        impact = self.config.impact_coef * gross
        rewards = base - impact

        self.cumulative_rewards += rewards
        self._t += 1
        done = self._t >= self.n_steps
        info = {"bar_return": bar_ret, "gross": gross, "impact": impact}
        return self._observe(), rewards, done, info

    # ------------------------------------------------------------------ rollouts

    def rollout(
        self, policies: Sequence[Callable[[Dict[str, np.ndarray]], int]]
    ) -> Dict[str, np.ndarray]:
        """Run a full episode with N callable policies, return reward stats.

        Each policy: ``f(obs_dict) -> int in {-1, 0, +1}``.
        """
        if len(policies) != self.config.n_agents:
            raise ValueError(
                f"need {self.config.n_agents} policies; got {len(policies)}"
            )
        obs = self.reset()
        history = []
        done = False
        while not done:
            actions = [int(p(obs)) for p in policies]
            obs, rewards, done, _info = self.step(actions)
            history.append(rewards.copy())
        rewards_arr = np.stack(history, axis=0) if history else np.zeros((0, self.n_agents))
        return {
            "rewards_per_step": rewards_arr,
            "cumulative": self.cumulative_rewards.copy(),
            "n_steps_played": rewards_arr.shape[0],
        }


# ---------------------------------------------------------------------------
# Built-in toy policies
# ---------------------------------------------------------------------------


def long_only_policy(obs: Dict[str, np.ndarray]) -> int:
    return 1


def flat_policy(obs: Dict[str, np.ndarray]) -> int:
    return 0


def momentum_policy(obs: Dict[str, np.ndarray]) -> int:
    """Long if last bar was up, short if down, flat at start."""
    r = float(obs["last_return"][0])
    if r > 0:
        return 1
    if r < 0:
        return -1
    return 0


__all__ = [
    "GYM_AVAILABLE",
    "SB3_AVAILABLE",
    "ACTIONS",
    "MultiAgentEnvConfig",
    "MultiAgentTradingEnv",
    "long_only_policy",
    "flat_policy",
    "momentum_policy",
]
