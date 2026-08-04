# Acceptance gates

## Principle

Gates are fixed before train performance is calculated. They distinguish **data validity**, **train eligibility**, **selection robustness** and **one-time validation success**. No narrative override is permitted.

## A. Package and implementation gates — all mandatory

| Gate | Pass condition | Failure label |
|---|---|---|
| File integrity | All 19 required files exist, parse as UTF-8, JSON/JSONL/YAML/CSV schemas pass and hashes match. | `TECHNICAL_FAILURE_PACKAGE` |
| Candidate cardinality | Exactly 168 unique candidate hashes and 28 families; no duplicates. | `TECHNICAL_FAILURE_DUPLICATE_OR_MISSING` |
| Position contract | Every evaluated date from first evaluable session has position exactly `-1` or `+1`; absolute exposure exactly 1. | `TECHNICAL_FAILURE_POSITION` |
| Cost contract | Every cost component equals numeric zero in source and computed ledger. | `TECHNICAL_FAILURE_COST` |
| Causal timestamps | Every feature value has `available_at <= decision_timestamp < execution_timestamp`. | `TECHNICAL_FAILURE_LOOKAHEAD` |
| Locked firewall | No file, API query, cache key, dataframe or log contains market observations dated 2021-01-01 or later. | `TECHNICAL_FAILURE_LOCKED_BREACH` |
| Return identity | `short_return == -long_return` under the specified zero-cost total-return ledger, including distributions. | `TECHNICAL_FAILURE_RETURN_ACCOUNTING` |
| Reproducibility | Two clean smoke runs with the same inputs/commit produce identical hashes and metrics. | `TECHNICAL_FAILURE_NONDETERMINISM` |

## B. Candidate data eligibility — before performance ranking

- At least 1,000 evaluable SPY sessions and at least five complete outer test years inside train.
- At least 98% coverage of expected target sessions after the candidate's causal start date.
- No unresolved missing daily market bar; release-frequency features may carry only the last published value.
- Every source is `usable_now` or has passed its documented `usable_after_repair` checklist.
- No paid dataset, current-member survivorship reconstruction, unversioned revised macro history or undisseminated backfill.
- Cross-source SPY daily raw-return differences must be within 5 basis points on at least 99.5% of overlapping sessions; every larger difference is reconciled.
- Corporate-action/open-return tests pass around every split and distribution event.

Failure means `DATA_INELIGIBLE`, not a zero return and not deletion from the search log.

## C. Minimum train eligibility for a validation finalist

Calculated only on outer out-of-fold train returns:

- CAGR > 0%.
- Sharpe > 0.30.
- Calmar > 0.25.
- Maximum drawdown > -55%.
- Positive calendar years >= 60%.
- Median rolling three-year CAGR > 0%.
- Worst outer-fold CAGR > -30%.
- No single calendar year contributes more than 60% of total positive log growth.
- Parameter-neighbour sensitivity: at least half of the already enumerated adjacent variants retain positive CAGR and Sharpe > 0.
- Deflated Sharpe probability > 0.80.
- CSCV/PBO estimate < 0.50.
- SPA p-value <= 0.10 against the strongest of the five mandatory benchmarks (buy-and-hold, always-long, always-short, symmetric SMA-200 and symmetric 12-month momentum), or the candidate must be explicitly retained only as the single family representative for validation diagnostic purposes. A diagnostic representative cannot receive `POSITIVE_VALIDATED_RESULT` unless validation gates pass.

At most two finalists per family and 30 overall.

## D. One-time validation success — all mandatory for a positive result

For 2011-01-01 through 2020-12-31, with no refit except causal model updates specified before opening:

1. CAGR > 0%.
2. Sharpe >= 0.45.
3. Calmar >= 0.35.
4. Maximum drawdown > -45%.
5. Positive calendar years >= 6 of 10.
6. Median rolling three-year CAGR > 0%.
7. Validation CAGR exceeds always-long, the symmetric 200-day benchmark and the symmetric 12-month momentum benchmark, **or** validation Calmar exceeds each by at least 0.15 while CAGR remains no more than 2 percentage points below always-long. This alternative prevents a false equation of raw return and risk-adjusted quality.
8. Validation Sharpe is at least 0.10 above the best Sharpe among always-long, the 200-day benchmark and the 12-month momentum benchmark.
9. No single year contributes more than 50% of the candidate's positive validation log growth.
10. Directional exposure is not degenerate: both long and short positions occur on at least 5% of validation sessions.
11. Train-to-validation degradation: validation Sharpe is not below 40% of train out-of-fold Sharpe and validation Calmar is not below 35% of train Calmar.
12. All implementation/data gates remain green and the frozen candidate hash is unchanged.

If zero candidates pass, the correct outcome is `NEGATIVE_RESULT`.

## E. Non-binding diagnostics

Because the requested experiment fixes costs at zero, turnover-cost sensitivity at 1/2/5/10 bps, borrow costs and execution slippage may be reported **only as clearly non-binding diagnostics**. They cannot alter selection, validation gates or the zero-cost headline metrics.
