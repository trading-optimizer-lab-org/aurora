# v23: technical analysis on one-minute bars of small caps (105,336 configurations): pre-registration

Written and committed on 2026-10-21, before any v23 result was computed, at the owner's request ("propon un v23, del
estilo de las v22 ... analisis tecnico, patrones tecnicos e indicadores de todo tipo, tambien soportes y
resistencias. todo en grafico de 1 minuto"; option B: "haz esta, y si necesitas ... descargar mas datos,
descargalos"). Exact rules: `research/v23_ta1m.py`, `scripts/run_v23.py` (on `scripts/run_v22.py`), the data in
`scripts/run_v23_data.py`; tests in `tests/test_v23.py`.

## 1. Data

- **New: the v23 minute store** (`scripts/run_v23_data.py`, Actions cache `v23-store-*`): Alpaca SIP one-minute bars
  (04:00-15:59 ET, raw prices) of the **100 most liquid small caps of every session** (by the prior 20-day dollar
  volume, among those whose prior close is $1-$20), 2016-01-04 to 2026-10-16, event or not; each symbol-day keeps its
  regular-session bars and its premarket high, low and dollar volume, the prior day's high, low and close, the five
  sessions' high and low and shares outstanding. Scope **liquid**.
- v14's event-day minute store (gap-ups, runners): scopes **gapup** and **runner**; their prior-day levels come from
  the daily arrays and their premarket low from the last 30 premarket minutes.
- Price bands by the day's raw open: $1-3, $3-8, $8-20. Walk-forward 2018-01 to 2026-10-16. No window is clean for the
  researcher; one-minute technical analysis on non-event days was not tested before in this series.

## 2. Costs, sizing

R4 as v22 (half-spreads by tier and leg time from 27,782 measured quote legs; most one-minute legs pay the session
values 0.36-0.51%; slippage of a quarter of the bar on breakouts and stops; IBKR all-in commissions with SEC and
FINRA fees; borrow x0.8 availability and doubled fees for shorts held overnight; the short-sale restriction), and the
scenarios low, high, auction and gross. v14 intraday sizing (0.5% of the account at risk to the stop, at most 20%, at
most 2% of the dollar volume traded before the entry, the first five trades a day by minute); one trade per
configuration and symbol-day (its first signal).

## 3. Hypotheses (grids, one-minute bars; side long and short)

Levels: premarket high and low; the prior day's high, low and close; the 5/15/30-minute opening range high and low;
the five-session high and low; the next round number above or below the open ($1 or $0.50); floor pivots
(P = (H + L + C) / 3 of the prior day, R1 = 2P - L, S1 = 2P - H); VWAP; the session's high and low so far.
Exits: R multiples, the next level (a limit at the nearest level or round number at least 0.5% away), a measured
move (the pattern's height), the first close beyond EMA9, the cross back, the oscillator back to 50, minutes (t15,
t30), the close, the third session's close (d3). Stops: 1% beyond the level, the pattern's extreme or the range's
other side or half of it, the ten-bar swing, 10%.

| family | signal | grid | n |
|---|---|---|---|
| SR_LEVEL | at 18 levels: a break (first close through), a failed break (through by 0.2%, back within three bars), a retest after a break (back within 0.3% and holding), upwards and downwards | level x setup (6) x minute volume {any, 2x the 30 before} x window {09:30-10:30, 10:30-15:00, all} x stop {1% beyond the level, 10%} x exit {2R, next level, EMA9, t30, close, d3} x scope {liquid, gapup, runner} x band | 69,984 |
| VW_VWAP | reclaim, loss, bounce, rejection; beyond two volume-weighted deviations, faded or followed | setup (8) x after {09:45, 10:30} x volume x stop {swing, 10%} x exit {2R, back through VWAP, EMA9, t30, close, d3} x scope x band | 3,456 |
| EM_EMA | EMA cross or a pullback to the fast EMA in trend, on 1/5/15-minute spans | pair {9/20, 20/50, 50/200} x timeframe x setup x side x stop x exit {cross back, 2R, t30, close, d3} x scope x band | 3,240 |
| OS_OSC | RSI(2/7/14) or stochastic(14) at 10/90 or 20/80, optionally turning, optionally within 1% of a level or VWAP | indicator x timeframe {1, 5} x level x side x confirmation x near x stop x exit {back to 50, 2R, t30, close} x scope x band | 9,216 |
| MD_MACD | signal cross, zero cross, divergence at a 30-bar extreme | set {12/26/9, 5/35/5} x timeframe x signal x side x stop x exit x scope x band | 2,160 |
| SQ_SQUEEZE | Bollinger(20, 2) inside Keltner(20, 1.5 or 2 ATRs) for 10/20 bars, then a close outside | Keltner x bars x side x volume x stop x exit {2R, EMA9, t30, close, d3} x scope x band | 1,440 |
| PT_PATTERN | double top or bottom (two extremes within 0.5% / 1.5%, a neckline break), ascending or descending triangle (two halves of 15 / 30 bars), bull or bear flag (a 6% / 15% pole) | pattern x size x after x stop {pattern, 10%} x exit {2R, measured move, EMA9, close, d3} x scope x band | 2,160 |
| CD_CANDLE | engulfing, pin bar, inside-bar break or doji on 1/5-minute bars at a level (premarket, prior day, VWAP, the session's extreme) | candle x side x level group x timeframe x stop x exit {1R, 2R, t15, t30, close} x scope x band | 5,760 |
| VC_CLIMAX | a minute of 5/10x volume with an upper or lower wick (faded) or a big body (followed) | multiple x candle x after x stop x exit x scope x band | 1,440 |
| OR_ORB | the 1/5/15/30/60-minute opening range break | k x side x filter {none, VWAP side, 2x volume, the gap's direction} x stop {range, half range, 10%} x exit {1R, 2R, 3R, close, d3, EMA9} x scope x band | 6,480 |

Total 105,336 configurations; every one counts as a trial for the deflated Sharpe.

Fills (as v22b): a signal known at a bar's close enters at the next bar's open and an indicator exit leaves there;
level breaks fill at the level (slipped a quarter of the bar), targets at their level or the open beyond; a runner is
traded only once its high so far is 40% above the prior close (the scope is defined by the day's high).

## 4. Selection, tests, criteria

As v22 (section 4 of V22_PREREGISTRATION.md): the activity rule (a pick needs at least 50 trades and a trade in 40%
of the months before), 500 placebos for each selected configuration (a random candidate of the scope and band that
day, same minute, side, stop distance and exit, with its own levels and bars), the gate, **COMBO23**, CPCV PBO,
Hansen's SPA test per family, the deflated Sharpe. **Success**: COMBO23 walk-forward monthly Sortino >= 4 over
2018-2026, >= 3 in 2018-2020 and in 2021-2026, PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16, at R4 costs.

## 5. Running

A first job waits for the data run (39561011760) to finish; then a canary, 300 shards x 4 processes of real returns,
the selection, 300 shards x 4 processes of placebos, the report.

## Amendment before any result (2026-10-21): v23b

Found while checking v22b, before v23's canary ran: (1) a runner counts as risen only by the bars before the entry
bar (a level break inside the bar that made the rise would know it); (2) bull and bear flags are searched on live bars
(the first flag of the day no longer decides it); (3) a double top or bottom pairs each second extreme with the
earliest matching first one and trades the earliest neckline break of any pair, where the search by first extremes
let a later pattern (one that formed after an earlier break) decide the trade. Grids, data and tests otherwise as
above.
