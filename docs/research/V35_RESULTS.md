# v35 results: growing the limit book

Pre-registration: [V35_PREREGISTRATION.md](V35_PREREGISTRATION.md). Target (owner's): one-year median at least
$30,000 from $5,000 with ruin at most 2.5%, base costs.

## Phase 0: diagnostic (run 40304857801; data/v35_diag.json)

Limit members at 30%, $5k level:

- The account is mostly empty: mean gross 0.31x of 2x, 1.6 positions open on average, no position on 40% of
  sessions. The caps never bind: gross 3x, 5 new or 40 open add 0-9 trades of 1,178, and the trades left out lose
  (PF 0.84).
- The real weight a position is 0.18-0.20, not 30% (borrow availability x0.8 and the 1% of dollar volume limit).
- By member: DS1 319 trades PF 2.89 (most of the gain), RU 71 PF 8.25, NS 399 PF 1.71, ON1 354 PF 1.13 (little
  gain, trades of -154% / -137%), SYMPATHY 35 PF 0.53.
- The tail is single-name squeezes, mostly HOT: 2020-06-16 one DS1 trade at -192% made a -53% session, -76% with
  the broker's liquidation.

## Phase 1: account levers (run 40307069098; data/v35_summary.json)

**Target not met.** Choice on 2018-2022 paths: 20% under $10k, 30% from $10k, base caps, single limit: median
$12,137, ruin 0.1% (2018-22 $10,776, 2023+ $13,647). v34's 30% book has ruin 2.8% on 2018-2022 paths, so it is not
eligible there.

- Caps: no effect (as phase 0 showed).
- Size from $10k above 30% lowers the median (30/35/40/50%: $17.4k/$15.3k/$14.6k/$13.2k with 30% below $10k).
- Entry ladders lower the median by about half ($8.3-9.0k at best): fewer fills, smaller positions.
- In-sample best of all 384 books with ruin <= 2.5% on all paths is still v34's book: $17,409.

## Phase 2: intraday members from a threshold (run 40309845908; data/v35_phase2.json)

**Target not met.** Choice: never add them. Adding v29's PAID intraday members from $10k lowers the median to
$9,854 (2023+ $9,732); from $25k $12,026, about the same as without them. The intraday members do not pay their
costs and the $105 data fee in this account.

## Verdict

**v35 does not reach a median of $30,000 with ruin <= 2.5%.** No pre-registered lever on these members (size
schedule, caps, entry ladder, intraday members) beats v34's limit book at 30% ($17,409, ruin 2.1% on all paths,
2.8% on 2018-2022 paths). The account holds 0.3x gross on average: the members give too few independent trades,
and one squeeze can cost a third of the account.
