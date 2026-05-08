# QuantForge

QuantForge v1.4 - standalone quant research engine with a hash-bound
7-stage protocol spine: policy, data providers, snapshots, experiment
registry, validation, agent gateway, and paper/live guards. The GA fitness
path is IS-only by construction; OOS_DEV is post-selection validation, and
OOS_LOCKED/FORWARD require explicit ceremonies. Current verified baseline:
2781 passed, 23 skipped, 10 deselected on the fast suite, 80.40% coverage,
mypy clean, ruff clean, strict-Sphinx docs build clean.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, commit style,
the OOS-sagrado contract for new code, and the validation-gates checklist
that every new strategy must pass before merge.

Vulnerability reports: see [SECURITY.md](SECURITY.md).

## Filosofia

Generate thousands of strategy candidates. Approve only those that survive every
mandated gate. Anything that fails one gate is rejected, no exceptions.

The non-negotiable doctrine:

1. **OOS sagrado** - the out-of-sample partition is sacred. The genetic algorithm
   never sees OOS prices. OOS is touched only after candidates have been chosen,
   and only by the final OOS gate. Enforced programmatically by `OOSGuard` in
   `quantforge/core/data_layer.py` and reaffirmed in `quantforge/ga/fitness.py`.
2. **Walk-forward** - candidate must beat buy-and-hold Calmar inside multiple
   non-overlapping windows.
3. **Monte Carlo** - block-bootstrap returns and trade-reorder MC.
4. **System Parameter Permutation (SPP)** - perturb each parameter +/-10% and
   require Calmar coefficient of variation below 30%.
5. **Deflated Sharpe Ratio** - Bailey / Lopez de Prado correction for selection
   bias across N candidates.

Every approved strategy then enters paper trading for 90 days minimum before live
deployment with a 1% risk-per-trade cap.

The full pipeline is reproducible from a single seed. Re-running months later
with the same seed reproduces identical results.

## Capabilities by area (v1.4)

### Core engine
- `core/engine.py` - single-asset event-driven backtest
- `core/engine_multi.py` - multi-asset portfolio engine
- `core/engine_jit.py` - numba JIT kernels (about 200x speedup on RSI)
- `core/engine_intraday.py` - minute / hourly bars, RTH / 24h / ETH calendars,
  optional flat-EOD, overnight cost on session-boundary carry
- `core/bars.py` - tick / volume / dollar bars (Lopez de Prado AFML Ch.2)
- `core/realtime.py` - yfinance polling adapter, ring buffer, replay generator
- `core/costs.py`, `core/costs_intraday.py`, `core/slippage.py` - cost / slippage
  models including Volume / SquareRoot / Linear / FixedBPS
- `core/data_layer.py` - parquet cache, OOS partition, `OOSGuard` lock with file
  + git-hash provenance
- `core/seed.py` - global RNG + per-component child RNG
- `core/config.py` (pydantic v2 YAML / TOML), `core/logging.py`,
  `core/features.py` (feature store with provenance), `core/taxes.py`
  (FIFO / LIFO / HIFO + wash sale)

### Strategy library (12 strategies)
- `MACross`, `RSIMeanRev`, `TSMomentum`, `DonchianBreakout`, `BollingerMR`,
  `DualMomentum`, `ATRBreakout`, `PairTrade` (multi-asset), `OnlineLearner`,
  `SeqModelStrategy` (LSTM / Transformer / RL wrapper), plus `StopWrapper` and
  `VolTargetWrapper` decorators

### Genetic algorithm
- `ga/runner.py` - NSGA-II with joblib parallel backend
- `ga/fitness.py` - multi-objective fitness, IS-only by construction
- `ga/bayes_opt.py` - Bayesian optimization (skopt)
- `ga/seed_population.py` - curated known-good seed configs
- `ga/multi_asset_runner.py` - multi-asset GA

### Validation (13 gates: 8 orchestrated + 5 standalone)
- `validation/walk_forward.py` (rolling / expanding / anchored)
- `validation/monte_carlo.py` (block bootstrap + trade reorder)
- `validation/spp.py`, `validation/deflated_sharpe.py`
- `validation/lookahead_check.py` (AST static + runtime shuffle)
- `validation/noise_injection.py`, `validation/gap_sim.py`,
  `validation/retraining.py`
- `validation/purged_cv.py` (Lopez de Prado purged K-Fold + embargo)
- `validation/cscv_pbo.py` (Combinatorially Symmetric CV / Probability of
  Backtest Overfitting)
- `validation/structural_breaks.py` (Chow / CUSUM / SADF)
- `validation/scenarios.py` (1987 / LTCM / dotcom / 2008 / COVID / 2022)
- `validation/tail_risk.py`, `validation/correlation_stress.py`
- `validation/pipeline.py` (orchestrator)

### ML
- `ml/labels.py` (triple-barrier + meta-labeling)
- `ml/feature_importance.py` (MDI / MDA / SFI)
- `ml/fracdiff.py` (fractional differentiation + ADF)
- `ml/microstructure.py` (Corwin-Schultz, Roll, Lee-Ready signed volume, OFI,
  VPIN, Kyle's lambda, Amihud)
- `ml/lstm.py` (PyTorch LSTM + walk-forward training)
- `ml/transformer.py` (encoder-only with causal mask, multi-horizon)
- `ml/rl_agent.py` (Gymnasium TradingEnv + PPO / DQN via stable-baselines3)
- `ml/features_pipeline.py` (rolling stats + lags + technicals + standardize)

### Analytics
- `analytics/metrics_full.py` (56 quantstats-parity metrics)
- `analytics/factor_analysis.py` (IC, quantile spread, factor returns)
- `analytics/attribution.py` (strategy / factor / time / Brinson)
- `analytics/round_trip.py` (trade-level MAE / MFE, holding stats)

### Regime
- `regime/hmm.py`, `regime/markov_switching.py`, `regime/bayes_alpha.py`,
  `regime/hurst.py`

### Registry
- `registry/registry.py` (SQLite backtest dedup), `registry/versioning.py`,
  `registry/journal.py` (live trade log), `registry/experiments.py`
  (MLflow-style runs)

### Deployment
- `deployment/paper.py`, `deployment/live.py` (Lumibot wrappers)
- `deployment/sizing.py` (fixed / vol-target / Kelly)
- `deployment/allocator.py`, `deployment/preflight.py` (10 checks)
- `deployment/hrp.py` (hierarchical risk parity)
- `deployment/risk_optim.py` (CVaR / CDaR efficient frontier)
- `deployment/black_litterman.py`, `deployment/cov_shrinkage.py`
  (Ledoit-Wolf / OAS), `deployment/risk_parity.py` (SQP / cyclic / cvxpy)
- `deployment/liquidity.py` (ADV caps + classification + haircuts)
- `deployment/brokers.py` - PaperBroker + IB / Alpaca / Coinbase / Kraken
  adapters

### Monitoring
- `monitoring/dashboard.py` - Streamlit live PnL, positions, alerts
- `monitoring/alerts.py` - SMTP email + Slack / Discord webhooks, per-rule
  cooldown, env-var-only credentials
- `monitoring/drift.py` - Page-Hinkley + ADWIN + KS, AutoRetrainController

### Research
- `research/llm_assistant.py` - Anthropic API integration, mock client
  injection for offline tests

### Reporting and CLI
- `reporting/tearsheet.py` (HTML / PDF, v2 with 8 sections + benchmark overlay)
- `cli/forge.py` (35+ subcommands across research, policy, data,
  agent gateway, audit, triage, ops, crypto, export, and legacy workflows)

## Quick start

```bash
# From the repository root, install the editable package.
python -m pip install -e ".[dev,ga,docs,mutate]"

# List strategies
forge list-strategies

# Validate a strategy on SPY (runs the full pipeline)
forge validate --strategy MACross --asset SPY --n-trials 5

# Run a single backtest
forge run --strategy MACross --asset SPY

# GA search
forge search --strategy MACross --asset SPY --population 100

# Tear sheet
forge tearsheet --strategy MACross --asset SPY --output tear.html

# Live dashboard
forge dashboard --journal quantforge.db
```

Programmatic basic backtest:

```python
from quantforge.core.seed import set_global_seed
from quantforge.core.engine import run_backtest
from quantforge.core.data_layer import load_asset
from quantforge.core.costs import IBKR_costs
from quantforge.strategies.library import MACross

set_global_seed(42)
prices = load_asset("SPY")              # IS-only by default
strat = MACross(fast=20, slow=100)
weights = strat.signals(prices)
result = run_backtest(prices, weights, costs=IBKR_costs)
print(result.calmar, result.sharpe, result.mdd)
```

## CLI subcommands

```
forge run                   single backtest
forge validate              run validation pipeline
forge search                GA candidate search
forge search-multi          multi-asset GA search
forge list-strategies
forge tearsheet
forge bench                 microbenchmark
forge config show|init
forge freeze                freeze hash-verified snapshots
forge preflight             pre-trade checks
forge label                 triple-barrier labels
forge factor                factor / IC / quantile spread
forge attribute             performance attribution
forge purge-cv              purged K-Fold CV
forge fracdiff
forge cscv                  CSCV / PBO from per-strategy returns
forge dashboard             Streamlit live monitor
forge policy show|verify
forge data list-providers|fetch|verify
forge agent token-issue|token-list|token-revoke|audit-verify|stage|commit|push
forge audit run|list-reviewers
forge research submit|batch|review-queue|archive|lineage|generate|promote|triage
forge triage run|list-promising|promote
forge ops daily|alerts|summary
forge crypto exchanges|fetch|submit-order|positions|balance|allow-live
forge export lean|lean-list|verify
```

## OOS sagrado (no negotiation)

- OOS partition is locked. Programmatic `OOSGuard` blocks access during
  optimization, with file lock and git-hash provenance.
- The IS / OOS split is defined in `quantforge/core/data_layer.py` and the
  formal research protocol in `docs/RESEARCH_PROTOCOL.md`.
- The GA reads only IS-train + walk-forward folds. OOS is consulted exactly
  once, after pareto-front selection, by the final gate in
  `quantforge/validation/pipeline.py`.
- Re-touching OOS_LOCKED requires explicit ceremony (see
  `docs/RESEARCH_PROTOCOL.md`).

## Anti-overfit thresholds

- Walk-forward: Calmar > buy-and-hold Calmar in each window.
- Monte Carlo: real MDD percentile in [0.20, 0.80] of the bootstrap
  distribution. Outside this band the result is either lucky or pathological.
- SPP: coefficient of variation of Calmar below 30% over +/-10% perturbation.
- Deflated Sharpe Ratio above 1.96 (95% confidence) after N-trial selection.
- Cost floor: 5 bps spread + 0.5 bps commission + 5 bps slippage per trade.
- Paper trading: 90 days minimum before any live capital.
- Live sizing: maximum 1% NAV risk per trade.

## Stack

- Python with numba JIT for hot paths
- DEAP for the multi-objective GA
- pandas / numpy / scipy / scikit-learn
- Optional: PyTorch (LSTM / Transformer), stable-baselines3 (RL),
  Streamlit (dashboard), Lumibot (paper / live brokers), Anthropic SDK
  (LLM assistant)
- Parquet for the data cache

## Documentation

- `docs/ARCHITECTURE.md` - module dependency graph, design principles,
  extension points
- `docs/v4_0_SPINE_REPORT.md` - current v1.4 spine state, test counts,
  modules added per batch, and production-readiness notes
- `docs/STRATEGY_AUTHOR.md` - tutorial for writing a custom Strategy
- `docs/GLOSSARY.md` - definitions of metrics, validation gates, and
  abbreviations
- `docs/RESEARCH_PROTOCOL.md` - formal data-split policy and OOS ceremony
- `docs/DEVELOPMENT_PLAN.md`, `DEVELOPMENT_PLAN_v1_1.md`,
  `DEVELOPMENT_PLAN_v1_2.md`, `DEVELOPMENT_PLAN_v1_3.md` - per-version plans
- `docs/v1_COMPLETION_REPORT.md`, `v1_1_COMPLETION_REPORT.md`,
  `v1_2_COMPLETION_REPORT.md`, `v1_3_COMPLETION_REPORT.md` - per-version
  reports
- `CHANGELOG.md`, `CONTRIBUTING.md` - if present at repository root
