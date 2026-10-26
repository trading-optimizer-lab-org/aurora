# v38: a size for each member: pre-registration

Written and committed on 2026-10-26, before any v38 result was computed, at the owner's request ("debes llegar al
objetivo": a one-year median of $30,000 from $5,000 with ruin at most 2.5%, base costs). Code:
`scripts/run_v38.py`, tests `tests/test_v38.py`, workflow `v38.yml`.

## 1. Setup

- **Members**: v33's run 40192951586 arm `limit` without SYMPATHY (v35's all-years diagnostic: PF 0.53).
- **Size for each member** (risk s/10, cap s): DS1 in {20, 30, 40%}, RU in {20, 30, 40, 50%}, NS in {10, 20, 30%},
  ON1 in {0 (out), 10, 20%}; HOT rule none or every HOT short at half its weight (v36's). 3 x 4 x 3 x 3 x 2 =
  **216 books**, each also at HOT 5%, spreads x2 and the high costs.
- **Account**: A1's (move order, 3 new and 20 open a session, gross 2x, $2.50 floor, TradeZero International
  costs, base locates HTB 1% / HOT 3%, v31's liquidation at θ = 15%); v29's 4,000 one-year bootstrap paths from
  $5,000; ruin = equity at or under $1,250 at any time; $6 a month.

## 2. The question

**Choice**: on paths drawn only from 2018-2022 sessions, the book with the highest median among those with ruin at
most 2.5% there. **The target is met if that book's median on all paths is at least $30,000 with ruin at most
2.5%.** Reported: the choice and the top 10 on all / 2018-2022 / 2023+ paths and the stress costs.

## 3. Caveats fixed now

The members' PFs that motivate the sizes were seen on all years (v35 phase 0); SYMPATHY's removal too. This is the
fourth search for the same target (v35-v38); a met target would still need a clean test. 2023-07+ is not clean;
limit fills on daily bars; locates assumed; DSR 0.
