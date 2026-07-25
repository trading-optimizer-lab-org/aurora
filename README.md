# Aurora

Aurora v1.5 -- quant research engine with 13 validation gates plus a
final OOS hold-out (see `docs/ARCHITECTURE.md` for the canonical
enumeration). `validate_pipeline` orchestrates 8 of the 13 gates;
purged CV, CSCV, scenarios, tail-risk, and correlation-stress run
standalone. 12 strategies, intraday + DL/RL + dashboard + multi-broker
+ LLM. Cumulative test coverage: 2800+ tests across v1.0 / v1.1 / v1.2
/ v1.3 / v1.4 / v1.5 (count in `tests/`; verify with
`pytest --collect-only -q`).

## GitHub-only performance framework

Los runs pesados nuevos usan
`.github/workflows/_aurora-future-run-v3.yml`: preflight, datos preparados una
vez, smoke, piloto real, planificación adaptativa hasta 360 runners estándar,
shards reanudables, retries selectivos, merge acotado, reconciliación exacta y
verificación independiente.

Comprobaciones disponibles:

- `github-performance-ci.yml`: contratos y smoke real de cuatro shards.
- `github-performance-reference.yml`: workload manual de 1.024 unidades.
- `github-performance-benchmark.yml`: baseline equivalente frente al modo
  optimizado; sólo compara velocidad si los resultados científicos coinciden.
- `github-performance-policy.yml`: impide que workflows pesados futuros eviten
  el framework.

La especificación de referencia está en
`config/github_performance_reference.yaml` y el estándar completo en
`docs/GITHUB_RUN_MASTER_STANDARD.md`.

Renamed from Aurora to Aurora in v1.5.0 (R23). The legacy
`aurora` namespace remains importable as a thin compat shim that
emits a `DeprecationWarning`; the shim is removed in v1.6.

## Filosofia

Generate thousands of strategy candidates. Approve only those that survive every
mandated gate. Anything that fails one gate is rejected, no exceptions.

The non-negotiable doctrine:

1. **OOS sagrado** - the out-of-sample partition is sacred. The genetic algorithm
   never sees OOS prices. OOS is touched only after candidates have been chosen,
   and only by the final OOS gate.
2. **Walk-forward** - candidate must beat buy-and-hold Calmar inside multiple
   non-overlapping windows.
3. **Monte Carlo** - block-bootstrap returns and trade-reorder MC.
4. **System Parameter Permutation (SPP)** - perturb each parameter +/-10% and
   require Calmar coefficient of variation below 30%.
5. **Deflated Sharpe Ratio** - Bailey / Lopez de Prado correction for selection
   bias across N candidates.

`OOSGuard` lives in `aurora/core/data_layer.py` and the GA fitness path
that defends the OOS sacred boundary lives in `aurora/ga/fitness.py`.

Every approved strategy then enters paper trading for 90 days minimum before live
deployment with a 1% risk-per-trade cap.

The full pipeline is reproducible from a single seed. Re-running months later
with the same seed reproduces identical results.

## Capabilities by area (v1.3)

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

### Monitoring (v1.3)
- `monitoring/dashboard.py` - Streamlit live PnL, positions, alerts
- `monitoring/alerts.py` - SMTP email + Slack / Discord webhooks, per-rule
  cooldown, env-var-only credentials
- `monitoring/drift.py` - Page-Hinkley + ADWIN + KS, AutoRetrainController

### Research (v1.3)
- `research/llm_assistant.py` - Anthropic API integration, mock client
  injection for offline tests

### Reporting and CLI
- `reporting/tearsheet.py` (HTML / PDF, v2 with 8 sections + benchmark overlay)
- `cli/forge.py` (15 subcommands)

## Quick start

```bash
# pyproject.toml lives at the repo root and declares the `aurora`
# package via [tool.setuptools.package-dir]. From the repo root:
pip install -e .

# List strategies
aurora list-strategies

# Validate a strategy on SPY (runs the full pipeline)
aurora validate --strategy MACross --asset SPY --n-trials 5

# Run a single backtest
aurora run --strategy MACross --asset SPY

# GA search
aurora search --strategy MACross --asset SPY --population 100

# Tear sheet
aurora tearsheet --strategy MACross --asset SPY --output tear.html

# Live dashboard
aurora dashboard --journal aurora.db
```

The legacy `forge` CLI keeps working as a deprecated alias during the
v1.5 shim window; both `forge` and `aurora` dispatch to the same entry
point.

Programmatic basic backtest:

```python
from aurora.core.seed import set_global_seed
from aurora.core.engine import run_backtest
from aurora.core.data_layer import load_asset
from aurora.core.costs import IBKR_costs
from aurora.strategies.library import MACross

set_global_seed(42)
prices = load_asset("SPY")              # IS-only by default
strat = MACross(fast=20, slow=100)
weights = strat.signals(prices)
result = run_backtest(prices, weights, costs=IBKR_costs)
print(result.calmar, result.sharpe, result.mdd)
```

## CLI subcommands (15)

```
aurora run                   single backtest
aurora validate              run validation pipeline
aurora search                GA candidate search
aurora list-strategies
aurora tearsheet
aurora bench                 microbenchmark
aurora config show|init
aurora preflight             pre-trade checks
aurora label                 triple-barrier labels
aurora factor                factor / IC / quantile spread
aurora attribute             performance attribution
aurora purge-cv              purged K-Fold CV
aurora fracdiff
aurora cscv                  CSCV / PBO from per-strategy returns
aurora dashboard             Streamlit live monitor
```

## OOS sagrado (no negotiation)

- OOS partition is locked. Programmatic `OOSGuard` blocks access during
  optimization, with file lock and git-hash provenance.
- The IS / OOS split is defined in `aurora/core/data_layer.py` and the
  formal research protocol in `docs/RESEARCH_PROTOCOL.md`.
- The GA reads only IS-train + walk-forward folds. OOS is consulted exactly
  once, after pareto-front selection, by the final gate in
  `aurora/validation/pipeline.py`.
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
- `docs/v1_3_COMPLETION_REPORT.md` - current state, test counts, modules
  added per batch
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
