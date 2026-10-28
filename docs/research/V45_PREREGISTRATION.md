# v45: the five best small-cap strategies alone, on one yardstick

Written 2026-10-28, before any v45 output exists. Descriptive study: no pass marks, nothing is chosen.

## Question

How do the book and its candidate pieces compare when each runs alone in the same $5,000 TradeZero International
account? Earlier figures mix yardsticks (family Sortino at R3 costs, account medians with sizes), so they cannot be
put side by side.

## Strategies (fixed now)

| id | strategy | members and size (cap; risk to the stop = cap / 10) | plan |
|---|---|---|---|
| BOOK | v39's robust book | v19:DS1 20%, v20:RU 70%, v20:NS 40% | FREE ($6 a month) |
| DS1 | run-up short, daily | v19:DS1 20% | FREE |
| RU | run-up short, daily | v20:RU 70% | FREE |
| NS | v20's NS | v20:NS 40% | FREE |
| XS1 | intraday gap-up short held to the 3rd close | v19:XS1 20% (its A28 picks, v29's PAID stops) | PAID ($105 a month) |
| RU20 | RU at equal size | v20:RU 20% | FREE |
| NS20 | NS at equal size | v20:NS 20% | FREE |

DS1, RU and NS are v33's limit members (run 40192951586, `arms.json`), as in v38/v39. XS1 is taken from v29's PAID
members (A28's intraday picks of the family v19:XS1). The book's sizes are kept for each member alone; RU20 and NS20
add the members at XS1's and DS1's 20%.

## Engine (unchanged)

v38/v39's daily engine: TradeZero International costs and locate tiers (v29), the book's joint caps (v33), v31's
forced liquidation at 15% equity, the five equity levels, 4,000 one-year bootstrap paths from $5,000 with the plan's
fixed cost a month, ruin = at or under $1,250 at any time. Cost sets: base, HOT 5%, spreads x2, high.

## Reported for each strategy

Median, ruin, p10, chance of -50%, 2018-2022 and 2023+ medians (base costs); the three stress medians and ruins; and
on the historical path at the $10,000 level: monthly Sortino (mean over downside deviation, annualised by sqrt 12),
CAGR, maximum drawdown and the worst day.

## Check

BOOK must reproduce v39's $23,143 median and 0.1% ruin within $200 and 0.2 points; otherwise the report says so and
the table is not used.

## Caveats fixed now

Every year 2018-2026 has been seen and all five were chosen on them, so the figures rank in-sample results. The
daily engine models the book's fills at auctions; v43 found the minute replay $1,137 lower for the book. HOT locate
costs are assumed as in v29.
