"""Reinforcement-learning trading agent.

Gymnasium-style single-asset trading environment with optional DQN/PPO
wrappers from stable_baselines3. Both gymnasium and stable_baselines3 are
optional dependencies; importing this module never fails when they are
missing — public classes raise ImportError on instantiation instead.

Public API:
- TradingEnvConfig:  dataclass for env hyperparameters.
- TradingEnv:        gymnasium.Env subclass for single-asset trading.
- RLAgentConfig:     dataclass for the SB3 agent hyperparameters.
- RLAgent:           thin SB3 PPO/DQN wrapper.
- evaluate_policy:   roll out a policy and report PnL metrics.

Module flags:
- GYM_AVAILABLE:  True if gymnasium is importable.
- SB3_AVAILABLE:  True if stable_baselines3 is importable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Optional deps — lazy detection
# ---------------------------------------------------------------------------

_BaseEnv: Any

try:
    import gymnasium as gym
    from gymnasium import spaces
    GYM_AVAILABLE = True
    _BaseEnv = gym.Env
except ImportError:
    GYM_AVAILABLE = False
    gym = None
    spaces = None

    class _FallbackEnv:  # minimal stub so class body parses without gymnasium
        pass
    _BaseEnv = _FallbackEnv

try:
    import stable_baselines3 as sb3
    SB3_AVAILABLE = True
except ImportError:
    SB3_AVAILABLE = False
    sb3 = None


def _require_gym() -> None:
    if not GYM_AVAILABLE:
        raise ImportError(
            "gymnasium is required for TradingEnv. "
            "Install with: pip install gymnasium"
        )


def _require_sb3() -> None:
    if not SB3_AVAILABLE:
        raise ImportError(
            "stable-baselines3 is required for RLAgent. "
            "Install with: pip install stable-baselines3"
        )


# ---------------------------------------------------------------------------
# Configs
# ---------------------------------------------------------------------------

@dataclass
class TradingEnvConfig:
    """Hyperparameters for TradingEnv.

    initial_cash:    starting cash (informational only; reward uses returns).
    max_position:    absolute max position units (-max_position .. +max_position).
                     With max_position=1 and 3-action space, actions map to
                     {short, flat, long} = {-1, 0, +1}. Note: equity
                     bookkeeping uses exp-compounding only when
                     ``max_position == 1`` (the unleveraged regime where
                     ``exp(position * log_return)`` matches a fully-invested
                     long/short). For ``max_position > 1`` the env switches
                     to linear ``cash *= (1 + position * simple_return)``
                     because exp-compounding of leveraged log-returns
                     systematically misprices the leveraged PnL.
    cost_bps:        transaction cost in basis points charged on |Δposition|.
    reward_scale:    scalar multiplier applied to the per-step reward.
    feature_columns: subset of columns from the price DataFrame to use as
                     features. None means use every numeric column.
    window:          number of past bars stacked into the observation.
    max_steps:       optional truncation step cap. None disables truncation.
    """
    initial_cash: float = 100_000.0
    max_position: int = 1
    cost_bps: float = 1.0
    reward_scale: float = 1.0
    feature_columns: Optional[list] = None
    window: int = 20
    max_steps: Optional[int] = None


@dataclass
class RLAgentConfig:
    """Hyperparameters for RLAgent (PPO/DQN wrapper)."""
    algo: str = "PPO"
    total_timesteps: int = 10_000
    learning_rate: float = 3e-4
    seed: int = 42
    verbose: int = 0
    policy: str = "MlpPolicy"
    extra_kwargs: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Trading environment
# ---------------------------------------------------------------------------

class TradingEnv(_BaseEnv):
    """Gymnasium env for single-asset trading.

    Observation: window of feature rows (flattened) concatenated with the
        current scalar position. Shape = (window * n_features + 1,).
    Action space: Discrete(2 * max_position + 1) — index i maps to position
        i - max_position. With the default max_position=1, the actions are
        {0: short, 1: flat, 2: long}.
    Reward: position * pct_return - cost_bps/10000 * |Δposition|, scaled by
        config.reward_scale.
    Termination: index pointer reaches the last bar.
    Truncation:  optional config.max_steps cap reached.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        prices: pd.DataFrame,
        config: Optional[TradingEnvConfig] = None,
    ) -> None:
        _require_gym()
        super().__init__()

        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pandas DataFrame")
        if config is None:
            config = TradingEnvConfig()
        if config.window < 1:
            raise ValueError("config.window must be >= 1")
        if config.max_position < 1:
            raise ValueError("config.max_position must be >= 1")

        self.config = config

        # Identify feature columns (drop non-numeric if user passes OHLCV).
        if config.feature_columns is not None:
            missing = [c for c in config.feature_columns if c not in prices.columns]
            if missing:
                raise KeyError(f"feature_columns missing in prices: {missing}")
            features = prices[config.feature_columns].copy()
        else:
            features = prices.select_dtypes(include=[np.number]).copy()
        if features.shape[1] == 0:
            raise ValueError("prices has no numeric columns to use as features")

        # Identify the price column for PnL. Prefer 'close' then first numeric.
        if "close" in prices.columns:
            price_series = prices["close"].astype(float)
        elif "Close" in prices.columns:
            price_series = prices["Close"].astype(float)
        else:
            price_series = features.iloc[:, 0].astype(float)

        if len(features) < config.window + 2:
            raise ValueError(
                f"prices length {len(features)} is too short for window "
                f"{config.window} (need at least window + 2)"
            )

        self._features = features.to_numpy(dtype=np.float64, copy=True)
        self._prices = price_series.to_numpy(dtype=np.float64, copy=True)
        self._n_features = self._features.shape[1]
        self._n_bars = self._features.shape[0]

        n_actions = 2 * config.max_position + 1
        obs_dim = config.window * self._n_features + 1

        self.action_space = spaces.Discrete(n_actions)
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_dim,),
            dtype=np.float32,
        )

        # Internal state (filled in reset).
        self._step_idx = config.window
        self._steps_taken = 0
        self._position = 0
        self._cash = float(config.initial_cash)
        self._equity_curve: list[float] = []
        self._n_trades = 0

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _get_obs(self) -> np.ndarray:
        start = self._step_idx - self.config.window
        window = self._features[start:self._step_idx]
        flat = window.flatten().astype(np.float32, copy=False)
        return np.concatenate(
            [flat, np.array([self._position], dtype=np.float32)],
            axis=0,
        )

    def _action_to_position(self, action: int) -> int:
        return int(action) - self.config.max_position

    # -------------------------------------------------------------------
    # Gym API
    # -------------------------------------------------------------------

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ):
        if GYM_AVAILABLE:
            super().reset(seed=seed)
        self._step_idx = self.config.window
        self._steps_taken = 0
        self._position = 0
        self._cash = float(self.config.initial_cash)
        self._equity_curve = [self._cash]
        self._n_trades = 0
        obs = self._get_obs()
        # Cache the most recent observation so we can return it from step()
        # if the index pointer advances past the available data on the
        # terminal bar.
        self._last_obs = obs
        info = {
            "step_idx": self._step_idx,
            "position": self._position,
            "cash": self._cash,
        }
        return obs, info

    def step(self, action):
        if not self.action_space.contains(int(action)):
            raise ValueError(
                f"action {action} not in action_space {self.action_space}"
            )

        prev_position = self._position
        target_position = self._action_to_position(action)

        # Realize PnL across the upcoming bar using the previous position.
        price_now = self._prices[self._step_idx]
        price_next_idx = self._step_idx + 1
        if price_next_idx >= self._n_bars:
            # Terminal bar — no further price; reward driven only by costs.
            pct_ret_log = 0.0
            pct_ret_simple = 0.0
            terminated = True
        else:
            price_next = self._prices[price_next_idx]
            # Guard against zero / negative / non-finite prices that would
            # otherwise produce inf/nan or sign-flipped pct returns.
            if (
                np.isfinite(price_now)
                and np.isfinite(price_next)
                and price_now > 0.0
                and price_next > 0.0
            ):
                # Track both the log return (used as reward signal because it
                # is stable in scale) and the simple return (used by the
                # equity bookkeeping when leverage > 1, where exp-compounding
                # of (position * log_ret) over-/under-states PnL).
                pct_ret_log = float(np.log(price_next / price_now))
                pct_ret_simple = float(price_next / price_now - 1.0)
            else:
                pct_ret_log = 0.0
                pct_ret_simple = 0.0
            terminated = False

        position_change = abs(target_position - prev_position)
        cost = (self.config.cost_bps / 10_000.0) * position_change
        # Position-PnL component (no costs); costs accounted as a separate
        # cash debit to avoid the dimensional mismatch where compounding the
        # combined number treated bps charges as if they were returns.
        position_pnl = float(prev_position) * pct_ret_log
        reward = position_pnl - cost
        reward *= self.config.reward_scale

        if position_change > 0:
            self._n_trades += 1

        # Apply position update and advance the index.
        self._position = target_position
        self._step_idx += 1
        self._steps_taken += 1

        # Truncation by step cap.
        truncated = False
        if (
            self.config.max_steps is not None
            and self._steps_taken >= self.config.max_steps
        ):
            truncated = True

        # Terminate on last bar.
        if self._step_idx >= self._n_bars - 1:
            terminated = True

        # Equity bookkeeping. Two regimes:
        #   * max_position == 1 (the default 3-action {-1, 0, +1} case):
        #     position is a single-asset fractional exposure; we compound
        #     using exp(position * log_return). This is exact for an
        #     unleveraged long/short and matches the historical behavior.
        #   * max_position >  1 (leveraged exposure):
        #     exp(position * log_return) systematically misstates the PnL
        #     of a notional ``position * notional`` exposure. We instead
        #     update cash linearly via (1 + position * simple_return), then
        #     debit costs as a multiplicative haircut.
        if self.config.max_position == 1:
            compound_factor = (
                float(np.exp(position_pnl)) if np.isfinite(position_pnl) else 1.0
            )
            self._cash = self._cash * compound_factor * (1.0 - cost)
        else:
            position_simple_pnl = float(prev_position) * pct_ret_simple
            if not np.isfinite(position_simple_pnl):
                position_simple_pnl = 0.0
            self._cash = self._cash * (1.0 + position_simple_pnl) * (1.0 - cost)
        self._equity_curve.append(self._cash)

        # Bounds-check before _get_obs(): if the index has advanced past the
        # available data (terminal step), reuse the last valid observation
        # instead of indexing past-end.
        if self._step_idx >= self._n_bars:
            obs = self._last_obs
        else:
            obs = self._get_obs()
            self._last_obs = obs

        info = {
            "step_idx": self._step_idx,
            "position": self._position,
            "prev_position": prev_position,
            "position_change": position_change,
            "cost": cost,
            "pct_return": pct_ret_log,
            "pct_return_simple": pct_ret_simple,
            "n_trades": self._n_trades,
            "cash": self._cash,
        }
        return obs, float(reward), bool(terminated), bool(truncated), info

    def render(self):
        print(
            f"step={self._step_idx} pos={self._position} "
            f"cash={self._cash:.2f} trades={self._n_trades}"
        )


# ---------------------------------------------------------------------------
# RL agent wrapper
# ---------------------------------------------------------------------------

class RLAgent:
    """Thin wrapper around stable_baselines3 PPO / DQN for a TradingEnv."""

    SUPPORTED_ALGOS = ("PPO", "DQN")

    def __init__(self, env, config: Optional[RLAgentConfig] = None) -> None:
        _require_sb3()
        if config is None:
            config = RLAgentConfig()
        algo = config.algo.upper()
        if algo not in self.SUPPORTED_ALGOS:
            raise ValueError(
                f"algo {config.algo!r} not supported, "
                f"choose from {self.SUPPORTED_ALGOS}"
            )
        self.config = config
        self.env = env
        self.algo = algo
        self.model = self._build_model(env, config)

    @staticmethod
    def _build_model(env, config: RLAgentConfig):
        algo = config.algo.upper()
        if algo == "PPO":
            from stable_baselines3 import PPO
            model_cls: Any = PPO
        else:
            from stable_baselines3 import DQN
            model_cls = DQN
        return model_cls(
            config.policy,
            env,
            learning_rate=config.learning_rate,
            seed=config.seed,
            verbose=config.verbose,
            **config.extra_kwargs,
        )

    def train(self, total_timesteps: Optional[int] = None) -> dict:
        steps = total_timesteps if total_timesteps is not None else self.config.total_timesteps
        self.model.learn(total_timesteps=steps)
        return {
            "algo": self.algo,
            "total_timesteps": steps,
            "learning_rate": self.config.learning_rate,
        }

    def predict(self, obs, deterministic: bool = True):
        action, _state = self.model.predict(obs, deterministic=deterministic)
        # SB3 returns numpy arrays; cast scalar Discrete actions to int.
        if isinstance(action, np.ndarray):
            if action.shape == () or action.size == 1:
                return int(action.item())
            return action
        return int(action)

    def save(self, path: str) -> None:
        self.model.save(path)

    def load(self, path: str, env) -> "RLAgent":
        """Reload weights from disk into this agent. Returns self."""
        algo = self.algo
        if algo == "PPO":
            from stable_baselines3 import PPO
            self.model = PPO.load(path, env=env)
        else:
            from stable_baselines3 import DQN
            self.model = DQN.load(path, env=env)
        self.env = env
        return self


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

def evaluate_policy(agent, env, n_episodes: int = 1, bars_per_year: int = 252) -> dict:
    """Roll out `agent` on `env` for n_episodes and report PnL metrics.

    Args:
        agent:         object with ``.predict(obs)`` or callable policy.
        env:           Gymnasium-compatible env exposing ``reset/step``.
        n_episodes:    number of full episodes to roll out.
        bars_per_year: annualization factor for the Sharpe ratio. Use 252 for
                       daily bars (default), 252*78 for 5-minute intraday,
                       12 for monthly bars, etc.

    Returns dict with keys: total_return, sharpe, max_drawdown, n_trades,
    n_episodes, mean_episode_return.
    """
    if n_episodes < 1:
        raise ValueError("n_episodes must be >= 1")
    if bars_per_year < 1:
        raise ValueError("bars_per_year must be >= 1")

    episode_returns: list[float] = []
    all_rewards: list[float] = []
    n_trades_total = 0

    for _ in range(n_episodes):
        obs, _info = env.reset()
        done = False
        truncated = False
        ep_reward = 0.0
        ep_last_n_trades = 0
        while not (done or truncated):
            if hasattr(agent, "predict"):
                action = agent.predict(obs)
            else:  # callable policy
                action = agent(obs)
            obs, reward, done, truncated, info = env.step(action)
            ep_reward += float(reward)
            all_rewards.append(float(reward))
            # ``n_trades`` reported by the env is cumulative WITHIN the
            # current episode and resets on env.reset(). Track only the
            # final value seen at terminal step; sum across episodes after
            # the loop so cross-episode trade counts accumulate correctly.
            ep_last_n_trades = int(info.get("n_trades", ep_last_n_trades))
        n_trades_total += ep_last_n_trades
        episode_returns.append(ep_reward)

    rewards = np.asarray(all_rewards, dtype=np.float64)
    if rewards.size == 0:
        sharpe = 0.0
        max_dd = 0.0
    else:
        # Rewards are already log-returns (env produces log P_t/P_{t-1}-style
        # PnL increments). Compose them additively, then exponentiate to
        # recover the equity curve. Using cumprod(1+r) here would be a
        # second-order error and double-discount via Jensen's gap.
        std = rewards.std(ddof=1) if rewards.size > 1 else 0.0
        sharpe = (
            float(rewards.mean() / std * np.sqrt(bars_per_year)) if std > 0 else 0.0
        )
        equity = np.exp(np.cumsum(rewards))
        running_max = np.maximum.accumulate(equity)
        drawdowns = equity / running_max - 1.0
        max_dd = float(drawdowns.min()) if drawdowns.size else 0.0

    total_return = float(np.sum(episode_returns))
    return {
        "total_return": total_return,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "n_trades": int(n_trades_total),
        "n_episodes": int(n_episodes),
        "mean_episode_return": float(np.mean(episode_returns)) if episode_returns else 0.0,
    }


__all__ = [
    "GYM_AVAILABLE",
    "SB3_AVAILABLE",
    "TradingEnvConfig",
    "TradingEnv",
    "RLAgentConfig",
    "RLAgent",
    "evaluate_policy",
]
