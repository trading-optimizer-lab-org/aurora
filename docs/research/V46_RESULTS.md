# v46 results: the book's trades on one-minute bars, technical analysis of every kind

Run 40705434436: 466 jobs, all succeeded. Stage 1 ran on 164 runners, stage 2 on 300 four-CPU runners; wall
clock 41 minutes. Canary 40701570598 passed every stage first. The full report is in the artifact `v46-report`
(V46_REPORT.md, v46_summary.json). Pre-registration: V46_PREREGISTRATION.md.

Check: the base book reproduces v44's central case ($22,006 median, 0.1% ruin).

## Pass marks

| question | result |
|---|---|
| Q1: the walk-forward book improves the book | **NOT MET** |
| Q2: robust single changes (descriptive) | one: close-entry market order at 15:55 |
| Q3: the fixed robust book (descriptive, in sample) | +4.8% median, ruin 0.2%; below Q1's 1.15x mark |
| Q4: from $2,000 | base $8,296; walk-forward $7,655; Q3 $8,825 |

## Data

Bootstrap from $5,000, one year (4,000 paths; ruin at or under $1,250):

| book | costs | median | ruin | p10 | 2018-22 median | 2023+ median |
|---|---|---|---|---|---|---|
| base | base | $22,006 | 0.1% | $8,295 | $21,891 | $20,999 |
| base | HOT 5% | $16,153 | 0.5% | $6,084 | - | - |
| base | high | $10,252 | 2.5% | $3,650 | - | - |
| walk-forward | base | $20,219 | 0.1% | $7,549 | $20,602 | $19,050 |
| walk-forward | HOT 5% | $14,694 | 0.8% | $5,511 | - | - |
| walk-forward | high | $9,401 | 3.2% | $3,244 | - | - |
| Q3 (market at 15:55) | base | $23,061 | 0.2% | $8,465 | $23,507 | $21,385 |
| Q3 (market at 15:55) | HOT 5% | $16,854 | 0.7% | $6,174 | - | - |
| Q3 (market at 15:55) | high | $10,789 | 2.7% | $3,717 | - | - |

Symbol halves at $10,000, summed log growth: base 6.22 / 6.84, walk-forward 6.02 / 6.26, Q3 6.34 / 7.13.

Walk-forward picks 2019-2024 were mostly T16 (first red Heikin-Ashi bar after 3 green, 180-minute deadline) with a
market close entry at 15:51 and passive open entries. 2025-2026 dropped the trigger.

Stage 1, each value alone (summed log growth at $10,000, base costs; base 12.79, worst yearly drawdown -70.3%):

| dimension | best value | its growth | range of the others | note |
|---|---|---|---|---|
| entry trigger (80) | T11 MACD turns negative, 180 deadline | 12.25 | 0.20 to 12.22 | none beats the base |
| close entry timing (13) | market at 15:51 / 15:55 | 13.18 / 13.18 | 8.22 to 12.25 | after-hours entries cut the worst yearly drawdown to -55% to -66% but lose growth |
| stop (12) | none | 12.57 | 0.43 to 8.35 | every tighter stop loses |
| TA exit (37) | RSI(14) under 15 | 10.10 | -2.65 to 8.45 | every exit loses, many turn negative |
| overnight cover (19) | target 15% | 6.59 | -4.76 to 4.89 | every one loses heavily |
| execution (2) | passive | 12.74 | 12.62 | both slightly below the auction |
| filter (54) | none | 12.79 | -0.37 to 11.80 (two no-ops equal none) | no filter beats none |

## Inference

- The book is not improved by technical analysis on one-minute bars. Of 163 single changes and 54 filters, one change
  passes the robustness test: sending close entries as a market order at 15:55 instead of in the closing auction.
  Its gain is small (+4.8% median, in sample) and below the pre-registered 1.15x mark.
- Exits and stops cost the most. The book earns over the nights it holds, so any rule that covers during the
  first session or before the next open gives up that edge. Delayed entries also lose, as v43 found.
- After-hours close entries lower the worst yearly drawdown, but they also cut growth, so they do not improve
  the book on the pre-registered measure.
- The walk-forward book is worse than the base ($20,219 vs $22,006). The grid overfits 2018-2022, as in v43 and v44.

## Caveats

- In-sample: every year 2018-2026 has been seen. The book was chosen on them.
- Design flaws found in the results, not fixed post hoc:
  - Four trigger rows with a 15-minute "skip" window cannot fire, because the indicator needs more than 15 bars:
    T9 RSI(14), T12 Bollinger(20), T20 the 15-minute range, T21 stochastic. Each of these rows equals
    "no open entries" (growth 0.20).
  - The "overnight cover" dimension's base is not an open-auction cover. The base holds through the open and exits
    at closes on its schedule. So every value there tested a full exit before the first carried open.
  - The filters "skip green_run bottom tercile" and "skip ha_run bottom tercile" are no-ops: the counts tie at 0.
    Both entered stage 2 as copies of "none".
- Q3's change is order timing. It needs no indicator data. The FREE bot needs TradeZero to accept a timed market
  order at 15:55; v46 did not model TradeZero's execution of that order. Every TA rule that did not pass would have
  needed minute data, which the owner's no-paid-data constraint rules out.
