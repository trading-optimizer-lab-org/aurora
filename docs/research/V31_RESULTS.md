# v31 results: v30 with the broker's forced liquidation

Pre-registration: [V31_PREREGISTRATION.md](V31_PREREGISTRATION.md). Run 40122462692 (2026-10-24, all 75 jobs
succeeded). Full report: the `v31-report` artifact; numbers in [data/v31_summary.json](data/v31_summary.json).

## The question

B_best against A1, one year: higher median **no**, smaller tail **yes**, no more 80% losses **no**.
**B is not better than A; B does not avoid the tail.**

| book | rule | median W 1y | p10 | W <= $1k | debt | worst 5% mean | deposit |
|---|---|---|---|---|---|---|---|
| A1 (risk 2%, cap 20%, 20 open, gross 2) | A | $12,831 | $4,482 | 0.0% | 0.0% | $2,569 | - |
| B_best (risk 2%, cap 20%, 10 open, gross 1, gate) | B | $8,312 | $4,012 | 0.4% | 0.0% | $2,756 | 8.8% |
| B_max (risk 4%, cap 40%) | B | $6,418 | $2,007 | 6.8% | 0.0% | $383 | 31.9% |
| B_max without the rule (v30) | B | $9,353 | $2,503 | 6.2% | 4.3% | -$3,008 | 30.3% |

- With the rule, debts disappear, but full risk gets worse, not better: forced closes at the session's worst moment
  lock in losses that v30 let recover. B_max is liquidated 10 times in the stream; its median falls from $9,353 to
  $6,418.
- Under the rule the best book for B is no longer full risk: it is A1's sizing with fewer positions and gross 1x.
- A1 is never liquidated at θ = 15% (4 times at θ = 30%, median $9,926).
