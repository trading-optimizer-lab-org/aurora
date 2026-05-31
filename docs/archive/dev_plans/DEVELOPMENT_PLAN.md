# Aurora Development Plan — v0.1 → v1.0

Roadmap from current MVP to production-ready quant research platform. Phases organized by dependency. Within phase, tasks are mostly independent → parallel execution.

## Current state (v0.1)

DONE:
- core/ engine, costs, metrics, seed, data_layer (single-asset)
- strategies/ base + 5 (MACross, RSIMR, TSMom, Donchian, VolTarget)
- ga/ DEAP NSGA-II runner + multi-objective fitness
- validation/ walk_forward, MC bootstrap, MC reorder, SPP, lookahead, DSR, pipeline
- deployment/ Lumibot paper wrapper (basic)
- cli/ forge run/validate/search
- tests/ 12 smoke tests pass
- docs/ ARCHITECTURE.md

GAPS for v1.0 (target perfect/complete):
- single-asset only (no portfolio engine)
- no regime detection
- no PDF/HTML tear sheets
- no live trading (only paper stub)
- no risk-per-trade sizing
- no allocator across strategies
- no numba JIT (slow for 100K GA)
- no config/yaml system
- no proper logging (only prints)
- limited strategy library (5)
- no robust costs (slippage scales w/ ADV missing)
- no integration tests
- no anchored vs rolling WF modes
- no noise injection / robustness sims
- no distributed GA (Ray/Dask)
- no feature store / signal cache

---

## Phase 1: Foundation hardening (independent, parallel)

### Task 1.1: Multi-asset native engine
**File:** `aurora/core/engine_multi.py`
- Class `MultiAssetEngine` accepting dict[symbol→prices] + dict[symbol→weights]
- Portfolio-level metrics with cross-asset correlation
- Gross leverage cap, net exposure limits
- Per-asset CostModel
- Returns `MultiAssetResult` with per-asset attribution

### Task 1.2: Numba JIT acceleration
**File:** `aurora/core/engine_jit.py`
- @numba.njit on hot loops in apply_costs, MA calc, RSI calc
- Benchmark 10x+ speedup vs current pure-python loops
- Maintain identical results (round-trip test)

### Task 1.3: Tear sheet PDF/HTML generator
**File:** `aurora/reporting/tearsheet.py`
- HTML report: equity curve, drawdown, monthly returns heatmap, distribution, rolling Sharpe, MDD periods, key stats table
- Optional PDF via weasyprint
- Function `generate_tearsheet(BacktestResult, output_path)`

### Task 1.4: Logging framework
**File:** `aurora/core/logging.py`
- Structured logging via `structlog` or stdlib
- Replace print() across modules
- Log levels: DEBUG / INFO / WARN / ERROR
- File + stderr handlers, rotating file

### Task 1.5: Config system
**File:** `aurora/core/config.py`
- YAML/TOML config loader
- Schema validation via pydantic
- Default config + override mechanism
- Used by CLI for repeated runs

---

## Phase 2: Strategy library expansion (parallel)

### Task 2.1: Mean-reversion family
**File:** `aurora/strategies/library/bollinger_mr.py`
- BollingerMR: long when price < lower band, short when > upper band

### Task 2.2: Momentum family
**File:** `aurora/strategies/library/dual_momentum.py`
- DualMomentum: cross-sectional + absolute momentum (Antonacci)

### Task 2.3: Volatility breakout
**File:** `aurora/strategies/library/atr_breakout.py`
- ATRBreakout: enter on N-ATR move from prior close

### Task 2.4: Pair trading primitive
**File:** `aurora/strategies/library/pair_trade.py`
- Cointegration-based pair: z-score of spread → long/short legs

### Task 2.5: Stop loss / take profit wrapper
**File:** `aurora/strategies/library/stop_wrapper.py`
- Wraps any Strategy with HL-based intraday stop + TP
- Exit logic on stop/TP, lockout K bars

---

## Phase 3: Validation hardening (parallel)

### Task 3.1: Anchored vs rolling WF modes
**File:** `aurora/validation/walk_forward.py` (extend)
- Add `mode='rolling'|'expanding'|'anchored'`
- Anchored = IS always starts at HIST_START
- Rolling = IS slides window
- Document trade-offs

### Task 3.2: Noise injection robustness
**File:** `aurora/validation/noise_injection.py`
- Add gaussian noise σ to prices, re-run, measure metric stability
- Threshold: Calmar should drop < 30% under realistic noise

### Task 3.3: Gap simulation
**File:** `aurora/validation/gap_sim.py`
- Inject simulated gap-up/gap-down events at random dates
- Tests strategy resilience to event-driven moves

### Task 3.4: Retraining cadence simulator
**File:** `aurora/validation/retraining.py`
- Simulate periodic re-optimization with rolling window
- Reports degradation rate of strategy params over time

### Task 3.5: Combined Pipeline v2
**File:** `aurora/validation/pipeline.py` (extend)
- Integrate noise injection + gap sim into main pipeline
- New gate threshold args

---

## Phase 4: Deployment + risk (parallel)

### Task 4.1: Risk-per-trade sizing
**File:** `aurora/deployment/sizing.py`
- Position sizer: target risk/trade = X% NAV
- Volatility-based sizing: ATR-derived stop → position size
- Kelly criterion (fractional)

### Task 4.2: Live trading wrapper
**File:** `aurora/deployment/live.py`
- Lumibot Live broker bindings (Alpaca, IB)
- Pre-trade risk checks (max position, daily loss limit, correlation)
- Order routing with retry

### Task 4.3: Strategy allocator (meta-portfolio)
**File:** `aurora/deployment/allocator.py`
- Combine N validated strategies → meta-portfolio
- Risk parity / equal vol allocation
- Rebalance schedule

### Task 4.4: Pre-trade validators
**File:** `aurora/deployment/preflight.py`
- Checks before live: sufficient data, broker connection, position consistency
- Aborts deployment if any check fails

---

## Phase 5: Search & optimization improvements (parallel)

### Task 5.1: Distributed GA via joblib
**File:** `aurora/ga/runner.py` (extend)
- joblib parallel evaluation across N workers
- Optional Ray backend for cluster

### Task 5.2: Bayesian optimization alternative
**File:** `aurora/ga/bayes_opt.py`
- BO via scikit-optimize or optuna
- For tighter parameter tuning post-GA

### Task 5.3: Hyperparameter import from existing R-rounds
**File:** `aurora/ga/seed_population.py`
- Initialize GA pop from known good params (R111, HEDGE R6, etc.)
- Avoid cold-start

### Task 5.4: Multi-asset GA
**File:** `aurora/ga/multi_asset_runner.py`
- GA over multi-asset strategies (uses MultiAssetEngine)

---

## Phase 6: Infrastructure (parallel)

### Task 6.1: Integration tests
**File:** `aurora/tests/test_integration.py`
- End-to-end: data load → strategy → backtest → validate → output
- Multiple strategies, multiple assets

### Task 6.2: Property-based tests
**File:** `aurora/tests/test_property.py`
- Hypothesis-based: randomized prices, randomized params
- Invariants: returns finite, weights bounded, NAV always > 0

### Task 6.3: Hardened OOSGuard
**File:** `aurora/core/data_layer.py` (extend)
- File-system lock on OOS partition
- Git hash check on lock file (cannot bypass without commit)
- CI hook to detect contamination

### Task 6.4: Feature store with provenance
**File:** `aurora/core/features.py`
- Cache computed indicators (RSI, MA, etc.) keyed by (symbol, indicator, params)
- Provenance: hash of source data + code version
- Auto-invalidate on source change

### Task 6.5: CLI improvements
**File:** `aurora/cli/forge.py` (extend)
- `forge list-strategies` show all + specs
- `forge tearsheet --strategy X --asset Y` generate report
- `forge bench` benchmark engine speed
- `forge config show` print loaded config
- Subcommands: better help, examples

---

## Execution strategy

Phases ordered by dependency:
- Phase 1 must complete before Phase 4 (engine_multi blocks allocator)
- Phase 1 must complete before Phase 5.4 (multi_asset_runner)
- Phases 2, 3, 6 mostly independent of others

Within each phase, all tasks parallel-friendly (different files, no shared state).

### Batch plan

Batch A (5 agents, parallel):
- Task 1.1 multi-asset engine
- Task 1.2 numba JIT
- Task 1.3 tear sheet
- Task 1.4 logging
- Task 1.5 config

Batch B (5 agents, parallel):
- Task 2.1 BollingerMR
- Task 2.2 DualMomentum
- Task 2.3 ATRBreakout
- Task 2.4 PairTrade
- Task 2.5 StopWrapper

Batch C (5 agents, parallel):
- Task 3.1 WF modes
- Task 3.2 Noise injection
- Task 3.3 Gap sim
- Task 3.4 Retraining
- Task 3.5 Pipeline v2

Batch D (4 agents, parallel):
- Task 4.1 Sizing
- Task 4.2 Live wrapper
- Task 4.3 Allocator
- Task 4.4 Preflight

Batch E (4 agents, parallel):
- Task 5.1 Distributed GA
- Task 5.2 Bayes opt
- Task 5.3 Seed population
- Task 5.4 Multi-asset GA

Batch F (5 agents, parallel):
- Task 6.1 Integration tests
- Task 6.2 Property tests
- Task 6.3 Hardened OOSGuard
- Task 6.4 Feature store
- Task 6.5 CLI improvements

Total: ~28 tasks across 6 batches. Code review between batches.
