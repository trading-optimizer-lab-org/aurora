# Aurora v1.2 Development Plan

Polish + advanced features. 3 batches.

## Batch J — Regime detection + adaptive (5 agents)

### J.1 HMM regime detection
File: `aurora/regime/hmm.py`
- Gaussian HMM via hmmlearn
- N-state regime fitting on returns
- Posterior regime probabilities
- Regime-conditional metrics

### J.2 Bayesian rolling regression alpha
File: `aurora/regime/bayes_alpha.py`
- Rolling regression of strategy returns vs benchmark
- Bayesian update with prior
- Posterior alpha + beta with uncertainty bands

### J.3 Online learning wrapper
File: `aurora/strategies/library/online_learner.py`
- Wraps sklearn online learners (SGDClassifier, PassiveAggressive)
- Refits incrementally each bar
- Anti-lookahead enforced

### J.4 Markov regime-switching strategy
File: `aurora/regime/markov_switching.py`
- 2-state markov switching mean
- Detects bull/bear automatically
- Used as filter for trend strategies

### J.5 Hurst exponent + DFA
File: `aurora/regime/hurst.py`
- Detrended Fluctuation Analysis
- Hurst > 0.5 = trending, < 0.5 = mean-reverting
- Rolling Hurst as regime classifier

## Batch K — Persistence + workflow (5 agents)

### K.1 Backtest result registry (SQLite)
File: `aurora/registry/registry.py`
- SQLite DB for storing backtest results
- Strategy + params + metrics hash
- Query by date, strategy class, performance

### K.2 Strategy versioning + provenance hash
File: `aurora/registry/versioning.py`
- Hash strategy code + params -> version ID
- Track which validation gates passed when
- Git integration

### K.3 CLI ML workflows
File: `aurora/cli/forge.py` (extend)
- forge label --method triple-barrier
- forge factor --asset SPY
- forge attribute --strategy X
- forge purge-cv --strategy X --k 5

### K.4 Trade journal database
File: `aurora/registry/journal.py`
- SQLite for live trade log
- Entry, exit, pnl, signal source
- Integrates with Lumibot live wrapper

### K.5 Experiment tracker
File: `aurora/registry/experiments.py`
- Logs all GA generations + Pareto fronts
- MLflow-style runs
- Compare experiments

## Batch L — Stress + scenarios (5 agents)

### L.1 Synthetic crash scenarios
File: `aurora/validation/scenarios.py`
- Replay 1987, 2008, 2020 crash periods
- Inject scaled crash into arbitrary date
- Stress test strategies

### L.2 Liquidity-aware sizing
File: `aurora/deployment/liquidity.py`
- Scale position to ADV-based budget
- Liquidity score per asset
- Reduce sizing for illiquid assets

### L.3 Tail risk scenarios
File: `aurora/validation/tail_risk.py`
- Block bootstrap of historical tail events
- Generate synthetic tail-heavy paths
- Stress at p99/p999 levels

### L.4 Correlation breakdown stress
File: `aurora/validation/correlation_stress.py`
- Force correlation matrix to identity (all decorrelated)
- Force to ones (all correlated, crisis)
- Measure portfolio impact

### L.5 Tax-aware backtest
File: `aurora/core/taxes.py`
- Short-term vs long-term capital gains tracking
- Wash sale rule simulation
- After-tax returns

Total: 15 new modules. Parallel-friendly (independent files).
