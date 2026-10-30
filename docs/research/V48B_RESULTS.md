# v48b results: the RU size dial under TradeZero API rules, and the capital plans

Run 41089499095, 2026-10-30. Pre-registration: `V48B_PREREGISTRATION.md`. Both checks reproduced (base seed 0 vs v47
TZA; RU 0.70 at 5 a day vs v48).

## Definitive strategy (pre-registered rules)

**Book DS1 0.20, NS 0.40, RU 0.30, at most 5 new positions a day, under the API rules. Capital plan A ($5,000 in one
account).**

| measure (TZA, ensemble of 31 seeds) | value |
|---|---|
| median after one year from $5,000 | $14,411 (seed 0 $15,689) |
| ruin (at or under $1,250) | 1.0%, p90 over seeds 2.5% |
| 2018-2022 / 2023+ paths | $16,221 / 0.7%; $12,039 / 1.6% |
| HOT 5% | $13,917 / 1.0% |
| plan A, one year: median / p10 / W <= $1,000 / es5 | $14,410 / $6,344 / 0.5% / $3,574 |
| plan A, three years | $110,177 / $30,565 / 0.7% / $13,666 |

## The dial under API rules

| RU | ens median | ens ruin | p90 | 2023+ |
|---|---|---|---|---|
| 0.70 (N5) | $18,765 | 7.7% | 15.8% | $12,065 / 17.4% |
| 0.50 | $16,502 | 6.8% | 13.4% | $11,760 / 16.5% |
| 0.40 | $15,201 | 7.1% | 15.6% | $11,392 / 17.0% |
| **0.30** | **$14,411** | **1.0%** | **2.5%** | **$12,039 / 1.6%** |
| 0.25 | $13,929 | 0.4% | 0.1% | $11,915 / 1.0% |
| 0.20 | $13,385 | 0.0% | 0.1% | $11,848 / 0.0% |
| 0.15 | $12,763 | 0.0% | 0.1% | $11,598 / 0.0% |

Ruin drops from about 7% to 1% between RU 0.40 and 0.30. On 2023+ paths RU 0.30 has the same median as RU 0.70
($12.0k) with 1.6% ruin instead of 17.4%: the larger RU sizes only pay on 2018-2022.

## Capital plans for the chosen book (base costs)

| plan | 1y median | p10 | W <= $1,000 | es5 | deposits | 3y median | 3y p10 |
|---|---|---|---|---|---|---|---|
| A $5,000 | $14,410 | $6,344 | 0.5% | $3,574 | - | $110,177 | $30,565 |
| B $2,500 + $2,500 reserve | $9,371 | $5,475 | 0.0% | $4,179 | 0.8% | $58,067 | $16,096 |
| C $2,000 | $5,363 | $2,231 | 1.6% | $1,268 | - | $42,771 | $9,685 |

B has a better tail but a lower median (half the money works for the year in 99% of paths), so A stays (v30's
rule; v30 found the same).

## Caveats

- Every year 2018-2026 was seen; v32-v39, v48 and v48b chose sizes on them.
- Three-year medians compound past the top level ($60,000); the book's returns above it reuse the $60,000 level and
  the 1% of dollar volume cap, which likely overstate growth at large equity.
- The 2:1 rule at 15:45 is measured, not enforced. The dropout ensemble is one model of which trades fill.
