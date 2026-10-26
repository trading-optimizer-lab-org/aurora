# v35: growing the limit book: pre-registration

Written and committed on 2026-10-26, before any v35 result was computed, at the owner's request ("si" to the plan:
a one-year median of $30,000 from $5,000 with ruin at most 2.5%, base costs). Code: `scripts/run_v35.py`, tests
`tests/test_v35.py`, workflows `v35-diag.yml` (phase 0) and, later, `v35.yml`.

## 0. Starting point and target

- **Book**: v34's limit members at 30% a position (v33 run 40192951586 arm `limit`, A1's account: move order, 3 new
  and 20 open a session, gross 2x, $2.50 floor, TradeZero International costs, base locates HTB 1% / HOT 3%, v31's
  liquidation at θ = 15%). v34: median $17,409, ruin 2.1%.
- **Paths**: v29's 4,000 one-year stationary block bootstrap paths (block 20, seed 29) from $5,000; ruin = equity at
  or under $1,250 at any time; the book's return at the equity level the path is at (v29's levels $2.5k, $5k, $10k,
  $25k, $60k).
- **Target (owner's)**: median at least $30,000 and ruin at most 2.5% at base costs.

## 1. Phase 0: diagnostic (nothing chosen)

At the $5k and $25k levels: trades and profit factor per member, the trades the caps leave out (base caps against
no caps, gross 3x, 5 new, 40 open), mean gross and how often it is full, the worst trades and the worst sessions
with each member's part. Informative only; it changes nothing below.

## 2. Phase 1: account levers on the same members

A book is (size schedule, caps, entry ladder). Each book's daily returns are computed at the five levels.

- **Size schedule** s(level): below $10k s1 in {20, 25, 30%}, from $10k s2 in {30, 35, 40, 50%} (risk s/10, cap s).
- **Caps**: gross in {2x, 3x}, new a session in {3, 5}, open in {20, 40}; TradeZero's per-share margin check stays.
- **Entry ladder** for DS1/RU (the open entries): v33's chosen single limit (as now), or two halves at limits
  (L1, L2) over the prior close in {(10%, 30%), (20%, 40%), (20%, 60%)}; each half fills by v33's rule (at the open
  if the open is at or above its limit, else at the limit when the high trades 1% through it). The second half is
  its own item: it may share the symbol with the first (the one-position-a-symbol rule skips it only), and it
  counts in the caps. Night members are unchanged.
- 12 schedules x 8 caps x 4 ladders = **384 books**.

**Choice**: on paths drawn only from 2018-2022 sessions, the book with the highest median among those with ruin at
most 2.5% there. **The target is met if that book's median on all paths is at least $30,000 with ruin at most
2.5%.** Reported for the choice and the top 10: all, 2018-2022, 2023+, HOT 5%, spreads x2, high costs.

## 3. Phase 2: intraday members once the account can pay for data

The chosen phase 1 book below a threshold equity X in {$10k, $25k}; from X, the same book plus v29's PAID intraday
members (their walk-forward picks, unchanged), paying $105 a month only while at or above X. Choice and target as
in section 2 among the two thresholds and "never". New daily families are not part of v35; any is a later,
separately pre-registered study.

## 4. Caveats fixed now

The members and their limit variants were chosen at 20%; the account levers are chosen on 2018-2022 paths, but the
researcher has seen v32-v34 on all years; 2023-07+ is not clean; limit fills on daily bars; locates assumed; DSR 0.
A book reaching the target on all paths while chosen on 2018-2022 is still in-sample for the members.
