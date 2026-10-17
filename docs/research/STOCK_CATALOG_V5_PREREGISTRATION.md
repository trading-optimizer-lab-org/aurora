# US stock strategy catalog v5 (new entries x new exits): pre-registration

Written and committed on 2026-10-17 **before any v5 result was computed**,
after v1-v4 were seen. Everything not stated (data, checks, universe,
indicators, costs, 0.5% risk / 20% cap sizing, engines, trade-level view,
periods, pass criteria, train-only top-15 selection with >= 300 train trades,
the "stable" list) is as in v1-v4. Survivorship bias not adjusted (owner's
choice). Locked period 2021+ never read. Exact rules are the code in
`research/stock_catalog_v5.py`, summarised here.

## 20 new entries (signal at the close, filled at that close)

| Setup | Idea | Stop |
|---|---|---|
| S26 strong_closes | three closes in the top 10% of the day's range, the last one a new 20-day high | lowest low of 3 days |
| S27 dryup_pullback | Stage 2; 5-day volume < 0.6 x 50-day average; yesterday within 3% of EMA21; up close on rising volume above EMA21 | lowest low of 5 days |
| S28 engulf_sma50 | bullish engulfing with the low within 2% of a rising SMA50, above SMA200 | today's low |
| S29 oops | Larry Williams: open below yesterday's low, close up, uptrend (above rising SMA50) | today's low |
| S30 weekly_breakout | weekly close above the highest close of the prior 130 days | close x (1 - 3 ADR) |
| S31 rs_line_lead | RS line (stock / S&P 500) at a 252-day high while the price is still >5% below its high, above SMA50 | close x (1 - 2 ADR) |
| S32 mom_12_1 | month end, top decile of 12-1 month return in the universe, above SMA200 | close x (1 - 3 ADR) |
| S33 low52_reclaim | within 15% of the 52-week low, close crosses above SMA20 on 1.5 x volume | lowest low of 10 days |
| S34 capitulation | down >= 25% in 10 days, volume >= 3 x average, close in the upper half of the range and above the open | today's low |
| S35 thrust_day | range >= 2 x ADR, close in the top 20% of the range, up close, above a rising SMA50 | today's low |
| S36 golden_cross | SMA50 crosses above SMA200 | close x (1 - 3 ADR) |
| S37 macd_cross | MACD(12,26) crosses above its 9-day signal while positive, above SMA200 | close x (1 - 2 ADR) |
| S38 keltner | close crosses above EMA20 + 2 x ADR (in price), above SMA50 | EMA20 |
| S39 post_thrust_pullback | a >= 15% 3-day thrust in the last ~10 days, then a 7-15% pullback from the 10-day high, today up | lowest low of 5 days |
| S40 lower_band | close below the lower Bollinger band (20, 2) while above SMA200 | close x (1 - 3 ADR) |
| S41 staircase | five consecutive higher lows, 5-day range <= 2 x ADR, above EMA21 | lowest low of 5 days |
| S42 leader_leader | industry RS >= 90, stock RS >= 95, new 20-day high | lowest low of 10 days |
| S43 short_base | 60-day base no deeper than 15%, breakout above its high on 1.5 x volume | lowest low of 10 days |
| S44 tight_closes | the three closes before today each within 0.5% of the previous one, then a close above the last two highs, above a rising SMA50 | lower of the last two lows |
| S45 ignition | top 1% 5-day return in the universe, above SMA50 | close x (1 - 2 ADR) |

## 12 exits (plus the setup's stop)

| Exit | Rule |
|---|---|
| XT5 | trailing stop at the highest close x (1 - 5 x ADR at entry) (v4's best) |
| XS50 | first close below SMA50 |
| XT8 | trailing stop at 8 x ADR |
| XBE | stop to break-even once a close reaches +1R; exit on the first close below SMA20 |
| XR3 | profit target at +3R (fills at the target or the open if it gaps above); else exit after 60 days |
| XTIME20 / XTIME60 | sell at the close of day 20 / 60 |
| XLOW10 / XLOW20 | first close below the lowest low of the prior 10 / 20 days (Turtle-style) |
| XRSI80 | sell when RSI(14) closes above 80 (sell into strength) |
| XEXT | sell when the close is >= 25% above SMA50 (extended, Minervini) or below SMA50 |
| XWK | weekly: on the last trading day of a week, sell if the close is below SMA50 |

## 4 filter sets

G0 none · G1 MF + IND50 + ADR4 · G3 MF + IND85 + ADR4 · G4 MF + IND50 + ADR4 +
RS80 (as defined in v4).

## Grid

20 x 12 x 4 = **960 trials**, named `<setup>_<exit>_<set>`. Deflated Sharpe
over these plus the 1,084 of v1-v4 (2,044 trials). Run on GitHub only
(`stock-ideas-v5.yml`): 20 parallel shards (one per setup) plus a merge job.
