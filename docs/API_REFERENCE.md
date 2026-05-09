# Aurora — Public API Reference

Auto-summary of the top-level public API exported from each submodule's
`__init__.py`. For full signatures, parameters, and behavior, see the source
docstrings of the corresponding modules.

> Conventions: `Series` = `pd.Series` with a `DatetimeIndex` of close prices.
> All backtests apply signal at bar `i` to the return of bar `i+1`
> (anti-lookahead is enforced inside the engine).

---

## `aurora.core`

Backtest primitives: engine, costs, metrics, data layer, RNG seeding.

| Symbol | Signature | Summary |
|---|---|---|
| `run_backtest` | `run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=252, slippage_model=None, daily_volume=None, ...)` | Run a single-asset backtest from a `signal_fn` and return a `BacktestResult`. |
| `BacktestResult` | dataclass `(metrics, nav, rets, weights, timestamps)` | Result of a backtest: metrics, NAV path, per-bar returns, weights, timestamps. |
| `compute_metrics` | `compute_metrics(returns, ppy=252) -> Metrics` | Compute Sharpe, CAGR, MDD, Calmar, etc. from a return array. |
| `CostModel` | dataclass `(commission_bps, spread_bps, slippage_bps, ...)` | Trading cost specification used by the engine. |
| `IBKR_costs` | `CostModel(...)` | Pre-built cost model approximating IBKR retail equity commissions. |
| `ZERO_costs` | `CostModel(0, 0, 0, ...)` | Zero-cost reference model. |
| `set_global_seed` | `set_global_seed(seed: int) -> None` | Seed `random`, `numpy`, `torch` (if installed) for reproducibility. |
| `load_asset` | `load_asset(symbol, source="yfinance", ..., include_oos=False) -> Series` | Load a single price series from yfinance/parquet cache. |
| `load_universe` | `load_universe(symbols: list[str], **kwargs) -> dict[str, Series]` | Load many symbols at once. |
| `OOSGuard` | class | Locks an OOS window so it cannot be touched during IS optimization. |

Other internal but useful classes:

- `MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0, align_calendar="intersection")` — portfolio backtester with leverage caps and per-asset attribution. Defined in `core.engine_multi`.

### `aurora.core.snapshots`

Frozen dataset snapshots (SHA-256 hash + provenance metadata) used to lock OOS slices and reproduce backtests deterministically.

| Symbol | Summary |
|---|---|
| `DataSnapshot` | Dataclass capturing a frozen `pd.Series`, its SHA-256 hash, symbol, provenance, and lock state. |
| `SnapshotStore` | Filesystem-backed snapshot store (`freeze`, `load`, listing, hash verification). |

---

## `aurora.validation`

13 validation gates, structural break tests, MC bootstrap, CSCV/PBO.

| Symbol | Signature | Summary |
|---|---|---|
| `walk_forward` | `walk_forward(prices, strategy_factory, ...) -> WFReport` | Out-of-sample walk-forward validation across rolling/anchored windows. |
| `monte_carlo_bootstrap` | `monte_carlo_bootstrap(returns, n_paths=500, block_size=21, ...)` | Stationary block bootstrap of return paths; returns Sharpe distribution. |
| `monte_carlo_trade_reorder` | `monte_carlo_trade_reorder(trades, n_paths=500)` | Reshuffle trade order and recompute path-dependent metrics. |
| `spp` | `spp(strategy_factory, prices, param_ranges, ...) -> SPPReport` | Strategy parameter perturbation: stability across the parameter neighborhood. |
| `scan_lookahead` | `scan_lookahead(strategy, prices) -> LookaheadReport` | Static scan for common look-ahead patterns in a strategy. |
| `deflated_sharpe_check` | `deflated_sharpe_check(sharpe, n_trials, ppy=252, T=...) -> dict` | Bailey & Lopez de Prado deflated Sharpe ratio gate. |
| `validate_pipeline` | `validate_pipeline(strategy_factory, prices, name, ..., min_dsr=0.95, min_wf_pass=3, ...) -> ValidationReport` | Orchestrates 8 validation gates (walk-forward, MC bootstrap, MC trade reorder, SPP, lookahead, DSR, optional noise injection, optional gap simulation). The remaining 5 gates (purged CV, CSCV/PBO, structural breaks, tail-risk, correlation stress) are available standalone. |
| `noise_injection` | `noise_injection(strategy_factory, prices, n_samples=100, sigma_bps=10.0)` | Inject Gaussian per-bar noise; track metric degradation. |
| `gap_sim` | `gap_sim(strategy_factory, prices, n_samples=100, n_per_path=5, gap_size_max=0.05)` | Splice random overnight gaps; check survival. |
| `simulate_retraining` | `simulate_retraining(strategy_factory, prices, ...)` | Simulate periodic retraining and compute degradation curve. |
| `chow_test` / `cusum_filter` / `sadf_test` | structural break detectors | Detect parameter break-points in a return series. |
| `cscv` | `cscv(rets_per_strategy, n_blocks=16) -> CSCVResult` | Combinatorial Symmetric Cross-Validation; returns PBO. |
| `plot_pbo_distribution` / `cscv_summary_table` | reporting helpers | Render CSCV outputs. |

Crash scenarios (in `validation.scenarios`, not re-exported by default):

- `KNOWN_CRASHES`: dict of pre-built `CrashScenario`s — `1987_black_monday`, `1998_ltcm`, `2000_dotcom`, `2008_gfc`, `2010_flash_crash`, `2020_covid`, `2022_drawdown`.
- `replay_crash(strategy_factory, prices, scenario, ...) -> StressResult`
- `stress_test_all_known(strategy_factory, prices, ...) -> dict[str, StressResult]`

---

## `aurora.ml`

Lopez de Prado AFML labeling, meta-labels, microstructure, sequence models.

| Symbol | Signature | Summary |
|---|---|---|
| `triple_barrier_labels` | `triple_barrier_labels(prices, events, pt_sl, ...)` | Labels using upper/lower barriers + time barrier (AFML ch. 3). |
| `daily_volatility` | `daily_volatility(prices, span=100)` | EWM-based daily vol estimate for barrier sizing. |
| `meta_labels` | `meta_labels(primary_signal, true_labels)` | Meta-label gating signal (AFML ch. 3.6). |
| `bet_size_from_proba` | `bet_size_from_proba(proba, num_classes=2)` | Convert classifier probabilities to bet sizes (AFML ch. 10). |
| `mean_decrease_impurity` / `mean_decrease_accuracy` / `single_feature_importance` | feature-importance estimators (AFML ch. 8) | |
| `corwin_schultz_spread` / `roll_spread_estimator` / `signed_volume` / `order_flow_imbalance` / `vpin` / `kyle_lambda` / `amihud_illiquidity` | microstructure estimators | |
| `frac_diff_ffd` / `find_min_d` | `(series, d, threshold) -> Series`, `(series, ...) -> float` | Fixed-window fractional differentiation (AFML ch. 5) and the d-search helper. Live in `aurora.ml.fracdiff`; import from there directly (not re-exported from `aurora.ml`). |
| `LSTMConfig` / `LSTMForecaster` | torch-optional LSTM wrapper | Walk-forward retrainable LSTM. |
| `TransformerConfig` / `TimeSeriesTransformer` | torch-optional transformer | Multi-horizon transformer forecaster. |
| `RLAgentConfig` / `RLAgent` / `TradingEnv` | RL trading components (gym + stable-baselines3 optional) | |
| `FeaturePipeline` / `FeaturePipelineConfig` | feature engineering pipeline | Standard feature builder for sequence/RL models. |

---

## `aurora.strategies`

Base class + 12 reference strategies in `aurora.strategies.library`.

Base:

| Symbol | Signature | Summary |
|---|---|---|
| `Strategy` | abstract base class | Override `signals(prices) -> Series`. |
| `StrategySpec` | dataclass | Static metadata: param ranges, tags, references. |

Library (`aurora.strategies.library`):

| Class | Signature | Summary |
|---|---|---|
| `MACross` | `MACross(fast=20, slow=100, allow_short=True)` | Two-MA crossover (long/short). |
| `RSIMeanRev` | `RSIMeanRev(period=2, oversold=10, overbought=90)` | Short-period RSI mean-reversion. |
| `TSMomentum` | `TSMomentum(lookback=252, allow_short=True)` | Time-series momentum on lookback. |
| `DonchianBreakout` | `DonchianBreakout(channel=55, exit_channel=20)` | Turtle-style channel breakout. |
| `BollingerMR` | `BollingerMR(window=20, k=2.0)` | Bollinger band mean reversion. |
| `VolTargetWrapper` | `VolTargetWrapper(inner, target_vol_annual=0.10)` | Wrap any strategy with realized-vol targeting. |
| `ATRBreakout` | `ATRBreakout(atr_window=14, k=2.0)` | ATR-based breakout. |
| `DualMomentum` | `DualMomentum(lookback=252, abs_threshold=0.0)` | Antonacci absolute + relative momentum. |
| `StopWrapper` | `StopWrapper(inner, stop_pct=0.05)` | Per-trade hard stop overlay. |
| `PairTrade` | `PairTrade(symbol_a, symbol_b, z_entry=2.0, z_exit=0.5)` | Cointegration pair trade. |
| `OnlineLearner` | `OnlineLearner(base_model, retrain_freq=22)` | Online retrain wrapper. |
| `SeqModelStrategy` | `SeqModelStrategy(model_cls, lookback=60, ...)` | Drives signals from an `LSTMForecaster` / transformer. |

---

## `aurora.ga`

Genetic and Bayesian optimizers; multi-asset GA; seed populations.

| Symbol | Signature | Summary |
|---|---|---|
| `run_ga` | `run_ga(strategy_cls, is_prices, oos_prices, fitness_fn, config: GAConfig)` | DEAP NSGA-II multi-objective GA over IS, OOS gate at the end. |
| `GAConfig` | dataclass `(population, generations, seed, ...)` | GA hyper-parameters. |
| `multi_objective_fitness` | `(genome, strategy_cls, is_p, oos_p, ...) -> tuple[Calmar, Sharpe, Robust, MDDpen]` | DEPRECATED — leaks OOS into the GA loop. Prefer `multi_objective_fitness_is`. |
| `multi_objective_fitness_is` | `(genome, strategy_cls, is_p, ...) -> tuple` | IS-only variant (no OOS leakage). |
| `scalar_fitness` / `scalar_fitness_is` | scalarized variants | |
| `validate_oos` | `validate_oos(genome, strategy_cls, oos_p, ...) -> bool` | Final OOS gate, run only after IS-only optimization. |
| `bayes_optimize` | `bayes_optimize(strategy_cls, is_p, oos_p, fitness_fn, config: BayesConfig)` | scikit-optimize Bayesian optimizer. |
| `BayesConfig` | dataclass | BO hyper-parameters (`n_calls`, `acquisition`, ...). |
| `run_multi_asset_ga` | `(strategy_cls, price_dict, fitness_fn, config: MultiAssetGAConfig)` | Joint optimization across a universe. |
| `seed_initial_population` | `(toolbox, n, known_configs)` | Seed GA population from `KNOWN_CONFIGS`. |
| `KNOWN_CONFIGS` / `load_known_configs` | curated good starting points | |

---

## `aurora.regime`

Regime detection: HMM, Markov switching, Hurst exponent.

| Symbol | Signature | Summary |
|---|---|---|
| `GaussianHMM` | class (hmmlearn-optional) | Hamilton-style Gaussian HMM regime detector. |
| `HMMResult` | dataclass | States, transition matrix, emission params. |
| `regime_conditional_metrics` | `(returns, states) -> DataFrame` | Per-regime metrics breakdown. |
| `detect_regime_change` | `(states, threshold) -> bool` | Flag a regime change vs. baseline state. |
| `hurst_rs` | `hurst_rs(series) -> HurstResult` | R/S Hurst exponent (Hurst 1951). |
| `hurst_dfa` | `hurst_dfa(series) -> HurstResult` | Detrended fluctuation analysis (Peng et al. 1994). |
| `rolling_hurst` | `rolling_hurst(series, window) -> Series` | Rolling Hurst exponent. |
| `hurst_regime_filter` | `hurst_regime_filter(series, ...) -> Series` | Filter signals by trending vs. mean-reverting regime. |
| `MarkovSwitchingMean` | class | Markov regime-switching mean (Hamilton 1989); statsmodels-optional with manual EM fallback. Re-exported from `aurora.regime`. |
| `BayesAlphaModel` / `bayesian_rolling_alpha` | `(strategy_returns, benchmark_returns, window, ...) -> BayesAlphaResult` | Rolling Bayesian alpha estimator. `BayesAlphaModel` is an alias for `bayesian_rolling_alpha`. |
| `BayesAlphaResult` | dataclass | Rolling posterior bands for alpha + beta. |

---

## `aurora.registry`

SQLite-backed result store, MLflow-style experiment tracker, trade journal.

| Symbol | Signature | Summary |
|---|---|---|
| `BacktestRegistry` | `BacktestRegistry(db_path)` | Persistent backtest result store with config-hash dedup. |
| `RegistryEntry` | dataclass | Single row representation. |
| `store_backtest_result` | `store_backtest_result(registry, result, config, ...)` | Convenience wrapper. |
| `hash_config` | `hash_config(config: dict) -> str` | Deterministic SHA hash for dedup. |
| `ExperimentTracker` | class | MLflow-style tracker for GA / optimization experiments. |
| `ExperimentMeta` / `GenerationLog` / `ExperimentResult` | dataclasses | Schema for experiment runs and per-generation logs. |
| `TradeJournal` | `TradeJournal(db_path)` | Live/paper trade log on SQLite. |
| `JournalEntry` | dataclass | Trade journal row. |

---

## `aurora.deployment`

Paper / live brokers, allocators, sizing, liquidity, preflight.

| Symbol | Signature | Summary |
|---|---|---|
| `PaperBroker` | `PaperBroker(BrokerConfig(...))` | In-process paper broker (subclass of `Broker`). |
| `AlpacaAdapter` / `IBAdapter` / `CoinbaseAdapter` / `KrakenAdapter` | broker adapters (optional deps) | |
| `create_broker` | `create_broker(config: BrokerConfig) -> Broker` | Factory based on `BrokerConfig.kind`. |
| `Order` / `Position` / `BrokerConfig` | dataclasses | Broker domain model. |
| `QFPaperStrategy` / `QFLiveStrategy` | Lumibot wrappers | Drop-in Lumibot adapters for Aurora `Strategy`. |
| `LiveConfig` | dataclass | Live trading configuration. |
| `submit_with_retry` / `run_preflight` | helpers | Resilient order submission and pre-trade checks. `preflight_checks` is kept as a back-compat alias for `run_preflight`. |
| `fixed_risk_size` | `fixed_risk_size(nav, entry_price, stop_price, risk_pct=0.01) -> int` | Risk-per-trade share count. |
| `vol_target_size` | `vol_target_size(nav, asset_price, asset_vol_annual, target_vol_annual)` | Vol-target sizing. |
| `kelly_size` | `kelly_size(nav, asset_price, win_rate, ...)` | Fractional Kelly criterion. |
| `equal_weight` / `equal_vol` / `inverse_dd` / `risk_parity` | `(strat_returns_dict, ...) -> dict` | Allocator weight rules. All four are re-exported from `aurora.deployment`. The canonical name `risk_parity` is also reachable as `risk_parity_allocator` (alias) and as `risk_parity_weights` from `aurora.deployment.risk_parity`. |
| `StrategyAllocator` | class | Multi-strategy allocator with rebalance schedule. |
| `BlackLittermanModel` | class | Black-Litterman views + posterior. |
| `hrp_allocate` | `(returns, ...) -> Series` | Hierarchical risk parity weights. |
| `ledoit_wolf_shrinkage` / `oas_shrinkage` / `exponential_cov` | covariance estimators | |
| `compute_liquidity_profile` / `LiquidityAwarePortfolio` | liquidity-aware sizing | |
| `PreflightCheck` / `PreflightReport` | preflight schemas | |

---

## `aurora.monitoring`

Streamlit dashboard, alert engine, drift detectors.

| Symbol | Signature | Summary |
|---|---|---|
| `run_dashboard` | `run_dashboard(config: DashboardConfig)` | Launch the Streamlit dashboard (requires `streamlit`). |
| `DashboardConfig` | dataclass | Dashboard wiring (registry path, journal path, refresh, ...). |
| `compute_dashboard_metrics` | `compute_dashboard_metrics(...) -> dict` | Pure metrics computation (no streamlit needed). |
| `fetch_dashboard_data` | `fetch_dashboard_data(...) -> dict` | Pull data for the dashboard from registry/journal. |
| `STREAMLIT_AVAILABLE` | `bool` | Streamlit-import probe. |
| `AlertEngine` | `AlertEngine(rules, config: AlertConfig)` | Alerting loop over rules. |
| `Alert` / `AlertConfig` / `AlertRule` | dataclasses | Alert schema. |
| `default_rules` | `default_rules() -> list[AlertRule]` | Sensible default rule set (DD, drift, daily loss). |
| `compute_daily_loss` / `compute_max_dd` / `compute_drift_metric` | pure metric helpers | |

Drift detectors live in `aurora.monitoring.drift` (Page-Hinkley, ADWIN, KS) and a higher-level `AutoRetrainController`.

---

## `aurora.analytics`

Comprehensive metrics + round-trip / per-trade attribution.

- `metrics_full` — full metric set (Sharpe, Sortino, Calmar, Omega, tail metrics, ...).
- `round_trip` — round-trip trade extraction and per-trade attribution.

---

## `aurora.cli`

`forge` console entry point (defined in `pyproject.toml`).

```
forge --help
```

Subcommands: `run`, `validate`, `search`, `list-strategies`, `tearsheet`, `bench`, `config` (`show`, `init`), `preflight`, `label`, `factor`, `attribute`, `purge-cv`, `fracdiff`, `cscv`, `dashboard`.

---

_Last regenerated: see `aurora/__version__`. Source of truth for any signature
is the module docstring, not this file._
