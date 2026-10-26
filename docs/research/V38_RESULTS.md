# v38 results: a size for each member

Pre-registration: [V38_PREREGISTRATION.md](V38_PREREGISTRATION.md). Run 40318676449 (2026-10-26, all jobs
succeeded). Numbers in [data/v38_summary.json](data/v38_summary.json).

**Target not met.** Choice on 2018-2022 paths: DS1 30%, RU 50%, NS 30%, ON1 20%, HOT shorts at full weight:
median $21,638, ruin 1.4% on all paths (2018-22 $20,284 / 2.3%, 2023+ $23,398 / 0.9%; HOT 5% $14,931 / 2.7%,
spreads x2 $17,067 / 2.0%, high costs $8,663 / 7.6%).

- No book of the 216 has an all-paths median of $30,000 or more; the highest median of any book, at any ruin, is
  the choice itself.
- Per-member sizes beat v36/v37's single size (~$15-18k) by about $3-6k. The gain comes from RU at 50% and NS at
  30%; DS1 above 20% and ON1 add median but most of the ruin.
- The safest strong book: DS1 20%, RU 50%, NS 30%, ON1 0%: median $18,780, ruin 0.1%, high costs $9,755 / 1.1%.
- The choice sits on the grid's edge (RU, NS and ON1 at their largest sizes). Inference, not tested: larger sizes
  would raise the median a little but its ruin is already 2.3% on 2018-2022 paths and 2.7% at HOT 5%, so they
  would not stay eligible.

## Where v35-v38 leave the $30,000 target

No pre-registered change reached it: account levers (v35), member sets and HOT rules (v36), new daily members
(v37), a size for each member (v38). With TradeZero's costs and the broker's liquidation, the one-year median from
$5,000 tops out at about $21-22k with ruin at or under 2.5%, and that book fails the HOT 5% and high-cost stresses.
This is the fourth search for the same target; even the v38 choice would need a clean test.
