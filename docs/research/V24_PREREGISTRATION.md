# v24: long-only small caps on one-minute bars (208,032 configurations): pre-registration

Written and committed on 2026-10-21, before any v24 result was computed, at the owner's request ("haz un v24 ...
centrado en small caps ... prueba en grid. todo tipo de entradas y de salidas - con costes lo mas realistas posibles -
tenlo todo en cuenta - y que haga analisis tecnico, patrones tecnicos e indicadores de todo tipo, y tambien nuevas
ideas que tu me proponga e ideas que encuentres en internet, tambien soportes y resistencias. todo en grafico de 1
minuto - solo en long"). Exact rules: `research/v24_long1m.py`, `research/v24_patterns.py`, `research/v24_fast.py`,
`scripts/run_v24.py` (on `scripts/run_v22.py`), the data in `scripts/run_v24_data.py`; tests in `tests/test_v24.py`.

Context: every small-cap long family tested so far (v14-v23) failed after costs, most of them even before costs;
v24 tests the long side alone with the widest set of one-minute rules of the series, on two universes the earlier
long tests did not have (the moderate gappers and the liquid non-event days).

## 1. Data

- **New: the v24 mover store** (`scripts/run_v24_data.py`, run 39591258262, Actions cache `v24-store-*`): Alpaca SIP
  one-minute bars (04:00-15:59 ET, raw prices) of the **100 small caps of every session with the largest absolute
  opening gap of at least 4%** (open over the prior close, known at 09:30; prior close $1-$20, prior 20-day dollar
  volume >= $500k), leaving out that day's v23 top-100 liquid set, 2016-01-04 to 2026-10-16; same layout and facts as
  the v23 store (symbol-days with at least 30 regular-session bars). Scopes **mover_up** (gap > 0), **mover_dn**.
- The v23 store (the 100 most liquid small caps of every session): scope **liquid**.
- v14's event days: **gapup** (gap >= 15%, top 80 a day), **runner** (high >= +40%, traded only once risen by the
  bars before the entry bar), **gapdown** (gap <= -20%), **day2** (prior day >= +50%).
- **inplay**: liquid or mover candidates whose first five minutes traded at least 3x (6x) the prior 20-day average
  per five minutes, or the top 5/10/20 of the day by that ratio (known at 09:35; entries from 09:35).
- Daily facts from the sessions before only (tested): 20/60/252-day highs, 20/60-day lows, 20/50/200-day averages,
  14-day ATR, the 60-day return, two red days in a row, the prior day's move and close location.
- Price bands by the day's raw open: $1-3, $3-8, $8-20. Walk-forward 2018-01 to 2026-10-16. No window is clean for the
  researcher.

## 2. Costs, sizing

R4 as v22 and v23 (half-spreads by tier and leg time from 27,782 measured quote legs, a quarter of the bar of slippage
on breakouts and stops, IBKR all-in commissions with SEC and FINRA fees); longs pay no borrow and have no short-sale
restriction. Scenarios low (spreads x0.5), high (x2), auction (open and close legs at the session half-spread) and
gross. v14 intraday sizing (0.5% of the account at risk to the stop, at most 20%, at most 2% of the dollar volume traded
before the entry, the first five trades a day by minute); one trade per configuration and symbol-day (its first
signal).

## 3. Hypotheses (all long; grids)

Common exits: R multiples (r1-r5), trailing stops (trail5/10/20), the close, the next open, the second, third and
fifth session's close (d2, d3, d5), up to five sessions out at the first close against (g5), minutes (t15, t30), the
first close below EMA9 (ema9) or VWAP (vwapx), the EMA cross back, the next level, the pattern's measured move, the
prior close (fill) or half the gap (half) or the day's open (openx) as limits, VWAP as a limit (tovwap), the
indicator's own opposite signal (opp), break-even after 1R (be1r), half at 2R and half at the close (scale).

Sources found on the web for this version: Zarattini, Barbon and Aziz (2024), "A Profitable Day Trading Strategy For
The U.S. Equity Market" (5-minute opening range breakout on stocks in play by relative volume; SP); Zarattini, Aziz and
Barbon (2024), "Beat the Market" (the noise boundary; NB); Zarattini and Aziz (2023), the VWAP trend (LV's reclaim, NB's
VWAP trail); Gao, Han, Li and
Zhou (2018, JFE), "Market intraday momentum" (the first half hour predicts the last; LH); Aziz's ABCD (AB) and opening
range; the micro pullback / first pullback of small-cap momentum traders (MP); the morning panic dip buy, the first
green day and red-to-green (MD, RG); LULD halts and resumptions (HR); Raschke's Holy Grail (HG); George and Hwang
(2004), the 52-week high (DL level h252). Heston, Korajczyk and Sadka's (2010) half-hour periodicity needs each stock's
same half hour on earlier days, which the stores do not keep, so it is not tested.

| family | signal | grid | n |
|---|---|---|---|
| DL_DAILY | daily levels (20/60/252-day high, 20/60-day low, 20/50/200-day average): first close above, a dip through by 0.2% and back within three bars, a retest after the break | level (8) x setup (3) x volume {any, 2x} x window x stop {1% under the level, 10%} x exit {2R, next level, EMA9, close, d3, trail10} x scope {liquid, mover_up, mover_dn, gapup, runner, gapdown} x band | 31,104 |
| SR_LONG | v23's 18 intraday levels, the three long setups, on the scopes v23 did not have | level (18) x setup (3) x volume x window x stop x exit {2R, next level, EMA9, close, d3, be1r} x scope {mover_up, mover_dn, gapdown, day2} x band | 46,656 |
| LV/LE/LO/LM/LS/LP/LC/LX/LR | v23's VWAP, EMA, oscillator, MACD, squeeze, pattern, candle, climax and ORB families, long side only, on mover_up, mover_dn, gapdown, day2 | v23's grids with the long values | 23,568 |
| SP_INPLAY | the k-minute opening range break of stocks in play (first candle green or any; gap up or any) | selection {top 5, 10, 20, rv >= 3, >= 6} x k {5, 15, 30} x candle x gap x stop {10% / 25% of the daily ATR, the range's low} x exit {close, 2R, 5R, trail10, VWAP, next open} x band | 3,240 |
| NB_NOISE | close above max(open, prior close) x (1 + k x ATR% x sqrt(minutes / 390)), every minute or on the half hours | k {0.5, 1, 1.5, 2} x check x filter {none, above VWAP, rv >= 2} x stop {5%, 10%} x exit {back under the boundary or VWAP, close, 2R, trail10, next open} x scope {liquid, mover_up, gapup, inplay} x band | 2,880 |
| LH_LATE | up 2/5/10/20% from the prior close at 10:00, buy at 14:00, 15:00 or 15:30 | up x filter {none, above VWAP, within 3% of the high} x time x stop {10%, 20%} x exit {close, next open, d2, d3} x scope x band | 3,456 |
| PH_POWER | first close above the high of the day after 13:30/14:00/14:30, up 0/5/10% on the day | after x day x volume x stop {swing, 5%, 10%} x exit {close, next open, d2, d3, trail5} x scope x band | 3,240 |
| MP_MICRO | a new high 3/6/10% above the ten-bar low, one to three bars of pullback (at most 1/3 or 1/2), the break of the prior bar's high | impulse x retrace x volume {any, drying} x window {09:30-10:30, all} x stop {pullback low, 5%} x exit {2R, 3R, trail5, trail10, EMA9, close} x scope {gapup, runner, mover_up, liquid, day2} x band | 4,320 |
| AB_ABCD | A, B a high 5/10/20% above A, C a pullback of 38-62% (24-50%) of AB; entry at C (a close above the prior bar's high) or at the break of B | run x retracement x entry x stop {C, 10%} x exit {C + AB, 2R, trail10, close, EMA9, d3} x scope x band | 2,160 |
| HR_HALT | a pause of four or more minutes after a 5-bar move of 8/15% up or down; buy the resumption (if it reopens at or above), the first close above the resumption bar's high, or the first dip bought | direction x move x entry x stop {pre-pause low or the low since, 10%, 20%} x exit {2R, trail10, trail20, close, next open, t15, EMA9} x scope x band | 3,780 |
| MD_MORNDIP | a low 10/20/30% under the high of the day before 10:00 (10:30), then a green 5-minute bar, a VWAP reclaim, a higher low or RSI(7) under 20 turning up, within the hour | drop x window x trigger x stop {low of the day, 10%} x exit {2R, the open, trail10, close, next open, EMA9} x scope x band | 4,320 |
| RG_RED2GREEN | open under the prior close (by 0/2/5%), the first close above it after 09:35 (09:45) | gap x after x context {any, two red days, above the 20-day average} x volume x stop x exit x scope {liquid, mover_dn, gapdown} x band | 3,888 |
| GF_GAPFILL | gap down 4/8/15%: opening range high, VWAP reclaim, higher low, or above the open at 10:00 | gap x trigger x stop x exit {the prior close, half the gap, close, next open, d3, 2R} x scope x band | 1,620 |
| D2_GO | prior day up 20/50/100% (closing in its top 20% or anywhere): premarket high, opening range, VWAP after 10:00, or the open if it gaps up | day1 x location x trigger x stop x exit x scope {day2, liquid, mover_up} x band | 3,240 |
| IX_IND | 16 indicators on 1/5/15-minute bars: SuperTrend flip, Parabolic SAR flip, Heikin-Ashi turn, Ichimoku (Tenkan over Kijun above the cloud), CCI over -100, Williams %R over -80, MFI over 20, OBV new high under the price high, Aroon, Donchian 20/55, Keltner, ROC, TRIX, ADX with +DI cross, EMA9 > EMA20 > VWAP | indicator x timeframe x filter {none, VWAP, EMA50} x stop {swing, 10%} x exit {opposite signal, 2R, trail10, EMA9, close, d3} x scope {liquid, mover_up, gapup, runner} x band | 20,736 |
| PX_PATTERN | inverse head and shoulders, triple bottom, cup and handle, rectangle, pennant, intraday high tight flag | pattern x size x after {09:45, 10:30} x break volume x stop {pattern, 10%} x exit {measured move, 2R, trail10, EMA9, close, d3} x scope x band | 6,912 |
| CK_CANDLE | hammer, bullish engulfing, morning star, piercing, three white soldiers, harami, tweezer bottom, marubozu, dragonfly doji on 1/5/15-minute bars, after a 3% drop, at the low of the day, at VWAP, at a level or on a pullback in trend | pattern x timeframe x context x volume x stop {candle low, 10%} x exit {1R, 2R, trail10, t30, close} x scope {liquid, mover_up, mover_dn, gapup} x band | 32,400 |
| WO_WASH | 4/7 red bars in a row, 10/20/30% under the high of the day, a minute of 3x/6x volume; the first higher high or a close above the three bars before | drop x reds x climax x confirmation x stop x exit {2R, t30, VWAP, trail10, close, next open} x scope x band | 5,184 |
| HG_GRAIL | ADX over 25/30 with +DI over -DI, a bar touching EMA20, EMA9 or VWAP, the break of its high | ADX x timeframe {1, 5} x line x stop x exit {2R, trail10, EMA cross back, close, d3} x scope x band | 1,440 |
| TS_TREND | a daily uptrend (close over the 20-day over the 50-day average, within 5% of the 20-day high, or up 30% in 60 days) and a dip of 3/6/10% from the open; VWAP reclaim, a green 5-minute bar, RSI(2) of 5-minute bars under 10 turning, back over the prior close | context x dip x trigger x stop x exit {2R, close, next open, d3, d5, g5} x scope {liquid, mover_dn, mover_up} x band | 3,888 |

Total 208,032 configurations in 28 families; every one counts as a trial for the deflated Sharpe.

Fills (as v22b-v23b): a signal known at a bar's close enters at the next bar's open and an indicator exit leaves there;
level breaks fill at the level (slipped a quarter of the bar) or the open beyond; pattern extremes are confirmed five
bars later and the earliest entry of any pattern is traded. `tests/test_v24.py` checks, for every family, that
changing the bars after the entry bar changes neither the entry bar, the price, the stop reference nor the target.

## 4. Selection, tests, criteria

As v22 and v23: the activity rule (a pick needs at least 50 trades and a trade in 40% of the months before), 500
placebos for each selected configuration (a random candidate of the scope and band that day, same minute, stop
distance and exit, with its own levels and bars), the gate, **COMBO24**, CPCV PBO, Hansen's SPA test per family, the
deflated Sharpe. **Success**: COMBO24 walk-forward monthly Sortino >= 4 over 2018-2026, >= 3 in 2018-2020 and in
2021-2026, PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16, at R4 costs.

## 5. Running

A first job waits for the data run (39591258262); then a canary (each family's first and last configuration), 300
shards x 4 processes of real returns (the configurations dealt in a fixed shuffled order, so that no shard gets a
whole slow family), the selection, 300 shards x 4 processes of placebos, the report.
