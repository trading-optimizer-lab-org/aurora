# v53b: v53's walk-forward books at smaller sizes: pre-registration

Written and committed on 2026-10-31, after v53 (V53_RESULTS.md) and before any v53b return was computed. The owner
asked to cut the risk until ruin is at most 2.5%.

## 1. What changes

Nothing in v53's choice: the same 8 procedures, the same 32 books chosen each test year from the years before only.
Every member's size in every chosen book is multiplied by one **scale** for the whole 2018-2026 sequence:
1.00, 0.75, 0.50, 0.35, 0.25, 0.15, 0.10, 0.05. Each (book, scale) is re-simulated with v51's engine (fills, TZC
costs, locates, data fee unchanged), at 31 seeds at base and HOT 5% and the stress sets at 10 seeds, exactly as
v53's oos stage. Scale 1.00 repeats v53.

## 2. Grading and decision

- The 64 (procedure, scale) pairs are graded as in v53 section 4: one-year paths from $5,000 on the joined test
  years, samples selection 2018-2024, lockbox 2025-2026, all 2018-2026.
- **Chosen pair**: the highest ensemble median on selection paths among pairs with selection ruin at most 2.5% at
  base and HOT 5%.
- **MET** if the chosen pair's lockbox median is $10,000 or more with lockbox ruin at most 2.5% at base and HOT 5%.
- Reported for every pair: every sample, the stress sets, the sequence from $5,000 through 2018-2026 and its low.

## 3. Caveats fixed now

- The scale is chosen on 2018-2024, which contains the 2020-2022 losses v53 showed; only the lockbox is untouched,
  and it is short (about 1.8 years).
- v53's lockbox medians came from compounding a few extreme CRASH-long days (v52); smaller sizes damp that but do not
  remove it, so a lockbox pass is weak evidence.
- 64 pairs chosen on one selection sample: a small, reported selection on top of v53's.
