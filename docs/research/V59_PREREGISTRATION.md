# v59 pre-registration: the night short limited to bigger opening gaps

Written 2026-11-14, before any v59 run. Owner's question: does the book do better if its night short (NS) trades
only gaps of 50% or more, or 100% or more?

## Design

- Book: v58's chosen DS0.20-NS0.60-RU0.25-N5, unchanged (2018-2026 walk-forward picks of v33's limit arm, close
  entries decided on IEX at 15:50, TZC costs, 31 seeds, one-year paths from $5,000).
- One change: an NS trade is kept only if its entry day's open is at least G above the prior close. G = none (the
  control, which must reproduce v56/v58's W0 result), 30, 50, 75, 100, 150 %. DS1 and RU are untouched. The filter
  is applied before the account's daily and open-position caps, so freed slots go to the next candidates.
- NS size stays 0.60. The years whose NS pick already needs a gap above G are unchanged by G.
- Worlds: v58's five locate worlds. Reported: median end equity and chance of ruin per G and world, HOT5 ruin and
  2023+ in W0, and the count of NS candidate trades kept.

## Reading

- A G beats the control only if, in v58's central world range (F0C0-F1C1), its median is higher and its ruin and
  HOT5 ruin are not higher. Six values on one fixed book: a winner is a hint to test on new data, not a new book.
- Known bias: the once-per-20-sessions rule ran on the unfiltered signals, so a big gap that followed a smaller
  one on the same name within 20 sessions stays blocked.
