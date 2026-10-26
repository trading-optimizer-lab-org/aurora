# v41 results: a dilution tilt at equal exposure on v39's best book

Pre-registration: [V41_PREREGISTRATION.md](V41_PREREGISTRATION.md). Run 40365817530 (2026-10-26; one runner of 4
CPUs, all 49 variants). Numbers in [data/v41_summary.json](data/v41_summary.json). The base book reproduces v39
($23,143, ruin 0.1%).

**v41 does not improve the book.**

| book | base costs | HOT 5% | spreads x2 | high costs | 2023+ paths |
|---|---|---|---|---|---|
| base book | $23,143 / 0.1% | $16,941 / 0.5% | $19,033 / 0.4% | $10,683 / 2.5% | $20,989 / 0.8% |
| walk-forward | $20,357 / 0.4% | $15,054 / 1.1% | $16,841 / 0.9% | $9,715 / 3.2% | $22,114 / 0.7% |

(median / ruin.) The walk-forward book is 12% below the base book on all paths and worse at every cost. Only the
2023+ median is higher. The picks change flag from year to year (runway, going concern, shares +25%), which is what
noise looks like.

## The answer to v40's open point (in-sample, all years; not a result)

At equal average exposure, the best fixed tilts (any flag x3, shares +25% x1.5, score x2) raise the all-paths median
by 4-8% over the base book ($24.2k-$25.1k vs $23.1k), at the same ruin. About half of the 48 tilts beat the base book
and half do not; the strongest event tilt (x3) breaks the book (ruin 6-7%). So the dilution flags carry a little
information, much less than v40's boost suggested: most of v40's dilution gain was added exposure.

Flag coverage of the book's 1,009 trades: EFFECT/8-K 3.02 39%, going concern 34%, runway under 6 19%, shares +25% 14%,
any 57%.

## Reading

No overlay, filter, exit or dilution tilt tested in v40-v41 improves the base book when chosen on earlier years.
DS1 20% RU 70% NS 40% stays the best book.
