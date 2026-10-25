# v34: bigger positions with limit entries: pre-registration

Written and committed on 2026-10-25, before any v34 result was computed, at the owner's request ("si" to testing
whether v33's limit entries, which halved the tail at about the same median, let a bigger size pass the ruin rule).
Code: `scripts/run_v34.py` (on `scripts/run_v33.py`), tests `tests/test_v34.py`, workflows `v34.yml`,
`v34-canary.yml`.

## 1. Setup

- **Members**: v33's run 40192951586 arms `A1` (v28's picks) and `limit` (v28's picks with the limit entry chosen
  each year on earlier years), unchanged; nothing is re-chosen.
- **Account**: A1's (move order, 3 new, 20 open, gross 2x, $2.50 floor, base locates HTB 1% / HOT 3%, v31's
  liquidation at θ = 15%, 4,000 one-year bootstrap paths from $5,000, ruin = at or under $1,250 at any time), with
  the size a position s = 20/25/30/40% (risk s/10, cap s, as in v32).
- **Costs**: base, HOT 5%, spreads x2, the high costs; paths also drawn only from 2018-2022 and only from 2023+.

## 2. The question

**The limit members at a size s above 20% raise A1's median if, against A1 at 20%, their median is higher at the
base costs, on 2023+ paths, at HOT 5% and at spreads x2, with ruin at most 1% at the base costs.** The choice is the
passing size with the highest base median; none: not shown. The A1 members at 25-40% are reported for reference
(v32 found them lower).

## 3. Caveats fixed now

The limit variants were chosen at 20%; v33's and earlier caveats hold (limit fills on daily bars, the 2023-07+
window not clean, locates assumed, DSR 0).
