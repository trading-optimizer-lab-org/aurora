# v45 results: the five best small-cap strategies alone, on one yardstick

Run 40681742435 (28 jobs + final, all succeeded). Full tables in the artifact `v45-report` (V45_REPORT.md).
Descriptive study: nothing is chosen. Check: BOOK reproduces v39's median $23,143 and ruin 0.1%.

## Data

Bootstrap from $5,000, one year, base costs (ruin = at or under $1,250 at any time):

| id | strategy | plan | median | ruin | p10 | -50% | 2018-22 | 2023+ | HOT 5% | high costs |
|---|---|---|---|---|---|---|---|---|---|---|
| BOOK | DS1 20% + RU 70% + NS 40% | FREE | $23,143 | 0.1% | $8,319 | 4.6% | $23,442 | $20,989 | $16,941 / 0.5% | $10,683 / 2.5% |
| DS1 | run-up short, 20% | FREE | $7,951 | 0.0% | $4,889 | 2.5% | $7,493 | $8,681 | $7,201 / 0.1% | $6,034 / 0.2% |
| RU | run-up short, 70% | FREE | $6,008 | 37.8% | $364 | 55.9% | $9,813 | $2,833 | $4,935 / 40.8% | $3,084 / 47.3% |
| NS | NS, 40% | FREE | $7,373 | 0.3% | $4,017 | 5.6% | $7,540 | $7,168 | $6,263 / 0.6% | $5,310 / 1.9% |
| XS1 | intraday gap-up short to d3, 20% | PAID | $3,759 | 0.0% | $2,720 | 6.3% | $4,200 | $3,252 | $3,289 / 0.0% | $2,877 / 0.2% |
| RU20 | RU, 20% | FREE | $7,693 | 0.0% | $4,644 | 4.0% | $7,339 | $8,326 | $7,245 / 0.1% | $6,176 / 0.2% |
| NS20 | NS, 20% | FREE | $6,171 | 0.0% | $4,459 | 0.2% | $6,162 | $6,130 | $5,625 / 0.0% | $5,142 / 0.0% |

Historical path at the $10,000 level's returns, base costs:

| id | monthly Sortino | CAGR | max drawdown | worst day | trades |
|---|---|---|---|---|---|
| BOOK | 7.47 | 347.9% | -70.4% | -41.0% | 1,009 |
| DS1 | 3.96 | 74.4% | -59.4% | -40.9% | 348 |
| RU | 1.33 | 4.4% | -98.8% | -82.1% | 230 |
| NS | 1.69 | 36.6% | -69.6% | -29.1% | 431 |
| XS1 | -0.02 | -2.0% | -49.3% | -12.8% | 1,490 |
| RU20 | 3.35 | 59.3% | -52.8% | -33.5% | 230 |
| NS20 | 1.72 | 21.5% | -44.7% | -14.6% | 431 |

## Inference

- The book is far better than any piece alone: its median is about three times the best single member's (DS1
  $7,951). The members' losing days do not coincide fully, and the book's joint caps (gross, open and new positions)
  hold RU's 70% back when other members are open; alone at 70% RU is ruinous (ruin 37.8%, worst day -82%).
- At equal 20% size, DS1 and RU are close (median $7,951 vs $7,693, both ruin 0.0-0.1%); NS is weaker ($6,171).
- XS1 loses money in the $5,000 account: the PAID plan's $105 a month is about 25% of the account a year and its
  edge a trade does not cover it (median $3,759, historical CAGR -2.0%). It is also excluded by the owner's
  constraint of a fully automated bot without paid data.
- The historical CAGRs are at fixed $10,000-level returns over 2018-2026 and are not reachable at scale; use the
  bootstrap medians for one year from $5,000.

## Caveats

- Every year 2018-2026 has been seen and all strategies were chosen on them: in-sample ranking.
- Daily engine: v43's minute replay put the book $1,137 lower ($22,006).
- HOT locate cost as assumed in v29; at HOT 5% the book's median falls to $16,941.
