from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _daily_index(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=periods)


def test_feasible_candidate_requires_positive_and_above_spy_every_year() -> None:
    from aurora.infra.sp500_megarun.dehb_objective import score_realized_returns

    index = _daily_index("2000-01-03", 522)
    strategy = pd.Series(0.001, index=index)
    spy = pd.Series(0.0005, index=index)

    feasible = score_realized_returns(strategy, spy, target_years=(2000, 2001))
    assert feasible.feasible is True
    assert feasible.failed_years == ()
    assert feasible.annualized_strategy_return > feasible.annualized_spy_return

    strategy.loc[strategy.index.year == 2001] = 0.0
    failed = score_realized_returns(strategy, spy, target_years=(2000, 2001))
    assert failed.feasible is False
    assert failed.failed_years == (2001,)
    assert failed.annual_returns[2001].strategy_return == pytest.approx(0.0)


def test_infeasible_high_return_candidate_never_beats_a_feasible_candidate() -> None:
    from aurora.infra.sp500_megarun.dehb_objective import (
        candidate_rank_key,
        score_realized_returns,
    )

    index = _daily_index("2000-01-03", 522)
    spy = pd.Series(0.0002, index=index)
    feasible_returns = pd.Series(0.0003, index=index)
    concentrated = pd.Series(0.01, index=index)
    concentrated.loc[concentrated.index.year == 2001] = -0.0001

    feasible = score_realized_returns(feasible_returns, spy, target_years=(2000, 2001))
    infeasible = score_realized_returns(concentrated, spy, target_years=(2000, 2001))

    assert feasible.feasible is True
    assert infeasible.feasible is False
    assert candidate_rank_key(feasible) < candidate_rank_key(infeasible)
    assert feasible.dehb_fitness < infeasible.dehb_fitness


def test_primary_annualized_return_precedes_weekly_beat_rate() -> None:
    from aurora.infra.sp500_megarun.dehb_objective import (
        candidate_rank_key,
        score_realized_returns,
    )

    index = _daily_index("2000-01-03", 260)
    spy = pd.Series(0.0, index=index)
    high_return = pd.Series(-0.0001, index=index)
    high_return.iloc[:60] = 0.01
    high_weekly = pd.Series(0.0005, index=index)

    primary_winner = score_realized_returns(high_return, spy, target_years=(2000,))
    weekly_winner = score_realized_returns(high_weekly, spy, target_years=(2000,))

    assert primary_winner.annualized_strategy_return > weekly_winner.annualized_strategy_return
    assert primary_winner.weekly_spy_beat_rate < weekly_winner.weekly_spy_beat_rate
    assert candidate_rank_key(primary_winner) < candidate_rank_key(weekly_winner)


def test_weekly_ties_do_not_count_as_beating_spy() -> None:
    from aurora.infra.sp500_megarun.dehb_objective import score_realized_returns

    index = _daily_index("2000-01-03", 15)
    spy = pd.Series(0.001, index=index)
    strategy = spy.copy()

    score = score_realized_returns(strategy, spy, target_years=(2000,))

    assert score.week_count == 3
    assert score.weeks_beating_spy == 0
    assert score.weekly_spy_beat_rate == 0.0
    assert score.feasible is False


def test_ledger_decisions_take_effect_only_at_the_next_open() -> None:
    from aurora.infra.sp500_megarun.dehb_objective import score_ledger_decisions

    index = pd.bdate_range("2000-01-03", periods=5)
    ledger = pd.DataFrame(
        {"long_return": [0.10, 0.20, -0.30, 0.40, np.nan]},
        index=index,
    )
    decisions = pd.Series([-1, 1, -1, 1, 1], index=index)

    result = score_ledger_decisions(
        ledger,
        decisions,
        target_years=(2000,),
        allowed_end="2010-12-31",
    )

    assert result.positions.tolist() == [1, -1, 1, -1, 1]
    assert result.strategy_returns.tolist() == pytest.approx([0.10, -0.20, -0.30, -0.40])
    assert result.realized_at.tolist() == index[1:].tolist()


def test_train_objective_rejects_validation_or_locked_dates() -> None:
    from aurora.infra.sp500_megarun.dehb_objective import ObjectiveContractError, score_ledger_decisions

    ledger = pd.DataFrame(
        {"long_return": [0.01, 0.01, np.nan]},
        index=pd.to_datetime(["2010-12-30", "2010-12-31", "2011-01-03"]),
    )
    decisions = pd.Series(1, index=ledger.index)

    with pytest.raises(ObjectiveContractError, match="OBJECTIVE_DATE_AFTER_ALLOWED_END"):
        score_ledger_decisions(
            ledger,
            decisions,
            target_years=(2010,),
            allowed_end="2010-12-31",
        )


def test_missing_year_nonfinite_or_wealth_destroying_return_fails_closed() -> None:
    from aurora.infra.sp500_megarun.dehb_objective import (
        ObjectiveContractError,
        score_realized_returns,
    )

    index = _daily_index("2000-01-03", 20)
    spy = pd.Series(0.0, index=index)

    with pytest.raises(ObjectiveContractError, match="MISSING_TARGET_YEAR:2001"):
        score_realized_returns(pd.Series(0.01, index=index), spy, target_years=(2000, 2001))
    bad = pd.Series(0.01, index=index)
    bad.iloc[3] = np.inf
    with pytest.raises(ObjectiveContractError, match="NONFINITE_RETURN"):
        score_realized_returns(bad, spy, target_years=(2000,))
    bad.iloc[3] = -1.0
    with pytest.raises(ObjectiveContractError, match="RETURN_LE_MINUS_ONE"):
        score_realized_returns(bad, spy, target_years=(2000,))
