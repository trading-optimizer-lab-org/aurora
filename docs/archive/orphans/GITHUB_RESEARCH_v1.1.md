# GITHUB RESEARCH — QuantForge v1.1 Gap Analysis

**Date:** 2026-05-06
**Method:** Direct `gh api` traversal of 16 quant repos + targeted source reads.
**Baseline:** QuantForge v1.0 (87 files, 289 tests, 6 modules: core/strategies/ga/validation/deployment/reporting/cli)
**Goal:** Identify SPECIFIC features QF v1.0 lacks; produce prioritized v1.1 plan.

---

## 0. Caveman summary (TL;DR)

QF strong on validation (DSR, MC, SPP, lookahead, OOSGuard with file lock + git hash). That's our moat. But QF blind in three big places:

1. **ML pipeline blind.** No purged k-fold, no triple-barrier labels, no meta-labeling, no fractional differentiation. mlfinlab + qlib eat us alive on this. AFML book gates are the next moat.
2. **Portfolio opt blind.** We have an allocator (4 methods) but no HRP, no Black-Litterman, no CVaR/CDaR, no efficient frontier. PyPortfolioOpt + Riskfolio-Lib drop these in <500 LOC each.
3. **Tear sheet thin.** quantstats has 80+ metrics, pyfolio has perf attribution, our tearsheet has ~12 metrics. Easy lift, big visual impact.

Also smaller gaps: alphalens-style factor analysis (IC, quantile spread), realistic slippage (zipline VolumeShareSlippage), structural break detection (CUSUM/SADF), bar types beyond time bars (dollar/volume/imbalance), sentiment data hook (yfinance news + alpha vantage), regime detection (HMM/Markov).

Big skip: full RL stack (FinRL), full LLM agent stack (TradingAgents), live broker zoo (Lean). Those are different products; only port the patterns we need.

---

## 1. Executive summary — top 10 most impactful additions

Ranked by **impact × ease-of-port** for a time-series quant lab.

| # | Feature | Source repo | Why it matters | Effort |
|---|---------|-------------|----------------|--------|
| 1 | **Purged K-Fold + Embargo CV** | mlfinlab/cross_validation/cross_validation.py | Replaces walk-forward as the default for ML strategies. Prevents label-leak when `t1` of training overlaps test. Single most-cited AFML technique. | LOW (~150 LOC) |
| 2 | **Triple-Barrier Labels + Meta-Labeling** | mlfinlab/labeling/labeling.py + bet_sizing/bet_sizing.py | Path-aware labels (PT/SL/vertical) → primary model predicts side, meta-model predicts size/skip. Foundation for any classifier-based strategy. | MEDIUM (~400 LOC) |
| 3 | **Hierarchical Risk Parity (HRP)** | PyPortfolioOpt/hierarchical_portfolio.py + Riskfolio-Lib/HCPortfolio.py | Beats Markowitz out-of-sample. Single-cluster correlation tree → recursive bisection. Plug-in as 5th allocator method. | LOW (~200 LOC, scipy.cluster) |
| 4 | **CVaR / CDaR / EVaR portfolio optimization** | PyPortfolioOpt/efficient_frontier/efficient_cvar.py | Tail-risk-aware optimization. Robust under fat tails. Drop-in cvxpy solve. | LOW (~150 LOC) |
| 5 | **Black-Litterman views model** | PyPortfolioOpt/black_litterman.py | Combine market equilibrium with our strategy signals as views → posterior weights. Bayesian portfolio. | MEDIUM (~300 LOC) |
| 6 | **quantstats-style tear sheet** | ranaroussi/quantstats/stats.py + reports.py | 80+ metrics: omega, gain-to-pain, ulcer-index, common-sense ratio, smart sharpe, prob-sharpe, treynor, payoff ratio, CVaR, tail ratio, etc. | LOW (port stats functions) |
| 7 | **Alphalens-style factor analysis** | quantopian/alphalens/performance.py | IC (Information Coefficient), quantile-spread returns, factor-rank autocorrelation, turnover by quantile. Signal hygiene for any factor. | MEDIUM (~500 LOC) |
| 8 | **Realistic slippage models** | zipline/finance/slippage.py | VolumeShareSlippage (fill ≤ 2.5% of bar volume), VolatilityVolumeShare, FixedBasisPointsSlippage. Our cost model = commission only; missing market-impact. | LOW (~200 LOC) |
| 9 | **CUSUM filter + structural break tests** | mlfinlab/filters/ + structural_breaks/ (chow.py, cusum.py, sadf.py) | Event-driven sampling (CUSUM). Regime-change detection (Chow, SADF). Adaptive walk-forward triggering. | MEDIUM (~400 LOC) |
| 10 | **Fractional differentiation** | mlfinlab/features/fracdiff.py | Stationarize prices while preserving memory. Inputs to ML models that need stationary features but lose info from `diff(1)`. AFML chapter 5. | LOW (~150 LOC) |

---

## 2. Per-category gap analysis

Each row: **Feature → Source repo path → QF gap → Port effort**.

### 2.1 DATA — ingestion, storage, alternative data

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| Multi-source data layer (yfinance / Alpha Vantage / Tushare / Shioaji / IB) | `finrl/meta/preprocessor/*downloader.py`, `tradingagents/dataflows/{alpha_vantage,y_finance}.py` | QF only has yfinance via `data_layer.load_asset()` | MEDIUM |
| Information bars (dollar/volume/tick/imbalance bars) | `mlfinlab/data_structures/{standard_data_structures,imbalance_data_structures,run_data_structures}.py` | QF time-bar only | MEDIUM (needs tick data input) |
| News / sentiment data | `tradingagents/dataflows/{alpha_vantage_news,yfinance_news}.py` | None | LOW (wrapper) |
| Earnings / fundamentals | finnhub MCP, alpha_vantage_fundamentals (already available via MCP); `finrl/meta/preprocessor/preprocessors.py` | None | LOW |
| Crypto / forex feeds | finrl crypto env, av_crypto_* MCPs | None | LOW |
| Storage backends (parquet, Arctic, qlib local binary) | `qlib/data/storage/`, `qlib/data/_libs/` (custom binary format, fast scan) | QF has parquet feature store (6.4) — adequate for now | SKIP |
| Universe survivor-bias correction | `finrl/meta/preprocessor/preprocessors.py` (delisted handling) | None — single-asset focus | MEDIUM |
| Point-in-time fundamentals | `qlib/data/pit.py` | None | HIGH |
| **High-frequency data handler** | `qlib/contrib/data/highfreq_handler.py` | None | OUT OF SCOPE (HFT) |

### 2.2 INDICATORS — technical, statistical, ML features

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| Alpha158 / Alpha360 feature library (KBAR, ROC, MA, STD, BETA, RSQR, RESI, CORR, CORD over [5,10,20,30,60] windows) | `qlib/contrib/data/loader.py` (`Alpha158DL`, `Alpha360DL`) | QF: 0 prebuilt features. Has feature store (provenance) but no library. | MEDIUM (~600 LOC port) |
| Microstructural features (Kyle, Amihud, Roll, VPIN, Hasbrouck, Corwin-Schultz) | `mlfinlab/microstructural_features/{first,second,third}_generation.py` | None | MEDIUM |
| Encoding features (entropy, encoding) | `mlfinlab/microstructural_features/{entropy,encoding}.py` | None | LOW |
| Pandas-TA-style indicator factory | vectorbt `vectorbt/indicators/factory.py` (auto-vectorized) | QF strategies use bespoke numba kernels (engine_jit) — not a library | MEDIUM |
| Zipline pipeline factor library (technical.py, statistical.py, factor.py — 64KB) | `zipline-reloaded/src/zipline/pipeline/factors/*.py` | None | HIGH (architecture-heavy) |
| Fractional differentiation (memory-preserving stationary transform) | `mlfinlab/features/fracdiff.py` | None | LOW |
| Trend scanning labels | `mlfinlab/labeling/trend_scanning.py` | None | LOW |

### 2.3 PORTFOLIO — optimization, risk parity, hierarchical

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| Mean-variance / efficient frontier | `pypfopt/efficient_frontier/efficient_frontier.py` | QF allocator has 4 methods (`equal/inverse_vol/min_var/max_sharpe`), but no full frontier | LOW (extend allocator) |
| **Hierarchical Risk Parity (HRP)** | `pypfopt/hierarchical_portfolio.py`, `riskfolio/HCPortfolio.py` | None | LOW |
| **Black-Litterman views model** | `pypfopt/black_litterman.py` | None | MEDIUM |
| Critical Line Algorithm (CLA) | `pypfopt/cla.py` | None | LOW |
| **Efficient CVaR** (tail-risk frontier) | `pypfopt/efficient_frontier/efficient_cvar.py` | None | LOW |
| Efficient CDaR (drawdown-at-risk) | `pypfopt/efficient_frontier/efficient_cdar.py` | None | LOW |
| Efficient Semivariance | `pypfopt/efficient_frontier/efficient_semivariance.py` | None | LOW |
| Risk parity (vanilla, equal risk contribution) | `riskfolio/Portfolio.py` | None (`inverse_vol` is a poor proxy) | LOW |
| Robust covariance (Ledoit-Wolf shrinkage, Oracle, exponential weighted) | `pypfopt/risk_models.py`, `sysquant/estimators/correlation_estimator.py` | None | LOW (sklearn covariance.LedoitWolf) |
| Black-Litterman with idzorek confidence | `pypfopt/black_litterman.py` | None | MEDIUM |
| Diversification multipliers (multi-asset risk overlay) | `pysystemtrade/sysquant/estimators/diversification_multipliers.py` | None | LOW |
| Discrete share allocation (integer LP for actual shares from weights) | `pypfopt/discrete_allocation.py` | None — QF has `sizing.py` but not integer-aware | LOW |
| Enhanced indexing (track index + alpha tilt) | `qlib/contrib/strategy/optimizer/enhanced_indexing.py` | None | MEDIUM |
| Owa weights (ordered weighted averaging) | `riskfolio/OwaWeights.py` | None | OUT OF SCOPE |

### 2.4 VALIDATION — novel tests, ML-specific

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| **Purged K-Fold CV (with embargo)** | `mlfinlab/cross_validation/cross_validation.py` (`PurgedKFold`, `ml_cross_val_score`, `ml_get_train_times`) | QF has WF (rolling/expanding/anchored) but NO purged CV → label leakage on overlapping `t1` | LOW |
| Combinatorial Purged CV (CPCV) | `mlfinlab/cross_validation/combinatorial.py` | None | MEDIUM (essential for backtest paths) |
| **CSCV / PBO (Combinatorially Symmetric Cross-Validation, Probability of Backtest Overfitting)** | `mlfinlab/backtest_statistics/backtests.py` | QF has DSR but not PBO | LOW |
| Sample weights (return attribution, time-decay, class weights) | `mlfinlab/sample_weights/attribution.py` | None | LOW |
| Sequential bootstrap (uniqueness-weighted) | `mlfinlab/sampling/bootstrapping.py`, `concurrent.py` | QF has plain block bootstrap | LOW |
| Structural breaks: Chow test, CUSUM, SADF | `mlfinlab/structural_breaks/{chow,cusum,sadf}.py` | None | MEDIUM |
| CUSUM event filter (event-driven sampling triggers) | `mlfinlab/filters/` | None | LOW |
| Feature importance: MDI, MDA, SFI | `mlfinlab/feature_importance/importance.py` | None | LOW |
| Orthogonal feature importance (decorrelated MDA) | `mlfinlab/feature_importance/orthogonal.py` | None | LOW |
| Feature fingerprint (linear, non-linear, pairwise) | `mlfinlab/feature_importance/fingerpint.py` | None | MEDIUM |
| Bailey/Lopez de Prado backtest stats (Min Track Record Length, BAB, Strategy Risk) | `mlfinlab/backtest_statistics/statistics.py` | QF has DSR; missing MinTRL, strategy risk | LOW |

### 2.5 EXECUTION — brokers, order types, slippage, intraday

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| **VolumeShareSlippage** (fill ≤ X% of bar vol, sqrt-impact) | `zipline-reloaded/src/zipline/finance/slippage.py` (`VolumeShareSlippage`, `FixedBasisPointsSlippage`, `VolatilityVolumeShare`) | QF `costs.py`: commission + bps spread only, no volume cap, no impact | LOW |
| Per-asset commission models | `zipline-reloaded/src/zipline/finance/commission.py` | QF has CostModel (ZERO/IBKR/CONSERVATIVE) — adequate but not per-asset | LOW |
| Borrow fee for shorts | `moonshot/commission/borrowfee.py` | None | LOW |
| FX/futures-specific commission | `moonshot/commission/{fut,fx,stk}.py` | None | LOW |
| Order types: limit, stop, stop-limit, MOC, LOC, trailing stop | `zipline/finance/execution.py`, `backtrader/orders` | QF only has market on close | MEDIUM |
| Cancel policy (good-til-cancelled vs day) | `zipline/finance/cancel_policy.py` | None | LOW |
| Asset restrictions (no-trade lists, halts) | `zipline/finance/asset_restrictions.py` | None | LOW |
| Trading controls (max position, max leverage, max order size) | `zipline/finance/controls.py` | QF preflight has 10 checks — partial overlap, but no live-runtime enforcement | MEDIUM |
| Multi-broker support (IB, Oanda, VC, custom) | `backtrader/brokers/{ibbroker,oandabroker,vcbroker}.py` | QF Lumibot wrapper covers IB+Alpaca; could expand | MEDIUM |
| Continuous futures rollover | `backtrader/feeds/rollover.py` | None | OUT OF SCOPE (no futures yet) |
| Intraday minute bar engine | `moonshot/strategies/base.py` | QF daily-only | HIGH |

### 2.6 ML — models, feature selection, RL

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| Sklearn-compatible model wrapper for strategies | `mlfinlab/*` patterns | None — strategies are rule-based | MEDIUM |
| Gradient boosting models (XGBoost, LightGBM, CatBoost) for alpha prediction | `qlib/contrib/model/{xgboost,gbdt,catboost_model}.py` | None | LOW (sklearn-style) |
| Linear model with regularization (alpha factor combination) | `qlib/contrib/model/linear.py` | None | LOW |
| LSTM / GRU / Transformer for time-series alpha | `qlib/contrib/model/pytorch_{lstm,gru,transformer}.py` | None | HIGH (heavy deps) |
| Double Ensemble (sample reweighting + feature reweighting) | `qlib/contrib/model/double_ensemble.py` | None | MEDIUM |
| TabNet / TFT / TCN | `qlib/contrib/model/{pytorch_tabnet,tcn}.py` | None | OUT OF SCOPE |
| Online learning rolling models (concept drift) | `qlib/contrib/rolling/{base,ddgda}.py`, `qlib/workflow/online/` | QF has retraining cadence sim but no production rolling pipeline | MEDIUM |
| Meta-DDG-DA (domain generalization for distribution shift) | `qlib/contrib/rolling/ddgda.py` | None | OUT OF SCOPE |
| Hyperparameter tuning (Optuna, hyperopt) integration | `finrl/agents/stablebaselines3/{hyperparams_opt,tune_sb3}.py` | QF has bayes_opt (skopt) | LOW (Optuna swap) |
| RL agents (PPO, A2C, SAC, TD3 for portfolio allocation) | `finrl/agents/{stablebaselines3,elegantrl,rllib}/` | None | OUT OF SCOPE (different product) |
| LLM multi-agent research (analyst → researcher → trader → risk-mgmt) | `tradingagents/agents/{analysts,researchers,trader,risk_mgmt}/` | None | OUT OF SCOPE |

### 2.7 ANALYTICS — reports, attribution, factor analysis

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| **80+ metrics tear sheet** (omega, gain-to-pain, ulcer, smart sharpe, treynor, payoff, common-sense ratio, prob-sharpe, prob-sortino, CVaR, tail-ratio, RAR, kurtosis, skew, autocorr-penalty, expected_shortfall, etc.) | `quantstats/stats.py` | QF has ~12 metrics in `core/metrics.py` | LOW (port) |
| Full HTML report w/ embedded plots | `quantstats/reports.py` (`html`, `full`, `basic`, `metrics`, `plots`) | QF has tearsheet (1.3) — basic HTML/PDF; missing rolling-sharpe heatmap, monthly returns table heatmap, eoy-returns table, drawdown-by-rank table | LOW |
| Performance attribution (sector, factor) | `pyfolio-reloaded/src/pyfolio/perf_attrib.py` | None | MEDIUM |
| Capacity analysis (max AUM before slippage kills alpha) | `pyfolio-reloaded/src/pyfolio/capacity.py` | None | MEDIUM |
| Round-trip trade analysis (winners/losers, avg holding, p&l distribution) | `pyfolio-reloaded/src/pyfolio/round_trips.py` | QF has trade reorder MC but not classic round-trip stats | LOW |
| "Interesting periods" benchmarking (2008 GFC, 2020 COVID, 2018 vol-spike) | `pyfolio-reloaded/src/pyfolio/interesting_periods.py` | None | LOW |
| Factor IC + IC distribution + IC IR | `alphalens/performance.py` (`factor_information_coefficient`, `mean_information_coefficient`) | None | MEDIUM |
| Quantile spread returns (long top decile / short bottom decile) | `alphalens/performance.py` (`mean_return_by_quantile`, `compute_mean_returns_spread`) | None | MEDIUM |
| Factor rank autocorrelation (signal stability) | `alphalens/performance.py` (`factor_rank_autocorrelation`) | None | LOW |
| Quantile turnover + stability | `alphalens/performance.py` (`quantile_turnover`) | None | LOW |
| Risk decomposition / model graph plotting | `qlib/contrib/report/{analysis_position,analysis_model}/` | None | LOW |
| `ffn` financial functions (calc_stats with 30+ metrics, drawdown_details, monthly_returns_table) | `pmorissette/ffn/core.py` (84KB) | None — overlap with quantstats but different API | SKIP (use quantstats) |

### 2.8 LIVE — monitoring, alerts, dashboards

| Feature | Source | QF status | Port effort |
|---------|--------|-----------|-------------|
| Live model rolling / retraining manager | `qlib/workflow/online/manager.py`, `online_model.py`, `operator.py`, `user.py` | QF retraining cadence is simulation-only; no online manager | MEDIUM |
| Experiment tracking (mlflow/qlib recorder) | `qlib/workflow/recorder.py`, `exp.py`, `expm.py` | QF has logging but no run-tracking | MEDIUM |
| Alerting / notifications (Telegram, Slack, email) | `vectorbt/messaging/` | None | LOW |
| Live preflight monitoring (drift, slippage actual-vs-expected, fill quality) | None comprehensive | QF has preflight (4.4) for entry; no continuous monitoring | MEDIUM |
| Strategy versioning + production registry | `qlib/workflow/expm.py` | None — git-hash in OOSGuard is closest | LOW |

---

## 3. Specific code-level pointers (for v1.1 implementers)

### 3.1 Purged K-Fold (mlfinlab) — exact API to reproduce

```python
# Source: mlfinlab/cross_validation/cross_validation.py
class PurgedKFold(KFold):
    def __init__(self, n_splits: int = 3,
                 samples_info_sets: pd.Series = None,  # index=t0, value=t1 (label horizon end)
                 pct_embargo: float = 0.):
        ...
    def split(self, X, y=None, groups=None) -> Tuple[List[int], List[int]]:
        # Train indices = all NOT in test AND NOT overlapping test t0..t1
        # Plus embargo: drop training samples within pct_embargo*N after test
```

QF target: `quantforge/validation/purged_cv.py` exporting `PurgedKFold`, `ml_cross_val_score(model, X, y, cv, sample_weight=None)`.

### 3.2 Triple-Barrier Labels — sequence

```python
# Source: mlfinlab/labeling/labeling.py
# 1. apply_pt_sl_on_t1(close, events, pt_sl, molecule)
# 2. add_vertical_barrier(t_events, close, num_days=N)
# 3. get_events(close, t_events, pt_sl, target, min_ret, num_threads, vertical_barrier_times)
# 4. get_bins(events, close)  → returns {-1, 0, +1} labels (or meta {0,1})
```

QF target: `quantforge/strategies/labels.py` (`triple_barrier`, `meta_label`).

### 3.3 HRP — Lopez de Prado recursive bisection

```python
# Source: pypfopt/hierarchical_portfolio.py (~10KB)
class HRPOpt(BaseOptimizer):
    def __init__(self, returns, cov_matrix=None):
        ...
    def optimize(self, linkage_method="single") -> Dict[str, float]:
        # 1. corr → distance matrix
        # 2. scipy.cluster.hierarchy.linkage(method='single')
        # 3. quasi-diagonalization (sort by leaf order)
        # 4. recursive bisection with inverse-variance weighting
```

QF target: extend `quantforge/deployment/allocator.py` with `Method.HRP`, `Method.CVAR`, `Method.BL`.

### 3.4 Slippage — zipline VolumeShareSlippage

```python
# Source: zipline-reloaded/src/zipline/finance/slippage.py:34-45
DEFAULT_EQUITY_VOLUME_SLIPPAGE_BAR_LIMIT = 0.025  # max 2.5% of bar volume
# class VolumeShareSlippage:
#   simulated_impact = (volume_share)**2 * simulated_volatility * mean_volume
#   filled_at = price * (1 + impact * sign)
#   if cumulative_volume_filled > volume_limit*bar_volume: LiquidityExceeded
```

QF target: extend `quantforge/core/costs.py` with `SlippageModel` ABC + `VolumeShareSlippage`, `FixedBpsSlippage`.

### 3.5 quantstats — port these metrics first (small, high signal)

From `quantstats/stats.py` (verified function list):
- `omega`, `gain_to_pain_ratio`, `ulcer_index`, `ulcer_performance_index` (UPI)
- `serenity_index`, `risk_of_ruin`
- `value_at_risk` / `cvar` (already partially there?), `expected_shortfall`
- `tail_ratio`, `payoff_ratio`, `win_loss_ratio`, `profit_factor`, `cpc_index`, `common_sense_ratio`
- `smart_sharpe` / `smart_sortino` (penalizes autocorr)
- `probabilistic_sharpe_ratio`, `probabilistic_sortino_ratio` (these complement our DSR)
- `treynor_ratio`, `rar`, `consecutive_wins`, `consecutive_losses`, `outlier_win_ratio`

QF target: extend `quantforge/core/metrics.py` (existing) with `extended_metrics(returns)` returning dict of 80 keys; tear sheet renders them in 4 tables.

### 3.6 Alpha158 / Alpha360 — kbar+price+volume+rolling feature config

```python
# Source: qlib/contrib/data/loader.py
# Categories used by Alpha158:
#   kbar: KMID, KLEN, KMID2, KUP, KUP2, KLOW, KLOW2, KSFT, KSFT2  (9 OHLC-shape features)
#   price: OPEN0..4, HIGH0..4, LOW0..4, VWAP0..4 (lag features)
#   volume: VOLUME0..4 lag
#   rolling: ROC, MA, STD, BETA, RSQR, RESI, MAX, LOW, QTLU, QTLD, RANK, RSV, IMAX, IMIN, IMXD, CORR, CORD, CNTP, CNTN, CNTD, SUMP, SUMN, SUMD, VMA, VSTD, WVMA, VSUMP, VSUMN, VSUMD
#   over windows: [5, 10, 20, 30, 60]
```

QF target: `quantforge/core/features.py` (existing feature store) gains `quantforge.core.alpha158.compute_features(prices)` returning a 158-column DataFrame, cached via existing provenance.

---

## 4. Prioritized recommendation list — value vs effort

### HIGH value × LOW effort — DO FIRST (v1.1 batch G)

| Module | Source | Time est | Status |
|--------|--------|----------|--------|
| `validation/purged_cv.py` (PurgedKFold + embargo + ml_cross_val_score) | mlfinlab | 4h | NEW |
| `core/costs.py` add `VolumeShareSlippage`, `FixedBpsSlippage` | zipline | 3h | EXTEND |
| `core/metrics.py` extended (80+ stats from quantstats) | quantstats | 6h | EXTEND |
| `reporting/tearsheet.py` add monthly heatmap, eoy table, dd-rank table, rolling sharpe heatmap | quantstats/reports.py | 5h | EXTEND |
| `deployment/allocator.py` add HRP method | PyPortfolioOpt | 4h | EXTEND |
| `validation/cscv.py` (PBO test — combinatorially-symmetric CV) | mlfinlab | 4h | NEW |
| `validation/feature_importance.py` (MDI/MDA/SFI) | mlfinlab | 5h | NEW |

**Subtotal: ~31 hours = 1 batch of 5-7 subagents.**

### HIGH value × MEDIUM effort — v1.1 batch H

| Module | Source | Time est |
|--------|--------|----------|
| `strategies/labels.py` (triple-barrier + meta-labeling + bet-sizing) | mlfinlab | 12h |
| `core/features_alpha158.py` (Alpha158 feature library) | qlib | 10h |
| `validation/structural_breaks.py` (Chow + CUSUM + SADF + CUSUM filter) | mlfinlab | 8h |
| `deployment/allocator.py` add CVaR + Black-Litterman | PyPortfolioOpt | 10h |
| `analytics/factor_analysis.py` (alphalens-style IC, quantile spread, turnover) | alphalens | 12h |
| `core/features.py` add fractional differentiation | mlfinlab | 4h |
| `core/data_layer.py` add multi-source (Alpha Vantage, fmpsdk, finnhub via existing MCPs) | finrl pattern | 8h |

**Subtotal: ~64 hours.**

### MEDIUM value × LOW/MED effort — v1.1 batch I (optional)

| Module | Source | Time est |
|--------|--------|----------|
| `strategies/labels.py` add CUSUM event sampling | mlfinlab/filters | 4h |
| `core/microstructure.py` (Amihud, Roll, Kyle, VPIN — informational only on daily data) | mlfinlab | 8h |
| `analytics/round_trips.py` (winner/loser stats, p&l dist) | pyfolio-reloaded | 5h |
| `analytics/interesting_periods.py` (GFC/COVID/2018 benchmarking) | pyfolio-reloaded | 3h |
| `validation/sample_weights.py` (return-attribution weights, time-decay) | mlfinlab | 5h |
| `validation/sequential_bootstrap.py` (uniqueness-weighted MC) | mlfinlab | 6h |
| `deployment/order_types.py` (limit/stop/stop-limit beyond market) | zipline | 8h |
| `core/risk_models.py` (Ledoit-Wolf, exponential-weighted cov) | PyPortfolioOpt | 4h |
| `monitoring/notifications.py` (Telegram + email alerts) | vectorbt/messaging | 6h |

**Subtotal: ~49 hours.**

### LOW priority — SKIP for v1.1

- Full RL stack (FinRL) — different product domain
- LLM multi-agent (TradingAgents) — different product domain
- HFT / minute-bar engine (moonshot intraday) — out of scope per QF time-series focus
- Tick-bar data structures (mlfinlab dollar/imbalance bars) — daily-bar focus
- PyTorch deep models (qlib) — heavy deps, 158 features + GBM is enough for v1.1
- Continuous futures (backtrader rollover) — equities first
- Multi-broker zoo beyond Lumibot — Lumibot already wraps IB/Alpaca/binance

---

## 5. Proposed v1.1 module map (concrete file paths)

```
quantforge/
├── core/
│   ├── costs.py                       (EXTEND: VolumeShareSlippage, FixedBpsSlippage)
│   ├── metrics.py                     (EXTEND: 80+ stats from quantstats)
│   ├── features.py                    (EXTEND: fractional differentiation)
│   ├── features_alpha158.py           (NEW: Alpha158 + Alpha360 ports from qlib)
│   ├── microstructure.py              (NEW: Amihud, Roll, Kyle, Corwin-Schultz)
│   ├── risk_models.py                 (NEW: Ledoit-Wolf, EW cov, semi-cov)
│   └── data_layer.py                  (EXTEND: multi-source via MCP wrappers)
├── strategies/
│   ├── labels.py                      (NEW: triple_barrier, meta_label, bet_size_*, CUSUM filter)
│   └── library/
│       └── ml_classifier.py           (NEW: sklearn-based generic ML strategy template)
├── validation/
│   ├── purged_cv.py                   (NEW: PurgedKFold, CombinatorialPurgedCV, ml_cross_val_score)
│   ├── cscv.py                        (NEW: Probability of Backtest Overfitting)
│   ├── feature_importance.py          (NEW: MDI, MDA, SFI, orthogonal)
│   ├── structural_breaks.py           (NEW: Chow, CUSUM, SADF)
│   ├── sample_weights.py              (NEW: return-attribution + time-decay)
│   └── sequential_bootstrap.py        (NEW: uniqueness-weighted MC)
├── deployment/
│   ├── allocator.py                   (EXTEND: HRP, CVaR, BL, full efficient frontier)
│   ├── order_types.py                 (NEW: limit/stop/stop-limit/trailing)
│   └── slippage_lab.py                (NEW: actual-vs-expected fill quality monitor)
├── analytics/                         (NEW directory)
│   ├── __init__.py
│   ├── factor_analysis.py             (NEW: IC, quantile spread, turnover, autocorr)
│   ├── round_trips.py                 (NEW: trade-level win/loss/holding stats)
│   ├── interesting_periods.py         (NEW: GFC/COVID benchmarking)
│   └── attribution.py                 (NEW: factor + sector decomp)
├── reporting/
│   └── tearsheet.py                   (EXTEND: monthly heatmap, eoy table, rolling sharpe heatmap, ddrank table — match quantstats `html`/`full`)
├── monitoring/                        (NEW directory)
│   ├── __init__.py
│   ├── notifications.py               (NEW: Telegram + email alerts)
│   └── live_monitor.py                (NEW: drift detection, slippage tracking)
└── cli/
    └── forge.py                       (EXTEND: forge label, forge factor-test, forge optimize-portfolio)
```

**Net delta v1.0 → v1.1:**
- New files: ~22
- Extended files: ~6
- New CLI subcommands: 3 (`label`, `factor-test`, `optimize-portfolio`)
- Estimated test count delta: +180 (target ~470 total)

---

## 6. Validation gate v1.1 — proposed addition

Current QF gates (v1.0) operate on equity-curve / trade level. v1.1 must add ML-grade gates for any strategy whose signals come from a fitted model:

| Gate # | Name | Source | Replaces / Adds |
|--------|------|--------|-----------------|
| 10 | **PurgedKFold + embargo OOS** | mlfinlab | Adds: ML-strategy WF replacement when labels overlap |
| 11 | **PBO < 0.5** (Probability of Backtest Overfitting via CSCV) | mlfinlab | Adds: complements DSR for selection-bias correction |
| 12 | **Feature importance stability** (MDI rank correlation across CV folds > 0.5) | mlfinlab | Adds: catches noise-feature strategies |
| 13 | **Structural break sentry** (CUSUM raises no break in last 6 months of OOS) | mlfinlab | Adds: regime-change pre-trade check |

Pipeline becomes 4-gate (current) + 4-ML-gate (v1.1, only triggered if `strategy.is_ml=True`).

---

## 7. Source repos summary table

| Repo | Stars | Last push | Why we mined it |
|------|------:|-----------|-----------------|
| polakowo/vectorbt | 7,417 | 2026-04-25 | Indicator factory, signal generators, messaging |
| microsoft/qlib | 42,096 | 2026-04-22 | Alpha158/Alpha360, online learning, rolling models |
| stefan-jansen/zipline-reloaded | 1,754 | 2026-01-06 | Slippage models, pipeline factors, controls |
| robertmartin8/PyPortfolioOpt | 5,692 | 2026-04-20 | HRP, BL, efficient_cvar, efficient_cdar |
| hudson-and-thames/mlfinlab | 4,708 | 2023-10-02 | AFML book ports: PurgedKFold, triple-barrier, meta-labeling, fracdiff, microstructure, structural breaks |
| ranaroussi/quantstats | 7,080 | recent | 80+ metrics, full HTML tear sheet |
| pmorissette/ffn | 2,545 | recent | Reference (overlap with quantstats) |
| quantopian/alphalens | 4,256 | (archived) | Factor IC, quantile-spread, turnover analysis |
| stefan-jansen/pyfolio-reloaded | 590 | recent | Capacity, perf attribution, interesting periods, round trips |
| quantopian/pyfolio | 6,301 | (deprecated) | Same as pyfolio-reloaded — use the reloaded fork |
| AI4Finance-Foundation/FinRL | 15,078 | recent | Reference for env design + multi-source data preprocessor |
| TauricResearch/TradingAgents | 70,157 | recent | Reference for LLM agent patterns + AlphaVantage/yfinance dataflow style |
| OpenBB-finance/OpenBB | 67,103 | recent | Reference for data provider abstraction (extensions/providers) |
| QuantConnect/Lean | 18,816 | recent | Reference for live broker patterns (C# — port not feasible) |
| mementum/backtrader | 21,413 | recent | Reference for analyzers + sizers + multi-broker patterns |
| robcarver17/pysystemtrade | (high) | recent | Reference for diversification multipliers, vol-targeting at scale |
| dcajasn/Riskfolio-Lib | 4,136 | recent | HCPortfolio + risk function reference |
| quantrocket-llc/moonshot | 263 | recent | Vectorized intraday + per-asset commission/borrowfee |

---

## 8. Caveman conclusion

QF v1.0 = solid validation, weak ML and weak portfolio. v1.1 should fix exactly that. Don't chase RL or LLM — different product. Port mlfinlab + quantstats + PyPortfolioOpt cores in two batches (~95 hours), add 4 ML-grade validation gates, ship `analytics/` module for factor/round-trip/attribution. After that, QF stops being a "rule-based backtest with strong gates" and becomes a "ML+rule lab with strongest gates in the FOSS quant world."

Big stones first:
1. PurgedKFold (4h)
2. Triple-barrier + meta-label (12h)
3. HRP + CVaR allocator (8h)
4. quantstats 80-metric tearsheet (11h)
5. Alpha158 feature library (10h)
6. Alphalens factor analysis (12h)

Six features = 57h = one focused 4-day push. Same OOSGuard discipline. Same seed-everywhere reproducibility. Now with ML grade.

End.
