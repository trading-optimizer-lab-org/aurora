# v30 results: one $5,000 account (A) or $2,500 at full risk with a $2,500 reserve (B)

Pre-registration: [V30_PREREGISTRATION.md](V30_PREREGISTRATION.md). Run 40120558984 (2026-10-24, 42 jobs, all
succeeded). Full report: the `v30-report` artifact; numbers in [data/v30_summary.json](data/v30_summary.json).

## The question (section 4)

B_best (B) against A1 (A), one year: higher median **no**, smaller tail **no**, no more 80% losses **no**.
**B is not better than A, and B does not avoid the tail.**

## Main numbers (base costs, total wealth W from $5,000)

| book | rule | horizon | median W | p10 | W <= $1k | debt | worst 5% mean | deposit |
|---|---|---|---|---|---|---|---|---|
| A1 (risk 2%, cap 20%) | A | 1y | $12,831 | $4,482 | 0.0% | 0.0% | $2,569 | - |
| A1 | B | 1y | $7,618 | $4,494 | 0.0% | 0.0% | $3,692 | 0.1% |
| B_best (risk 4%, cap 40%, 10 open) | B | 1y | $12,502 | $3,820 | 2.1% | 1.2% | $1,075 | 19.9% |
| B_max (risk 4%, cap 40%, 20 open) | B | 1y | $9,353 | $2,503 | 6.2% | 4.3% | -$3,008 | 30.3% |
| A1 | A | 3y | $93,434 | $16,856 | 0.2% | 0.0% | $5,003 | - |
| B_best | B | 3y | $86,350 | -$786 | 17.4% | 13.8% | -$50,729 | 39.1% |

- v29 check: A1 with v29's path rule gives median $12,831 and ruin 0.5%, as v29.
- B_best's median ($12,502) is just under A1's; its tail is worse, and it can end in debt. The full-risk books
  carry a real chance of debt in this model (B_max 4.3% in a year, 24% in three years).
- With A1's book, B's reserve barely matters (deposit 0.1%) and halving the trading capital halves the growth.

## Caveat that v31 addresses

The model has no forced liquidation by the broker: a short keeps losing for days past the account's size, which
gives debts of millions in the worst three-year paths. Those extremes are not realistic. v31
([V31_PREREGISTRATION.md](V31_PREREGISTRATION.md)) adds the broker's liquidation and asks the same question.
