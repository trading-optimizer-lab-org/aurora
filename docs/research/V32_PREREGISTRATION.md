# v32: a bigger A account with tail controls and entries ranked by edge: pre-registration

Written and committed on 2026-10-25, before any v32 result was computed, at the owner's request ("haz la 1 y la 2"
on the plan: 1 = control the tail so a bigger size can pass the ruin rule, 2 = rank the entries by their expected
net edge). The account is v29's A1 ($5,000, one TradeZero International account, FREE plan) under v31's forced
liquidation. Code: `scripts/run_v32.py` (on `scripts/run_v31.py`), tests `tests/test_v32.py`, workflows `v32.yml`,
`v32-canary.yml`. The members and their trades are v29's FREE members, unchanged.

## 1. Why

In v29 the chosen book A1 (risk 2%, cap 20%) sits on a plateau: about 15 books end within 1% of its median
($12,831), and risks 2/3/4% give the same book because each position stops at 20% of the equity. No book with
positions above 20% met the ruin rule (at most 1% of paths at or under $1,250 at any time). If the tail can be cut,
a bigger size may pass the rule and raise the median. Which trades enter on a busy session is set by the size of the
move; ranking by edge net of the locate may pick better ones.

## 2. Unchanged

v29's FREE members, TradeZero International's costs (base locates HTB 1%, HOT 3%), the five equity levels, the
4,000 one-year bootstrap paths (block 20, seed 29), the fixed $6 a month, gross at most 2x, the $2.50 price floor,
no HOT-night rule off, the locate gate off, v31's liquidation rule at θ = 15% (TradeZero America's published level).
A path that loses more than its equity ends at zero (v29's path rule).

## 3. The grid (192 books x 3 brakes = 576)

- **Size** s = 20/25/30/40% a position (risk s/10, cap s, as v29's daily sizing caps a position at the lesser of
  the cap and 10 x the risk).
- **Order** of entry on a session with more candidates than slots: `move` (v29's: the size of the move) or `edge`:
  the family's mean net return a trade (after costs, before the locate) over the book's candidates in earlier years,
  minus the trade's locate, highest first; a family's first year has no edge and ranks after the rest.
- **At most 1/2/3/5 new** a session (1 and 2 are new; 3 and 5 are v29's).
- **At most 10/20 open.**
- **HOT cap**: the open HOT shorts' total weight at most 60% / 100% of the equity / no cap.
- **Drawdown brake**: off, or when the equity at the previous close is more than 20% / 30% under its highest
  close so far in the path, the session uses the same book at half the size (s/2); full size again once it is back
  within the limit. The half-size book is computed in full (its own trades, costs, limits and liquidations).

A1 is in the grid: s 20%, `move`, 3 new, 20 open, no HOT cap, no brake.

## 4. The choice and the question

- **The choice**: the highest median ending equity with a chance of ruin of at most 1% (v29's rule), at the base
  costs, under the liquidation rule.
- **The question: does v32 raise A1's median?** Yes only if the choice's median beats A1's at the base costs, with
  HOT locates at 5%, and with spreads x2, each under the rule and with the same paths. Otherwise: not shown.
- Also reported: the best median for each value of each lever (with ruin at most 1%), the top 10 books, and for A1
  and the choice: the chance of -50% and of a loss, p10/p90, the mean of the worst 5% of paths, and the forced
  liquidations in the 2018+ stream at $5,000.

## 5. Battery (A1 and the choice)

HOT locates 5% and 8%; spreads x2; the high costs (spreads x2, borrow x3); θ = 30%; the rule off; the bootstrap
drawn only from 2018-2022 sessions and only from 2023+ sessions (each with the choice fixed, not re-chosen).

## 6. Caveats fixed now

- The brake switches between two precomputed books: a position held across the switch is resized at no cost, and
  the half-size book's own positions appear at once. This flatters the brake slightly.
- The choice is made on the same 2018-2026 stream it is measured on, now over more knobs than v29: the median of
  the choice is biased up. The 2018-2022 / 2023+ split is reported, not used to choose.
- The edge order uses only earlier years' candidates, but the families were picked by v28 on the whole stream.
- v29's and v31's caveats hold (locates and borrow are assumptions until quoted; DSR 0; halts are only the next
  open's gap).
