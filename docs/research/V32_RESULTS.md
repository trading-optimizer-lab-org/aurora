# v32 results: A1 stays the best book

Pre-registered in [V32_PREREGISTRATION.md](V32_PREREGISTRATION.md). Run 40186641213 (canary 40185726654), all 8 grid
cells and 14 battery shards succeeded. Full report: the run's `v32-report` artifact; data: `data/v32_summary.json`.

## Summary

- **v32 does not raise A1's median.** The choice under v29's rule (highest median, ruin at most 1%) is A1 itself:
  size 20%, order by move, 3 new, 20 open, no HOT cap, no brake. One year from $5,000: median $12,831, ruin 0.5%,
  no forced liquidation at θ = 15% (as in v31).
- **A bigger size lowers the median even before the ruin rule.** Best median of each size over all its books, any
  ruin: 20% $12,831 (ruin 0.5%); 25% $12,726 (ruin 5.7%); 30% $11,468 (15.3%); 40% $11,344 (14.9%). With ruin at
  most 1%: 25% reaches $10,016 (with a 30% brake); 30% and 40% have no book (lowest ruin 5.2% and 5.0%). So 20% is
  already at or past the size that maximizes the median; the tail is not what holds the median back.
- **Tail controls cost more than they give.** Best median with ruin at most 1%: brake 20% $9,015, brake 30% $10,016
  (both need size 25% to get there), off $12,831. HOT cap 60% $11,213, 100% $12,039 (ruin 0.8%, higher than no cap),
  none $12,831. A HOT cap skips the HOT shorts that carry most of the profit (v29) and the slots go to weaker trades
  (inferred from v29's tier table, not measured here).
- **The edge order is worse than the move order**: best $11,213 against $12,831.
- **Entries a day**: 1 new $9,697, 2 $12,474, 3 $12,831, 5 $12,800.
- **The two halves differ a lot**: A1 bootstrapped only from 2018-2022 sessions: median $9,022 (ruin 0.3%); only
  from 2023+: $20,528 (ruin 1.1%). The 2023-07+ window is not clean for the researcher.

## Caveats

v29's and v31's caveats hold. The brake's switch between two precomputed books flatters it, and it still loses.
