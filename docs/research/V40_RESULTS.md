# v40 results: a large walk-forward grid of overlays on v39's best book

Pre-registration: [V40_PREREGISTRATION.md](V40_PREREGISTRATION.md). Run 40339217411 (2026-10-26; 300 runners of 4
CPUs, all 5,174,400 variants computed; one shard's upload failed on a network reset and was rerun, attempt 2).
Numbers in [data/v40_summary.json](data/v40_summary.json). The base book reproduces v39 ($23,143, ruin 0.1%).

**v40 does not improve the book.**

| book | base costs | HOT 5% | spreads x2 | high costs |
|---|---|---|---|---|
| base book | $23,143 / 0.1% | $16,941 / 0.5% | $19,033 / 0.4% | $10,683 / 2.5% |
| walk-forward | $25,182 / 2.5% | $17,188 / 4.3% | $19,888 / 3.4% | $9,522 / 8.8% |

(median / ruin on all paths; 2023+ paths: base $20,989 / 0.8%, walk-forward $26,893 / 2.0%.)

The walk-forward median is 8.8% higher (the bar was 15%), its ruin at HOT 5% is 4.3% and it is worse at the high
costs. From 2019 it picks the 1.25 size scale every year, with a dilution boost: most of its gain is more
leverage, and leverage is what the stress costs punish.

## What the grid says (in-sample, all years; not a result)

Mean all-years log growth by value, over every other dimension:

- **Dilution flags pick the better shorts.** Boosting flagged trades beats none for every flag (going concern
  6.50, shares +25% 6.22, any 6.26 vs 5.71) and halving unflagged ones loses (3.65-4.56). The one consistent new
  signal.
- **Stops hurt**: none 6.63, +30% 4.05, +60% 5.11, +100% 4.98. The squeezes that hit a stop mostly come back.
- **Regime filters hurt**: none 6.87 is the best value; skipping on many runners or low VIX costs the most.
- **Calendar hurts** (none 5.65, June 5.33, quarter ends 5.07); **cluster and crowding do nothing**; a 5-session
  hold hurts; a -50% target is about neutral.
- Size: growth rises with scale (0.6 3.79 to 1.25 6.38), which the ruin and stress results bound.

## Reading

The base book's trades are already near what daily data can do with them: filters that skip trades lose more
winners than losers, stops cut squeezes that would have reverted, and the only signal with a consistent sign
(dilution) improves growth mainly when it adds weight. A dilution-based member or selection rule would be the
next study, pre-registered on its own; it would sit on the same years.
