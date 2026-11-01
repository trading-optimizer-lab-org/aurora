# v53c: v53's walk-forward books with the size also chosen out of sample: pre-registration

Written and committed on 2026-11-01, after v53b (V53B_RESULTS.md) and before any v53c number was computed. v53b met
its rule at scale 0.25, but that scale was chosen on 2018-2024 as a whole, losses of 2020-2022 included. v53c asks
whether a size chosen each year from the years before only keeps ruin at 2.5% or less.

## 1. What is reused

v53's 8 procedures and their 32 books, chosen each test year from the years before; v53b's daily returns of every
(book, scale), scales 1.00, 0.75, 0.50, 0.35, 0.25, 0.15, 0.10, 0.05 (run 41231859502). Nothing is re-simulated.

## 2. The size rule, for each procedure and test year

- 2018 has no out-of-sample history: scale 0.10.
- From 2019 on: for each scale, one-year paths (v29's bootstrap, 4,000 paths, blocks of 20) drawn from the
  procedure's own sessions of 2018 to the year before, each year with the book it had chosen, at that scale; seeds
  0-2, base and HOT 5%. Two variants:
  - **safe**: the largest scale with ruin at most 2.5% at base and HOT 5%;
  - **best**: among those, the one with the highest median; cash when that median is below $5,000.
  - No scale meeting the ruin cap: cash.

## 3. Grading and decision

- The 16 (procedure, variant) pairs are graded as in v53 section 4: selection 2018-2024, lockbox 2025-2026, all
  2018-2026, 31 seeds at base and HOT 5%, stress sets at 10 seeds, the sequence from $5,000.
- **Chosen pair**: the highest selection median among pairs with selection ruin at most 2.5% at base and HOT 5%.
- **MET** if its lockbox median is $10,000 or more with lockbox ruin at most 2.5% at base and HOT 5%.
- **ROBUST** if MET and also all-2018-2026 ruin at most 2.5% in every stress set (borrow x2, locates never fail,
  locates failing half as often).

## 4. Caveats fixed now

- The scale grid and the 2018 scale were set after seeing v53b; the size rule itself uses only past years.
- The lockbox is short and dominated by CRASH-long (v52: its profit is a few extreme trades).
