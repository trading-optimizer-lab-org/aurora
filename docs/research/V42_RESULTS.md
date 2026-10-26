# v42 results: a long small-cap sleeve beside v39's best book

Pre-registration: [V42_PREREGISTRATION.md](V42_PREREGISTRATION.md). Run 40371046574 (2026-10-26; one runner of 4
CPUs, all 19 variants). Numbers in [data/v42_summary.json](data/v42_summary.json). The base book reproduces v39
($23,143, ruin 0.1%).

**v42 does not improve the book** (growth test and hedge test both fail).

| book | base costs | HOT 5% | spreads x2 | high costs |
|---|---|---|---|---|
| base book | $23,143 / 0.1% | $16,941 / 0.5% | $19,033 / 0.4% | $10,683 / 2.5% |
| walk-forward | $22,493 / 0.1% | $16,562 / 0.5% | $18,347 / 0.4% | $10,340 / 2.7% |

The walk-forward choice keeps the base book every year except 2019, so the two books are almost the same. On the
historical path both have the same worst 21 sessions (-53.2%) and maximum drawdown (-70.3%).

## Why (in-sample, all years; not a result)

Every long sleeve loses money on its own: all 18 lose almost all of their capital over 2018-2026 (growth x 0.00-0.01).
In the shorts' worst 5% of sessions the sleeves gain only +0.1% to +1.7% a session, far too little to offset what they
lose the rest of the time. Added to the book, every variant lowers the median ($15.5k at best, $146 at worst) and
raises ruin. Gating on runner euphoria loses less than trading always, but still loses.

## Reading

Small-cap momentum longs after the close on daily data have no edge in this sample, as v24 found with one-minute
entries. They do not hedge the short book: the squeezes that hurt the shorts are not captured by buying breakouts,
bursts or runners at the close. DS1 20% RU 70% NS 40% stays the best book.
