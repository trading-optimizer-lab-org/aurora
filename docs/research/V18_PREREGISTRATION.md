# v18: small caps, wide (302 configurations in 43 families): pre-registration

Written and committed on 2026-10-20, before any v18 result was computed, at the owner's request ("quiero que la
v18 este enfocada en smallcaps. prueba todo tipo de estrategias ... minimo 300 variantes diferentes entre si").
Exact rules are the code in `research/v18_rules.py` and `scripts/run_v18*.py`.

## 1. Data, period and honesty about the window

- The v14 survivorship-free universe and downloads (minute bars of the event days with the premarket, after-hours
  bars, SEC filings with 8-K items, FINRA short and off-exchange volume, shares outstanding, splits), rebuilt
  through **2026-10-16**. Small caps = raw open (intraday) or close (daily) **$1-$20**, split into two bands where
  stated: low $1-$5, high $5-$20.
- **Walk-forward over the whole sample**: for each year Y from 2018 to 2026, each family's configuration is chosen
  only on data before Y (the v14 plateau score); the stitched record 2018-01-01 to 2026-10-16 is the family stream.
- The window 2023-07-01 to 2026-10-16 was opened once (the sealed test of v16) and its result is known: small-cap
  gap fades were weak there. v18 was designed after seeing it, so that window is **not clean for the researcher**,
  only for the selection rule. It is reported separately.

## 2. Costs and sizing

v15's R1: the v14 middle half-spreads by price tier and $0.005 a share, no locate fee, shorts weighted by IBKR's
calibrated availability and charged its fee per night held. Reported also: half-spreads x0.5 and x2, and the
**gross** record (no costs at all), which shows which ideas lose before costs (the condition for inverting one).
Sizing as v14 (intraday: 0.5% risk to the stop, 20% cap, 5 a day; daily: 5% a position, 20 open; weekly: 5% a name,
20 a side).

## 3. Hypotheses

Intraday on the minute bars (shorts cover at the close unless stated; HOD = the session high so far; no news = no
8-K the session before or that day):

| family | rule | grid | n |
|---|---|---|---|
| F1_TIMEFADE | gap-up, short at a fixed minute if below VWAP; stop HOD | gap {30, 50}% x minute {5, 15, 30, 60} x band | 16 |
| F2_VWAPREJECT | gap-up, after the first close below VWAP short the first bar that touches VWAP and closes below it, before a cut-off | gap {30, 50}% x before {11:00, 15:00} x band | 8 |
| F3_ORLMULTI | gap-up without news, short the break of the k-minute low; stop HOD | gap {20, 40}% x k {5, 15, 30, 60} x band | 16 |
| F4_HODFAIL | gap-up, a new day high after a minute, then a close below the lowest low of the 5 bars before; stop HOD | gap {20, 40}% x after {10:30, 12:00} x band | 8 |
| F5_EXTFADE | high {20, 30, 50}% above VWAP after 10:00, short a lower high closing below the previous low; cover at VWAP or the close | ext x exit {VWAP touch, close} x band | 12 |
| F6_CLOSEFADE | up {50, 100}% at {15:00, 15:30} and below VWAP; short; stop HOD | up x time x band | 8 |
| F7_PMFADEOPEN | gap {30, 60}%, open {10, 20}% below the premarket high; short the open; stop the premarket high | gap x drop x band | 8 |
| F9_CATALYST | gap >= 30%, 5-minute-low break; split by catalyst: none, 8-K item 1.01, 8.01, 2.02, 7.01, other 8-K | catalyst x band | 12 |
| F10_FLOATROT | gap >= 30%, shares traded before the entry >= {1, 3} x shares outstanding; 5-minute-low break | rotation x exit {close, VWAP} x band | 8 |
| F11_REPEAT | gap >= 30% in a stock with >= {2, 3} days of +50% in the last 60 sessions; 5-minute-low break | runs x premarket $ volume {$250k, $1M} x band | 8 |
| F12_SRFADE | gap >= 30%, prior day's FINRA short ratio {>= 0.6, <= 0.4}; 5-minute-low break | ratio x band | 4 |
| F13_OFFFADE | gap >= 30%, prior day's off-exchange share {>= 0.6, <= 0.4}; 5-minute-low break | share x band | 4 |
| F14_DILUTIONFADE | gap >= 30% with {an S-3/F-3/424B in the 30 days before, a 424B that day or the day before, neither}; 5-minute-low break | x band | 6 |
| F15_HALTFADE | after an up-halt (rise {10, 20}% in the 5 minutes before), short the first bar after it with a lower high that closes below its open; stop the high since the halt | rise x band | 4 |
| F16_OPENDRIVE | gap {30, 50}%, first bar closes {2, 5}% below its open; short the break of its low; stop its high | gap x drop x band | 8 |
| F17_GAPFILL | gap 15-30%, 15-minute-low break; cover at the prior close (else the close) or at the close | exit x news {none, any} x band | 8 |
| F18_AFTERNOONFADE | gap {30, 50}%, still above the open at 13:00; short the break of the 13:00-13:30 low; stop that range's high | gap x band | 4 |
| F19_SECONDPUSH | gap {30, 50}%, after the 5-minute low breaks and the price closes back above it, short the second break | gap x band | 4 |
| F20_HOTPREMARKET | gap >= 30%, premarket $ volume >= {$1M, $5M}; 5-minute-low break | volume x band | 4 |
| F21_LOWFLOAT | gap >= 50%, shares outstanding < {5, 10}M; 5-minute-low break | float x exit {close, VWAP} x band | 8 |
| G1_DIPVWAP | gap-up, after a minute the low touches VWAP and the bar closes above it after 3 bars above; buy; stop session low | gap {30, 50}% x after {10:30, 12:00} x band | 8 |
| G2_RECLAIM | gap-up, after a minute 3 closes above VWAP after having been below; buy; stop session low | gap {30, 50}% x after {11:00, 12:30} x band | 8 |
| G3_GAPDOWNREV | gap-down without news, buy the break of the k-minute high; stop the k-minute low | gap {-20, -35}% x k {15, 30} x band | 8 |
| G4_PANICBUY | a fall of {30, 50}% from the day high within 30 minutes; buy the first close above the previous bar's high; stop the low | drop x exit {VWAP, close} x band | 8 |
| G5_EARNGO | earnings 8-K, |gap| >= {10, 20}%; trade with the gap on the 5-minute break | gap x exit x band | 8 |
| G6_INVERTED | the losing longs inverted (short at the same trigger, stop at the same distance above, cover at the close): premarket-high break, day-2 5-minute break, red to green, micro pullback | 4 rules x 2 settings x band | 16 |
| G7_HODRECLAIM | a gap-up that fell {20, 30}% from its high breaks that high after {13:00, 14:00}; buy; stop VWAP | drop x time x band | 8 |
| G8_LATEPUSH | gap {30, 50}%, above VWAP and within 5% of the high at 15:00; buy at 15:00; exit close | gap x band | 4 |
| G9_FIRSTPULLBACK | gap {20, 40}%, the first pullback in the first 15 minutes after a new high; buy the break of the bar before; stop the pullback low | gap x exit {close, VWAP} x band | 8 |

Overnight on daily bars:

| family | rule | grid | n |
|---|---|---|---|
| H1_STRONGCLOSE | a day of +{30, 50}% closing in the top {10, 25}% of its range; buy the close, sell the next open | x band | 8 |
| H2_FADEOVERNIGHT | gap {30, 50}% closing {10, 20}% below its open; short the close, cover the next open | x band | 8 |

Daily and weekly (shorts pay the calibrated borrow fee every night):

| family | rule | grid | n |
|---|---|---|---|
| W1_FADEGRID | a rise of {100, 200, 300}% within 5 sessions, then the first close below the prior day's low; short the next open | x hold {3, 10} x stop {50%, none} | 12 |
| W2_SUPERNOVA | a rise of {300, 500}% within 20 sessions; short the next open | x hold {10, 20} | 4 |
| W3_RSPLITLONG | reverse split of {5, 10}x or more (S10 inverted); buy the first open | x hold {5, 20} | 4 |
| W4_DEFICLONG | 8-K item 3.01 (S11 inverted); buy the next open | hold {20, 60} | 2 |
| W5_OFFERBOUNCE | a 424B the day or the day before and a close-to-close fall of {20, 30}%; buy the next open | x hold {3, 10} | 4 |
| W6_CRASHBOUNCE | a close-to-close fall of 30% or more, news {none, any}; buy the next open | x hold {3, 10} | 4 |
| W7_LOTTERYSHORT | weekly, short the top MAX decile (largest daily gain of 21 sessions) | price >= {$1, $3} x hold {1, 2} weeks | 4 |
| W8_SRWEEKLY | weekly, buy the lowest short-ratio decile {only, and short the highest} | x price >= {$1, $3} | 4 |
| W9_OFFSPIKE | off-exchange share >= {70, 80}% and a day of +{20, 50}%; short the next open, hold 3 | | 4 |
| W11_IWMTOM | IWM over the last {1, 4} sessions of each month and the first 3 of the next | | 2 |
| W14_OFFERDAYSHORT | a 424B the day or the day before and a gap of -{10, 20}%; short the open, cover the close | x band | 4 |
| W16_EARNDRIFT | earnings 8-K and a gap beyond +-10%; hold 5 sessions with the gap | x band | 4 |

Total 302; every one counts as a trial for the deflated Sharpe.

## 4. Placebos, selection, combination, criteria

200 placebos per configuration as in v16 (intraday: random stock of the same scope that day, same minute, side,
stop distance and exit; daily: random stock of the same universe that day; weekly: random names). The v14 gate and
the yearly inclusion rule. `COMBO18` = the v18 families. Success: COMBO18 walk-forward monthly Sortino >= 4 over
2018-01-01 to 2026-10-16, >= 3 in both 2018-2020 and 2021-2026, PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16
(reported with the caveat of section 1). Reported for every family: walk-forward, halves, the 2023-07+ segment, the
gross record, the three spread levels, placebo years, PBO.

## Amendment after the first run (2026-10-20): a bookkeeping error, fixed before the rerun

The first run (39423482318) showed W2 `SUPERNOVA` at +70,553% over 2018-2026. The cause was in the multi-day
books shared with v14-v17: each day's return was taken on a constant weight, as if a short were topped up every day
while its stock fell (and a long trimmed while it rose). A real position is opened once, so a short can make at most
100%. From now on each day's P&L is measured on the entry price (`research/v14_swing.py`) and, in the weekly books,
on the price at the rebalance. Intraday and one-night trades were not affected. The rules and grids are unchanged;
v18 is rerun in full, and the multi-day results of v14-v17 (B10-B14, C18-C22, S7-S11, L6-L8, N11) carry the same
error and are flagged in their results.

## Amendment after the diagnostic (v18b, 2026-10-20, run 3)

The trade-level diagnostic of the second run (39431219007) found warrants, rights and units among the traded
symbols (2-6% of the multi-day trades) and renamed companies counted twice (the old and the new ticker carry the
same bars; 1.5-2.4% of the trades). v18b drops every symbol with a Nasdaq fifth letter W, R or U and, of each pair of
symbols whose bars repeat each other (same day, close and volume on 20 or more days), the one with fewer bars. The
high-cost scenario of the daily and weekly families now also triples the calibrated borrow fees (spreads x2 as
before), because the stocks these shorts take are among the most expensive to borrow. Rules and grids are unchanged.
