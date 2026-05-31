# Aurora v1.3 — Deep Read-Only Audit

**Date:** 2026-05-07
**Method:** SDD parallel investigation, 8 read-only agents, ~321 findings
**Scope:** Entire Aurora package post-v1.3 + mejoras P/Q/R/S/T

## Findings count by domain

| Domain | Files audited | Findings | Critical | High | Medium | Low |
|--------|--------------:|---------:|---------:|-----:|-------:|----:|
| A Core engine | 17 | 62 | 6 | 24 | 19 | 13 |
| B Validation | 16 | 47 | 3 | 11 | 18 | 9+6 INFO |
| C ML/DL/RL | 9 | 35 | 1 | 9 | 14 | 11 |
| D Strategies+GA | 17 | 33 | 0 | 11 | 12 | 10 |
| E Regime+Registry | 10 | 30 | 0 | 10 | 12 | 8 |
| F Deployment | 12 | 40 | 8 | 12 | 10 | 10 |
| G Monitoring+Research | 9 | 31 | 0 | 9 | 13 | 9 |
| H Infra+Tests+Docs | ~20 | 43 | 0 | 8 | 21 | 14 |
| **Total** | **~110** | **~321** | **18** | **94** | **119** | **84+6** |

## Top 18 Critical findings (must fix before production)

### Engine layer
1. **engine.py:124-125** — `nav[0]=1.0` silently overwrites first-bar PnL when net_rets[0]≠0; pattern repeats in engine_jit.py, but engine_intraday.py and engine_multi.py zero net_rets[0] first → inconsistent NAV across engines.
2. **engine_jit.py:300-303** — JIT path raises on weights >1+1e-9 but does NOT clip; engine.py clips. Breaks "1e-9 equivalence" invariant.
3. **engine_multi.py:255-275** — multi-asset apply_costs aggregation: per-asset cost on rescaled weights then summed with first-bar zero leaks turnover across assets.
4. **data_layer.py:268-276** — `load_from_snapshot` wrapper bypasses OOSGuard requirement (only enforced inside SnapshotStore.load).
5. **taxes.py:255-262** — NAV mark-to-market computes `shares_during = prev_shares - delta` AFTER prev_shares is overwritten; wrong on tiny rebalances; also branch with `delta > 1e-12` is logically broken.
6. **engine.py:99-122 + engine_jit.py:30-39** — slippage Python loop O(T) dispatch + bare `except Exception` swallows real bugs as "rejection".

### Validation layer
7. **pipeline.py:163-169** — `monte_carlo_trade_reorder` called TWICE; first call passes `np.zeros(...)` and is dead, but consumes the same child_rng → reproducibility hash poisoned.
8. **pipeline.py:154 + core/metrics.py:113-144** — DSR uses annualized Sharpe with per-period Mertens variance → systematically inflated DSR for daily strategies.
9. **monte_carlo.py:130-131** — fixed-method bootstrap truncates last block; biases distribution.

### ML/DL/RL layer
10. **labels.py:201-217** — triple-barrier `prices.loc[t0:t1_target]` inclusive on both ends + duplicate-indexed timestamps → wrong labels silent corruption.

### Deployment layer
11. **brokers.py:165-176** — `KillSwitch` no automatic daily reset → permanent halt after first daily-loss event.
12. **brokers.py:209** — `AuditLog` SQLite no WAL/no synchronous=FULL → crash between INSERT and OS fsync loses fills/rejects.
13. **brokers.py:183-260** — `AuditLog` no rotation; long sessions span midnight UTC writing to yesterday's DB.
14. **brokers.py:233** — `_dt.utcnow()` deprecated + naive datetime in audit `ts` field → reconciliation breaks at midnight UTC.
15. **brokers.py:501-540** — `submit_order` no idempotency on `client_order_id` → retry on lost-response double-submits.
16. **live.py:83-109 + 142-303** — `submit_with_retry` blind retry + `QFLiveStrategy` class-level mutable state (`_qf_strategy`, `_qf_halted`) → multi-instance unsafe + halt flag persists across sessions.
17. **brokers.py:806-811 (and IB/Coinbase/Kraken)** — adapter `sync()` returns broker positions under `missing_local` → `reconcile()` ALWAYS raises in live; entire reconciliation feature non-functional.

### Cross-cutting
18. **snapshots.py:54-67** — sha256 over `arr.tobytes()` depends on host endianness; cross-platform hash mismatch.

## Top High findings (94 total) by category

### Anti-leak / overfit (10)
- monte_carlo trade reorder CAGR uses wrong horizon
- monte_carlo defines "trade" too narrowly (vol-target/Kelly collapse to 1 trade)
- lookahead_check single-shuffle false-negative + rank-feature blind spot
- purged_cv default embargo 1% too small for 60-day momentum
- walk_forward strategy_factory no IS-slice argument → can use globally-tuned params
- multi_asset_runner OOS leak in fitness selection (single-asset already fixed in P.1)
- VPIN bucket alignment shifted by `(window-1)` bucket widths
- Donchian + ATRBreakout windows produce 2-bar entry lag (engine adds another shift)
- triple-barrier slippage symmetric on PT/SL — inspection looks economic-equivalent but inspection-worthy
- BL Omega no low-end confidence floor → numerical instability silent

### Concurrency / production (12)
- SQLite registry/journal/snapshots/AuditLog all lack WAL + busy_timeout
- OOSGuard `_stack` class-level → not thread-safe
- KillSwitch no daily reset
- Halt flag persists across sessions
- AuditLog no rotation
- Double-submit on retry
- Reconcile() always raises
- Rate limiter single-process + unfair sleep
- PaperBroker avg-cost wrong on side flip
- Kraken `cl_ord_id` ignored (Kraken uses `userref`)
- versioning git_status no fsync before rename
- Versioning history file no advisory lock → duplicate lines under parallel GA

### Numerical / statistical (12)
- HRP "iterative bisection" is naive halving, dendrogram structure ignored
- Kelly formula appears miscalibrated (Thorp form not preserved)
- EWMA cov biased (no `1 - sum(w^2)` correction)
- PSD spectral clip floors at 0 → singular matrix
- Markov switching EM no convergence floor → degenerate regimes
- Bayes alpha singular fallback uses `y.std()/sqrt(n)` (SE of mean, not residual std)
- Hurst clip silent without nan_on_unstable default
- DSR Mertens variance unit mismatch
- CSCV stratified sampling has memory spike fallback
- triple-barrier vol reindex silent NaN drop
- VPIN reports values at past timestamps
- Monte Carlo "p-value" is empirical quantile, mis-reported

### Security (5)
- LLM-generated code runs without sandbox/import allow-list → RCE
- torch.load `weights_only=False` in lstm.py + transformer.py → RCE on malicious checkpoint
- SMTP STARTTLS without `ssl.create_default_context()` → cert validation skipped
- Tearsheet HTML f-string interpolation unescaped → XSS
- Webhook substring host detection (`"slack" in host`) → misroute to lookalike domains

### API / integration (10)
- pydantic imported in core/config.py but NOT in pyproject.toml dependencies
- lumibot/coinbase/krakenex not in any extra
- Pipeline advertises "13 gates" but only orchestrates 8
- README test count 946 stale (actual 1122)
- DEAP `creator` global state collision between consecutive `run_ga` calls
- VolTargetWrapper/StopWrapper unusable from `run_ga` (require base positional)
- DataLayer cache writes inside site-packages on installed wheel
- monitoring/validation/__init__.py re-exports don't match API_REFERENCE
- snapshots.py not referenced in API_REFERENCE / ARCHITECTURE
- analytics/Brinson decomposition produces zero selection/interaction (dead code)

### Drift / detectors (5)
- AutoRetrainController cooldown reset semantics off-by-one + leak
- ADWIN evaluates only median split → multi-comparison correction wrong direction
- KSDriftDetector deque overlap on consecutive tests
- PageHinkley warmup bias (initialize to first sample missing)
- KS reference required not enforced through public API

## Test coverage gaps (~30)

- No symmetric purge regression test
- No correlation_stress realized-corr test
- No shift(-1.0) float edge case
- No rank-feature lookahead test
- No simulate_retraining decay slope test
- No wf generate_wf_windows non-overlap stress
- No pipeline overall_passed=False composite test
- No JIT-vs-engine 1e-9 equivalence test (shipped but might pass with rounding)
- No multi-asset HRP+BL E2E (added in S.4)
- No regime-conditional Sharpe gate
- No parameter rank stability gate
- No bootstrap CI on Sharpe/Calmar
- No compiled-strategy hash invalidation test
- No SMTP TLS cert validation test
- No webhook URL hostname validation test

## Documentation gaps

- API_REFERENCE references functions not exported (deployment/__init__ empty)
- API_REFERENCE drift detector list (PSI/KL) doesn't match implementation (PageHinkley/ADWIN/KS)
- API_REFERENCE forge subcommand list wrong (lists `backtest`, `ga`, `monitor` — none exist)
- v1_3_COMPLETION_REPORT shows 946 tests, mejoras report shows 1122 — inconsistent
- Snapshots feature undocumented in user-facing docs
- "13-gate pipeline" mismatch in README/ARCHITECTURE
- multi_objective_fitness API doc still describes pre-P.1 OOS-aware version

## CI gaps

- No `cache: pip` → 5-10 min wasted per run
- No `concurrency:` block → double-runs on push
- No security scan (pip-audit, bandit)
- No macOS in matrix
- No `timeout-minutes` cap (default 6h)
- pytest-cov not in fixed addopts → CI runs with cov but local devs don't
- pre-commit only runs `ruff --fix` (lint subset), no `ruff format`, no mypy
- Pin `pip cache` to `aurora/pyproject.toml` only — repo-root `.github/workflows/` has no path-mapping fallback

## Recommended remediation order

**P0 (block production):**
1. Fix double-submission risk (broker idempotency + retry pre-check) [F.15-16]
2. Fix KillSwitch daily reset + halt flag persistence [F.11, F.13]
3. Add SQLite WAL + busy_timeout across registry/journal/snapshots/AuditLog [E, F.12]
4. Fix `reconcile()` to compute real diffs across all live adapters [F.17]
5. Sandbox LLM-generated code (AST allow-list) [G.security]
6. Fix `weights_only=False` torch.load to True [C.security]
7. Fix DSR unit mismatch (annualize vs per-period) [B.8]
8. Fix taxes NAV mark-to-market [A.5]
9. Fix triple-barrier inclusive slicing [C.10]
10. Fix engine_multi cost aggregation first-bar zeroing inconsistency [A.3]

**P1 (block major release):**
- All 12 concurrency findings
- All 5 security findings
- HRP true tree-aware bisection OR rename to "QuasiDiagHRP"
- Monte Carlo fixed-block truncation bias
- Lookahead multi-shuffle test
- Purged CV embargo tied to lookback
- Wire missing 5 validation gates into `validate_pipeline` OR fix docs
- Fix pyproject pydantic + lumibot + coinbase + krakenex declarations
- Multi-asset GA OOS leak (mirror P.1 single-asset refactor)
- DEAP creator global-state collision

**P2 (next minor):**
- Numerical/statistical 12
- API/integration 10
- Drift detectors 5
- Test coverage 30
- Documentation gaps
- CI gaps

## Risk assessment

Aurora **research layer** is largely sound: backtest engine + GA + most validation gates work as documented after the v1.3+P/Q/R/S/T fixes. **Production layer is NOT ready**: 8 critical findings concentrated in deployment (kill switch, audit log, idempotency, reconciliation, halt) plus security findings (LLM sandbox, torch.load, SMTP TLS, XSS) make live trading unsafe without the P0 fixes.

The core engine has **6 critical findings** that affect backtest correctness across paths (NAV[0], JIT no-clip divergence, multi-asset cost, taxes NAV). These should be fixed even for pure research use.

The validation layer has **3 critical findings** that cause silent statistical bias (DSR units, double MC reorder call, fixed-block truncation). These directly affect reported gate pass/fail.

## Conclusion

After 24 SDD agents shipping the v1.3 + mejoras_pendientes work, **~321 issues remain**. Most are non-blocking polish, but **18 critical** + a sizable cluster of **production hardening** items mean the system should be marked v1.3-rc rather than v1.3-stable until P0/P1 cleared.

mejoras_pendientes_a_implementar.md was a partial audit (110 items). This deeper audit found ~3x more issues. Consistent with software auditing economics: each pass surfaces ~3x the prior pass's findings until convergence.

**Recommended next iteration:** Batch U covering P0 + P1 (~120 items, ~6-8 parallel agents).
