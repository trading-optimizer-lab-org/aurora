# Glossary

Definitions of metrics, validation gates, and abbreviations used across
QuantForge. Where a formal reference exists, it is cited.

## Performance metrics

### CAGR (Compound Annual Growth Rate)
Annualized geometric return: `(NAV_end / NAV_start) ** (1 / years) - 1`.

### Sharpe ratio
Annualized excess-return-per-unit-volatility:
`(mean(excess_returns) / std(excess_returns)) * sqrt(periods_per_year)`.
Excess return is over the risk-free rate (or zero when the rate is
ignored). Implemented in `core/metrics.py`.

### Sortino ratio
Like Sharpe but the denominator uses downside deviation only (negative
excess returns). Penalizes drawdowns rather than total volatility.
Reference: Sortino and Price (1994).

### Calmar ratio
`CAGR / |maximum drawdown|`. The signature metric of the QuantForge
validation pipeline because it captures both return and tail risk in a
single scalar. Higher is better.

### MAR ratio
Synonym of Calmar in much of the trading literature, after Managed Account
Reports. QuantForge uses the term Calmar throughout the code.

### MDD (Maximum Drawdown)
Largest peak-to-trough loss in equity, expressed as a positive fraction.
`MDD = max((peak - equity) / peak)` over the series.

### DSR (Deflated Sharpe Ratio)
Bailey and Lopez de Prado correction for selection bias when reporting the
best Sharpe across N candidates. Accounts for the number of trials, the
skew and kurtosis of the strategy returns, and the variance of Sharpe
across the candidate pool. Reference: Bailey and Lopez de Prado (2014),
"The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting, and Non-Normality". Threshold used in QuantForge: DSR > 1.96
for 95% confidence. Implemented in `validation/deflated_sharpe.py`.

### PSR (Probabilistic Sharpe Ratio)
Probability that the observed Sharpe exceeds a benchmark Sharpe given the
sample size and higher moments of returns. Companion to DSR. Reference:
Bailey and Lopez de Prado (2012).

## Validation gates

### OOS / IS (Out-of-sample / In-sample)
The dataset is split in two on a fixed calendar date. IS is used for
optimization (GA, parameter selection, model fitting). OOS is used only
once, after candidates are chosen, to check whether the strategy
generalizes. In QuantForge the split is `IS_END = 2012-12-31`,
`OOS_START = 2013-01-01`. See `docs/RESEARCH_PROTOCOL.md` for the formal
multi-tier split (IS_TRAIN / IS_VALID / WF / OOS_DEV / OOS_LOCKED /
FORWARD).

### WF (Walk-Forward)
Train on a rolling, expanding, or anchored in-sample window, evaluate on
the next out-of-sample chunk, then advance and repeat. The criterion in
QuantForge: Calmar > buy-and-hold Calmar in each window. Implemented in
`validation/walk_forward.py` with three modes (rolling, expanding,
anchored).

### MC (Monte Carlo)
Two flavors used in QuantForge:

- **Block bootstrap on returns**: resample contiguous blocks of returns to
  preserve autocorrelation and rebuild the equity curve. Produces a
  distribution of MDD, Calmar, etc.
- **Trade reorder**: shuffle the order of completed trades and recompute
  the equity curve. Tests whether the equity path is robust to ordering.

The pipeline gate requires the realized MDD percentile to land in
[0.20, 0.80] of the bootstrap distribution. Outside this band the run is
either lucky or pathological.

### SPP (System Parameter Permutation)
Perturb each parameter by +/-10% across a neighborhood and run the
backtest at each perturbation. Reject if the coefficient of variation of
Calmar exceeds 30%. The intent is to filter out brittle "magic-parameter"
configurations. Reference: Dave Walton (2014), "Know Your System! - Turning
Data Mining from Bias to Benefit through System Parameter Permutation".
Implemented in `validation/spp.py`.

Note on terminology: in some literature SPP also denotes "Single-Parameter
Plot" - sweep one parameter while holding the rest fixed and plot the
metric versus the parameter. QuantForge uses SPP to mean System Parameter
Permutation throughout, since it is the stricter test. The
single-parameter sweep is available via `forge bench` and ad-hoc
notebooks.

### Lookahead check
Two layers in QuantForge:

- **AST** (`validation/lookahead_check.scan_lookahead`) statically scans
  the strategy source for forward-slice patterns.
- **Runtime** (`runtime_lookahead_check`) shuffles bars after a chosen
  index and asserts that earlier signals do not change.

### Purged K-Fold CV
K-fold cross-validation adapted for time series with overlapping labels.
Observations whose labels overlap any test fold are purged from the
training set, and an embargo period is applied at fold boundaries.
Reference: Lopez de Prado, "Advances in Financial Machine Learning"
(AFML), Ch.7. Implemented in `validation/purged_cv.py`.

### CSCV (Combinatorially Symmetric Cross-Validation)
Split returns from N candidate strategies into S equal-size groups, take
all combinations of S/2 groups for IS and the complement for OOS, and
compute the rank of the IS-best strategy on OOS across all combinations.
The fraction of combinations where the IS-best ranks below median is the
PBO. Reference: Bailey, Borwein, Lopez de Prado, Zhu (2014),
"Pseudo-mathematics and financial charlatanism: The effects of backtest
overfitting on out-of-sample performance". Implemented in
`validation/cscv_pbo.py`.

### PBO (Probability of Backtest Overfitting)
Output of CSCV: the probability that the IS-best strategy underperforms
the median strategy on OOS. PBO close to 0.5 indicates overfitting; close
to 0 indicates the IS leaderboard generalizes.

### Triple-barrier labeling
Label each event with the first of three barriers to be hit: an upper
profit-take, a lower stop-loss, or a vertical time horizon. Produces
adaptive labels suited to volatile regimes. Reference: AFML Ch.3.
Implemented in `ml/labels.py`.

### Meta-labeling
Two-model stack. The primary model decides side (long / short). A
secondary "meta" model is trained on triple-barrier outcomes and decides
size (or a binary act / pass). Reference: AFML Ch.3. Implemented in
`ml/labels.py` alongside triple-barrier.

### Fracdiff (Fractional differentiation)
Differencing with a non-integer order `d` in `(0, 1)`. Removes
non-stationarity while preserving as much memory as possible. The minimum
`d` for which the series passes ADF is reported. Reference: AFML Ch.5.
Implemented in `ml/fracdiff.py`.

### HRP (Hierarchical Risk Parity)
Allocator that clusters assets by correlation distance, builds a
quasi-diagonal covariance, and recursively splits the budget. Robust to
ill-conditioned covariance estimates. Reference: Lopez de Prado (2016),
"Building Diversified Portfolios that Outperform Out-of-Sample".
Implemented in `deployment/hrp.py`.

### VPIN (Volume-synchronized Probability of Informed Trading)
A toxicity metric for order flow. Volume bars are grouped into buckets;
within each bucket, the absolute imbalance between buyer- and
seller-initiated volume divided by total volume is the VPIN. High VPIN is
associated with stressed liquidity. Reference: Easley, Lopez de Prado,
O'Hara (2012). Implemented in `ml/microstructure.py`.

## Other terms used in the codebase

### IBKR_costs
Default cost model in `core/costs.py`: 5 bps spread + 0.5 bps commission +
5 bps slippage per trade. Used as the floor for any "real" backtest.

### OOSGuard
Context manager in `core/data_layer.py` that records every OOS read with a
timestamp and the current git hash to `data_cache_qf/.oos_lock.json`. Used
to detect contamination during optimization. See
`docs/RESEARCH_PROTOCOL.md` for the lockbox ceremony.

### NSGA-II
Non-dominated Sorting Genetic Algorithm II. Multi-objective evolutionary
algorithm used in `ga/runner.py`. Optimizes Calmar, Sharpe, MDD penalty,
and walk-forward robustness simultaneously, returning a pareto front.

### ADV (Average Daily Volume)
Used in liquidity-aware sizing (`deployment/liquidity.py`) and intraday
cost models (`core/costs_intraday.py`) for square-root impact.

### ADWIN, Page-Hinkley, KS
Drift detectors in `monitoring/drift.py`. ADWIN keeps an adaptive window
and detects distribution change. Page-Hinkley accumulates the deviation
from a running mean. KS is a two-sample Kolmogorov-Smirnov test on a
recent window vs a reference window.

### Ledoit-Wolf, OAS
Covariance shrinkage estimators in `deployment/cov_shrinkage.py`. Used to
stabilize covariance matrices before HRP / risk-parity allocation.

### Roll spread, Corwin-Schultz
Bid-ask spread proxies estimated from OHLC data, used when quoted spreads
are unavailable. Implemented in `ml/microstructure.py`.

### OFI (Order-Flow Imbalance)
Difference between buyer-initiated and seller-initiated volume per bar,
typically classified by the Lee-Ready algorithm. Implemented in
`ml/microstructure.py`.

### Kyle's lambda
Price-impact coefficient regressing returns on signed volume. Implemented
in `ml/microstructure.py`.

### Amihud illiquidity
`mean(|return| / dollar_volume)` over a window. Higher values indicate
less liquid markets. Implemented in `ml/microstructure.py`.
