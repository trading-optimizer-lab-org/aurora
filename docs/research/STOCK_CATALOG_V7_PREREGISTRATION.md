# US stock strategy catalog v7 (235,200 trials): pre-registration

Written and committed on 2026-10-18 **before any v7 result was computed**,
after v1-v6 were seen. Everything not stated (data, checks, universe,
indicators, costs, 0.5% risk / 20% cap sizing, engines, periods, pass
criteria) is as in v1-v6. Survivorship bias not adjusted (owner's choice).
Locked period 2021+ never read. Exact rules are the code in
`research/stock_catalog_v7.py` and the modules it reuses.

## Dimensions

80 entries x 30 exits x 14 filter sets x 7 initial stops = **235,200 trials**,
named `<entry>_<exit>_<filters>_<stop>`.

### Entries (80)

The 51 of v6 (S1-S7, S2T, S10-S14, S18-S55) plus 29 new:

- Candles: S56 hammer at a rising SMA50/EMA21 · S57 morning star above SMA200 ·
  S58 three white soldiers above SMA50 · S59 inside-bar breakout in an uptrend ·
  S60 NR4 breakout above SMA50.
- Calendar: S61 last trading day of the month, RS >= 80 · S62 day before a market
  holiday, RS >= 70 · S63 first trading day of January, RS >= 90.
- Short-term mean reversion in uptrends: S64 IBS < 0.2 above SMA200 · S65 RSI(2) < 5
  above SMA200 · S66 close below the lower Bollinger band with RSI(14) < 30 above
  SMA200 · S67 three closes below EMA20 - 1.5 x ADR above SMA200.
- Multi-timeframe: S68 weekly-equivalent MACD (EMA60 - EMA130 vs its EMA45) above
  its signal, a touch of EMA21 in the last 3 days and an up close above EMA10 ·
  S69 previous month closed at an all-time monthly high, then a 20-day-high breakout.
- Monthly cross-sectional ranks (month end): S70 lowest 10% 63-day volatility above
  SMA200 · S71 "frog in the pan": top 30% 12-1 momentum and top 20% share of up days
  over a year · S72 top 10% closeness to the 52-week high (George-Hwang) · S73 bottom
  10% 21-day return while above SMA200 (short-term reversal).
- Relative: S74 20-day return >= 10 points above the industry median and a 20-day-high
  breakout · S75 the industry's equal-weight index at a 252-day high and the stock
  (RS >= 90) at a 20-day high.
- Volatility: S76 ADR at a 252-day low within the last 5 days, then a 20-day-high breakout.
- Two-signal confluence (second signal within the last 5 days): S77 VCP + pocket
  pivot · S78 high tight flag + volume dry-up pullback · S79 golden cross + RS line
  lead · S80 Weinstein Stage 2 + industry RS >= 85 · S81 9/21 pullback + OBV at a
  50-day high · S82 52-week high + up/down volume ratio >= 1.5.
- S83 within 2% of the 52-week high after a 5-day volume dry-up (< 0.7 x average)
  and an up close · S84 inside-week breakout (5-day range inside the prior 5-day
  range, close above it) above SMA50.

### Exits (30)

The 23 of v6 plus 7 new:
- `XCH` chandelier: stop at the highest high since entry minus 3 x ADR (at entry).
- `XSAR` parabolic-style: the stop moves up each day by an acceleration factor x
  (highest high - stop), the factor starting at 0.02 and rising 0.02 with each new
  high, capped at 0.2.
- `XDEC` decaying trail: trailing stop at the highest close x (1 - k x ADR) with
  k = 8 minus 0.25 per week held, never below 2.
- `XS100`: first close below SMA100.
- `XLOW50`: first close below the lowest low of the prior 50 days.
- `XKELL`: after any close >= +20% from entry, sell at the first close below EMA10;
  before that, sell at the first close below SMA50.
- `XT8H`: 8 x ADR trailing stop, and sell half when the price reaches +50%.

### Filter sets (14)

G0-G9 as in v6, plus: G10 CALM (S&P 500 20-day realised volatility below its
252-day median) + MF · G11 BREADTH (more universe stocks in perfect uptrends than
downtrends) + ADR4 · G12 CALM + IND85 + ADR4 · G13 MF + IND50 + ADR4 + no entries in
September or October.

### Initial stops (7)

`SS` the entry's own stop (as before) · `A1`, `A15`, `A2`, `A3`, `A5`, `A8`: close x
(1 - k x ADR) with k = 1, 1.5, 2, 3, 5, 8. Position size follows from the stop (0.5%
risk, 20% cap) as before.

## Selection and reporting (designed for 235,200 trials)

- Validation is also split into **2011-2015** and **2016-2020**.
- Train-only selection: the top 50 by train trade-level PF with >= 300 train trades.
- "Robust" list (descriptive): PF >= 1.3 with >= 100 trades in train, 2011-2015 **and**
  2016-2020.
- Portfolio pass criteria as before on 2011-2020; deflated Sharpe over all v7 trials
  plus the earlier ones.
- Marginal tables: median PF by entry, exit, filter set and stop, per period. These
  summaries over thousands of trials are the main output; single trials are
  expected to include many lucky ones.

## Execution

GitHub only (`stock-ideas-v7.yml`): 320 jobs (80 entries x 4 exit groups) in two
matrices of 160, 4 worker processes each, plus a merge job. Shards write compact
per-trial rows (parquet), not daily returns.
