# v61 pre-registration: most dollars when ruin means losing the account

Written 2026-11-14, before the run, on the owner's request: ruin is losing 100% instead of 75%, the ruin limit is
10% instead of 5%, and the goal is the book with the most dollars.

## Definitions

- Ruin: equity at or under $50 (1% of $5,000) at any point of the one-year path. At $50 the account cannot trade
  and the $6 monthly fee empties it; a path only reaches exactly $0 through a single day's loss of 100% or more.
- Also reported for every book: chance of losing 75% (the old ruin), chance of losing 50%, the mean end equity.

## Engine

v58's engine unchanged: TZC costs, IEX 15:50 decision, the tzi margin rule (v60m: the rule does not change the
result), 2:1 gross and the 15:45 2:1 rule, N5, 31 seeds, 4,000 one-year block-bootstrap paths from $5,000.
Locate worlds W0 (optimistic), F0C1 (central), F1C1 (pessimistic).

## Grid, 80 books

DS1 {0.10, 0.20, 0.30, 0.45} x NS {0.60, 0.80, 1.00, 1.25, 1.50} x RU {0.25, 0.35, 0.50, 0.70}.
Control: DS0.20-NS0.60-RU0.25 (the bot's sizes; v56 W0 $13,041).

## Choice, fixed now

Per world, eligible books have ruin at most 10% on 2018-2022 paths and on 2023-2026 paths, at base costs and at
HOT5. v60m showed that a size can look safe on one period and ruin half the paths on the other, so the limit holds
in each. Among eligible books the choice is the highest all-years median. The central world F0C1 decides; W0 and
F1C1 show how much the choice depends on locate costs.

## Caveats, stated now

- Every year 2018-2026 has been seen by earlier studies, so the choice is in-sample; there is no untouched period
  left to grade it on.
- A book within the 10% limit can still have a large chance of losing 75% in a year; that number is reported next
  to it and the owner decides with it in view.
