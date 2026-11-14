# v60 pre-registration: night-short gap filter x NS size, chosen on 2018-2022

Written 2026-11-14, before any v60 run, after v59 (a gap filter at fixed NS size 0.60 lowered the median; since
2023 G100 looked 6% better). Question: with fewer, bigger gaps, does a larger NS size beat the current book?

## Design

- Books: DS1 0.20, RU 0.25, N5 fixed; NS gap filter G = none, 50, 75, 100, 150 % (v59's rule: entry day's open at
  least G above the prior close) x NS size 0.60, 0.80, 1.00, 1.20. 20 books. Gnone-NS0.60 is v58's book and must
  reproduce its W0 result ($13,041, ruin 1.0%).
- Engine, costs, seeds and worlds as v58/v59.
- Choice per world by v56's rule: among books whose 2018-2022 ruin is at most 5% under base and HOT5 costs, the
  highest 2018-2022 median.

## Verdict

- IMPROVED if, in the central worlds F0C1 and F1C1, the chosen book is not the control and on 2023-2026 its
  median beats the control's with ruin no higher than the control's + 0.5 points.
- Otherwise NOT IMPROVED and the bot keeps the current book.
