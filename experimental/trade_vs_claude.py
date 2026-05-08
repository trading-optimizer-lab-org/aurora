"""Trade-vs-Claude — pit a user strategy against an LLM-decided strategy.

Runs the user's signal function and a mocked LLM signal function over the
same price series, returning side-by-side equity curves and headline
metrics. The "LLM" here is a deterministic mock so the test suite stays
hermetic; in production this would forward observation windows to a real
chat model (Claude API, etc.) and parse the response into a {-1, 0, 1}
position.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd


SignalFn = Callable[[pd.Series], pd.Series]


def _equity_curve(prices: pd.Series, signal: pd.Series) -> pd.Series:
    rets = prices.pct_change().fillna(0.0)
    pos = signal.shift(1).fillna(0.0)
    strat_rets = pos * rets
    return (1.0 + strat_rets).cumprod()


def _sharpe(equity: pd.Series, periods_per_year: int = 252) -> float:
    rets = equity.pct_change().dropna()
    if rets.std(ddof=0) == 0 or len(rets) == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * rets.mean() / rets.std(ddof=0))


def mock_llm_signal(prices: pd.Series) -> pd.Series:
    """Mock LLM strategy: rolling 20-day momentum with a 5-day confirmation.

    Stands in for "ask Claude what to do over a window of recent prices".
    Deterministic and dependency-free.
    """
    mom = prices.pct_change(20)
    conf = prices.pct_change(5)
    sig = pd.Series(0, index=prices.index, dtype=float)
    sig[(mom > 0) & (conf > 0)] = 1.0
    sig[(mom < 0) & (conf < 0)] = -1.0
    return sig


@dataclass
class TradeVsClaude:
    """Run user vs LLM strategies side by side.

    Parameters
    ----------
    user_signal : SignalFn
        ``user_signal(prices) -> position series`` in {-1, 0, 1}.
    llm_signal : SignalFn, optional
        Defaults to :func:`mock_llm_signal`.
    """

    user_signal: SignalFn
    llm_signal: Optional[SignalFn] = None

    def run(self, prices: pd.Series) -> dict:
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series")
        if len(prices) < 25:
            raise ValueError("need at least 25 price points for the LLM mock window")

        llm = self.llm_signal or mock_llm_signal
        u_sig = self.user_signal(prices)
        l_sig = llm(prices)

        u_eq = _equity_curve(prices, u_sig)
        l_eq = _equity_curve(prices, l_sig)

        return {
            "user_equity": u_eq,
            "llm_equity": l_eq,
            "user_sharpe": _sharpe(u_eq),
            "llm_sharpe": _sharpe(l_eq),
            "user_final": float(u_eq.iloc[-1]),
            "llm_final": float(l_eq.iloc[-1]),
            "winner": "user" if u_eq.iloc[-1] > l_eq.iloc[-1] else "llm",
        }
