# v54m: how much a safety margin costs the fixed daily book: pre-registration

Written and committed on 2026-11-02, before any v54m number was computed. v54 found that v49's fixed book
(DS0.20-NS0.40-RU0.20-N5) was positive in every year 2019-2026 with ruin under 1%, but one step up in RU (25%)
turns 2024 from +74% into -46%: the book sits at the edge of a cliff. v54m asks what a book with a step of margin
on every member earns, using v54's daily account returns as they are (run 41497719624, no new simulation).

## 1. Books and grading

- The 126 v54 books (DS 0/20/30/40%, NS 0/40/60/80%, RU 0/15/20/25%, 5 or 8 new a day), each held fixed through
  2019-2026 and graded as v54 graded its fixed references: one-year paths from $5,000 drawn from selection
  2019-2024, lockbox 2025-2026 and all 2019-2026, at base and HOT 5% (31 seeds) and the three stress sets (10
  seeds), plus the single sequence from $5,000 with each calendar year's sum.
- **Neighbours** of a book: the books with one member one grid step larger, the rest and the new-a-day count the
  same. A member at the top of its grid (DS 40%, NS 80%, RU 25%) has no step above: such a book has no tested
  margin on that member.

## 2. Margin rule and decision

- A book **has margin** if it has a neighbour on every member it holds, and the book and all its neighbours have
  all-sample ruin at most 2.5% at base and HOT 5%, and no calendar year 2019-2026 below -30% in the single
  sequence; and the book itself has all-sample ruin at most 2.5% in every stress set.
- **Margin pick**: the highest all-sample median at base among books with margin.
- Reported against v49's book: the cost of margin is v49's all-sample median minus the margin pick's, and the same
  for lockbox. **Cheap** if the margin pick's all-sample median is at least 90% of v49's; **dear** otherwise.
- Check: v49's fixed grade here should equal v54's (all-sample median and ruin).

## 3. Caveats fixed now

- Every book here is graded on the same 2019-2026 it is chosen on: the margin pick is still chosen in hindsight.
  Margin protects against a nearby cliff, not against a new kind of year.
- The members' own rules were chosen in v19-v33; v54m varies only their sizes.
