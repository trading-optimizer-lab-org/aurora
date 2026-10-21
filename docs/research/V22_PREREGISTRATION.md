# v22: technical analysis on small caps (88,254 configurations): pre-registration

Written and committed on 2026-10-21, before any v22 result was computed, at the owner's request ("propon un v22, del
estilo de las v20 y v21 ... centrado en analisis tecnico, patrones tecnicos e indicadores"; "amplialo. y lanzalo").
Exact rules: `research/v22_ta.py` (daily), `research/v22_intra.py` (intraday), `scripts/run_v22.py`; tests in
`tests/test_v22.py`.

## 1. Data, universe, honesty

- The v18b inputs through 2026-10-16. **Daily families scan every small cap**, not only event days: each day, every
  stock with a raw close in the price band ($1-3, $3-8, $8-20) and $1M of 20-day dollar volume. Intraday families use
  the minute bars of event days (gap-ups, runners, gap-downs) in the same bands.
- Walk-forward 2018-01 to 2026-10-16, each year's choice on earlier data only. Indicators use split-adjusted prices and
  only bars up to the signal day's close. No window is clean for the researcher (v14-v21 were run on the same data);
  technical analysis on small caps was not tested before in this series, apart from Donchian-style breakouts in the
  2026-10-18 catalog grids.

## 2. Costs, sizing, books

- **R4** (v21's calibration on 27,782 measured quote legs): half-spread by tier and leg time (open / session / last
  minute): under $2 0.66% / 0.47% / 0.58%, $2-5 0.80% / 0.36% / 0.48%, $5-10 0.82% / 0.40% / 0.46%, $10-20 0.99% /
  0.51% / 0.45%; slippage of a quarter of the bar beyond the level on stop-type fills; IBKR tiered all-in $0.0065 a
  share a leg (at most 1%) with SEC and FINRA fees; borrow availability x0.8 and fees doubled with a 100% floor, per
  night; the short-sale restriction. Scenarios: middle; low (half-spreads x0.5); high (x2, borrow x3); **auction**
  (open and close legs at the session's half-spread, as opening and closing auction orders); gross (no costs, no
  slippage).
- Daily: 5% a position, at most 20 open, gross 100%; **at most 30 signals a day enter the book, the highest priority
  first** (the book cannot take more), and a symbol is not entered again while a trade on it could be open. Intraday:
  v14 sizing as v19-v21.

## 3. Hypotheses (grids)

Daily (entry at the signal day's close or the next open where stated; exits: tN = N sessions; indicator exits at the
first close where the condition holds, within 40 sessions; atrK = a trailing stop K ATRs(14) from the best close;
targetX; stops as fractions, in ATRs, at the pattern's extreme, or close-based c50):

| family | signal | grid | n |
|---|---|---|---|
| RS_RSI | RSI(n) at or below the level (long) or at or above 100 minus it (short) | n {2, 3, 5, 14} x level {5, 10, 25} x side x trend {none, above or below SMA200, above SMA50} x entry x exit {RSI back to 50, close beyond SMA5, t3, t5, t10} x stop {none, 10%, 20%} x band | 8,640 |
| BB_BOLL | close beyond Bollinger bands, faded or followed | n {10, 20, 50} x k {2, 2.5, 3} x mode x side x trend {none, SMA200} x entry x exit {middle, opposite band, t5, t10, atr2} x stop x band | 6,480 |
| MA_CROSS | moving-average cross, or a pullback to the fast average in trend | pair {5/20, 10/50, 20/100, 50/200, 10/20, 20/50} x SMA or EMA x signal x side x entry x exit {cross back, close beyond the fast, atr3, t20} x stop x band | 3,456 |
| DN_DONCHIAN | close beyond the N-day high or low | N {10, 20, 55, 120, 252} x volume {any, 1.5x, 3x} x close location {any, top or bottom quarter} x side x entry x exit {5/10/20-day low or high, atr2, atr3, t10, t20, t40} x stop {none, 8%, 15%} x band | 8,640 |
| FB_FAILBREAK | a break of the N-day high (low) within 1-3 days, then a close back inside | N {20, 55, 252} x within x volume {any, 2x} x side x exit {t3, t5, t10, target20, new extreme} x stop x band | 1,080 |
| CS_CANDLE | 14 candles: engulfing, hammer, shooting star, doji at a 20-day extreme, inside-bar break, outside bar, NR7 break, three soldiers or crows | pattern x context {any, after -15%/+15% in 3 days, -20%/+20% in 5, -50%/+50% in 20} x entry x exit {t1, t3, t5, t10, target10} x stop {the candle's extreme, 10%, none} x band | 5,040 |
| MC_MACD | MACD signal cross, zero cross, histogram turn, divergence at a 20-day extreme | set {12/26/9, 5/35/5, 3/10/16} x signal x side x trend x entry x exit {opposite cross, t5, t10, t20, atr3} x stop x band | 6,480 |
| SO_STOCH | stochastic cross inside the zone, or leaving it | set {14/3, 5/3} x level {20, 10} x signal x side x trend x entry x exit {opposite zone, t3, t5, t10} x stop x band | 3,456 |
| AX_ADX | +DI/-DI cross or a pullback to EMA20 with ADX above a threshold | threshold {20, 25, 30} x signal x side x entry x exit {DI cross back, atr3, t10, t20} x stop x band | 864 |
| VC_BASE | a tight base (range of the last 10/20/40 days within 10/20/30%) broken on volume | length x tightness x prior rise {0, 30%, 100%} x volume dry-up x breakout volume {1.5x, 3x} x entry x exit {10/20-day low, close below SMA10, t20, t60, target20, target50} x stop {base low, 8%, 15%} x band | 13,608 |
| EX_EXTEND | close 3/4/6/8 ATRs beyond EMA10/20/50, faded | EMA x ATRs x side x confirmation {none, candle colour, lower high or higher low} x entry x exit {back to the EMA, t3, t5, t10, target20, target30} x stop {none, 1 ATR, 20%, c50} x band | 10,368 |
| IB_IBS | close location in the day's range at an extreme | threshold {0.05, 0.10, 0.20} x side x trend x prior day move {any, 10%} x exit {next open, next close, IBS back to 0.5, t3} x band | 432 |
| VO_CLIMAX | volume 3/5/10x with an upper or lower wick, or a big body | multiple x candle x after {any, +50% or -30% in 5 days} x entry x exit {t1, t3, t5, t10, target20} x stop x band | 3,240 |
| DV_DIVERGE | a 20/55-day closing extreme with RSI(5/14) above (below) its own earlier extreme | RSI x lookback x side x confirmation x entry x exit {t5, t10, t20, RSI back to 50, atr3} x stop x band | 1,440 |
| GP_GAPDAY | a gap of 5-40% up or down that closes with it or against it | gap x direction x close x entry x exit {t1, t3, t5, gap fill, target20} x stop x band | 1,800 |

Intraday (minute bars of event days; scope {gap-ups, runners, gap-downs}; entries at the signal bar's close or the
break of a flag; exits: close, d3, next open, 2R, trail20, or the indicator exit; stops: swing (the 10 bars before),
the session's extreme, the flag's extreme, 10%, 20%):

| family | signal | grid | n |
|---|---|---|---|
| IE_EMA | EMA cross (spans x1, x3, x5 for longer bars) after 09:45 or 10:30 | pair {5/13, 9/20, 20/50} x multiple x side x scope x after x exit {cross back, close, d3, next open} x stop x band | 3,888 |
| IV_VWAPBAND | close beyond VWAP +- k volume-weighted deviations, faded or followed | k {1, 1.5, 2, 3} x mode x side x scope x after x exit {touch of VWAP, close, d3, next open} x stop x band | 3,456 |
| IR_RSI1M | one-minute RSI(7/14) at 80/90 (20/10) | n x level x side x scope x confirmation {none, a turn} x exit {RSI back to 50, close, d3, next open} x stop x band | 1,728 |
| IM_MACD | MACD on five-minute-equivalent spans: signal or zero cross | set x signal x side x scope x after x exit {cross back, close, d3, next open} x stop x band | 1,728 |
| IF_FLAG | a pole of 10/20/40% within 15 minutes, a pullback of at most 38/50/62% over 3-10 bars, the break | pole x retrace x side x scope x exit {close, 2R, trail20, d3, next open} x stop x band | 2,430 |

Total 88,254 configurations; every one counts as a trial for the deflated Sharpe.

## 4. Selection, tests, criteria

- **Activity rule (new):** in the walk-forward, a configuration can be picked for year Y only with at least 50 trades
  and a trade in at least 40% of the months before Y; the plateau score averages only such neighbours. The best design
  configuration of a family is chosen among those active over the whole period.
- **Placebos:** 500 for each picked or best configuration (daily: a random symbol of the band that day, same entry,
  side and exit terms; intraday: a random candidate of the scope and band that day, same minute, side, stop distance
  and exit), at the middle costs. The gate and COMBO22 use them as v14.
- **Hansen's SPA test** (consistent version, stationary bootstrap, 1,000 draws, mean block 6 months) of each family's
  active configurations' monthly returns over cash: whether its best configuration beats cash after costs given how
  many were tried. It replaces v20-v21's false discovery rate against placebos, whose placebos lose under costs.
- CPCV PBO on the active configurations; the deflated Sharpe over all trials; COMBO22 by v14's rule.
- **Success**: COMBO22 walk-forward monthly Sortino >= 4 over 2018-2026, >= 3 in 2018-2020 and in 2021-2026,
  PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16, at the middle (R4) costs.

## 5. Running

A canary (the first and last configuration of every family on the real inputs), then 300 shards x 4 processes of
real returns (contiguous blocks, so neighbouring configurations share their indicators), the selection, 300 shards x 4
processes of placebos, and the report.

## Amendment after the first run (2026-10-21): v22b, a look-ahead in the intraday runner scope

The first run (39556504856, report rebuilt in 39562299158) gave the five intraday families walk-forward Sortinos at
the cap of 20 and 89-500% a year at every cost level, while the median configuration of each of them lost (Sortino
-1.4 to -2.8). Every pick was a long in the **runner** scope, and that scope is defined by the day's high (a rise of
40% above the prior close at some point of the session): a long entered before the rise knew that it was coming. v14
to v21 used runners only with entries after the rise (the run-up condition was part of the entry). The daily families
do not use the scope and are not affected.

v22b fixes it and reruns the whole of v22, rules and grids otherwise unchanged: (1) a runner is traded only once its
high so far is 40% above the prior close; (2) a signal known at a one-minute bar's close is filled at the next bar's
open (not at that close, a single print in a small cap), an indicator exit likewise, and the VWAP-touch exit is a
resting limit at the VWAP of the bar before. The first run's intraday results and its COMBO22 are void.
