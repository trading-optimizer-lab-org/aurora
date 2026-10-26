# v36: dropping weak members and capping HOT shorts: pre-registration

Written and committed on 2026-10-26, before any v36 result was computed, at the owner's request ("si" to v36 A
after v35 missed the target). Code: `scripts/run_v36.py`, tests `tests/test_v36.py`, workflow `v36.yml`.

The ideas come from v35's phase 0 diagnostic, which looked at all years: ON1 (PF 1.13, single trades of -154% and
-137%) and SYMPATHY (PF 0.53) add little or lose, and the worst trades are mostly HOT names. **The choice is
therefore made on 2018-2022 paths only, and the result is partly in-sample.**

## 1. Setup

- **Members**: v33's run 40192951586 arm `limit` (as v34/v35), with a member set: all; without ON1; without
  SYMPATHY; without both.
- **HOT rule** (HOT = v29's tier 2, known at the entry): none; open HOT weight at most 0.25 or at most 0.50 of the
  equity (v32's hot_cap); every HOT short at half its weight (the shares as sized at full weight; the commission's
  minimum is not re-applied).
- **Size** a position s = 25/30/35/40% at every equity level (risk s/10, cap s).
- **Account**: A1's (move order, 3 new and 20 open a session, gross 2x, $2.50 floor, TradeZero International
  costs, base locates HTB 1% / HOT 3%, v31's liquidation at θ = 15%); v29's 4,000 one-year bootstrap paths from
  $5,000; ruin = equity at or under $1,250 at any time; $6 a month.
- 4 sets x 4 HOT rules x 4 sizes = **64 books**, each also at HOT 5%, spreads x2 and the high costs.

## 2. The question

**Choice**: on paths drawn only from 2018-2022 sessions, the book with the highest median among those with ruin at
most 2.5% there. **The target (owner's) is met if that book's median on all paths is at least $30,000 with ruin at
most 2.5%.** Reported for every book: all, 2018-2022, 2023+ and the three stress costs.

## 3. Caveats fixed now

The member set and the HOT rules were suggested by a diagnostic on all years; the members and their limit
variants were chosen at 20%; 2023-07+ is not clean; limit fills on daily bars; locates assumed; DSR 0.
