# v19: small caps, entry x exit grids (5,542 configurations in 12 families): pre-registration

Written and committed on 2026-10-20, before any v19 result was computed, at the owner's request ("Piensa en una
nueva v19 centrada en small caps, prueba todo tipo de criterios de entrada y de salida. Haz grid. Prueba todo tipo de
ideas. 4 cpu y minimo 300 servidores. Ejecutalo"). The exact rules are the code in `research/v19_grid.py` and
`scripts/run_v19.py`; the tests in `tests/test_v19.py` check them on synthetic data.

## 1. Data, period and honesty about the window

- The v18b inputs, unchanged (Actions cache `v18-inputs-39433812183-1`): the survivorship-free FINRA universe without
  warrants, rights, units or duplicated series; daily bars, minute bars of the event days, SEC filings and the IBKR
  borrow calibration, through **2026-10-16**. Small caps = raw price **$1-$20** (the day's open for intraday families,
  the setup day's close for daily ones); where a grid has a band: low $1-$5, high $5-$20.
- **Walk-forward over 2018-01 to 2026-10-16**: for each year Y each family's configuration is chosen on data before Y
  only (the v14 plateau score).
- The 2023-07+ window was opened once (the sealed test of v16), and v18's results over the whole sample are known
  (short small caps after extreme runs, the overnight fade). v19 was designed after seeing them and its grids contain
  the neighbourhoods of v18's winners (W1, W2 and H2 sit inside DS1 and ON1). So no part of 2018-2026 is clean for the
  researcher: v19 maps which entry and exit choices matter; it cannot confirm v18.

## 2. Costs, sizing and the book

- v15's R1 costs, as v18b: the v14 middle half-spreads by price tier x0.5, x1 and x2 (the x2 scenario also triples the
  borrow fees), $0.005 a share, no locate fee; a short is weighted by its calibrated availability and pays its fee / 360
  per night held; a daily-bar short opened 10% or more below the prior close pays 0.5% more (short-sale restriction).
  The gross record has no costs at all.
- Every trade is a path of daily returns measured on its entry price (a short makes at most 100%).
- Intraday-entry families: v14 sizing (0.5% of the account at risk to the stop, at most 20%, at most 2% of the dollar
  volume traded before the entry, the first five trades of a day by minute). Daily families: 5% a position (at most 1%
  of the prior 20-day dollar volume). Every book holds at most 20 positions and 100% gross; a trade that does not fit is
  skipped.

## 3. Hypotheses

### Intraday (minute bars of the event days; entries until 15:00)

| family | candidates | grid | n |
|---|---|---|---|
| XS1_GAPFADE (short) | gap-up of at least {20, 30, 50, 100}% | gap x band x trigger {open, orl1, orl5, orl15, orl30, vwaploss, t30, t60} x stop {hod, pct20} x exit {close, vwap, t60, r2, trail20, fill, next_open, d3} | 1,024 |
| XS2_RUNFADE (short) | gap-up or intraday runner, up at least {40, 80}% from the prior close at the entry | up x trigger {lowerhigh, vwaploss, hodfail, backside, t120} x band x stop {hod, pct20} x exit {close, vwap, r2, trail20, next_open, d3} | 240 |
| XS3_DAY2FADE (short) | the day after a rise of at least {50, 100}% | rise x trigger {open, orl5, orl15, vwaploss, t30} x band x stop {hod, pct20} x exit {close, vwap, trail20, next_open, d3, d5} | 240 |
| XS4_PMFADE (short) | gap-up of at least {30, 60}% opening {5, 10, 20}% or more below its premarket high | gap x drop x trigger {open, orl1, orl5} x stop {pmh, hod} x exit {close, vwap, r2, next_open, d3} x band | 360 |
| XL1_GAPGO (long) | gap-up of at least {20, 40, 80}% | gap x band x trigger {orh1, orh5, orh15, pmhbreak, vwapreclaim, hod13} x stop {lod, pct10} x exit {close, vwap, trail10, trail20, next_open, d3, d5} | 504 |
| XL2_GAPDOWNLONG (long) | gap-down of at least {20, 35}% | gap x band x trigger {orh5, orh15, vwapreclaim, t30} x stop {lod, pct10} x exit {close, vwap, fill, next_open, d3} | 160 |

Triggers: **open** the first regular bar's open; **orlK / orhK** the first break of the K-minute opening range's low
(short) or high (long), filled at that level or at the bar's open beyond it; **tK** at minute K after 09:30 at that
bar's open if it is below (short) or above (long) the VWAP of the bar before; **vwaploss** the first close below VWAP
after minute 15 once the price has closed above it; **vwapreclaim** three closes in a row above VWAP after minute 15
once the price has closed below it; **lowerhigh** after 10:00 the first bar whose high is below the previous bar's high
and whose close is below the previous bar's low; **hodfail** a new session high after 10:30, then the first close below
the lowest low of the five bars before; **backside** a session high at least 30 minutes old, a close 15% or more below
it that breaks the five-bar low; **pmhbreak** the first trade above the premarket high; **hod13** the first break of the
session high after 13:00 (until 15:30). Close-based triggers enter at that close. A short 10% or more below the prior
close fills only on an up-close minute (as v14).

Stops: **hod / lod** the session's high (short) or low (long) before the entry bar (at the open: the premarket high if
above the open, else 20% above; 10% below for a long); **pmh** the premarket high; **pctX** X% from the entry.

Exits: **close**; **vwap** the first close beyond VWAP five or more minutes after the entry; **t60** the close of the bar
60 minutes after the entry; **r2** a target at twice the stop distance; **trailX** a stop that trails X% from the best
low (short) or high (long) since the entry, as of the bar before; **fill** the prior close; **next_open** held over the
night and closed at the next open (no stop overnight); **d3 / d5** held to the close of the third or fifth session, the
stop live on the daily bars. The stop is always live; when a stop and a target or trailing level fall in the same bar,
the stop is taken.

### Daily bars (one trade per symbol within 20 sessions, except the overnight families)

| family | setup -> trigger within 5 sessions | grid | n |
|---|---|---|---|
| DS1_RUNUP (short) | a close at least {50, 100, 200, 300}% above the lowest close of the {1, 5, 20} sessions before | rise x window x trigger {open, lowclose, redclose, redclose_c, gapdown} x hold {3, 10, 20} x stop {25%, 50%, 100%, none} x exit {time, target50, strength} | 2,160 |
| DS2_EVENTSHORT (short) | an offer spike (a 424B after a +50% run, v16), a reverse split of 1:5 or more, an 8-K item 3.01, an offering form (S-1, S-3, F-1, F-3, 424B) -> the next open | event x hold {5, 10, 20, 60} x stop {25%, 50%, none} x exit {time, target50} | 96 |
| DL1_CRASHBOUNCE (long) | a close-to-close fall of at least {30, 50}%, with or without an 8-K that day or the day before | fall x news {any, none} x trigger {open, greenclose, highclose} x hold {1, 3, 5, 10} x stop {20%, 50%, none} x exit {time, target30, weak} | 432 |
| DL2_MOMO (long) | a rise of at least {20, 50}% closing in the top quarter of the day's range on three times the 20-day volume | up x trigger {open, redclose, highclose} x hold {5, 10, 20, 40} x stop {10, 20, 30}% x exit {time, trail20, ma10} | 216 |
| ON1_NIGHTSHORT (short at the close) | gapfail30/50 (gap of 30/50% closing 10% below its open), weak50/100 (up 50/100% closing in the bottom quarter), run200red (a close three times the lowest of the five sessions before, on a red day) | setup x exit {next_open, next_close, close2, close3} x band x stop {none, 30%} | 80 |
| ON2_NIGHTLONG (long at the close) | strong20/30/50 (up 20/30/50% closing in the top tenth), crash20/40 (down 20/40%) | setup x exit {next_open, next_close, close3} x band | 30 |

Triggers: **open** the next open; **lowclose** the first close below the prior day's low, then the next open;
**redclose** the first close below its open, then the next open; **redclose_c** at that close; **gapdown** the first
open 5% or more below the prior close, at that open; **greenclose** the first close above its open, then the next
open; **highclose** the first close above the prior day's high, then the next open. Exits: **time** the holding period;
**target50 / target30** 50% / 30% in favour; **strength** (short) out at the first close above the prior day's high;
**weak** (long) out at the first close below the prior day's low; **trail20** a stop 20% from the best close;
**ma10** out at the first close below the 10-day average. Stops act on the daily highs or lows, at the stop or the open
beyond it. Setups use the setup day's close, range, volume and 20-day dollar volume (at least $1M), known at that close;
events use the prior day's price and dollar volume.

Total 5,542 configurations; every one counts as a trial for the deflated Sharpe.

## 4. Placebos, selection, combination, criteria

- **Real stage**: every configuration at the three cost levels and gross, with the statistics of the trades the
  middle-cost book took.
- **Selection**: each family's walk-forward pick for each year (the v14 rule: the minimum of the two halves' Sortino,
  capped at 20, averaged over the configurations that differ in one value) and its best design configuration. The picks
  depend on the real returns only, and these are the only configurations whose placebos the gates use, so the placebos
  are computed for them only: 200 each, as v14-v18 (intraday: a random candidate of the same scope and band that day,
  same minute, side, stop distance and exit; daily: a random symbol of the price band that day, same entry kind, side
  and exit terms).
- **Gate** (v14): walk-forward Sortino >= 1 and placebo p <= 0.05 in at least two thirds of the years. **COMBO19**: each
  year a v19 family enters if its pick's plateau score is >= 1 and its placebo p <= 0.05 on the data before; inverse
  volatility weights, cap 35%.
- **Success**: COMBO19 walk-forward monthly Sortino >= 4 over 2018-01-01 to 2026-10-16, >= 3 in 2018-2020 and in
  2021-2026, PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16 (with the caveat of section 1).
- **Reported** for every family: walk-forward, halves, the cost levels, the gross record, the 2023-07+ segment, placebo
  years, PBO, the trades of the walk-forward stream (a month, mean net return, win rate, worst), and for every
  dimension the median Sortino of all configurations with each value and how many walk-forward years picked it
  (descriptive and in sample).

## 5. Known limits

- The overnight families enter at the close of a day whose close is part of the setup (as v14-v18).
- Borrow availability and fees come from a 2026 IBKR snapshot by price and size cells, not from each stock on each day.
- The minute store holds the regular session of event days only; overnight and multi-day intraday exits continue on
  the daily bars.
