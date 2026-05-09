# Aurora Architecture

Aurora is layered: a deterministic core engine, a strategy library, an
optimization layer (GA + Bayesian), a militant validation pipeline, an
analytics + reporting layer, and a deployment + monitoring layer for paper /
live trading. The OOS partition is sacred at every layer.

## Pipeline (gate sequence)

```
[Strategy class + param ranges]
            |
            v
   [GA / Bayesian search over IS only]
            |
            v
   [IS-fitness filter]              -> top candidates
            |
            v
   [Walk-forward]                   <-- gate 1
            |
            v
   [MC bootstrap]                   <-- gate 2
            |
            v
   [MC trade reorder]               <-- gate 3
            |
            v
   [SPP +/-10%]                     <-- gate 4
            |
            v
   [Deflated Sharpe]                <-- gate 5
            |
            v
   [Lookahead AST + runtime]        <-- gate 6
            |
            v
   [Noise injection]                <-- gate 7  (optional)
            |
            v
   [Gap simulation]                 <-- gate 8  (optional)
            |
            v
   [Purged K-Fold CV]               <-- gate 9
            |
            v
   [CSCV / PBO]                     <-- gate 10
            |
            v
   [Synthetic crash scenarios]      <-- gate 11
            |
            v
   [Tail-risk amplification]        <-- gate 12
            |
            v
   [Correlation-breakdown stress]   <-- gate 13
            |
            v
   [SURVIVORS] -> single OOS hold-out gate
            |
            v
   [Paper trading 90 days]
            |
            v
   [Live with 1% risk-per-trade sizing + drift monitor]
```

## Design principles

### 1. OOS sagrado (sacred)

This is the principal architectural invariant. It is enforced at three places:

- `aurora/core/data_layer.py` defines `IS_END = 2012-12-31` and
  `OOS_START = 2013-01-01`. `load_asset()` defaults `include_oos=False`. The
  `OOSGuard` context manager records every OOS read with a timestamp and the
  current git hash to `data_cache_qf/.oos_lock.json`.
- `aurora/ga/fitness.py` builds fitness using IS prices only. The legacy
  signature that accepted `prices_oos` is retained as a deprecated alias that
  ignores its OOS argument and emits a warning on first call. Walk-forward
  robustness inside the GA fitness is computed across IS sub-windows, never
  IS-vs-OOS.
- `aurora/validation/pipeline.py` is the only orchestrator allowed to call
  the final OOS gate, and only after the IS pipeline has selected survivors.

The formal data-split policy lives in `docs/RESEARCH_PROTOCOL.md`.

### 2. Reproducibility

`aurora.core.seed.set_global_seed(N)` once at start. All randomness flows
from this. `child_rng(name)` for per-component RNG, deterministic given the
global seed.

### 3. Anti-lookahead

Three layers:

- API: `Strategy.signals(prices)` returns weights, where `weights[i]` is the
  position at close of bar `i`, applied to the return of bar `i+1`. Causality
  rule: `weights[i]` may use `prices[:i+1]` only.
- Static: `validation/lookahead_check.scan_lookahead()` walks the AST of a
  strategy module and flags forward-slice patterns.
- Runtime: `validation/lookahead_check.runtime_lookahead_check()` shuffles
  bars after index `k` and asserts that `signals[:k]` is unchanged.

### 4. Cost realism

`ZERO_costs` is for sanity checks only. `IBKR_costs` is the default for any
real backtest. `core/slippage.py` adds Volume / SquareRoot / Linear /
FixedBPS models. `core/costs_intraday.py` adds bid-ask scaling, time-of-day
participation, and square-root market impact via ADV.

### 5. Multi-test correction

`validation/deflated_sharpe.py` corrects for selection from N trials. Always
pass `n_trials` when reporting best-of-search Sharpe.

### 6. Determinism + provenance

- Backtest registry (`registry/registry.py`) deduplicates by config hash.
- Trade journal (`registry/journal.py`) logs live trades with daily PnL.
- Experiment tracker (`registry/experiments.py`) is MLflow-style.
- Feature store (`core/features.py`) records provenance for every feature.

## Directory layout (v1.3 state)

```
aurora/
├── __init__.py                # version sourced from pyproject.toml
├── README.md
├── core/
│   ├── engine.py              single-asset backtest core
│   ├── engine_multi.py        portfolio engine
│   ├── engine_jit.py          numba JIT kernels
│   ├── engine_intraday.py     v1.3: minute / hourly bars
│   ├── bars.py                v1.3: tick / volume / dollar bars
│   ├── costs.py               cost models
│   ├── costs_intraday.py      v1.3: intraday cost model
│   ├── slippage.py            slippage models
│   ├── metrics.py             Calmar / Sharpe / Sortino / DSR / PSR
│   ├── seed.py                global + child RNG
│   ├── data_layer.py          OOS partition + OOSGuard
│   ├── realtime.py            v1.3: yfinance polling + ring buffer
│   ├── config.py              pydantic v2 YAML / TOML
│   ├── logging.py             structured logging
│   ├── features.py            feature store with provenance
│   └── taxes.py               FIFO / LIFO / HIFO + wash sale
├── strategies/
│   ├── base.py                Strategy ABC + StrategySpec
│   └── library/
│       ├── ma_cross.py
│       ├── rsi_meanrev.py
│       ├── tsmom.py
│       ├── donchian.py
│       ├── bollinger_mr.py
│       ├── dual_momentum.py
│       ├── atr_breakout.py
│       ├── pair_trade.py      multi-asset
│       ├── stop_wrapper.py
│       ├── voltarget_wrapper.py
│       ├── online_learner.py
│       └── seq_model.py       v1.3: LSTM / Transformer / RL wrapper
├── ga/
│   ├── runner.py              NSGA-II + joblib
│   ├── fitness.py             IS-only multi-objective fitness (OOS sagrado)
│   ├── bayes_opt.py           skopt
│   ├── seed_population.py
│   └── multi_asset_runner.py
├── validation/
│   ├── walk_forward.py        rolling / expanding / anchored
│   ├── monte_carlo.py         block bootstrap + trade reorder
│   ├── spp.py
│   ├── lookahead_check.py     AST + runtime
│   ├── deflated_sharpe.py
│   ├── noise_injection.py
│   ├── gap_sim.py
│   ├── retraining.py
│   ├── purged_cv.py           Lopez de Prado purged K-Fold + embargo
│   ├── cscv_pbo.py            CSCV / PBO
│   ├── structural_breaks.py   Chow / CUSUM / SADF
│   ├── scenarios.py           historical crash templates
│   ├── tail_risk.py
│   ├── correlation_stress.py
│   └── pipeline.py            orchestrator
├── ml/
│   ├── labels.py              triple-barrier + meta-labeling
│   ├── feature_importance.py  MDI / MDA / SFI
│   ├── fracdiff.py            fractional differentiation + ADF
│   ├── microstructure.py      v1.3: spread, OFI, VPIN, Kyle, Amihud
│   ├── lstm.py                v1.3: PyTorch LSTM
│   ├── transformer.py         v1.3: encoder-only transformer
│   ├── rl_agent.py            v1.3: Gymnasium TradingEnv + PPO / DQN
│   └── features_pipeline.py   v1.3: rolling stats + lags + technicals
├── analytics/
│   ├── metrics_full.py
│   ├── factor_analysis.py
│   ├── attribution.py
│   └── round_trip.py
├── regime/
│   ├── hmm.py
│   ├── markov_switching.py
│   ├── bayes_alpha.py
│   └── hurst.py
├── registry/
│   ├── registry.py
│   ├── versioning.py
│   ├── journal.py
│   └── experiments.py
├── deployment/
│   ├── paper.py
│   ├── live.py
│   ├── sizing.py
│   ├── allocator.py
│   ├── preflight.py
│   ├── hrp.py
│   ├── risk_optim.py          CVaR / CDaR
│   ├── black_litterman.py
│   ├── cov_shrinkage.py       Ledoit-Wolf / OAS
│   ├── risk_parity.py         SQP / cyclic / cvxpy
│   ├── liquidity.py
│   └── brokers.py             v1.3: Paper + IB / Alpaca / Coinbase / Kraken
├── monitoring/                v1.3
│   ├── dashboard.py           Streamlit live PnL + positions + alerts
│   ├── alerts.py              SMTP + Slack / Discord webhooks
│   └── drift.py               Page-Hinkley + ADWIN + KS
├── research/                  v1.3
│   └── llm_assistant.py       Anthropic API integration
├── reporting/
│   └── tearsheet.py           HTML / PDF (v2: 8 sections + benchmark)
├── cli/
│   └── forge.py               15 subcommands
├── tests/                     60+ test files, 946 cumulative tests
├── examples/
└── docs/
    ├── ARCHITECTURE.md        this file
    ├── RESEARCH_PROTOCOL.md
    ├── STRATEGY_AUTHOR.md
    ├── GLOSSARY.md
    ├── DEVELOPMENT_PLAN*.md
    └── v1_*_COMPLETION_REPORT.md
```

## v1.3 additions (summary)

The v1.3 release adds three orthogonal layers without changing the existing
gate sequence.

- **`monitoring/`** - Streamlit dashboard, SMTP / webhook alerts with per-rule
  cooldown and env-var-only credentials, drift detectors (Page-Hinkley, ADWIN,
  KS) wired to an `AutoRetrainController`.
- **`research/`** - Optional LLM research assistant. Uses the Anthropic API to
  read `RESEARCH_LOG`, propose strategy ideas, draft Strategy code, critique
  results, and summarize. Mock client injection is supported for offline tests.
- **`deployment/brokers.py`** - Adapter pattern over PaperBroker plus IB /
  Alpaca / Coinbase / Kraken. Lazy SDK imports with clear install hints. All
  credentials via env-var name, never stored in code.
- **`core/engine_intraday.py`, `core/bars.py`, `core/costs_intraday.py`,
  `core/realtime.py`** - intraday backtest engine, alternative bar
  constructions per AFML Ch.2, intraday cost model with bid-ask + U-shape
  participation + square-root impact, and yfinance-based polling adapter
  with anti-lookahead replay.
- **`ml/microstructure.py`, `ml/lstm.py`, `ml/transformer.py`,
  `ml/rl_agent.py`, `ml/features_pipeline.py`,
  `strategies/library/seq_model.py`** - microstructure features
  (Corwin-Schultz, Roll, Lee-Ready, OFI, VPIN, Kyle, Amihud), PyTorch LSTM
  with walk-forward training, encoder-only transformer with causal mask,
  Gymnasium TradingEnv with PPO / DQN via stable-baselines3, reusable
  feature pipeline, and a generic strategy wrapper exposing any predictor
  through the Strategy interface.

## OOS sagrado (re-affirmed)

The contract is owned by these three call sites:

1. `aurora/core/data_layer.py` -> `OOSGuard`, `load_asset(include_oos=False)`
2. `aurora/ga/fitness.py` -> `multi_objective_fitness_is`,
   `scalar_fitness_is`, `validate_oos`
3. `aurora/validation/pipeline.py` -> single OOS hold-out call after
   selection

The formal split (IS_TRAIN, IS_VALID, WF, OOS_DEV, OOS_LOCKED, FORWARD)
and the lockbox ceremony for re-touching OOS_LOCKED are documented in
`docs/RESEARCH_PROTOCOL.md`.

## Module dependency

```
core/
├── seed.py        (no deps)
├── costs.py       (numpy)
├── slippage.py    (numpy)
├── metrics.py     (numpy, scipy)
├── data_layer.py  (pandas, yfinance)
├── engine.py      (above)
├── engine_multi.py
├── engine_jit.py  (numba)
├── engine_intraday.py
├── bars.py        (numpy, optional numba)
├── costs_intraday.py
├── realtime.py
├── features.py    (provenance)
├── config.py      (pydantic)
├── logging.py
└── taxes.py

strategies/
├── base.py        (numpy, pandas)
└── library/       (depends on base; seq_model.py depends on ml/)

ga/
├── fitness.py     (engine, costs)
├── runner.py      (deap, joblib)
├── bayes_opt.py   (skopt)
├── seed_population.py
└── multi_asset_runner.py

validation/
├── walk_forward.py
├── monte_carlo.py
├── spp.py
├── lookahead_check.py
├── deflated_sharpe.py
├── noise_injection.py
├── gap_sim.py
├── retraining.py
├── purged_cv.py
├── cscv_pbo.py
├── structural_breaks.py
├── scenarios.py
├── tail_risk.py
├── correlation_stress.py
└── pipeline.py    (orchestrates above + final OOS gate)

ml/                 (optional torch / sb3 / numba deps)
analytics/          (numpy / pandas / statsmodels)
regime/             (hmmlearn / statsmodels)
registry/           (sqlite, stdlib only)

deployment/
├── sizing.py
├── allocator.py
├── preflight.py
├── hrp.py / risk_optim.py / black_litterman.py / cov_shrinkage.py /
│   risk_parity.py / liquidity.py
├── paper.py / live.py  (lumibot)
└── brokers.py     (lazy imports for ibapi / alpaca / coinbase / kraken)

monitoring/         (streamlit, smtplib, urllib stdlib, numpy, pandas)
research/           (anthropic, optional)

reporting/
└── tearsheet.py    (matplotlib, optional weasyprint)

cli/
└── forge.py        (entry point)
```

## Extending

### Add a new strategy

1. Create `strategies/library/my_strat.py`.
2. Subclass `Strategy`, implement `signals(prices) -> np.array`.
3. Implement `spec()` returning `StrategySpec` with param ranges.
4. Register in `strategies/library/__init__.py` (import + `__all__`).
5. Run `forge validate --strategy MyStrat --asset SPY`.
6. Run `forge search --strategy MyStrat --asset SPY`.

See `docs/STRATEGY_AUTHOR.md` for the full tutorial.

### Add a new gate

1. Create `validation/my_check.py`.
2. Implement a function returning a report dataclass with a `passed` field.
3. Integrate the call in `validation/pipeline.py`.
4. Add the result to the unified `ValidationReport`.
5. Add threshold args to the `validate_pipeline()` signature.

### Add a new broker adapter

1. Add a class in `deployment/brokers.py` implementing the broker protocol
   (place_order, fetch_position, etc.).
2. Use lazy imports for the underlying SDK so the rest of the package stays
   importable without it.
3. Read credentials from environment variables only.
4. Expose the new adapter through the broker factory.

## TODO (next iterations)

- [ ] Distributed GA via Ray / Dask (currently joblib only)
- [ ] CI tests with synthetic-data generators per gate
- [ ] Tear sheet PDF without WeasyPrint dependency
- [ ] Native vectorbt path inside `engine_jit` (currently independent)
- [ ] Tick-level backtest (currently minute is the smallest native bar)
