# v52 results

Run 41220426939 (19 factory jobs, 22 book shards, final; all success, about 15 minutes). Data run 41219555974: 8,315
holdout events 2016-02-01 to 2017-12-29 (4,163 and 4,152 a year, like 2018-2019's 4,951 and 5,236), 26,820 of 26,827
symbol-days with one-minute bars (0.14 GB, Actions cache only). Diagnostic run 41220921317 (aggregates in
`data/v52_diag.json`). Pre-registration: `V52_PREREGISTRATION.md`; frozen list: `data/v52_frozen.json`.

## Verdict

- **NOT MET.** H1 (CRASH-long c_1555 d1pm/t0.25/s1.00 [$1M] 30% + RUNUP-short c_ah5 d10c 30% + FADE-short c_pm0
  d1pm/t0.50/s1.00 30%, 5 new a day) on one-year paths drawn from 2016-2017: median **$6,827**, ruin 0.0% (HOT 5%
  $6,741, 0.0%). Locates never failing $9,960; every short HOT $6,115; borrow x2 $6,092; symbol halves $7,545 and
  $4,169. The actual sequence from $5,000 ends 2017 at $9,333.
- v51's in-sample $51,191 does not carry over. No frozen book reaches $10,000 at base (best: v51's answer $8,793);
  all keep ruin near 0%.
- CRASH-long alone: every size and limit stays near $5,000 or below (best $5,282 at 20%, 3 new a day); at 40% ruin
  rises to 3.7-5.7%.

## Why CRASH-long's 2016-2017 PF of 6.3 is not an edge

At the trade level the 10 CRASH-long selections show PF 5.3-6.3 and a mean of +9-11% a trade on 2016-2017. The
diagnostic shows where it comes from: for selection 6 (898 trades) the median trade is -0.5%, the 10th and 90th
percentiles -6.0% and +5.8%, and the top 1% of trades (about 9) add up to **103%** of the total return: without them
the rest is slightly negative. Those few trades are extreme jumps of sub-$1 to $15 names, most likely bad
extended-session prints or rare squeezes; in the account they are capped by the 1%-of-dollar-volume size and rarely
fall in a one-year path, so the median path stays flat. The marks and the trade returns agree (sums 104 and 99), so
it is not an engine fault.

## Other holdout facts (trade level, report only)

- RUNUP-short c_ah5 d10c: 10 trades in two years, all winners; FADE-short c_pm0 d1pm/t0.50/s1.00: 29 trades, PF 2.11.
  The shorts work but trade too rarely to carry a $5,000 account to $10,000.
- Of v51's 193 selections, the high-PF short groups fall hard (median PF in 2018-2022 vs 2016-2017: STRONG-short
  16.1 vs 1.7, GAPUP-short 19.1 vs 0.54, RUN100-short 7.9 vs 0.36): the grid's top scores are mostly selection.

## Report (verbatim from run 41220426939)

# v52 report: v51's CRASH-long book on 2016-2017

Pre-registered in V52_PREREGISTRATION.md. One-year paths drawn from the sessions 2016-02-01 to 2017-12-29, from $5,000, v51's engine and TZC costs.

**NOT MET.** H1: CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% + FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%, 5 new a day.

- base: median $6,827, ruin 0.0% (90th percentile of the seeds 0.1%), 10th percentile $3,651, a loss in 27.2%
- HOT 5%: median $6,741, ruin 0.0%
- history from $5,000: $9,333 at 2017-12-29, low $4,530; by year at the $5,000 level: 2016 +45%, 2017 +48%

## Frozen books

| book | role | new | median | ruin | HOT5 median | HOT5 ruin | borrow x2 | locates never fail | half rates | every short HOT | half 0 | half 1 | history from $5k |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1: CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% + FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | decides | 5 | $6,827 | 0.0% | $6,741 | 0.0% | $6,092 / 0.1% | $9,960 / 0.1% | $9,385 / 0.0% | $6,115 / 0.1% | $7,545 | $4,169 | $9,333 |
| low2: FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | report | 5 | $6,906 | 0.0% | $6,820 | 0.0% | $6,187 / 0.1% | $9,876 / 0.1% | $9,597 / 0.0% | $6,213 / 0.1% | $7,665 | $4,158 | $9,587 |
| low3: RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% + FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% | report | 5 | $8,168 | 0.0% | $8,063 | 0.0% | $7,275 / 0.0% | $11,397 / 0.0% | $10,818 / 0.0% | $7,324 / 0.0% | $8,067 | $4,992 | $15,145 |
| low4: FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% | report | 5 | $8,214 | 0.0% | $8,108 | 0.0% | $7,344 / 0.0% | $11,350 / 0.0% | $10,874 / 0.0% | $7,384 / 0.0% | $8,205 | $4,926 | $15,328 |
| low5: RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | report | 5 | $8,128 | 0.0% | $8,027 | 0.0% | $7,324 / 0.0% | $11,244 / 0.0% | $10,671 / 0.0% | $7,568 / 0.0% | $8,289 | $4,935 | $15,125 |
| low6: RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | report | 5 | $8,206 | 0.0% | $8,099 | 0.0% | $7,403 / 0.0% | $11,250 / 0.0% | $10,725 / 0.0% | $7,624 / 0.0% | $8,433 | $4,874 | $15,308 |
| v51 answer: STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% + FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | report | 5 | $8,793 | 0.0% | $8,670 | 0.0% | $7,874 / 0.0% | $12,024 / 0.0% | $11,554 / 0.0% | $7,876 / 0.0% | $7,192 | $6,131 | $16,504 |
| v50 book: RUNUP-short c_open d5c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20% + RUNUP-short c_open d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20% + FADE-short c_1555 d3c/t0.00/s0.00 [price2-2 str0 dv1 so:all tier:all age:all] 60% | report | 5 | $8,572 | 0.0% | $8,373 | 0.0% | $6,878 / 0.0% | $10,553 / 0.0% | $8,985 / 0.0% | $7,341 / 0.0% | $6,864 | $6,130 | $14,093 |

## CRASH-long selections alone

| configuration | size | new | median | ruin | HOT5 median | HOT5 ruin |
|---|---|---|---|---|---|---|
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 3 | $4,913 | 0.0% | $4,913 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 5 | $4,783 | 0.0% | $4,783 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 3 | $5,282 | 0.0% | $5,282 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 5 | $4,971 | 0.0% | $4,971 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 3 | $4,175 | 0.2% | $4,175 | 0.2% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 5 | $4,051 | 0.6% | $4,051 | 0.6% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 3 | $3,277 | 3.7% | $3,277 | 3.7% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 5 | $3,128 | 5.7% | $3,128 | 5.7% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 3 | $4,714 | 0.0% | $4,714 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 5 | $4,544 | 0.0% | $4,544 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 3 | $4,969 | 0.0% | $4,969 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 5 | $4,657 | 0.0% | $4,657 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 3 | $4,467 | 0.1% | $4,467 | 0.1% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 5 | $4,261 | 0.4% | $4,261 | 0.4% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 3 | $3,449 | 2.5% | $3,449 | 2.5% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 5 | $3,284 | 4.3% | $3,284 | 4.3% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 3 | $4,745 | 0.0% | $4,745 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 5 | $4,609 | 0.0% | $4,609 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 3 | $4,895 | 0.0% | $4,895 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 5 | $4,644 | 0.0% | $4,644 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 3 | $3,793 | 0.5% | $3,793 | 0.5% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 5 | $3,572 | 1.3% | $3,572 | 1.3% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 3 | $2,594 | 7.8% | $2,594 | 7.8% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 5 | $2,445 | 12.0% | $2,445 | 12.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 3 | $4,623 | 0.0% | $4,623 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 10% | 5 | $4,500 | 0.0% | $4,500 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 3 | $4,654 | 0.0% | $4,654 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 20% | 5 | $4,405 | 0.1% | $4,405 | 0.1% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 3 | $3,881 | 0.4% | $3,881 | 0.4% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 30% | 5 | $3,713 | 0.8% | $3,713 | 0.8% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 3 | $2,992 | 4.3% | $2,992 | 4.3% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 40% | 5 | $2,884 | 5.9% | $2,884 | 5.9% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 3 | $4,952 | 0.0% | $4,952 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 5 | $4,886 | 0.0% | $4,886 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 3 | $5,207 | 0.0% | $5,207 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 5 | $5,057 | 0.0% | $5,057 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 3 | $3,697 | 0.4% | $3,697 | 0.4% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 5 | $3,392 | 1.6% | $3,392 | 1.6% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 3 | $3,213 | 4.4% | $3,213 | 4.4% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 5 | $2,990 | 8.1% | $2,990 | 8.1% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 3 | $4,471 | 0.0% | $4,471 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 5 | $4,485 | 0.0% | $4,485 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 3 | $4,372 | 0.0% | $4,372 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 5 | $4,340 | 0.0% | $4,340 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 3 | $3,088 | 1.0% | $3,088 | 1.0% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 5 | $2,892 | 2.7% | $2,892 | 2.7% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 3 | $2,361 | 9.7% | $2,361 | 9.7% |
| CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 5 | $2,283 | 12.9% | $2,283 | 12.9% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 3 | $5,031 | 0.0% | $5,031 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 5 | $5,003 | 0.0% | $5,003 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 3 | $5,384 | 0.0% | $5,384 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 5 | $5,287 | 0.0% | $5,287 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 3 | $3,948 | 0.2% | $3,948 | 0.2% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 5 | $3,636 | 0.4% | $3,636 | 0.4% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 3 | $3,662 | 1.6% | $3,662 | 1.6% |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 5 | $3,485 | 2.6% | $3,485 | 2.6% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 10% | 3 | $4,885 | 0.0% | $4,885 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 10% | 5 | $4,791 | 0.0% | $4,791 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 20% | 3 | $4,937 | 0.0% | $4,937 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 20% | 5 | $4,754 | 0.0% | $4,754 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 30% | 3 | $4,117 | 0.1% | $4,117 | 0.1% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 30% | 5 | $4,059 | 0.5% | $4,059 | 0.5% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 40% | 3 | $3,453 | 3.2% | $3,453 | 3.2% |
| CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 40% | 5 | $3,352 | 5.3% | $3,352 | 5.3% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 3 | $4,614 | 0.0% | $4,614 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 10% | 5 | $4,590 | 0.0% | $4,590 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 3 | $4,560 | 0.0% | $4,560 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 20% | 5 | $4,493 | 0.0% | $4,493 | 0.0% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 3 | $3,297 | 0.5% | $3,297 | 0.5% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 30% | 5 | $3,070 | 1.1% | $3,070 | 1.1% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 3 | $2,612 | 5.2% | $2,612 | 5.2% |
| CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 40% | 5 | $2,522 | 7.3% | $2,522 | 7.3% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 10% | 3 | $5,106 | 0.0% | $5,106 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 10% | 5 | $5,112 | 0.0% | $5,112 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 20% | 3 | $5,173 | 0.0% | $5,173 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 20% | 5 | $5,154 | 0.0% | $5,154 | 0.0% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 30% | 3 | $4,082 | 0.1% | $4,082 | 0.1% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 30% | 5 | $4,078 | 0.2% | $4,078 | 0.2% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 40% | 3 | $3,391 | 2.3% | $3,391 | 2.3% |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 40% | 5 | $3,423 | 2.9% | $3,423 | 2.9% |

## v51's 193 selections at the trade level ($1,000 reference size, TZC costs)

| group | selections | holdout events | median PF 2018-22 | median PF 2023+ | median PF 2016-17 | PF 2016-17 over 1 | trades 2016-17 |
|---|---|---|---|---|---|---|---|
| CRASH-long | 10 | 1,976 | 1.82 | 1.33 | 6.10 | 10 of 10 | 9,926 |
| RUN200-short | 10 | 23 | 33.82 | 4.59 | 1.71 | 9 of 10 | 58 |
| STRONG-short | 10 | 1,493 | 16.11 | 4.77 | 1.70 | 10 of 10 | 64 |
| GAPDN-long | 10 | 830 | 1.74 | 1.20 | 1.49 | 7 of 10 | 4,175 |
| RUNUP-short | 12 | 568 | 14.36 | 2.24 | 99.00 | 12 of 12 | 162 |
| RUN40-short | 10 | 798 | 1.40 | 1.16 | 1.10 | 10 of 10 | 4,522 |
| GAPUP-short | 10 | 618 | 19.09 | 2.06 | 0.54 | 0 of 10 | 90 |
| RUN60-short | 10 | 350 | 1.53 | 1.34 | 1.32 | 9 of 10 | 1,186 |
| RUN100-short | 10 | 113 | 7.92 | 2.01 | 0.36 | 4 of 10 | 182 |
| RUN40-long | 10 | 798 | 1.24 | 1.10 | 1.86 | 10 of 10 | 2,092 |
| FADE-short | 11 | 309 | 3.86 | 1.12 | 1.94 | 11 of 11 | 267 |
| STRONG-long | 10 | 1,493 | 1.50 | 1.06 | 0.90 | 3 of 10 | 943 |
| GAPDN-short | 10 | 830 | 4.66 | 0.40 | 2.04 | 6 of 10 | 40 |
| RUN60-long | 10 | 350 | 1.72 | 0.86 | 1.87 | 10 of 10 | 354 |
| FADE-long | 10 | 309 | 2.10 | 0.93 | 0.73 | 4 of 10 | 201 |
| RUNUP-long | 10 | 568 | 1.27 | 0.89 | 1.37 | 10 of 10 | 655 |
| RUN100-long | 10 | 113 | 3.31 | 0.88 | 1.65 | 10 of 10 | 147 |
| GAPUP-long | 10 | 618 | 1.28 | 0.97 | 0.84 | 3 of 10 | 716 |
| RUN200-long | 10 | 23 | 2.59 | 0.63 | 5.78 | 9 of 10 | 52 |

| id | configuration | PF 2018-22 | PF 2023+ | trades 2016-17 | PF 2016-17 | mean | worst |
|---|---|---|---|---|---|---|---|
| 0 | CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 1.77 | 1.32 | 1094 | 5.35 | 9.1% | -51.6% |
| 1 | CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.76 | 1.36 | 1094 | 5.38 | 9.1% | -51.6% |
| 2 | CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] | 1.75 | 1.31 | 1094 | 5.32 | 9.0% | -51.6% |
| 3 | CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.75 | 1.34 | 1094 | 5.35 | 9.0% | -51.6% |
| 4 | CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 1.85 | 1.30 | 898 | 6.28 | 11.1% | -30.0% |
| 5 | CRASH-long c_1555 d1pm/t0.50/s0.25 [price0-4 str0 dv1 so:all tier:all age:all] | 1.84 | 1.29 | 898 | 6.24 | 11.0% | -30.0% |
| 6 | CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 1.84 | 1.34 | 898 | 6.32 | 11.1% | -48.6% |
| 7 | CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:old] | 1.82 | 1.34 | 979 | 6.08 | 10.2% | -30.0% |
| 8 | CRASH-long c_1555 d1pm/t0.50/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | 1.83 | 1.32 | 898 | 6.29 | 11.0% | -48.6% |
| 9 | CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 1.81 | 1.37 | 979 | 6.12 | 10.2% | -48.6% |
| 10 | RUN200-short r_t15 d5c/t0.00/s0.00 [price0-4 str0 dv1 so:known tier:all age:old] | 42.44 | 4.49 | 5 | 1.18 | 1.7% | -33.4% |
| 11 | RUN200-short r_t15 d5c/t0.50/s0.00 [price0-4 str0 dv1 so:known tier:all age:old] | 40.69 | 4.07 | 5 | 1.18 | 1.7% | -33.4% |
| 12 | RUN200-short r_t15 d5c/t0.00/s0.00 [price0-4 str0 dv1 so:known tier:all age:all] | 36.73 | 5.27 | 7 | 2.66 | 11.1% | -33.4% |
| 13 | RUN200-short r_t15 d5c/t0.50/s0.00 [price0-4 str0 dv1 so:known tier:all age:all] | 35.40 | 4.65 | 7 | 2.73 | 11.6% | -33.4% |
| 14 | STRONG-short c_ah10 d10c/t0.25/s0.00 [price2-4 str0 dv2 so:all tier:hot age:all] | 35.05 | 7.10 | 5 | 1.23 | 3.7% | -79.3% |
| 15 | RUN200-short r_t15 d5c/t0.00/s0.00 [price0-3 str0 dv1 so:known tier:all age:all] | 34.11 | 4.93 | 6 | 2.76 | 13.2% | -33.4% |
| 16 | RUN200-short r_t15 d5c/t0.50/s0.00 [price0-3 str0 dv1 so:known tier:all age:all] | 33.53 | 4.41 | 6 | 2.84 | 13.8% | -33.4% |
| 17 | RUN200-short r_t0 d5c/t0.50/s0.00 [price0-4 str0 dv1 so:known tier:all age:old] | 31.45 | 4.10 | 5 | 1.58 | 5.4% | -33.9% |
| 18 | RUN200-short r_t0 d5c/t0.00/s0.00 [price0-4 str0 dv1 so:known tier:all age:old] | 31.35 | 4.54 | 5 | 1.58 | 5.4% | -33.9% |
| 19 | RUN200-short r_t15 d5c/t0.25/s0.00 [price0-4 str0 dv1 so:known tier:all age:old] | 30.58 | 6.31 | 5 | 0.85 | -1.4% | -33.4% |
| 20 | RUN200-short r_t15 d5c/t0.25/s0.00 [price0-4 str0 dv1 so:known tier:all age:all] | 26.61 | 7.02 | 7 | 1.84 | 5.6% | -33.4% |
| 21 | GAPDN-long o_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:all] | 1.74 | 1.28 | 349 | 1.50 | 0.7% | -21.5% |
| 22 | GAPDN-long o_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv1 so:all tier:nohot age:old] | 1.55 | 0.67 | 561 | 0.66 | -0.7% | -21.9% |
| 23 | GAPDN-long o_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:all] | 1.73 | 1.27 | 349 | 1.49 | 0.7% | -21.5% |
| 24 | STRONG-short c_ah10 d5c/t0.25/s0.00 [price2-4 str0 dv2 so:all tier:hot age:all] | 28.44 | 3.73 | 5 | 1.29 | 4.4% | -75.9% |
| 25 | RUNUP-short c_ah5 d10c/t0.25/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] | 29.87 | 3.84 | 10 | 99.00 | 23.0% | 21.7% |
| 26 | GAPDN-long o_ah0 d1pm/t0.00/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:all] | 1.72 | 1.25 | 349 | 1.49 | 0.7% | -21.5% |
| 27 | GAPDN-long o_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] | 1.46 | 0.72 | 678 | 0.68 | -0.6% | -21.9% |
| 28 | GAPDN-long o_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] | 1.79 | 1.19 | 332 | 1.51 | 0.7% | -21.5% |
| 29 | GAPDN-long o_1555 d1pm/t0.50/s0.00 [price0-4 str0 dv1 so:all tier:nohot age:old] | 1.53 | 0.69 | 561 | 0.66 | -0.7% | -21.9% |
| 30 | GAPDN-long o_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] | 1.79 | 1.20 | 332 | 1.52 | 0.7% | -21.5% |
| 31 | GAPDN-long o_ah0 d1pm/t0.00/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:old] | 1.78 | 1.18 | 332 | 1.51 | 0.7% | -21.5% |
| 32 | GAPDN-long o_ah0 d1pm/t0.50/s0.00 [price1-4 str0 dv0 so:all tier:nohot age:all] | 1.77 | 1.38 | 332 | 1.43 | 0.6% | -21.5% |
| 33 | RUN40-short r_t0 d2c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.39 | 1.10 | 485 | 1.19 | 1.6% | -522.5% |
| 34 | RUN40-short r_t0 d1c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.39 | 1.16 | 485 | 1.03 | 0.3% | -262.8% |
| 35 | RUN40-short r_t0 d1c/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.38 | 1.16 | 485 | 1.09 | 0.9% | -262.8% |
| 36 | RUN40-short r_t0 d1c/t0.00/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.38 | 1.16 | 485 | 1.11 | 1.0% | -262.8% |
| 37 | RUN40-short r_t0 d1c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] | 1.48 | 1.04 | 369 | 1.03 | 0.3% | -262.8% |
| 38 | RUN40-short r_t0 d1c/t0.25/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.41 | 1.16 | 432 | 1.04 | 0.4% | -262.8% |
| 39 | RUN40-short r_t0 d1c/t0.50/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.41 | 1.16 | 432 | 1.10 | 0.9% | -262.8% |
| 40 | RUN40-short r_t0 d1c/t0.00/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.41 | 1.16 | 432 | 1.11 | 1.1% | -262.8% |
| 41 | RUN40-short r_t0 d2c/t0.25/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.40 | 1.10 | 432 | 1.23 | 2.1% | -522.5% |
| 42 | RUN40-short r_t0 d2c/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.35 | 1.11 | 485 | 1.22 | 2.0% | -522.5% |
| 43 | GAPUP-short o_hodf d1m/t0.25/s0.00 [price0-3 str1 dv0 so:u10 tier:nohot age:old] | 20.04 | 2.55 | 9 | 0.54 | -8.7% | -77.8% |
| 44 | GAPUP-short o_hodf d1m/t0.25/s1.00 [price0-3 str1 dv0 so:u10 tier:nohot age:old] | 20.04 | 1.96 | 9 | 0.54 | -8.7% | -77.8% |
| 45 | GAPUP-short o_hodf d1m/t0.50/s0.00 [price0-3 str1 dv0 so:u10 tier:nohot age:old] | 19.09 | 1.96 | 9 | 0.54 | -8.7% | -77.8% |
| 46 | GAPUP-short o_hodf d1m/t0.00/s0.00 [price0-3 str1 dv0 so:u10 tier:nohot age:old] | 19.09 | 2.09 | 9 | 0.54 | -8.7% | -77.8% |
| 47 | GAPUP-short o_hodf d1m/t0.00/s1.00 [price0-3 str1 dv0 so:u10 tier:nohot age:old] | 19.09 | 1.97 | 9 | 0.54 | -8.7% | -77.8% |
| 48 | GAPUP-short o_hodf d1m/t0.50/s1.00 [price0-3 str1 dv0 so:u10 tier:nohot age:old] | 19.09 | 1.85 | 9 | 0.54 | -8.7% | -77.8% |
| 49 | GAPUP-short o_hodf d1m/t0.25/s1.00 [price0-4 str1 dv0 so:u10 tier:nohot age:old] | 15.46 | 2.14 | 9 | 0.54 | -8.7% | -77.8% |
| 50 | GAPUP-short o_hodf d1m/t0.25/s0.00 [price0-4 str1 dv0 so:u10 tier:nohot age:old] | 15.46 | 2.77 | 9 | 0.54 | -8.7% | -77.8% |
| 51 | RUNUP-short c_ah5 d10c/t0.25/s0.00 [price0-4 str2 dv0 so:all tier:all age:all] | 18.13 | 4.27 | 10 | 99.00 | 23.0% | 21.7% |
| 52 | GAPUP-short o_hodf d1m/t0.50/s1.00 [price0-4 str1 dv0 so:u10 tier:nohot age:old] | 14.80 | 2.03 | 9 | 0.54 | -8.7% | -77.8% |
| 53 | GAPUP-short o_hodf d1m/t0.50/s0.00 [price0-4 str1 dv0 so:u10 tier:nohot age:old] | 14.80 | 2.15 | 9 | 0.54 | -8.7% | -77.8% |
| 54 | STRONG-short c_ah10 d5c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:all] | 16.04 | 4.74 | 7 | 1.91 | 9.8% | -75.9% |
| 55 | STRONG-short c_ah10 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:old] | 18.50 | 8.95 | 6 | 1.54 | 7.1% | -79.3% |
| 56 | STRONG-short c_ah10 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:all] | 15.12 | 9.26 | 7 | 1.83 | 9.4% | -79.3% |
| 57 | STRONG-short c_ah10 d5c/t0.25/s0.00 [price2-3 str0 dv1 so:all tier:hot age:all] | 17.75 | 4.80 | 6 | 1.58 | 7.3% | -75.9% |
| 58 | STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] | 13.17 | 0.70 | 2 | 99.00 | 32.5% | 15.8% |
| 59 | STRONG-short c_ah10 d5c/t0.50/s0.00 [price2-4 str0 dv2 so:all tier:hot age:all] | 16.18 | 2.70 | 5 | 1.98 | 14.9% | -75.9% |
| 60 | RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] | 16.79 | 2.52 | 10 | 99.00 | 41.0% | 21.8% |
| 61 | STRONG-short c_ah10 d10c/t0.50/s0.00 [price2-4 str0 dv2 so:all tier:hot age:all] | 15.68 | 5.16 | 5 | 2.05 | 16.7% | -79.3% |
| 62 | STRONG-short c_rl10 d3c/t0.25/s0.00 [price0-3 str1 dv0 so:u50 tier:nohot age:all] | 14.17 | 1.32 | 16 | 1.15 | 1.4% | -74.1% |
| 63 | RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] | 16.51 | 2.54 | 10 | 99.00 | 39.6% | 21.8% |
| 64 | RUN60-short r_t0 d3c/t0.25/s0.00 [price0-3 str0 dv2 so:u10 tier:all age:old] | 15.32 | 1.96 | 11 | 1.12 | 1.7% | -144.9% |
| 65 | RUN60-short r_t0 d2c/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.52 | 1.33 | 199 | 1.34 | 3.7% | -424.5% |
| 66 | RUNUP-short c_1555b d3c/t0.25/s0.00 [price2-3 str0 dv1 so:known tier:all age:all] | 11.56 | 0.99 | 17 | 2.09 | 5.7% | -55.6% |
| 67 | RUN60-short r_t0 d3c/t0.25/s0.00 [price1-3 str0 dv2 so:u10 tier:all age:old] | 14.72 | 1.87 | 10 | 0.99 | -0.1% | -144.9% |
| 68 | RUN100-short r_1555 d2c/t0.25/s0.00 [price2-2 str0 dv2 so:all tier:all age:old] | 13.20 | 2.30 | 10 | 0.30 | -16.1% | -154.4% |
| 69 | RUNUP-short c_1555b d3c/t0.25/s0.00 [price2-3 str0 dv2 so:known tier:all age:all] | 12.57 | 0.99 | 12 | 7.37 | 11.5% | -11.4% |
| 70 | RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv0 so:all tier:all age:all] | 14.04 | 2.89 | 10 | 99.00 | 41.0% | 21.8% |
| 71 | RUN60-short r_t0 d2c/t0.00/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.51 | 1.35 | 199 | 1.36 | 3.9% | -424.5% |
| 72 | RUNUP-short c_1555b d3c/t0.25/s0.00 [price2-3 str0 dv3 so:known tier:hot age:all] | 14.68 | 0.92 | 3 | 99.00 | 15.9% | 10.6% |
| 73 | RUNUP-short c_1555b d3c/t0.25/s0.00 [price2-3 str0 dv3 so:known tier:all age:all] | 14.68 | 0.91 | 3 | 99.00 | 15.9% | 10.6% |
| 74 | RUNUP-short c_1555b d3c/t0.25/s0.00 [price2-3 str0 dv1 so:known tier:hot age:all] | 11.29 | 0.98 | 17 | 2.09 | 5.7% | -55.6% |
| 75 | RUN60-short r_t0 d1c/t0.25/s1.00 [price3-4 str0 dv2 so:all tier:all age:young] | 13.68 | 0.38 | 2 | 99.00 | 24.1% | 24.0% |
| 76 | RUN60-short r_t0 d1c/t0.25/s0.00 [price3-4 str0 dv2 so:all tier:all age:young] | 13.68 | 0.32 | 2 | 99.00 | 24.1% | 24.0% |
| 77 | RUN60-short r_t0 d2c/t0.50/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.54 | 1.32 | 188 | 1.31 | 3.5% | -424.5% |
| 78 | RUN60-short r_t0 d2c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.49 | 1.43 | 199 | 1.25 | 2.7% | -424.5% |
| 79 | RUN60-short r_t0 d2c/t0.25/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.53 | 1.42 | 188 | 1.24 | 2.6% | -424.5% |
| 80 | RUN60-short r_t0 d2c/t0.00/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.53 | 1.33 | 188 | 1.33 | 3.8% | -424.5% |
| 81 | RUN40-long r_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv2 so:all tier:all age:old] | 1.25 | 1.13 | 227 | 2.12 | 2.3% | -22.5% |
| 82 | RUN100-short r_t0 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:all age:all] | 3.57 | 2.41 | 27 | 1.42 | 4.2% | -90.7% |
| 83 | RUN40-long r_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv2 so:all tier:all age:old] | 1.24 | 1.10 | 227 | 2.02 | 2.2% | -22.5% |
| 84 | RUN40-long r_ah0 d1pm/t0.25/s0.00 [price1-4 str0 dv2 so:all tier:all age:old] | 1.26 | 1.10 | 212 | 1.86 | 1.9% | -22.5% |
| 85 | RUN40-long r_ah0 d1pm/t0.50/s0.00 [price1-4 str0 dv2 so:all tier:all age:old] | 1.25 | 1.06 | 212 | 1.77 | 1.8% | -22.5% |
| 86 | RUN100-short r_t0 d10c/t0.25/s0.00 [price1-4 str0 dv1 so:all tier:all age:all] | 2.75 | 2.29 | 40 | 1.74 | 6.2% | -90.7% |
| 87 | FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] | 3.66 | 1.14 | 29 | 2.22 | 3.2% | -11.2% |
| 88 | FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] | 3.62 | 1.12 | 29 | 2.11 | 2.9% | -11.2% |
| 89 | FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] | 3.83 | 1.16 | 23 | 2.64 | 4.1% | -11.2% |
| 90 | FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-2 str0 dv0 so:all tier:all age:all] | 5.34 | 0.93 | 22 | 1.63 | 2.1% | -11.2% |
| 91 | FADE-short c_pm0 d1pm/t0.50/s0.00 [price2-2 str0 dv0 so:all tier:all age:all] | 5.34 | 0.75 | 22 | 1.63 | 2.1% | -11.2% |
| 92 | RUN100-short r_t15 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:all age:all] | 3.29 | 2.16 | 27 | 1.25 | 2.5% | -93.6% |
| 93 | RUN100-short r_pm0 d1pm/t0.50/s0.00 [price2-4 str0 dv1 so:o10 tier:hot age:all] | 10.01 | 0.84 | 6 | 0.16 | -28.3% | -64.5% |
| 94 | RUN100-short r_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv1 so:o10 tier:hot age:all] | 10.01 | 1.28 | 6 | 0.00 | -56.9% | -101.3% |
| 95 | RUN100-short r_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:o10 tier:hot age:all] | 10.01 | 1.26 | 6 | 0.00 | -56.9% | -101.3% |
| 96 | RUN100-short r_pm0 d1pm/t0.00/s0.00 [price2-4 str0 dv1 so:o10 tier:hot age:all] | 10.01 | 0.82 | 6 | 0.16 | -28.3% | -64.5% |
| 97 | RUN100-short r_t0 d10c/t0.25/s0.00 [price0-4 str0 dv1 so:all tier:all age:all] | 2.45 | 2.35 | 44 | 1.99 | 7.6% | -90.7% |
| 98 | FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] | 3.78 | 1.16 | 23 | 2.48 | 3.7% | -11.2% |
| 99 | FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-2 str0 dv0 so:all tier:all age:all] | 5.27 | 0.96 | 22 | 1.59 | 2.0% | -11.2% |
| 100 | FADE-short c_pm0 d1pm/t0.25/s0.00 [price2-2 str0 dv0 so:all tier:all age:all] | 5.27 | 0.77 | 22 | 1.59 | 2.0% | -11.2% |
| 101 | RUN100-short r_t0 d5c/t0.25/s0.00 [price1-3 str0 dv1 so:all tier:nohot age:old] | 5.84 | 1.86 | 10 | 0.41 | -16.7% | -223.9% |
| 102 | RUN40-long r_ah0 d1pm/t0.00/s0.00 [price0-4 str0 dv2 so:all tier:all age:old] | 1.20 | 1.08 | 227 | 2.03 | 2.2% | -22.5% |
| 103 | RUN40-long r_ah0 d1pm/t0.25/s1.00 [price1-4 str0 dv2 so:known tier:all age:old] | 1.32 | 1.10 | 136 | 1.38 | 0.9% | -22.5% |
| 104 | FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] | 3.92 | 1.14 | 28 | 1.90 | 2.5% | -11.2% |
| 105 | RUN40-long r_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv2 so:known tier:all age:old] | 1.28 | 1.14 | 149 | 1.72 | 1.6% | -22.5% |
| 106 | RUN40-long r_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv2 so:all tier:all age:all] | 1.16 | 1.15 | 263 | 1.90 | 2.0% | -30.9% |
| 107 | STRONG-long c_1555 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:all tier:nohot age:old] | 1.37 | 0.92 | 149 | 0.88 | -1.0% | -62.6% |
| 108 | RUN40-long r_ah0 d1pm/t0.25/s0.25 [price0-4 str0 dv2 so:all tier:all age:old] | 1.19 | 1.09 | 227 | 1.86 | 2.0% | -29.5% |
| 109 | RUN40-long r_ah0 d1pm/t0.00/s0.00 [price1-4 str0 dv2 so:all tier:all age:old] | 1.21 | 1.05 | 212 | 1.78 | 1.8% | -22.5% |
| 110 | FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] | 3.86 | 1.12 | 28 | 1.94 | 2.6% | -11.2% |
| 111 | STRONG-long c_1555 d5c/t0.25/s1.00 [price0-4 str0 dv2 so:all tier:nohot age:old] | 1.35 | 0.95 | 149 | 0.76 | -1.9% | -62.6% |
| 112 | STRONG-long c_1555 d10c/t0.25/s0.00 [price1-4 str0 dv3 so:o10 tier:nohot age:all] | 2.09 | 1.25 | 35 | 0.96 | -0.2% | -25.0% |
| 113 | STRONG-long c_1555 d10c/t0.25/s0.00 [price0-4 str0 dv2 so:all tier:nohot age:old] | 1.34 | 0.96 | 149 | 0.87 | -1.1% | -69.9% |
| 114 | STRONG-long c_1555 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:all tier:nohot age:all] | 1.29 | 0.87 | 159 | 0.84 | -1.3% | -62.6% |
| 115 | STRONG-long c_1555 d10c/t0.25/s0.00 [price1-4 str0 dv3 so:o10 tier:nohot age:old] | 2.08 | 1.20 | 33 | 1.07 | 0.3% | -25.0% |
| 116 | STRONG-long c_1555 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:o10 tier:nohot age:all] | 1.49 | 1.06 | 102 | 1.33 | 1.9% | -47.8% |
| 117 | STRONG-long c_1555 d10c/t0.25/s0.00 [price0-4 str0 dv3 so:o10 tier:nohot age:all] | 1.98 | 1.19 | 36 | 0.91 | -0.5% | -25.0% |
| 118 | STRONG-long c_1555 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:o10 tier:nohot age:old] | 1.52 | 1.07 | 97 | 1.49 | 2.7% | -47.8% |
| 119 | STRONG-long c_1555 d10c/t0.25/s0.00 [price2-4 str0 dv3 so:o10 tier:nohot age:all] | 2.17 | 1.25 | 34 | 0.82 | -1.0% | -25.0% |
| 120 | GAPDN-short o_0945 d2c/t0.50/s1.00 [price3-4 str0 dv3 so:all tier:all age:old] | 5.28 | 0.00 | 1 | 0.00 | -11.8% | -11.8% |
| 121 | GAPDN-short o_0945 d2c/t0.00/s1.00 [price3-4 str0 dv3 so:all tier:all age:old] | 5.17 | 0.00 | 1 | 0.00 | -11.8% | -11.8% |
| 122 | GAPDN-short o_0945 d2c/t0.50/s0.00 [price3-4 str0 dv3 so:all tier:nohot age:old] | 5.13 | 0.00 | 1 | 0.00 | -11.8% | -11.8% |
| 123 | GAPDN-short o_0945 d2c/t0.00/s1.00 [price3-4 str0 dv3 so:all tier:nohot age:all] | 5.02 | 0.00 | 1 | 0.00 | -11.8% | -11.8% |
| 124 | GAPDN-short o_0931 d2c/t0.50/s0.00 [price3-4 str0 dv3 so:all tier:all age:all] | 4.66 | 0.66 | 6 | 2.04 | 5.4% | -18.4% |
| 125 | GAPDN-short o_0931 d2c/t0.50/s0.00 [price3-4 str0 dv3 so:all tier:all age:old] | 4.66 | 0.40 | 6 | 2.04 | 5.4% | -18.4% |
| 126 | GAPDN-short o_0931 d2c/t0.00/s1.00 [price3-4 str0 dv3 so:all tier:all age:all] | 4.56 | 0.66 | 6 | 2.19 | 6.2% | -18.4% |
| 127 | GAPDN-short o_0931 d2c/t0.00/s0.00 [price3-4 str0 dv3 so:all tier:all age:old] | 4.56 | 0.40 | 6 | 2.19 | 6.2% | -18.4% |
| 128 | GAPDN-short o_0931 d2c/t0.50/s0.00 [price3-4 str0 dv3 so:all tier:nohot age:all] | 4.53 | 0.66 | 6 | 2.04 | 5.4% | -18.4% |
| 129 | GAPDN-short o_0931 d2c/t0.50/s1.00 [price3-4 str0 dv3 so:all tier:nohot age:old] | 4.53 | 0.40 | 6 | 2.04 | 5.4% | -18.4% |
| 130 | RUN60-long r_ah0 d1m/t0.00/s0.00 [price0-2 str0 dv1 so:o10 tier:nohot age:old] | 1.81 | 0.86 | 30 | 2.33 | 6.5% | -36.0% |
| 131 | RUN60-long r_ah0 d1m/t0.00/s0.25 [price0-2 str0 dv1 so:o10 tier:nohot age:old] | 1.79 | 0.91 | 30 | 2.28 | 6.4% | -26.8% |
| 132 | RUN60-long r_1555 d1m/t0.00/s0.25 [price0-1 str0 dv1 so:all tier:nohot age:old] | 1.74 | 0.71 | 42 | 1.18 | 1.2% | -28.8% |
| 133 | RUN60-long r_1555 d1m/t0.00/s0.25 [price0-2 str0 dv1 so:o10 tier:nohot age:old] | 1.70 | 0.86 | 37 | 1.89 | 4.2% | -28.8% |
| 134 | RUN60-long r_ah0 d1m/t0.00/s0.00 [price0-2 str0 dv0 so:o10 tier:nohot age:old] | 1.57 | 0.95 | 38 | 1.85 | 4.5% | -36.0% |
| 135 | RUN60-long r_ah0 d1m/t0.00/s0.00 [price0-3 str0 dv1 so:o10 tier:nohot age:old] | 1.63 | 0.80 | 37 | 2.07 | 5.0% | -36.0% |
| 136 | RUN60-long r_ah0 d1m/t0.00/s0.00 [price0-4 str0 dv1 so:o10 tier:nohot age:old] | 1.57 | 0.80 | 44 | 1.99 | 4.1% | -36.0% |
| 137 | RUN60-long r_1555 d1m/t0.00/s0.25 [price0-1 str0 dv1 so:o10 tier:nohot age:old] | 2.25 | 0.90 | 25 | 1.34 | 1.9% | -28.8% |
| 138 | RUN60-long r_ah0 d1m/t0.00/s0.25 [price0-1 str0 dv1 so:all tier:nohot age:old] | 1.76 | 0.83 | 33 | 1.22 | 1.7% | -29.5% |
| 139 | RUN60-long r_ah0 d1m/t0.00/s0.25 [price0-2 str0 dv0 so:o10 tier:nohot age:old] | 1.54 | 1.01 | 38 | 1.82 | 4.4% | -26.8% |
| 140 | FADE-long c_1030 d1pm/t0.00/s1.00 [price1-3 str1 dv2 so:all tier:all age:all] | 2.33 | 0.87 | 16 | 1.20 | 0.7% | -19.6% |
| 141 | FADE-long c_orb d1pm/t0.00/s0.00 [price1-4 str0 dv2 so:all tier:all age:all] | 1.95 | 0.94 | 21 | 0.52 | -1.9% | -20.6% |
| 142 | FADE-long c_1030 d1pm/t0.00/s0.00 [price0-3 str1 dv2 so:all tier:hot age:all] | 2.17 | 0.77 | 17 | 0.69 | -1.7% | -40.4% |
| 143 | RUNUP-long c_ah5 d1o/t0.00/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] | 1.31 | 0.90 | 73 | 1.45 | 2.3% | -29.9% |
| 144 | FADE-long c_1030 d1pm/t0.00/s0.00 [price2-3 str1 dv2 so:all tier:all age:all] | 2.76 | 0.84 | 11 | 4.54 | 4.6% | -13.8% |
| 145 | RUNUP-long c_ah5 d1o/t0.00/s0.00 [price0-3 str0 dv0 so:all tier:all age:old] | 1.33 | 0.82 | 66 | 1.72 | 3.3% | -29.9% |
| 146 | FADE-long c_orb d1pm/t0.00/s1.00 [price1-3 str0 dv2 so:all tier:all age:all] | 2.03 | 0.91 | 19 | 0.35 | -2.8% | -20.6% |
| 147 | RUNUP-long c_ah5 d1o/t0.00/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | 1.27 | 0.83 | 68 | 1.62 | 2.9% | -29.9% |
| 148 | RUNUP-long c_ah5 d1o/t0.00/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | 1.24 | 0.89 | 76 | 1.35 | 1.9% | -29.9% |
| 149 | FADE-long c_orb d1pm/t0.00/s0.25 [price1-4 str0 dv2 so:all tier:all age:all] | 1.85 | 0.90 | 21 | 0.37 | -3.5% | -26.8% |
| 150 | FADE-long c_1030 d1pm/t0.00/s1.00 [price1-4 str0 dv2 so:all tier:all age:all] | 1.47 | 0.96 | 39 | 0.76 | -0.7% | -19.6% |
| 151 | FADE-long c_1030 d1pm/t0.00/s0.25 [price1-3 str0 dv2 so:all tier:all age:all] | 1.56 | 0.96 | 37 | 0.59 | -1.6% | -26.6% |
| 152 | FADE-long c_1200 d1pm/t0.00/s0.00 [price2-3 str0 dv0 so:all tier:all age:young] | 3.39 | 1.29 | 10 | 1.86 | 1.6% | -5.3% |
| 153 | FADE-long c_1200 d1pm/t0.00/s0.25 [price2-3 str0 dv0 so:all tier:all age:young] | 3.39 | 1.31 | 10 | 1.86 | 1.6% | -5.3% |
| 154 | RUNUP-long c_ah5 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:hot age:all] | 1.27 | 1.02 | 66 | 1.26 | 1.2% | -29.9% |
| 155 | RUNUP-long c_ah5 d1o/t0.00/s1.00 [price0-3 str0 dv1 so:all tier:all age:all] | 1.30 | 0.86 | 59 | 1.39 | 2.1% | -27.2% |
| 156 | RUNUP-long c_ah5 d1o/t0.00/s0.00 [price0-3 str0 dv1 so:all tier:all age:old] | 1.33 | 0.82 | 53 | 1.65 | 3.1% | -26.5% |
| 157 | RUNUP-long c_ah5 d1pm/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:hot age:all] | 1.27 | 1.03 | 66 | 1.26 | 1.2% | -29.9% |
| 158 | RUN100-long r_ah0 d1o/t0.00/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:old] | 1.68 | 0.79 | 22 | 2.07 | 6.2% | -55.6% |
| 159 | RUNUP-long c_ah5 d1o/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:hot age:all] | 1.26 | 0.97 | 66 | 1.19 | 1.1% | -29.9% |
| 160 | RUNUP-long c_ah5 d1o/t0.25/s0.00 [price0-4 str0 dv1 so:all tier:all age:all] | 1.25 | 1.06 | 62 | 1.28 | 1.6% | -27.2% |
| 161 | RUN100-long r_ah0 d1m/t0.00/s0.25 [price0-4 str0 dv0 so:all tier:nohot age:old] | 1.66 | 0.84 | 22 | 1.42 | 3.8% | -55.6% |
| 162 | RUN100-long r_ah0 d1m/t0.00/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] | 1.66 | 0.84 | 22 | 1.67 | 5.2% | -55.8% |
| 163 | RUN100-long r_ah0 d1o/t0.00/s0.00 [price0-0 str0 dv0 so:all tier:nohot age:all] | 3.93 | 1.06 | 4 | 2.97 | 7.8% | -8.8% |
| 164 | RUN100-long r_1555 d1o/t0.00/s0.00 [price0-0 str0 dv0 so:all tier:nohot age:all] | 3.68 | 0.92 | 4 | 1.49 | 1.8% | -9.2% |
| 165 | RUN100-long r_ah0 d1m/t0.00/s0.25 [price0-0 str0 dv0 so:all tier:nohot age:all] | 3.85 | 0.97 | 4 | 1.64 | 5.3% | -26.2% |
| 166 | RUN100-long r_1555 d1o/t0.00/s0.25 [price0-0 str0 dv0 so:all tier:nohot age:all] | 3.63 | 0.99 | 4 | 1.49 | 1.8% | -9.2% |
| 167 | RUN100-long r_ah0 d1o/t0.00/s0.25 [price0-0 str0 dv0 so:all tier:nohot age:all] | 3.80 | 1.15 | 4 | 1.41 | 3.4% | -26.2% |
| 168 | RUN100-long r_1555 d1m/t0.00/s0.25 [price0-1 str0 dv1 so:all tier:nohot age:old] | 3.00 | 0.41 | 7 | 2.43 | 7.7% | -25.9% |
| 169 | RUN100-long r_ah0 d1o/t0.00/s0.00 [price0-4 str0 dv1 so:all tier:all age:old] | 1.28 | 0.72 | 54 | 2.85 | 8.3% | -29.9% |
| 170 | GAPUP-long o_pm10 d1pm/t0.25/s0.00 [price0-1 str0 dv0 so:known tier:nohot age:old] | 1.88 | 0.91 | 12 | 0.84 | -1.0% | -33.5% |
| 171 | GAPUP-long o_pm10 d1pm/t0.25/s0.00 [price0-1 str0 dv0 so:known tier:nohot age:all] | 1.73 | 0.90 | 12 | 0.84 | -1.0% | -33.5% |
| 172 | GAPUP-long o_orb d10c/t0.25/s0.25 [price1-4 str0 dv2 so:all tier:nohot age:old] | 1.21 | 0.95 | 88 | 0.67 | -2.9% | -27.7% |
| 173 | GAPUP-long o_vwap d1pm/t0.25/s0.00 [price2-3 str0 dv1 so:o10 tier:nohot age:old] | 1.29 | 1.02 | 83 | 1.46 | 1.1% | -14.0% |
| 174 | GAPUP-long o_vwap d1pm/t0.25/s0.00 [price2-3 str0 dv0 so:o10 tier:nohot age:old] | 1.24 | 0.99 | 99 | 1.21 | 0.6% | -30.3% |
| 175 | GAPUP-long o_0931 d1m/t0.00/s0.25 [price4-4 str2 dv1 so:known tier:all age:old] | 3.27 | 0.67 | 7 | 0.84 | -0.4% | -7.5% |
| 176 | GAPUP-long o_vwap d1pm/t0.25/s0.00 [price2-4 str0 dv1 so:o10 tier:nohot age:old] | 1.20 | 1.01 | 148 | 1.07 | 0.2% | -14.0% |
| 177 | GAPUP-long o_vwap d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:o10 tier:nohot age:old] | 1.17 | 0.99 | 167 | 0.96 | -0.1% | -30.3% |
| 178 | GAPUP-long o_vwap d1pm/t0.25/s0.00 [price2-4 str0 dv2 so:o10 tier:nohot age:old] | 1.27 | 0.83 | 91 | 0.72 | -0.8% | -14.0% |
| 179 | GAPUP-long o_pm10 d1pm/t0.25/s0.00 [price0-1 str0 dv0 so:o10 tier:nohot age:all] | 1.77 | 1.20 | 9 | 0.37 | -5.3% | -33.5% |
| 180 | RUN200-long r_ah0 d1o/t0.25/s1.00 [price0-4 str0 dv2 so:known tier:hot age:all] | 2.88 | 0.60 | 4 | 5.78 | 10.4% | -8.7% |
| 181 | RUN200-long r_ah0 d1o/t0.25/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] | 2.60 | 0.68 | 4 | 5.78 | 10.4% | -8.7% |
| 182 | RUN200-long r_ah0 d1o/t0.00/s1.00 [price0-4 str0 dv2 so:known tier:all age:all] | 2.56 | 0.43 | 4 | 6.13 | 11.1% | -8.7% |
| 183 | RUN200-long r_ah0 d1o/t0.50/s0.00 [price0-4 str0 dv2 so:known tier:all age:old] | 2.68 | 0.67 | 4 | 6.13 | 11.1% | -8.7% |
| 184 | RUN200-long r_ah0 d1o/t0.50/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] | 2.55 | 0.70 | 4 | 6.13 | 11.1% | -8.7% |
| 185 | RUN200-long r_ah0 d1o/t0.25/s1.00 [price0-4 str0 dv2 so:known tier:all age:old] | 2.64 | 0.69 | 4 | 5.78 | 10.4% | -8.7% |
| 186 | RUN200-long r_ah0 d1o/t0.25/s0.00 [price1-4 str0 dv2 so:known tier:all age:all] | 2.70 | 0.62 | 4 | 5.78 | 10.4% | -8.7% |
| 187 | RUN200-long r_ah0 d1o/t0.00/s0.00 [price0-4 str0 dv0 so:o10 tier:all age:old] | 1.90 | 0.63 | 7 | 0.75 | -1.8% | -33.5% |
| 188 | RUN200-long r_ah0 d1o/t0.00/s1.00 [price0-4 str0 dv2 so:known tier:all age:old] | 2.57 | 0.41 | 4 | 6.13 | 11.1% | -8.7% |
| 189 | RUN200-long r_ah0 d1o/t0.00/s1.00 [price0-4 str0 dv0 so:all tier:all age:old] | 1.43 | 0.60 | 13 | 3.62 | 14.0% | -33.5% |
| 190 | RUNUP-short c_open d5c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] v50:DS1 | 2.22 | 1.97 | 30 | 4.38 | 16.0% | -51.8% |
| 191 | RUNUP-short c_open d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] v50:RU | 2.67 | 3.45 | 30 | 7.60 | 20.0% | -38.1% |
| 192 | FADE-short c_1555 d3c/t0.00/s0.00 [price2-2 str0 dv1 so:all tier:all age:all] v50:NS | 3.36 | 2.13 | 19 | 2.20 | 3.6% | -14.2% |
