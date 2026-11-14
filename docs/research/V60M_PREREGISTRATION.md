# v60m pre-registration: does the short margin rule cap what a bigger size can earn?

Written 2026-11-14, before the run. Diagnostic only: it chooses no book and changes nothing in the bot.

## Why

In v58 and v60 a much larger size barely lifts the median (DS0.20-NS0.60-RU0.25 $11,634 in F0C1, NS 1.00
$12,805, NS 1.20 $13,132) while ruin jumps in steps. The engine's account (run_v28_after.joint, rule "tzi")
asks a short held overnight for equity of 1.0 per dollar at $2.50-$5 and 2.50 / price under $2.50, and takes a
trade only while the open shorts' margin stays at or under the equity. If that check binds, a bigger size buys
fewer trades, not more exposure.

TradeZero International's published table (support page "What are your margin requirements?", read 2026-11-14)
gives for shorts: under $2.50, $2.50 a share at every hour; $2.50-$5, 16.67% overnight maintenance but $5.00 a
share from 4 to 8 PM; at $5 and up, 16.67% overnight and 50% from 4 to 8 PM; and at most 2:1 leverage into the
4 PM close. Which column binds on a short held through 4-8 PM is not stated, so both ends are run.

## What runs

v58's engine unchanged (TZC costs, IEX 15:50 decision, 5 locate worlds, 31 seeds, 4,000 one-year paths from
$5,000, ruin = touching $1,250), N5, 2:1 gross cap and the 15:45 2:1 rule in every cell. 20 cells:

- Books (DS1, NS, RU): (0.10, 0.40, 0.10), (0.20, 0.60, 0.25), (0.20, 1.00, 0.25), (0.30, 1.00, 0.25),
  (0.45, 1.50, 0.50).
- Margin rules: tzi (the engine's, control), tzus ($5 a share under $5, the 4-8 PM column held all night, the
  strict end), tz6 (published overnight maintenance: 2.50 / price under $2.50, 1/6 at $2.50 and up, the lenient
  end), none (no margin check, gross 2:1 still binds).

Logged per cell at the $5,000 level, base costs, seed 0, worlds W0 and F0C1: candidates and trades taken per
member, mean and 90th percentile gross exposure, mean margin used under the tzi rule, share of days above 90%.

## Reading, fixed now

- Control check: (0.20, 0.60, 0.25) under tzi in W0 must give v56's $13,041 and 1.0% ruin.
- The margin rule caps size if, under tzi, mean gross exposure rises less than half as fast as the sizes from the
  second book to the last, and under none it rises at least twice as fast as under tzi.
- Whatever it shows, the next search (v61, the owner's 100% ruin and 10% limit) uses the margin rule this run
  shows to matter, with both TradeZero ends reported.
