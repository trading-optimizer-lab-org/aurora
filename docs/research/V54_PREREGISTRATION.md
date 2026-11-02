# v54: the FREE daily book chosen year by year from the years before only: pre-registration

Written and committed on 2026-11-02, before any v54 number was computed. v53 showed that a book chosen on the
whole period can fall apart out of sample. The best honest daily book so far (v49: DS0.20-NS0.40-RU0.20-N5,
$8,498, ruin 0.0%; v50: DS0.20-NS0.60-RU0.20-N5, $9,065, ruin 0.1%, under TradeZero's costs and rules) was sized
on 2018-2026 as a whole. v54 asks whether a book chosen each year from the years before survives.

## 1. Books and engine

- The FREE members DS1, NS and RU (no data fee), v50's engine under TZC (borrow by calendar day, 9% margin, failed
  locates HTB 10% / HOT 50%, the 2:1 rule, close entries at most 10% of volume), v48's 31-seed ensemble at base and
  HOT 5%; stress sets at 10 seeds: borrow x2, locates never fail, locates failing half as often.
- 126 books: DS 0/20/30/40%, NS 0/40/60/80%, RU 0/15/20/25%, 5 or 8 new a day; a member at 0% is left out. Each
  book's daily account returns at every equity level and seed are kept.

## 2. Walk-forward

- Test years 2019-2026; the first training year is 2018. Two windows: **exp** (2018 to the year before) and
  **roll3** (the 3 years before).
- Each test year: one-year paths (v29's bootstrap) from the window's sessions, seeds 0-2. The book is the highest
  median among books with ruin at most 2.5% at base and HOT 5%; none: cash.
- v49's and v50's books held fixed through 2019-2026 are graded the same way, as references (they were chosen on
  the whole period).

## 3. Grading and decision

- The chosen books' daily returns are joined over the test years and graded on one-year paths from $5,000:
  selection 2019-2024, lockbox 2025-2026 (to 2026-10-16), all 2019-2026; plus the single sequence from $5,000.
- **Chosen window**: the highest selection median among windows with selection ruin at most 2.5% at base and
  HOT 5%.
- **SURVIVES** if the chosen window's lockbox and all-sample ruin are at most 2.5% at base and HOT 5%.
- **MET** if it survives and its lockbox median is $10,000 or more at base and HOT 5%.
- **ROBUST** if it survives and all-sample ruin is at most 2.5% in every stress set.
- Check: v50's answer on all paths should come out near $9,065 with ruin near 0.1%.

## 4. Caveats fixed now

- The members themselves (their setups, entries, exits and filters) were chosen in v19-v33 on data through 2022 and
  after; v54 walks forward the sizes and which members are in, not the members' rules.
- 2018 has no year before it, so it is not graded.
