# Aurora v1.1 Development Plan

Driven by GitHub research (`GITHUB_RESEARCH_v1.1.md`). Adds ML pipeline, portfolio optim, analytics breadth.

## Batch G — ML pipeline (parallel, 6 agents)

### Task G.1: Purged K-Fold CV + embargo
File: `aurora/validation/purged_cv.py`
Source: mlfinlab/cross_validation.py
- `PurgedKFold(n_splits, embargo_pct)` — train/test splits with overlap purging
- `cv_score(strategy, prices, n_splits, embargo_pct)` -> array of OOS metrics
- Critical for label-overlapping ML strategies

### Task G.2: Triple-barrier labeling + meta-labeling
File: `aurora/ml/labels.py`
Source: mlfinlab/labeling.py + bet_sizing.py
- `triple_barrier_labels(prices, vol, pt_sl_factors, holding_period)` -> labels {-1,0,+1}
- `meta_labels(primary_signals, returns)` -> binary trade/no-trade
- `bet_size_from_proba(proba, threshold)` -> position size

### Task G.3: Feature importance (MDI/MDA/SFI)
File: `aurora/ml/feature_importance.py`
Source: mlfinlab/feature_importance/
- `mean_decrease_impurity(model, features)` -> ranked dict
- `mean_decrease_accuracy(model, X, y, n_repeats)` -> ranked dict via permutation
- `single_feature_importance(features, target, cv)` -> per-feature OOS score

### Task G.4: Fractional differentiation
File: `aurora/ml/fracdiff.py`
Source: mlfinlab/features/fracdiff.py
- `frac_diff_ffd(series, d, threshold)` -> stationary differenced series
- `find_min_d(series, threshold)` -> min d that passes ADF

### Task G.5: Structural breaks (Chow, CUSUM, SADF)
File: `aurora/validation/structural_breaks.py`
Source: mlfinlab/structural_breaks/
- `chow_test(returns, breakpoint)` -> F-stat + p-value
- `cusum_filter(returns, threshold)` -> array of break dates
- `sadf_test(prices, lags, min_size)` -> SADF series

### Task G.6: CSCV / PBO (Probability of Backtest Overfitting)
File: `aurora/validation/cscv_pbo.py`
Source: mlfinlab probabilistic backtesting
- `cscv(strategy_returns_matrix, n_splits=16)` -> PBO probability
- Used to detect overfit-by-search across N strategies

## Batch H — Portfolio optimization (parallel, 5 agents)

### Task H.1: HRP allocator
File: `aurora/deployment/hrp.py` (or extend allocator.py)
Source: pypfopt/hierarchical_portfolio.py
- `HRPAllocator(returns)` -> hierarchical risk parity weights
- Tree clustering + recursive bisection

### Task H.2: CVaR / CDaR efficient frontier
File: `aurora/deployment/risk_optim.py`
Source: pypfopt/efficient_frontier/
- `min_cvar(returns, alpha=0.05)` -> weights minimizing 5% CVaR
- `min_cdar(returns, alpha=0.05)` -> conditional drawdown-at-risk
- `efficient_cvar(returns, target_return, alpha)`

### Task H.3: Black-Litterman views
File: `aurora/deployment/black_litterman.py`
Source: pypfopt/black_litterman.py
- `BlackLittermanModel(prior_returns, cov, views, view_confidence)`
- `posterior_returns()` -> blended mean
- `posterior_cov()` -> blended cov

### Task H.4: Ledoit-Wolf shrinkage
File: `aurora/deployment/cov_shrinkage.py`
Source: sklearn.covariance + pypfopt
- `ledoit_wolf_shrinkage(returns)` -> shrunk cov matrix
- `oas_shrinkage(returns)` -> Oracle Approximating Shrinkage

### Task H.5: Risk parity (proper iterative solver)
File: `aurora/deployment/risk_parity.py`
Source: Riskfolio-Lib + pypfopt
- `risk_parity_weights(cov, target_risk_contributions=None)`
- Proper convex optimization via cvxpy or scipy

## Batch I — Analytics + execution (parallel, 6 agents)

### Task I.1: Comprehensive metrics suite (quantstats parity)
File: `aurora/analytics/metrics_full.py`
Source: quantstats/stats.py
- 80+ metrics: omega, kelly_criterion, common_sense_ratio, value_at_risk, conditional_value_at_risk, payoff_ratio, gain_to_pain_ratio, recovery_factor, ulcer_index, serenity_index, comp_returns, monthly_returns, drawdown_details, autocorrelation, etc.

### Task I.2: Alphalens-style factor analysis
File: `aurora/analytics/factor_analysis.py`
Source: alphalens/performance.py
- `information_coefficient(factor, forward_returns)` -> daily IC + IC IR
- `quantile_spread(factor, forward_returns, n_quantiles=5)` -> long-short spread by quantile
- `factor_returns(factor, prices)` -> factor-portfolio returns
- `turnover(factor, periods)` -> rebalance turnover

### Task I.3: Performance attribution
File: `aurora/analytics/attribution.py`
- `attribution_by_strategy(allocator_result)` -> per-strategy contribution
- `attribution_by_factor(returns, factor_loadings)` -> factor returns
- `attribution_by_time(returns, regime_labels)` -> regime-conditional returns
- `brinson_attribution(weights, sector_weights, returns)` -> selection vs allocation

### Task I.4: Round-trip trade analysis
File: `aurora/analytics/round_trip.py`
- `extract_trades(weights, prices)` -> list of (entry, exit, pnl, holding_days)
- `trade_stats(trades)` -> avg trade, win rate by holding, max consecutive losses
- `mae_mfe(trades, prices)` -> Maximum Adverse / Favorable Excursion

### Task I.5: VolumeShareSlippage execution model
File: `aurora/core/slippage.py`
Source: zipline/finance/slippage.py
- `VolumeShareSlippage(volume_limit=0.025, price_impact=0.1)` -> integrate with CostModel
- `FixedBasisPointsSlippage(basis_points=5)` -> simple linear
- Apply via engine: realistic fill prices given order size vs ADV

### Task I.6: Tear sheet v2 (quantstats sections)
File: `aurora/reporting/tearsheet.py` (extend)
Source: pyfolio + quantstats
- Add: round-trip table, factor exposures, regime breakdown, monthly returns table with row totals, distribution comparison vs benchmark
- New PDF export option

## Execution

Each batch ~5-6 parallel agents. Code review between batches. Total estimated: ~17 new files, ~3 extended files, ~180 new tests.

Out-of-scope:
- RL stack (FinRL)
- LLM agents (TradingAgents)
- Tick/minute bar engine
- Pytorch deep models
- Broker zoo (Lean parity)
