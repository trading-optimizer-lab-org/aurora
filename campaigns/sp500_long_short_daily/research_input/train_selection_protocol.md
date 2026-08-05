# Train-only selection protocol

## Direct rule

All design, fitting, ranking, multiplicity correction and candidate selection occur using data dated **no later than 2010-12-31**. The 2011-2020 validation set is opened once after a complete cryptographic freeze. Data from 2021 onward are never opened in this campaign.

## 1. Common evaluation period

The tradeable target SPY begins in 1993. The default common target period is the first fully reconciled SPY session after warmup through 2010-12-31. Candidates with later feature availability are evaluated only after their causal first date and are penalized for shorter history. A paper's older index sample cannot extend the SPY backtest by splicing a non-tradeable index into the target.

## 2. Candidate freeze and deduplication

- Parse all 168 JSONL objects.
- Recompute every canonical hash after removing only the stored hash field.
- Reject duplicate hashes and economically equivalent parameter aliases.
- Confirm exactly `[-1,+1]`, absolute exposure `1.0` and every cost field `0`.
- Store source-code commit, data-manifest hash, candidate-pack hash and environment lockfile hash in `freeze/train_campaign_freeze.json`.
- No candidate may be created, removed or edited after train execution starts. Technical parser corrections require a new campaign ID and invalidate prior performance.

## 3. Train-only outer walk-forward

Use annual out-of-fold evaluation within the train boundary:

- Minimum fitting/burn-in endpoint: 1997-12-31 or candidate-specific later causal warmup.
- Outer test folds: calendar years 1998 through 2010.
- At each fold, fit/normalize using observations strictly before the first test session.
- Test on the next calendar year; append only truly out-of-fold daily returns.
- Static rules have no fitted coefficients but still receive causal normalization and the same fold accounting.
- Use a one-session embargo around fitted next-open labels; any feature with overlapping longer-horizon target requires an embargo equal to that target horizon.

## 4. Nested model selection

For Markov/logistic candidates, hyperparameters are selected inside each outer training set with chronological inner folds. The grid is already stored in each candidate. Use the one-standard-error rule to prefer the simplest setting. The outer test year cannot affect normalization, state labels, regularization or missing-data decisions.

## 5. Metrics computed from out-of-fold train returns

CAGR, total return, annual return, Sharpe, Sortino, Calmar, maximum drawdown, worst year, volatility, daily hit rate, monthly hit rate, positive years, turnover, long days, short days, position switches, rolling 1-year, rolling 3-year and rolling 5-year results, skew, CVaR and performance by frozen market regime. Also report worst day/month, average holding duration, fold-level metrics, missing-data coverage and concentration of gains.

Annualization uses the actual NYSE session count and a zero risk-free rate for Sharpe/Sortino to match the zero-cost experimental contract.

## 6. Exact train ranking score

Within the eligible candidate universe, winsorize each metric at the cross-sectional 2.5th/97.5th percentiles, convert to percentile ranks where higher is better (invert drawdown magnitude/instability), and calculate:

```text
base_score =
  0.20 * pct_rank(CAGR)
+ 0.15 * pct_rank(Calmar)
+ 0.10 * pct_rank(Sharpe)
+ 0.08 * pct_rank(Sortino)
+ 0.10 * pct_rank(positive_year_fraction)
+ 0.10 * pct_rank(median_rolling_3y_CAGR)
+ 0.10 * pct_rank(worst_year_return)
+ 0.07 * pct_rank(min_outer_fold_CAGR)
+ 0.05 * pct_rank(benchmark_win_fraction)
+ 0.05 * pct_rank(1 - turnover_instability)

penalty =
  0.05 * complexity_normalized
+ 0.07 * parameter_sensitivity_failure_rate
+ 0.06 * fold_concentration_penalty
+ 0.05 * missing_data_dependency
+ 0.04 * post_2010_evidence_indicator
+ 0.03 * proxy_data_dependency

train_selection_score = base_score - penalty
```

No coefficient or threshold in this score can change after train results are seen.

## 7. Pareto and family controls

1. Apply hard data/causality/return-accounting gates first.
2. Construct a Pareto frontier on CAGR, Calmar, maximum drawdown, worst year, fold stability and complexity.
3. Retain at most two candidates per family before the global comparison, except exact benchmark rules.
4. Keep no more than 30 validation finalists.
5. A family with no candidate passing hard gates contributes zero finalists; its place is not reassigned through new variants.
6. Parameter-neighbour sensitivity is evaluated around each finalist using only already enumerated variants. A sharp isolated peak incurs the predefined penalty.

## 8. Multiple-testing controls

Run all controls against the disclosed 168-candidate universe and the benchmark loss differential:

- White Reality Check with stationary bootstrap;
- Hansen SPA;
- CSCV/PBO on candidate return columns;
- Deflated Sharpe Ratio using the effective number of independent trials estimated from return correlations;
- block-bootstrap confidence intervals;
- false-discovery reporting for individual statistics, clearly secondary to portfolio-level tests.

Bootstrap block length is selected by a train-only automatic rule and recorded. Sensitivity at fixed 5, 10, 20 and 60 sessions is reported, not selected.

## 9. Benchmarks and negative controls

Mandatory benchmarks, all using exactly the same calendar, open-to-open total-return ledger, timing and zero costs:

1. Buy-and-hold SPY total return (`+1` throughout).
2. Always long `+1` (reported separately; must reconcile exactly with buy-and-hold).
3. Always short `-1`.
4. Symmetric SMA-200: decide after close `t`, `+1` above, `-1` below, tie previous, execute open `t+1`.
5. Symmetric 12-month momentum: `+1` when the causal 252-session SPY total-return momentum is positive, `-1` when negative, tie previous, execute open `t+1`.

Negative controls:

- Equal random sign with seed `20260803`, diagnostic only.
- Block-permuted labels and circularly shifted signals, non-economic controls only.

## 10. Validation opening and one-shot rule

After train selection:

1. Write finalist IDs, order, scores, code commit and all hashes to `freeze/train_selection_freeze.json`.
2. Sign/hash the file and upload it as an immutable GitHub artifact.
3. Require the exact acknowledgment `OPEN_VALIDATION_2011_2020_ONCE`.
4. Open 2011-2020 once and calculate the frozen candidates/benchmarks.
5. Do not retune, replace, reweight, repair by outcome or run a second validation search.
6. A genuine upstream data correction creates a new version labelled `validation_invalidated_technical`, never a quiet rerun.
7. Keep every 2021+ path blocked by date assertion and artifact inspection.

## 11. Outcome labels

- `POSITIVE_VALIDATED_RESULT`: at least one frozen finalist passes every acceptance gate.
- `NEGATIVE_RESULT`: computation and data are valid but no finalist passes.
- `TECHNICAL_FAILURE`: results are not interpretable because code/data/causality checks failed.
- `VALIDATION_NOT_OPENED`: train phase completed but the one-time authorization was not supplied.

A negative result is final for this candidate universe. New research requires a new campaign and cannot reuse 2011-2020 as a fresh holdout.
