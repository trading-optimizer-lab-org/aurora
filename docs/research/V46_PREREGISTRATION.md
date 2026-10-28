# v46: the book's trades on one-minute bars, technical analysis of every kind: pre-registration

Written and committed on 2026-10-28, before any v46 return was computed, at the owner's request: a large run on
one-minute bars, every kind of technical analysis, indicator and approach not tested before, with the aim of
improving the book, on at least 300 four-CPU GitHub runners. Code: `scripts/run_v46.py`, tests `tests/test_v46.py`,
generator `scripts/gen_v46_wf.py`, workflows `v46-canary.yml`, `v46.yml`.

## 0. What is already tested and left out

v23b (105,336 one-minute TA configurations as new members: levels, VWAP, EMA, oscillators, MACD, squeeze, patterns,
candles, climax, ORB), v24/v25 (421,032 long and mirrored short one-minute families), v26 (stops, holds, after-hours
and premarket stops, rally exits, splits, name filters), v28 (premarket and after-hours entries as new members),
v43 (entry delay, stop scale, flat time, intraday cover on a fall, trailing stop, size; 96 fill cases), v44 (26
entry features as tercile filters and two models, entry triggers T1-T8, TWAP and passive entries, emergency exits
X1-X6, locate flat times, a partial cover; 15 new one-minute families). Literature (Allen and Karjalainen-type
bootstraps of 7,846 intraday rules; Neely and Weller; Marshall et al.) finds no intraday TA edge after data snooping
and costs as stand-alone strategies, so v46 uses TA only to time and manage the book's own trades, whose edge exists.
Intraday calendar effects (end-of-day reversal; an 11:00 effect in small caps) enter as time exits.

## 1. The book and the engine

v43/v44's book (DS1 20%, RU 70%, NS 40%) and engine unchanged: the same 1,009 trades, v43's central realism case
(`next_open` fills, 10% of a bar's volume, liquidation at `next_vwap`, auction entries), TradeZero International
costs, v31's liquidation checked every minute, the four cost sets (base, HOT 5%, spreads x2, high), the $10,000
level for the grid, v29's bootstrap (4,000 one-year paths from $5,000; ruin at or under $1,250). v43's replay gains
three hooks, inactive by default (the v43 and v44 tests still pass): a stop level, a cover set off before the open of
a carried session (after-hours or premarket), and a close entry moved into the after-hours.

## 2. The dimensions (each value's signal uses only bars up to the bar it fires on; fills from the next bar)

Indicators on the regular-session one-minute bars of the session: RSI (Wilder), EMA, MACD (12, 26, 9), Bollinger
(20), ATR (14, Wilder), SuperTrend, Parabolic SAR (0.02, 0.02, 0.2), Heikin-Ashi, stochastic %K (14, 3), Donchian,
VWAP and v44's z-score to it, volume over the session's running median.

| dimension | values | n |
|---|---|---|
| entry trigger (open entries) | none; T9 RSI(14) crosses under 70; T10 RSI(7) under 80; T11 MACD histogram turns negative; T12 a close back inside the upper Bollinger(20, 2); T13 EMA 9 crosses under EMA 20; T14 SuperTrend(10, 3) turns down; T15 Parabolic SAR turns down; T16 the first red Heikin-Ashi bar after 3 or more green; T17 a shooting star at a new session high; T18 a close back under the premarket high after trading above it; T19 a close under the premarket low; T20 a close under the 15-minute opening range low; T21 stochastic %K crosses under 80; T22 a climax bar (volume >= 3 x the running median, a new session high, the close in the bar's lower half); T23 a double top (a high within 1% of a session high set 10 or more bars before, red close); T24 the z-score to VWAP back under 2 from above. Windows: within 15 minutes (else skip), 30 (skip), 30 (else enter at the deadline), 90 (deadline), 180 (deadline) | 81 |
| close entry timing (close entries) | the auction (now); market at 15:51, 15:55; after-hours market at 16:05, 16:15, 16:30, 17:00, 18:00, 19:00, 19:55; after-hours sell limit at the close x 1.02, 1.05, 1.10 (unfilled by 19:59: no trade); the 16:00-16:59 after-hours VWAP | 14 |
| stop | the shield's (now); none; the highest high of the entry session before the entry x 1.01, 1.03, 1.05, 1.10 (if under the entry: the entry x the same); the entry + 5, 10, 20 x the ATR(14) of the bars before the entry; the entry x 1.10, 1.20, 1.30, 1.50 | 13 |
| TA exit (a cover set off at a bar's close in the regular session) | none; RSI(14) under 15, 20, 25; RSI(7) under 10, 15; RSI(14) crosses up 25, 30; a low at the lower Bollinger(20) at 2, 2.5, 3 sd; a close back over VWAP after 10, 30, 60 bars under it; EMA 9 over 20; EMA 20 over 50; MACD histogram turns positive; SuperTrend(10, 2), (10, 3) turns up; Parabolic SAR turns up; 2, 3 green Heikin-Ashi bars after a red; a hammer at a new session low; a capitulation bar (volume >= 3, 5 x the running median, red, lower wick >= half the range); a high over the prior 15, 30, 60 bars' highest; stochastic %K crosses up 20; time covers at 10:00, 10:30, 11:00, 11:30, 12:00, 13:00, 14:00, 15:00, 15:30 | 38 |
| overnight cover (carried sessions, before 09:30) | the open auction (now); premarket market at 04:00, 05:00, 06:00, 07:00, 08:00, 08:30, 09:00, 09:15, 09:25; a premarket or after-hours target at the last close x 0.97, 0.95, 0.90, 0.85; a premarket stop at the last close x 1.05, 1.10, 1.20; after-hours market at 16:05, 17:00, 19:55 | 20 |
| execution (open entries) | the auction (now); v44's TWAP 3; v44's passive limit | 3 |
| filter (meta-label at the entry) | none; 22 new features at the entry, skip the top or the bottom tercile (cuts from the trades of the years before): RSI 14, RSI 7, MACD histogram / price, Bollinger %b, Bollinger width, ATR / price, stochastic %K, EMA 9 / EMA 20, close / EMA 50, CCI 20, Williams %R 14, MFI 14, OBV change over 30 bars / their volume, VWAP slope over 30 bars, position in the 30-bar range, 5- and 30-bar returns, mean upper-wick share of the last 5 bars, green bars in a row, Heikin-Ashi green bars in a row, skew of the last 60 one-minute returns, bars since the session high / bars; 2 binary features (SuperTrend and SAR direction), skip either value; a logistic regression and a gradient boosting (depth 3, 100 trees) trained each year on the trades before it on v44's 26 and these 24 features, target net return > 0: skip p < 0.4, p < 0.5, size x (0.5 + p) | 55 |

Open entries use the bars 04:00-09:29 for their features; close entries the session's bars to 15:49. After-hours
market and VWAP entries and every cover before the open pay one extra tier half-spread (v19r's) on top of the
daily model's cost; after-hours limit entries pay none.

## 3. The run (two stages, chosen in advance)

- **Stage 1 (one dimension at a time)**: the base book and every non-base value of each replay dimension with the
  others at the base: 1 + 80 + 13 + 12 + 37 + 19 + 2 = **164 replays**, each with the 55 filters at the four cost
  sets = 9,020 books x 4, plus each replay's base-cost book on the two symbol halves. 164 runners.
- **Selection** (rule fixed now): for each replay dimension, the 7 values with the highest 2018-2022 summed log
  growth at base costs among those whose worst 2018-2022 yearly drawdown is no worse than the base's (filled by
  2018-2022 log growth alone if fewer than 7 are eligible), plus the base value; all 3 executions; the 7 filters chosen
  the same way on the base replay, plus none. 2023+ is not used to build the stage 2 grid.
- **Stage 2 (the factorial)**: 8 x 8 x 8 x 8 x 8 x 3 = **98,304 replays** x 8 filters = **786,432 books** at the four
  cost sets (3,145,728), each as yearly log growth and worst drawdown at $10,000. 300 runners of 4 CPUs.
- **Final**: v43's walk-forward rule on the stage 2 books (each year after the first, among the books whose worst
  yearly drawdown before it is no worse than the base's, the highest summed log growth before it; 2018 the base);
  the bootstrap of the walk-forward book and the base at the five levels and four cost sets; the symbol halves.

A canary first (V29_QUICK: two replays per shard on the real cached data, every stage and the final).

## 4. The questions and the pass marks

- **Q1 (the walk-forward book improves the book)**: its median >= 1.15 x the base's, ruin <= 2.5% at base costs and
  at HOT 5%, its high-cost median >= the base's, summed log growth better than the base's on both symbol halves, and
  its 2023+ bootstrap median >= the base's 2023+ median.
- **Q2 (descriptive)**: the stage 1 values that beat the base's summed log growth in all four cells (2018-2022 and
  2023+, by symbol half) at base costs and over all years at HOT 5%.
- **Q3 (descriptive, in sample)**: the fixed book made of each dimension's Q2 value with the highest all-years log
  growth (the base where none), and the best Q2 filter: bootstrap, stress and halves.
- **Q4**: from $2,000 (ruin at or under $500): the base, the walk-forward book, Q3's book.
- **Check**: the base book must reproduce v44's central case (median $22,006, ruin 0.1%) within $200 and 0.2 points.

## 5. Caveats fixed now

Every year 2018-2026 has been seen; the book was chosen on them; the stage 2 grid is built on 2018-2022 so its
walk-forward years 2019-2022 are not clean, 2023+ is cleaner but seen by the researcher. Grids this large overfit
(v43: walk-forward ruin 10.3%; v44: 10.5%): the pass marks, the symbol halves and Q1's 2023+ condition are the
guards. After-hours shorting needs a locate the evening before and TradeZero's after-hours short rules are not
modelled beyond the spread; bar-less minutes do not fill. The bot would need minute data for many of these rules:
the owner's constraint (no paid data) applies to any rule that passes, and is reported.
