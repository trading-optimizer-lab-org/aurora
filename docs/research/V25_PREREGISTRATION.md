# v25: short-only small caps on one-minute bars, the mirror of v24 (213,000 configurations): pre-registration

Written and committed on 2026-10-21, before any v25 result was computed (and before any v24 result), at the owner's
request ("ahora prepara un v25 igual que v24 pero de shorts"). Exact rules: `research/v25_short1m.py` (on
`research/v24_long1m.py`, `research/v24_patterns.py`, `research/v24_fast.py` and `research/v23_ta1m.py`),
`scripts/run_v25.py` (on `scripts/run_v22.py`); tests in `tests/test_v25.py`.

## 1. Data

The same as v24 (V24_PREREGISTRATION.md section 1): the v24 mover store (mover_up, mover_dn), the v23 liquid store
(liquid), v14's event days (gapup, runner, gapdown, day2) and inplay; daily facts from the sessions before only, plus
the 252-day low and two up days in a row. Bands $1-3, $3-8, $8-20. Walk-forward 2018-01 to 2026-10-16. No window is
clean for the researcher; the small-cap short fades of v14-v22 were found on the same period.

## 2. Costs, sizing

R4 as v22-v24, with the short side's costs: borrow at 0.8x the IBKR snapshot's availability and doubled fees for
shorts held overnight, and the short-sale restriction (an entry 10% or more under the prior close fills only on an
up-close minute within 15 minutes, v14's rule). Scenarios low, high (spreads x2, borrow fees x3), auction and gross.
v14 intraday sizing; one trade per configuration and symbol-day (its first signal).

## 3. Hypotheses (all short; grids)

Two kinds of family.

**v23's families with their own short rules** (exact), on the scopes v23 did not have, and the daily levels:

| family | signal | grid | n |
|---|---|---|---|
| DD_DAILY | daily levels (20/60/252-day high and low, 20/50/200-day average): first close under, a push through by 0.2% and back under within three bars, a retest from under after the break | level (9) x setup {break down, failed break up, retest} x volume x window x stop {1% over the level, 10%} x exit {2R, next level, EMA9, close, d3, trail10} x scope {liquid, mover_up, mover_dn, gapup, runner, gapdown} x band | 34,992 |
| SR_SHORT | v23's 18 intraday levels, the three short setups | as v24's SR_LONG, scopes {mover_up, mover_dn, gapdown, day2} | 46,656 |
| XV/XE/XO/XM/XQ/XP/XC/XX/XR | v23's VWAP (loss, rejection, beyond +2 deviations faded, under -2 followed), EMA, oscillator, MACD, squeeze, pattern (double top, descending triangle, bear flag), candle, climax (upper wick, big red body) and ORB families, short side | v23's grids with the short values, on mover_up, mover_dn, gapdown, day2 | 23,568 |

**v24's own families on the reciprocal price 1/p** (each long rule's mirror image): bars, VWAP and the day's facts
are mirrored (the premarket high becomes the premarket low, the 20-day high the 20-day low, a gap up a gap down, the
daily ATR kept as a fraction of the price); the bars on which an entry may be taken are the real ones (a runner traded
only once risen 40% by the bars before, inplay from 09:35); the entry, stop and target are mapped back to real
prices. Percentages apply in the mirror: a 10% stop of 1/p is 11.1% over the entry, a 4% gap down of 1/p is a 4.2%
gap up. Grids as v24's (V24_PREREGISTRATION.md section 3), with the scopes below.

| family (mirror of) | the short rule | scopes | n |
|---|---|---|---|
| SB_INPLAY (SP) | the k-minute opening range low broken by a stock in play (first candle red or any; gap down or any) | inplay | 3,240 |
| NL_NOISE (NB) | close under min(open, prior close) / (1 + k x ATR% x sqrt(minutes / 390)) | liquid, mover_dn, gapdown, inplay | 2,880 |
| LL_LATE (LH) | down 2/5/9/17% from the prior close at 10:00, short at 14:00, 15:00 or 15:30 | liquid, mover_dn, gapdown, mover_up | 3,456 |
| PL_POWER (PH) | first close under the low of the day after 13:30/14:00/14:30 | liquid, mover_dn, gapdown, gapup | 3,240 |
| MB_MICRO (MP) | a new low of the day, one to three bars of bounce, the break of the prior bar's low | gapdown, mover_dn, liquid, gapup, runner | 4,320 |
| AS_ABCD (AB) | the bearish ABCD (a lower high C, or the break of B's low) | as MB | 2,160 |
| HS_HALT (HR) | after a pause: the resumption reopening at or under the last price, the first close under the resumption bar's low, the first pop sold | gapup, runner, mover_up, mover_dn, liquid | 3,780 |
| MP_MORNPOP (MD) | a high 11/25/43% over the low of the day before 10:00 (10:30), then a red 5-minute bar, a VWAP loss, a lower high or RSI(7) over 80 turning down | gapup, runner, mover_up, gapdown, mover_dn | 4,320 |
| GR_GREEN2RED (RG) | open over the prior close (by 0/2/5%), the first close under it | liquid, mover_up, gapup | 3,888 |
| GU_GAPFILL (GF) | gap up 4/9/18%: the opening range low, a VWAP loss, a lower high, or under the open at 10:00; exits at the prior close, half the gap | liquid, mover_up, gapup | 1,620 |
| D2_FADE (D2) | the day after an up day of 20/50/100% (real, not mirrored): the premarket low, the opening range low, a VWAP loss after 10:00, or the open if it gaps down | day2, liquid, mover_up, mover_dn | 4,320 |
| IS_IND (IX) | the 16 indicators' short signals (SuperTrend and SAR flips down, Heikin-Ashi turning red, Ichimoku under the cloud, CCI under +100, Williams %R under -20, MFI under 80, OBV new low over the price low, Aroon down, Donchian lows, Keltner lower, ROC, TRIX, ADX with -DI, EMA9 < EMA20 < VWAP) | liquid, mover_up, gapup, runner | 20,736 |
| PS_PATTERN (PX) | head and shoulders, triple top, inverted cup, rectangle and pennant breakdowns, low tight flag | liquid, mover_up, gapup, runner | 6,912 |
| CS_CANDLE (CK) | shooting star, bearish engulfing, evening star, dark cloud, three black crows, bearish harami, tweezer top, red marubozu, gravestone doji, after a rise, at the high of the day, at VWAP from under, at a level, on a rally in a downtrend | liquid, mover_up, mover_dn, gapup | 32,400 |
| BT_BLOWOFF (WO) | 4/7 green bars in a row, 11/25/43% over the low of the day, a minute of 3x/6x volume; the first lower low or a close under the three bars before | liquid, mover_up, mover_dn, gapup, runner, gapdown | 5,184 |
| HD_GRAIL (HG) | ADX over 25/30 with -DI over +DI, a bar touching EMA20, EMA9 or VWAP from under, the break of its low | liquid, mover_up, gapup, runner | 1,440 |
| TD_TREND (TS) | a daily downtrend (close under the 20-day under the 50-day average, within 5.3% of the 20-day low, or down 23% in 60 days) and a rally of 3/6/11% from the open | liquid, mover_dn, mover_up | 3,888 |

Total 213,000 configurations in 28 families; every one counts as a trial for the deflated Sharpe.

Fills as v24 (signals at a bar's close enter at the next bar's open, level breaks at the level slipped a quarter of
the bar, pattern extremes confirmed five bars later and the earliest entry traded), then the short-sale restriction.
`tests/test_v25.py` checks for every family that changing the bars after the entry bar changes neither the entry
bar, the price, the stop reference nor the target, and that the stop reference is above the entry.

## 4. Selection, tests, criteria

As v22-v24: the activity rule, 500 placebos for each selected configuration (a random candidate of the scope and band
that day, same minute, stop distance and exit), the gate, **COMBO25**, CPCV PBO, Hansen's SPA test per family, the
deflated Sharpe. **Success**: COMBO25 walk-forward monthly Sortino >= 4 over 2018-2026, >= 3 in 2018-2020 and in
2021-2026, PBO < 20%, and >= 3 over 2023-07-01 to 2026-10-16, at R4 costs. Caveat stated in advance: the earlier
short fades (v19-v22) held up in design and failed the sealed test of v16, and borrow is calibrated on a current
snapshot of IBKR's availability, not a historical one.

## 5. Running

A first job waits for the v24 run (39594220034) to finish; then a canary, 300 shards x 4 processes of real returns
(the configurations dealt in a fixed shuffled order), the selection, 300 shards x 4 processes of placebos, the report.
