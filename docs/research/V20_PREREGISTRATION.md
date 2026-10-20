# v20: small caps, a wide overnight grid under realistic costs (38,762 configurations): pre-registration

Written and committed on 2026-10-20, before any v20 result was computed, at the owner's request ("prepara un v20
nocturno, para que se quede 5 horas aprox probandolo todo - 4 cpu, minimo 300 servidores - centrado en small caps -
prueba en grid. todo tipo de entradas y de salidas - con costes lo mas realistas posibles - tenlo todo en cuenta").
Exact rules: `research/v20_grid.py` (on v19's engine, `research/v19_grid.py`) and `scripts/run_v20.py`; tests in
`tests/test_v20.py` check the vectorised procedure against the original v14 functions.

## 1. Data, period and honesty

- The v18b inputs (Actions cache `v18-inputs-39433812183-1`): survivorship-free small caps, through 2026-10-16. Price
  bands by raw price: $1-2, $2-5, $5-10, $10-20 (or $1-5 / $5-20 where stated).
- Walk-forward 2018-01 to 2026-10-16, each year's choice on earlier data only. No window is clean for the researcher:
  v20 was designed after v18 and v19 (small-cap shorts held for days work before costs; costs take most of it).
  v20 maps the space more finely and controls for the number of trials; it cannot confirm v19.

## 2. Costs, sizing, books

- **R3, the realistic costs of the v19r amendment, as the middle scenario**: measured event-day half-spreads by tier
  (under $2 0.48%, $2-5 0.36%, $5-10 0.33%, $10-20 0.37%) on each leg, 1.5x at the open; slippage of a quarter of the
  bar beyond the level on stop-type fills (breakouts, stops, trailing stops; targets fill at their level); IBKR
  tiered all-in $0.0065 a share a leg (at most 1%), SEC and FINRA sale fees; borrow availability of the IBKR cells
  x0.8 and fees doubled with a floor of 100% a year, per night held; the short-sale restriction. Low = half-spreads
  x0.5; high = half-spreads x2 and borrow fees x3; gross = no costs and no slippage.
- Every trade is a path of daily returns on its entry price. Intraday entries: 0.5% of the account at risk to the
  stop, at most 20%, at most 2% of the dollar volume before the entry, the first five a day. Daily entries: 5% (at
  most 1% of the prior 20-day dollar volume). At most 20 open positions and 100% gross.

## 3. Hypotheses (grids)

Intraday, on the minute bars of event days (triggers, stops and exits as defined in V19_PREREGISTRATION.md section 3;
new here: orl60, t15, t180, t240; pct10/30/50 stops; holds to the close of the 2nd, 4th and 7th session, d2/d4/d7):

| family | side | candidates | grid | n |
|---|---|---|---|---|
| GF_GAPFADE | short | gap-up of at least {15, 20, 30, 40, 50, 75, 100}% | gap x band (4) x trigger {open, orl1, orl5, orl15, orl30, orl60, vwaploss, t15, t30, t60, t120} x stop {hod, pct10, pct20, pct30, pct50} x exit {close, r2, trail20, next_open, d2, d3, d4, d5, d7} | 13,860 |
| GX_GAPFILTER | short | gap-up of at least {30, 50}%, stop 20% | gap x band {1-2, 2-5, 5-20} x news {any, none} x premarket $ volume {0, 1M, 5M} x shares outstanding {any, < 10M, >= 10M} x trigger {orl15, vwaploss, t30} x exit {next_open, d3, d5} | 972 |
| RF_RUNFADE | short | gap-up or runner up at least {40, 60, 80, 120}% at the entry | up x trigger {lowerhigh, vwaploss, hodfail, backside, t120, t180, t240} x band x stop {hod, pct20, pct30} x exit {close, next_open, d3, d5} | 1,344 |
| D2_DAY2FADE | short | the day after a rise of at least {50, 100, 200}% | rise x trigger {open, orl5, orl15, orl30, vwaploss, t30} x band x stop {hod, pct20, pct30} x exit {close, next_open, d3, d5} | 864 |
| PM_PMFADE | short | gap-up of {30, 60}% opening {5, 10, 20}% below the premarket high | gap x drop x trigger {open, orl1, orl5, orl15} x stop {pmh, pct20} x exit {close, next_open, d3, d5} x band | 768 |
| GD_GAPDOWN | short or long | gap-down of at least {20, 35, 50}% | side x gap x trigger {5- or 15-minute range break, VWAP loss or reclaim, t30} x band x stop {session extreme, pct10, pct20} x exit {close, next_open, d3} | 864 |
| LG_GAPGO | long | gap-up of at least {20, 40, 80}% | gap x trigger {orh1, orh5, orh15, pmhbreak, vwapreclaim, hod13} x band x stop {lod, pct10, pct20} x exit {close, trail20, next_open, d3, d5} | 1,080 |

Daily bars (one trade per symbol within 20 sessions, except NS; setups known at their close):

| family | side | setup -> trigger within 5 sessions | grid | n |
|---|---|---|---|---|
| RU_RUNUP | short | a close at least {50, 100, 150, 200, 300, 500}% above the lowest close of the {1, 3, 5, 20} sessions before | rise x window x trigger {open, lowclose, redclose, close_c (the setup day's close), gapdown} x hold {2, 3, 5, 10, 20, 30} x stop {25%, 50%, 100%, none} x exit {time, target30, target50, strength, trail30} | 14,400 |
| NS_NIGHTSHORT | short at the close | a gap of at least {20, 30, 50, 100}% closing at least {0, 5, 10, 20}% below its open, anywhere or in the bottom quarter of the range | gap x drop x location x exit {next_open, next_close, close2, close3, close5} x band x stop {none, 30%} | 1,280 |
| EV_EVENTSHORT | short | offer spike, reverse split of 1:5 or more, 8-K 3.01, offering form | event x hold {3, 5, 10, 20, 40} x stop {25%, 50%, none} x exit {time, target30, target50} x band {1-5, 5-20} | 360 |
| CB_CRASHLONG | long | a fall of at least {25, 40, 60}% close to close, with or without an 8-K | fall x news x trigger {close_c, open, greenclose, highclose} x hold {1, 2, 3, 5, 10} x stop {20%, 50%, none} x exit {time, target20, weak} x band {1-5, 5-20} | 2,160 |
| MO_MOMOLONG | long | a rise of at least {20, 50, 100}% closing in the top quarter on 3x the 20-day volume | up x trigger {open, redclose, highclose} x hold {3, 5, 10, 20, 40} x stop {10, 20, 30}% x exit {time, trail20, ma10} x band {1-5, 5-20} | 810 |

Total 38,762 configurations; every one counts as a trial for the deflated Sharpe.

## 4. Placebos, selection, multiple testing, criteria

- **200 placebos for every configuration** (as v14-v19: intraday, a random candidate of the same scope and band that
  day, same minute, side, stop distance and exit; daily, a random symbol of the price band that day, same entry kind,
  side and exit terms), at the middle costs. For each placebo the Sortino ratio over the whole period and over the
  months before each walk-forward year are kept.
- **The v14 procedure**, vectorised and tested equal to the original: the plateau walk-forward pick of each family for
  each year; the gate (walk-forward Sortino >= 1 and placebo p <= 0.05 in at least two thirds of the years); CPCV PBO;
  **COMBO20** (each year a family enters if its pick's plateau score is >= 1 and its placebo p <= 0.05; inverse
  volatility, cap 35%); the deflated Sharpe over all trials.
- **False discovery rate over all 38,762 configurations**: each configuration's whole-period Sortino against its own
  placebos (p empirical and p from the placebos' z-score), Benjamini-Hochberg at 5%; reported by family with the
  best surviving configurations.
- **Success**: COMBO20 walk-forward monthly Sortino >= 4 over 2018-2026, >= 3 in 2018-2020 and in 2021-2026,
  PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16, at the middle (R3) costs.
- Reported: every family's walk-forward at the four cost levels, halves, the 2023-07+ segment, placebo years, PBO,
  trades, the median Sortino of every entry and exit choice and how often the walk-forward picked it.

## 5. Running

300 shards x 4 processes (the configurations dealt round-robin), about 3-4 hours of computing; a shard starts no
configuration after 320 minutes, and any configuration not computed is reported. One report job.

## 6. Known limits

As v19: the overnight families enter at a close that is part of their setup; borrow availability and fees are a 2026
snapshot by cells, not each stock's day; the minute store holds only the regular session of event days, so overnight
and multi-day intraday exits continue on daily bars; the R3 slippage, the x0.8 availability and the doubled fees are
judgement fixed before the run.
