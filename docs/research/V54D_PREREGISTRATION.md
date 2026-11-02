# v54d: CRASH-long in 2016-2017 against 2018 on, market or data: pre-registration

Written and committed on 2026-11-02, before any v54d number was computed. v52 found CRASH-long (buy a small cap down
20% or more near the close, sell the next morning) with no edge in 2016-2017 once the extreme trades are dropped
(PF 0.96) and a broad edge from 2018 (PF 1.53 in 2018-2022, 1.24 from 2023). The owner asked why.

## 1. Three independent looks, by year

- **Daily panel only** (v18's daily bars, whole history): every close 20% or more under the prior close, bought at
  that close and sold at the next open, and at the next close; gross, all prices and by price band; the number of
  valid symbols a year. No minute data.
- **Minute bars** (v51+v52, 2016-02 to 2026-10): CRASH-long net of TZC costs with the "all" filter, entries c_1555
  (market at 15:55) and c_ah0 (after-hours limit at the close), exits next open, next premarket limit, next 10:00,
  next close and second close, with and without the 25% target and 100% stop. Trades, PF, PF without the top and
  bottom 1%, median trade; entry outcome codes.
- **Coverage**: for every CRASH event, the gap between the last regular-session minute close and the daily close,
  the gap between the first regular-session minute open next day and the daily open, the after-hours bars that day,
  the premarket bars and premarket dollar volume next day.

## 2. Reading fixed now

- **Market**: the daily panel shows the same split (trimmed PF at most 1 in 2016-2017 and above 1 from 2018), and
  in the minute bars the exit at the regular open shows it too.
- **Data**: the daily panel has a 2016-2017 edge the minute bars lack, or the minute edge from 2018 lives only in
  extended-session fills (c_ah0 entries or premarket-limit exits) and not at the regular open and close, or the
  coverage of 2016-2017 differs from 2018 on (premarket bars missing at least twice as often, or minute-daily gaps
  over 2% at least twice as often).
- Anything else is reported as unresolved.

## 3. Caveats

- The daily panel is gross of costs; costs are about the same each year, so it reads the pattern, not the level.
- The daily panel and the minute bars may share an upstream source; agreement between them rules out a minute-only
  problem, not every data problem.
