# v57: v56's books on a grid of locate worlds: pre-registration

Written and committed on 2026-11-12, before any v57 number was computed. v56 found that the 150% a year target at
5% ruin depends on how often TradeZero's locates fail, and assumed v47's locate price a share (HTB $0.01, HOT $0.03)
and an ETB tier that needs no locate. The borrow logger now has TradeZero quotes; they stay private (encrypted
artifacts), so v57 runs a generic grid and the world that matches the quotes is read privately.

## 1. Engine (as v56)

- v56's engine unchanged: TZC costs, close entries decided on Alpaca's IEX bars (v55), 31 seeds, one-year paths
  from $5,000, ruin at or under $1,250, the same 48 books (DS1 {0.10, 0.20, 0.30} x NS {0.40, 0.60, 0.80, 1.00} x
  RU {0.10, 0.15, 0.20, 0.25}, 5 new names a day).
- New: every short's locate cost is repriced at the world's price a share (v47's scaling by tier and cost set
  kept), and in **E** worlds a short the model calls ETB pays the HTB price and fails as HTB.

## 2. Worlds

- **W0**: v56's W0 (no failures, $0.01 / $0.03 a share, ETB free). Check: DS0.20-NS0.60-RU0.25 must give
  v56's $13,041 and 1.0% ruin.
- Failures (HTB / HOT): **F1** 2% / 10%, **F2** 2% / 20%, **F3** 5% / 30%, **F4** 5% / 40%.
- Price a share (HTB / HOT): **C2** $0.03 / $0.12, **C3** $0.05 / $0.25.
- ETB: as the model, or **E** (ETB shorts treated as HTB).
- 4 x 2 x 2 = 16 worlds plus W0.

## 3. Selection and decision, per world (as v56)

- The book is chosen on 2018-2022 paths: highest ensemble median among books with ensemble ruin at most 5% at base
  costs and at HOT 5% on those paths.
- **MET** in a world if that book has, on all paths 2018-2026, ensemble median at least $12,500 and ruin at most
  5% at base and HOT 5%, and ruin at most 5% on 2023+ paths at base costs.
- Private reading, fixed now: the **central** world is the grid point nearest the quotes' measured failure rates
  and mean price a share by tier; the **stress** world is the grid point at or above the upper 95% bound of the
  failure rates, with C3 and E. The owner gets the central world's answer, with the stress world beside it.

## 4. Caveats fixed now

- The quotes are few days and mostly before 11:00 New York; the book enters near 15:50. Fill rates at the decision
  time may differ; the reading is redone when the logger has two weeks of 15:50 quotes.
- Failures are still drawn at random by symbol and day, not clustered on the hottest names.
- A mean price a share stands in for a skewed distribution; a bot that declines dear locates would do better, a
  bot that pays a tail price on its best trades worse.
- Every year has been seen in earlier studies; 48 books on seen years, the 2023+ ruin test is the guard.
