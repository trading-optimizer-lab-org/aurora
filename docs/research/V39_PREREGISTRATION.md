# v39: volatility-cut sizes beyond v38's edge: pre-registration

Written and committed on 2026-10-26, before any v39 result was computed, at the owner's request ("continua hasta
lograr tu objetivo": a one-year median of $30,000 from $5,000 with ruin at most 2.5%, base costs). Code:
`scripts/run_v39.py`, tests `tests/test_v39.py`, workflow `v39.yml`.

**This is the last search for this target.** v35-v38 did not reach it; each further search on the same data makes a
hit less credible. Whatever v39 shows, the search for the $30,000 target stops here.

## 1. Setup

- **Members**: v38's (v33's run 40192951586 arm `limit` without SYMPATHY), HOT shorts at full weight.
- **Volatility cut**: a trade's volatility is the standard deviation of its symbol's 20 daily log close-to-close
  returns ending the session before the entry session (known before the entry). Its weight is the member's size
  times min(1, (v_ref / vol) ^ p), with v_ref the median volatility of that member's 2018-2022 trades, p in
  {0 (no cut), 0.5, 1}. The cut only lowers weights.
- **Sizes**, from v38's choice outward: DS1 in {20, 30, 40%}, RU in {50, 60, 70%}, NS in {30, 40%}, ON1 in
  {0, 20%}. 3 x 3 x 2 x 2 x 3 = **108 books**, each also at HOT 5%, spreads x2 and the high costs.
- **Account**: v38's (A1's account, v31's liquidation at θ = 15%, v29's 4,000 one-year bootstrap paths from
  $5,000, ruin = equity at or under $1,250 at any time, $6 a month).

## 2. The question

**Choice**: on paths drawn only from 2018-2022 sessions, the book with the highest median among those with ruin at
most 2.5% there. **The target is met if that book's median on all paths is at least $30,000 with ruin at most
2.5%.** Reported: the choice, the top 10 and the stress costs. The book DS1 30% RU 50% NS 30% ON1 20% p 0 must
reproduce v38's choice ($21,638 / 1.4%).

## 3. Caveats fixed now

Fifth search for the same target (v35-v39); a met target would still need a clean test. The volatility cut was
chosen without looking at the trades' volatility. 2023-07+ is not clean; limit fills on daily bars; locates
assumed; DSR 0.
