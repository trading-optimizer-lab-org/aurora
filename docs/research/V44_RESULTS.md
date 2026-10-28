# v44 results: new one-minute families, the book's meta-labels and execution, their combination

Run 40639063412 (v44.yml, attempt 2; attempt 1 lost shard 32 of part N's real returns to a pip download error,
`IncompleteRead`, and was re-run with `gh run rerun --failed`, code unchanged). Data run 40551641084. Part M:
1,204,320 of 1,204,320 books. Part N: 772,632 of 772,632 configurations, 0 errors, 500 placebos per selected
configuration. Full tables in the artifacts `v44m-report` (V44M_REPORT.md), `v44n-report` (REPORT.md) and
`v44c-report` (V44C_REPORT.md). Pass marks from `V44_PREREGISTRATION.md` section 4; bootstrap of 4,000 one-year
paths from $5,000, ruin at or under $1,250.

## Q1 (part M): does the walk-forward book improve the book? NOT MET

Data:

| book | costs | median | ruin | p10 |
|---|---|---|---|---|
| base book | base | $22,006 | 0.1% | $8,295 |
| base book | HOT 5% | $16,153 | 0.5% | $6,084 |
| base book | high | $10,252 | 2.5% | $3,650 |
| walk-forward | base | $17,106 | 10.5% | $0 |
| walk-forward | HOT 5% | $12,635 | 11.3% | $0 |
| walk-forward | high | $7,977 | 14.0% | $0 |

| mark | needed | walk-forward | pass |
|---|---|---|---|
| median vs base | >= 1.15 x $22,006 = $25,307 | $17,106 | no |
| ruin, base costs | <= 2.5% | 10.5% | no |
| ruin, HOT 5% | <= 2.5% | 11.3% | no |
| high-cost median | >= $10,252 | $7,977 | no |
| log growth, symbol half 0 | > 6.22 | -0.61 | no |
| log growth, symbol half 1 | > 6.84 | 5.88 | no |

- Historical path at $10,000: walk-forward 4.65 vs base 12.79 summed log growth.
- Picks: 2018 base; 2019 T3 trigger within 120m with TWAP 5; 2020 skip `bvc30` top tercile, T5 within 15m, passive;
  2021-2022 gradient boosting size x(0.5+p), T2 within 60m, passive; 2023-2026 pairs of tercile skips, auction.
- Each dimension alone, in sample: no emergency exit, locate rule or partial cover beats the base book (the best
  emergency exit is X4 10 at 7.49 vs 12.79). The execution choices move log growth by at most +0.31 (passive 13.10).
  The best fixed filter pair in hindsight reaches 13.29, +0.50 over nine years.

Inference: the base book's base-cost median reproduces v43's central case ($22,006), so part M ran on the same
book. The walk-forward rule picks among 1.2 million books on one to eight earlier years and lands on books that
blow up out of sample (2021-2022's size x(0.5+p) has a -99.9% worst yearly drawdown over all years). The in-sample
gains of the best fixed books are of the order of noise for this grid size.

## Q2 (part N): COMBO44 criterion. NOT MET

Data:

- COMBO44: Sortino 2018+ -1.91 (needed >= 4), 2018-20 -0.52, 2021+ -2.59, 2023-07+ -3.37 (needed >= 3), DSR 0.00,
  PBO 0%, CAGR -0.2%, max DD -5.7%. At the strict fills: Sortino -2.02.
- Members: 2018 CP, KF; 2019 CP, FB, RO; 2020-2021 CP; 2022 CP, RO; 2023-2026 none.
- One family of fifteen passes run_v22's gate: RO (rotation), walk-forward Sortino 1.24 (2018-20 0.20, 2021+ 1.65),
  CAGR 9.3%, max DD -20.9%, PBO 0%, SPA p 0.028, 7/9 years placebo-ok; 2023-07+ Sortino 1.52, CAGR 16.4%; symbol
  halves 0.24 and 0.75; at strict fills -0.41; worst trade -131%.
- NW (news) has the best 2023-07+ Sortino after RO (1.08) but 0.09 at strict fills and fails the gate.
- Every other family has a negative walk-forward Sortino 2018+ except KF (0.32) and LP (0.03).
- In-sample median Sortino of every family's configurations is negative in every dimension value.

Inference: no new one-minute family carries an edge that survives costs. RO is the only one with a positive
placebo-adjusted signal; it is far from the Sortino 4 target, turns negative at strict fills, and its worst trade
(-131%) is a loss larger than the position, a short squeeze.

## Q3 (part C): does the sleeve improve the account? NOT MET

Data:

- Book: the base rule, since Q1 failed. COMBO44 members cover only 2018-2022 (9 pick-years).
- The walk-forward size rule chose "no sleeve" in every year 2018-2026, so the walk-forward account equals the book
  alone: median $22,006, ruin 0.1% (HOT 5% $16,153 / 0.5%; high $10,252 / 2.5%). The 1.15 x median mark fails.
- Each fixed size in every member year, in sample, lowers the median: risk 0.5% cap 10% $19,421; risk 1% $18,814
  (cap 10% and cap 20% identical); risk 2% cap 20% $17,520 with ruin 0.7%.

Inference: the sleeve costs the PAID plan ($105 a month) and its members lose money net, so every size hurts.

## Q4: from $2,000 (ruin at or under $500). Descriptive

| account | median | ruin | p10 | chance of -50% |
|---|---|---|---|---|
| base book | $8,296 | 0.3% | $2,967 | 5.4% |
| part M walk-forward | $6,455 | 11.0% | $0 | 17.4% |
| part C account (= book alone) | $8,296 | 0.3% | $2,967 | 5.4% |

## Verdict

v44 does not improve the book. The current book (v43's central case at TradeZero International, $5,000) stays:
median $22,006 a year, ruin 0.1%, worst yearly drawdown on the historical path -70.3%.

## Caveats

- Section 5 of the pre-registration holds: every year 2018-2026 has been seen and the book was chosen on them.
- `spy_vwap` (SPY above its VWAP, a 0/1 feature) never acts as a tercile filter. Its two values are each more than a
  third of the trades, so the strict cuts are 0 and 1 and nothing is above the upper or below the lower one; both
  of its filters equal the base book (12.79). Section 6 says a binary feature flags its rarer value; that holds only
  when the rarer value is under a third. Not fixed after seeing results. The bottom-tercile filters of `offering24`,
  `filing7` and `block` are also no-ops, as designed (those features are mostly 0).
- The "Counts" sections of the M and C reports are empty: the counters are updated in the worker processes and never
  reach the parent (the same bug as v43). No result depends on them.
- Several families' worst trades exceed -100% of the position (RO -131%, LP -121%, KF -117%): short squeezes; the bootstrap
  includes them but intraday marks of part C's sleeve do not enter the broker's 15% check.
- News coverage is Benzinga's through Alpaca and may be thinner in early years; EDGAR times are SEC acceptance
  times; SIC codes are today's.
