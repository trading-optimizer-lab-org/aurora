# v21: small caps, a five-times-larger grid with new ideas under realistic costs (192,114 configurations): pre-registration

Written and committed on 2026-10-20, while v20 was running and before any v20 or v21 result was seen, at the owner's
request ("cuando termine esa v20, haz la v21, que sea del estilo de la 20, pero probando nuevas cosas y 5 veces mas
grande ... con costes lo mas realistas posibles - tenlo todo en cuenta"; "quiero que la v21 arranque
automaticamente"). Exact rules: `research/v21_grid.py` (on `research/v19_grid.py` and `research/v20_grid.py`) and
`scripts/run_v21.py`; tests in `tests/test_v21.py`.

## 1. Data, period, honesty

As v20 (section 1 of V20_PREREGISTRATION.md): the v18b inputs through 2026-10-16, small caps $1-$20 in the bands
$1-2, $2-5, $5-10, $10-20 (or $1-5 / $5-20), walk-forward 2018-01 to 2026-10-16. No window is clean for the
researcher; v21 widens the map and controls for the number of trials.

## 2. Costs: R4

R3 of the v19r amendment (slippage of a quarter of the bar on stop-type fills, IBKR tiered all-in $0.0065 a share a
leg with SEC and FINRA fees, borrow availability x0.8 and fees doubled with a 100% floor, the short-sale
restriction), with each leg's half-spread taken **by price tier and leg time** (the open; during the session; the
last minute or a daily close) from every quote measured so far: the v17 quote study and the v19q quotes, pooled. A
cell is the 99th-percentile-winsorised mean of its legs' half-spreads when it has at least 200 legs; otherwise it
keeps R3's value (the tier value, 1.5x at the open). The calibration job runs first and prints the table; the
shards use it. An exit inside a later day's daily bar counts as a last-minute leg. Low = half-spreads x0.5, high =
x2 with borrow fees x3, gross = no costs and no slippage. Sizing and books as v20.

## 3. What is new

- **Market regime** on every family: any, IWM up or IWM down (its return over the 20 sessions before the day).
- **Entries**: `belowopen` (the first close below the day's open from 10:00), `pmhfail` (a close back below the
  premarket high after trading above it).
- **Stops**: `cpct30`, `cpct50` (close-based: out at a session or daily close 30% / 50% against the entry, nothing
  intraday; the distance sizes the trade); daily `c50` (out at a close 50% against the entry).
- **Exits**: `g5` (held up to five sessions after the entry day, out at the first close against the position);
  `half3` (half at the entry day's close, half at the third session's close); daily `green` (out at the first close
  against the position).
- **Twenty candidate filters** for gap fades (news or none, premarket dollar volume, float, relative volume of the
  first five minutes, earlier +50% days, shelf or offering filings, earnings, prior-day short ratio and off-exchange
  share, catalyst type).
- **Two daily families**: a long after a run of 200-500% within 20 sessions has collapsed 50-70% from its peak
  (DK_DEADCATLONG), and a short at the open of the day after a +30-100% day that opens 0-20% higher still
  (RX_DAY2GAP).

## 4. Hypotheses (grids)

Definitions of the other triggers, stops and exits as in V19_PREREGISTRATION.md and V20_PREREGISTRATION.md.

| family | side | grid | n |
|---|---|---|---|
| GA_GAPFADE | short | gap {20, 30, 40, 50, 75, 100, 150, 200}% x band (4) x trigger {open, orl5, orl15, orl30, vwaploss, t30, t60, belowopen, pmhfail} x stop {hod, pct10, pct20, pct30, pct50, cpct30, cpct50} x exit {close, next_open, d2, d3, d5, d7, half3, g5} x regime (3) | 48,384 |
| GB_GAPFILTER | short | gap {30, 50}% x band {1-2, 2-5, 5-20} x filter (20) x trigger {orl15, vwaploss, t30, belowopen} x stop {pct20, pct30, cpct30} x exit {next_open, d3, d5, g5} x regime | 17,280 |
| RB_RUNFADE | short | up {40, 60, 80, 120, 200}% x trigger {lowerhigh, vwaploss, hodfail, backside, t120, t180, t240, belowopen} x band x stop {hod, pct20, pct30, cpct30} x exit {close, next_open, d3, d5, d7, half3, g5} x regime | 13,440 |
| DB_DAY2FADE | short | day-one rise {50, 100, 200}% x trigger {open, orl5, orl15, orl30, vwaploss, t30, belowopen} x band x stop {hod, pct20, pct30, cpct30} x exit {close, next_open, d3, d5, d7, g5} x regime | 6,048 |
| PB_PMFADE | short | gap {30, 60}% x drop below the premarket high {5, 10, 20}% x trigger {open, orl1, orl5, orl15, pmhfail} x stop {pmh, pct20, cpct30} x exit {close, next_open, d3, d5, d7, g5} x band x regime | 6,480 |
| GE_GAPDOWN | short or long | side x gap {-20, -35, -50}% x trigger (4) x band x stop (3) x exit {close, next_open, d3, d5} x regime | 3,456 |
| LB_GAPGO | long | gap {20, 40, 80}% x trigger (6) x band x stop {lod, pct10, pct20} x exit {close, trail20, next_open, d3, d5} x regime | 3,240 |
| RV_RUNUP | short | rise {50, 100, 200, 300, 500}% x window {1, 3, 5, 20} x trigger {open, lowclose, redclose, close_c, gapdown} x hold {3, 5, 10, 20, 30} x stop {50%, 100%, c50, none} x exit {time, target30, target50, strength, green} x volume {any, 3x the 20-day average} x regime | 60,000 |
| NT_NIGHTSHORT | short at the close | gap {15, 20, 30, 50, 100, 150}% x close below the open {0, 5, 10, 20}% x location {any, bottom quarter} x exit {next_open, next_close, close2, close3, close5, green5} x band x stop {none, 30%} x regime | 13,824 |
| EW_EVENTSHORT | short | event (4) x hold {3, 5, 10, 20, 40} x stop {25%, 50%, none} x exit {time, target30, target50, green} x band {1-5, 5-20} x regime | 1,440 |
| CC_CRASHLONG | long | fall {25, 40, 60}% x news x trigger {close_c, open, greenclose, highclose} x hold {1, 2, 3, 5, 10, 20} x stop {20%, 50%, none} x exit {time, target20, weak} x band x regime | 7,776 |
| MP_MOMOLONG | long | up {20, 50, 100}% x trigger (3) x hold {3, 5, 10, 20, 40} x stop {10, 20, 30}% x exit {time, trail20, ma10} x band x regime | 2,430 |
| DK_DEADCATLONG | long | peak run {200, 300, 500}% x fall from the peak {50, 70}% x trigger {open, greenclose, highclose} x hold {1, 3, 5, 10, 20} x stop {20%, 30%, none} x exit {time, target20, target50} x band x regime | 4,860 |
| RX_DAY2GAP | short at the open | day-one rise {30, 50, 100}% x next open at least {0, 10, 20}% higher x hold {1, 2, 3, 5, 10, 20} x stop {25%, 50%, c50, none} x exit {time, target30, strength, green} x band (4) x regime | 10,368 |

Total 192,114 configurations (4.96 times v20); every one counts as a trial for the deflated Sharpe.

## 5. Placebos, selection, multiple testing, criteria

As v20 (section 4 of V20_PREREGISTRATION.md): 200 placebos for every configuration (summarised in the shard by the
placebo p-value of each walk-forward window and the placebos' whole-period mean, deviation and count above the real
Sortino), the vectorised v14 procedure, the gate, CPCV PBO, **COMBO21**, the deflated Sharpe, and the
Benjamini-Hochberg false discovery rate over all configurations. **Success**: COMBO21 walk-forward monthly Sortino
>= 4 over 2018-2026, >= 3 in 2018-2020 and in 2021-2026, PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16, at the
middle (R4) costs.

## 6. Running

Started automatically: a first job waits until the v20 run (39474595370) and the v19q quote run (39468048575) have
finished; then the calibration job, a canary (the first and last configuration of every family on the real inputs),
and 600 shards x 4 processes with no time limit of their own (about 2 hours each on the v20 timings; GitHub's limit is
6 hours a job), then the report.
