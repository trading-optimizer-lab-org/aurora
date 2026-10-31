# v53: the whole v51 grid on 2016-2026 by walk-forward, every year chosen out of sample: pre-registration

Written and committed on 2026-10-31, before any v53 return was computed. The owner asked for one grid run that tries
everything to maximise the one-year median from $5,000 with ruin at most 2.5%.

## 1. Why a walk-forward

v51 chose on 2018-2022 and its answer fell apart after 2022; v52 showed that v51's in-sample favourite has no edge in
2016-2017 (its PF came from 1% of the trades). Picking the best of hundreds of millions of configurations on years
already seen always looks good. v53 therefore does not grade configurations but **procedures**: for each test year,
a procedure chooses a book using only the years before it, trades that book in the test year, and the test years are
joined. Every return graded is out of sample for the choice that produced it.

## 2. Data and engine

- v51's events and one-minute bars (2018-01-02 to 2026-10-16) and v52's (2016-02-01 to 2017-12-29), joined on the
  runner disk; v51's engine, fills, TZC costs and account rules unchanged. Before 2018 the HOT tier has no short
  interest (v52 section 2).
- The grid: every setup x side x entry x exit x filter set (v51 section 1, about 212 million configurations a
  scoring), scored by (PF - 1) x trades a year with v51's vetoes (10 trades a year, PF 1.1) on each training window.

## 3. Procedures (8)

- **Window**: expanding (2016 to the year before) or the last 3 years.
- **Score**: on the net returns as they are, or on returns capped at +-25% (v52: a few extreme trades made a fake PF).
- **Rule**: the book's ensemble ruin on the window's paths at most 2.5%, or at most 1.0%, at base and HOT 5%.

For each test year 2018-2026 and each window and score: the 30 best configurations of every entry, the 5 best distinct
trade sets of every group, then the 40 best across groups; each alone at 10/20/30/40% of equity, 3 or 5 new a day, on
one-year paths drawn from the window's sessions (v29's bootstrap, 4,000 paths, blocks of 20, 3 seeds); the 8 best
singles with ruin at most 2.5% and every book of 1-3 of them at 10/20/30% each, 3 or 5 new a day, on the same paths.
The procedure's book for the year: the highest ensemble median among singles and books meeting its rule; none: cash.

## 4. Grading and decision

- Each chosen book's daily returns in its test year (31 seeds at base and HOT 5%; borrow x2, locates never fail and
  locates failing half as often at 10 seeds) are joined over the test years. One-year paths are drawn from three
  samples of those joined sessions: **selection** 2018-2024, **lockbox** 2025-2026 (to 2026-10-16), all 2018-2026.
  The data fee is the highest of the procedure's books.
- **Chosen procedure**: the highest ensemble median on selection paths among the procedures with selection ruin at
  most 2.5% at base and HOT 5%.
- **MET** if the chosen procedure's lockbox median is $10,000 or more with lockbox ruin at most 2.5% at base and HOT
  5%. Everything else reports: every procedure on every sample, the books chosen each year, the stress sets, the
  sequence from $5,000 through 2018-2026.

## 5. Caveats fixed now

- The lockbox is short (about 1.8 years). Eight procedures chosen on 2018-2024 is a small, reported selection.
- The design of v53 was made after seeing v51 and v52 (the capped score comes from v52), so 2018-2026 is not
  untouched by the author, only by the procedures.
- Extended-session limit fills stay optimistic; 2016-2017 short tiers lack short interest; one-year paths above
  $60,000 keep that level's sizes.
