# QuantForge Architecture Diagram

ASCII data-flow diagram of the QuantForge pipeline. Each layer is responsible
for one concern; each arrow is one-way (no cross-layer leakage). The OOS data
is locked behind `OOSGuard` until the IS-only optimization stage is complete.

```
+-------------------------------------------------------------------+
|                          DATA LAYER                               |
|                                                                   |
|   yfinance / parquet cache / IBKR / crypto feeds                  |
|              |                                                    |
|              v                                                    |
|   load_asset() / load_universe()  --->  pd.Series (DatetimeIndex) |
|              |                                                    |
|              v                                                    |
|   OOSGuard.split(IS, OOS)  ---  OOS locked, IS exposed            |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                            ENGINE                                 |
|                                                                   |
|   run_backtest(prices, signal_fn, costs, ppy)                     |
|     - anti-lookahead: signal[i] applied to ret[i+1]               |
|     - cost model + slippage + ADV cap                             |
|     - metrics: Sharpe / CAGR / MDD / Calmar / Sortino / ...       |
|                                                                   |
|   MultiAssetEngine: portfolio + leverage caps + attribution       |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                       STRATEGY LIBRARY                            |
|                                                                   |
|   Strategy (abstract base)  ->  signals(prices) -> pd.Series      |
|     |                                                             |
|     +--  MACross         BollingerMR     PairTrade                |
|     |    RSIMeanRev      ATRBreakout     OnlineLearner            |
|     |    TSMomentum      DualMomentum    SeqModelStrategy         |
|     |    DonchianBreakout VolTargetWrapper StopWrapper            |
|     |                                                             |
|     +--  StrategySpec  (param ranges, tags, references)           |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                    GA OPTIMIZER  (IS ONLY)                        |
|                                                                   |
|   run_ga(strategy_cls, IS, OOS_locked, fitness_fn, GAConfig)      |
|     - DEAP NSGA-II multi-objective (Calmar, Sharpe, Robust, MDD)  |
|     - bayes_optimize (skopt) as alternate optimizer               |
|     - run_multi_asset_ga for joint cross-symbol optimization      |
|     - seed_initial_population from KNOWN_CONFIGS                  |
|                                                                   |
|   Output: Pareto front of candidate genomes (IS metrics only).    |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                    VALIDATION GATES (13)                          |
|                                                                   |
|   validate_pipeline(strategy_factory, prices, ...)                |
|     1. walk_forward         8.  noise_injection                   |
|     2. monte_carlo bootstrap 9.  gap_sim                          |
|     3. mc trade reorder     10. simulate_retraining               |
|     4. spp (param robust)   11. structural breaks (Chow/CUSUM/SADF)|
|     5. scan_lookahead       12. cscv / pbo                        |
|     6. deflated_sharpe      13. crash scenarios (KNOWN_CRASHES)   |
|     7. correlation_stress                                         |
|                                                                   |
|   ValidationReport: per-gate pass/fail + aggregate verdict.       |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                 OOS GATE  (FINAL — runs once)                     |
|                                                                   |
|   OOSGuard.unlock()  ->  validate_oos(genome, OOS_prices)         |
|     - one-shot evaluation                                         |
|     - any subsequent re-tuning re-locks the lockbox               |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                  REGISTRY  /  TRADE JOURNAL                       |
|                                                                   |
|   BacktestRegistry (SQLite)  -- store_backtest_result()           |
|     - hash_config dedup                                           |
|   ExperimentTracker  -- per-generation GA logs + Pareto           |
|   TradeJournal (SQLite)  -- live/paper executions                 |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                        DEPLOYMENT                                 |
|                                                                   |
|   PaperBroker (in-process)                                        |
|   AlpacaAdapter / IBAdapter / Coinbase / Kraken (live)            |
|   QFPaperStrategy / QFLiveStrategy  (Lumibot wrappers)            |
|                                                                   |
|   Sizing:    fixed_risk_size / vol_target_size / kelly_size       |
|   Allocators: equal_weight / equal_vol / inverse_dd / risk_parity |
|               StrategyAllocator / hrp_allocate / Black-Litterman  |
|   Liquidity: ADV cap, participation rate, liquidity-aware portfolio|
|   Preflight: PreflightCheck / PreflightReport                     |
+-------------------------------------------------------------------+
                |
                v
+-------------------------------------------------------------------+
|                        MONITORING                                 |
|                                                                   |
|   Streamlit Dashboard  ->  run_dashboard(DashboardConfig)         |
|   AlertEngine          ->  default_rules() (DD / loss / drift)    |
|   Drift detectors      ->  PSI / KS / KL on features and returns  |
+-------------------------------------------------------------------+
```

## One-way flow guarantees

- IS data never re-enters OOS evaluation; OOSGuard enforces the lockbox.
- GA reads only IS-conditioned fitness; OOS is unlocked exactly once at the
  validation step, after which the configuration becomes deployment-ready.
- Validation gates do not feed back into GA fitness; failing a gate is a hard
  reject, not a re-weighted score.
- The deployment layer reads from registry artifacts only, never from raw GA
  internal state.
