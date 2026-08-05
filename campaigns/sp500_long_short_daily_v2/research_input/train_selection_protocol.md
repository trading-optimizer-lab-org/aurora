# Frozen V2 train-selection protocol

## 1. Boundaries

```text
train_end = 2010-12-31
validation = 2011-01-01 through 2020-12-31
locked_start = 2021-01-01
```

All design, implementation, ranking and candidate selection occur without reading validation or locked outcomes.

## 2. Outer train evaluation

Use annual outer test years `1998..2010` when a candidate is available. A candidate may begin later because of ETF inception or model warmup, but must have:

- at least 1,000 eligible sessions;
- at least five complete calendar test years;
- at least 98% coverage after causal start;
- a one-session embargo;
- no future-filled predictor.

Static rules are evaluated out of fold without fitted parameters. The shallow tree is refit monthly on its expanding lawful sample and evaluated only on subsequently generated decisions.

## 3. Metrics

Calculate all metrics in the original contract, including CAGR, Sharpe, Sortino, Calmar, drawdown, worst year, hit rates, rolling 1/3/5-year measures, skew, CVaR, turnover, switches and regime breakdowns. Store daily positions and returns for every evaluable strategy and benchmark.

## 4. Frozen ranking score

Among technically eligible V2 candidates, compute cross-sectional percentile ranks using only outer-OOF train results:

```text
18% CAGR
18% Calmar
14% Sharpe
10% Sortino
10% positive-year fraction
10% median rolling 3-year CAGR
10% worst outer-fold CAGR
 5% inverse turnover-instability
 5% inverse complexity
```

For adverse metrics, transform direction before ranking. Ties are broken by lower complexity, then lower turnover, then strategy ID. This ranking does not override hard gates.

## 5. Cumulative multiple testing

V2 is not a statistical reset.

### Declared-trial accounting

```text
V1 declared = 168
V2 declared = 144
binding declared count = 312
```

Use `312` as the conservative trial count in the binding Deflated Sharpe Ratio. A correlation-adjusted effective count may be reported only as a secondary diagnostic.

### FDR

Compute raw candidate p-values under the frozen bootstrap/test contract. Apply FDR over all 312 declared candidates. V1 technical/data rejections remain in the declaration ledger with conservative p-value `1`; they are not assigned return zero.

### Combined WRC and SPA

Load all 65 V1 evaluable daily-return streams from the exact embedded artifact and all V2 evaluable streams. Align each with the five benchmarks and construct a binding common causal interval containing at least 1,500 sessions. Use the strongest mandatory benchmark determined without validation.

Run:

- White Reality Check;
- Hansen SPA;
- stationary circular bootstrap;
- block-length sensitivity `5,10,15,20,60`;
- at least 5,000 deterministic bootstrap replications for the final run;
- seeds recorded in the artifact.

If a single common interval with 1,500 sessions cannot be constructed, status is `COMBINED_MULTIPLICITY_INCOMPLETE`; V2 may report diagnostics but cannot open validation.

### CSCV/PBO

Use the combined matrix of all V1 and V2 evaluable differential returns on the same common interval. Report PBO, logit ranks and partition sensitivity. Rejected candidates are excluded from the return matrix but remain in declared-trial accounting.

## 6. Hard train gate

A validation-eligible candidate must satisfy all of:

```text
CAGR > 0
Sharpe > 0.30
Calmar > 0.25
max_drawdown > -55%
positive years >= 60%
median rolling 3y CAGR > 0
worst outer-fold CAGR > -30%
single-year contribution to positive log growth <= 60%
at least half of declared neighboring variants: CAGR > 0 and Sharpe > 0
Deflated Sharpe probability > 0.80 using 312 trials
candidate SPA p <= 0.10
candidate FDR q <= 0.10
global combined SPA p <= 0.10
combined PBO < 0.50
```

At most one finalist per family and 20 overall. Candidates tagged `post_2010_research` are never validation eligible.

## 7. Freeze and one-shot validation

Create an immutable `v2_train_selection_freeze.json` with code/data/environment/candidate hashes and the combined V1+V2 multiple-testing inputs. Verify the downloaded artifact hash before validation.

Required acknowledgment:

```text
OPEN_VALIDATION_2011_2020_ONCE_V2
```

Validation can open only if at least one `pre_2011_evidence` finalist survives every gate. It may open once. No retuning, new variants, sign changes, data repairs by outcome or second validation search are allowed.

## 8. Locked

No request, cache, file, log, dataframe or metadata scan may expose a market observation dated `>=2021-01-01`.
