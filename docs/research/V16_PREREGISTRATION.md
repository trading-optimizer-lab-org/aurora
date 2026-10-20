# v16: small-cap ideas from the literature and from practitioners: pre-registration

Written and committed on 2026-10-20, before any v16 result was computed, at the owner's request ("investiga a fondo
el tema de smallcaps ... prueba todo tipo de cosas"). The ideas and their sources are in
[SMALLCAP_RESEARCH_ES.md](SMALLCAP_RESEARCH_ES.md). Universe, data, periods (design 2016-01-04 to 2023-06-30; the
sealed 2023-07-01 to 2026-10-16 opened only when the owner asks), placebos (200), walk-forward, gate and
combination are those of [V14_PREREGISTRATION.md](V14_PREREGISTRATION.md); costs are v15's R1 (IBKR-calibrated
availability, no locate fee, overnight shorts pay the calibrated fee, see
[V15_PREREGISTRATION.md](V15_PREREGISTRATION.md)), with the v14 middle half-spreads; spreads x0.5 and x2 are
reported. Exact rules are the code in `research/v16_small.py` and `scripts/run_v16*.py`.

## 1. Flags and series added (all known before the trade)

- **news:** an 8-K filed on the trading day before or on the day itself (dates only; a same-day 8-K filed after the
  trade is counted too, which can only blur the split).
- **shelf:** an S-3 or F-3 filed within the 3 years before, or a 424B within the 365 days before.
- **repeat:** a close-to-close gain of 50% or more in the 60 sessions before.
- **off-exchange share:** FINRA TRF volume / total volume of the day; **short ratio:** FINRA short volume / TRF
  volume, 5-day mean.
- **reverse split:** the day the split adjustment factor falls by 5x or more; **MAX:** the largest daily return of the
  last 21 sessions.

## 2. Hypotheses (80 configurations)

Intraday, on the v14 minute store (raw $1-$20, v14 intraday sizing, exits at the stop, a VWAP rule or the close):
- `S1_B8NEWS`: B8 (5-minute-low break, cover at the close) with gap >= {30, 50}%, PMV >= {$250k, $1M}, {news, no news}. 8.
- `S2_B8SHELF`: the same, gap {30, 50}%, PMV $250k, {shelf, no shelf}. 4.
- `S3_B8FIRST`: the same, gap {30, 50}%, PMV $250k, {first run, repeat}. 4.
- `S4_PARABOLIC` (gap-ups and runners): after 10:00, once the high is {30, 50}% above VWAP, short the close of the
  first bar with a lower high that closes below the previous bar's low; stop at the session high; cover {when a
  bar touches VWAP (at VWAP), at the close}. 4.
- `S5_BACKSIDE`: after the price is {15, 25}% below the day's high (set {before 11:00, at any time}), short the close
  of the first bar (at least 5 bars after) closing below the lowest low of the 5 bars before it, while still under the
  high; stop at the highest high since the drop; cover at the close. 4.
- `S6_GAPDOWN`: gap <= -{20, 35}%, PMV {$250k, $1M}; short the break of the 5-minute low (short-sale restriction
  applied); stop at the 5-minute high; cover at the close. 4.
- `L1_NEWSGO`: gap >= {20, 40}% with news; buy the break of the {1, 5}-minute high; stop at its low; exit {close,
  VWAP}. 8.
- `L2_PANIC` (day after a +50% day): within the first 60 minutes the low is {20, 35}% below the open; buy the close of
  the first bar after it that closes above the previous bar's high; stop at the low; exit {close, VWAP}. 4.
- `L3_R2G` (day after a +50% day): opens below the prior close; buy the close of the first bar within {30, 120}
  minutes that closes above the prior close; stop at the session low; exit {close, VWAP}. 4.
- `L4_MICROPB` (gap-ups >= {20, 40}%): within the first 30 minutes, after 3 or more green bars ending at a new high,
  1-3 red bars that keep above the midpoint of that run; buy the break of the last red bar's high; stop at the
  pullback low; exit {close, VWAP}. 4.
- `L5_PMHOD` (gap-ups >= {20, 40}%, PMV {$250k, $1M}, above the open at 14:00): buy the break of the day's high
  between 14:00 and 15:30; stop at VWAP; exit at the close. 4.

Daily (whole universe, raw price $1-$20 unless stated; shorts weighted by availability and charged the fee):
- `S7_DAY2FADE`: a day with gap >= {30, 50}% that closed 10% or more below its open; short the next open; hold {1, 3}
  days; stop 30% above entry. 4.
- `S8_RETAIL`: off-exchange share >= {60, 75}%, day return >= +30% and volume >= 5x its 20-day mean; short the next
  open; hold {5, 10} days; stop 50%. 4.
- `S9_OFFERSPIKE`: a 424B filed within 5 sessions after a 5-session rise of 50% or more; short the next open; hold
  {20, 60} days; stop {none, 100%}; 2% per position, at most 40. 4.
- `S10_RSPLIT`: reverse split of {5, 10}x or more; short the first open after it; hold {20, 60} days; no stop; 2%,
  at most 40. 4.
- `S11_DEFICIENCY`: 8-K item 3.01; short the next open; hold {60, 120} days; no stop; 2%, at most 40. 2.
- `L6_MAXREV` (raw price >= {$2, $5}, dollar volume >= $1M): weekly, among the top decile by MAX, buy the bottom fifth
  by last week's return {only, and short the top fifth}; at most 20 names a side, 5% each. 4.
- `L7_SHORTRATIO` (raw price >= $2, dollar volume >= $1M): weekly, buy the lowest decile of the short ratio {only, and
  short the highest decile}; at most 20 a side, 5% each. 2.
- `L8_NEWSDRIFT` (raw price >= $1, dollar volume >= $1M): a day with news and a close-to-close move of {10, 20}% or
  more; buy the next open after gains {only, and short after losses}; hold 5 days. 4.

## 3. Placebos, selection, combination, criteria

As v14: intraday families move each trade to a random stock of the same scope that day (same minute, side, stop
distance and exit rule); daily families to a random stock of their universe that day (same side, holding and stop
distance); weekly families pick the same number of random names from their universe. `COMBO16` = the families of
v14 (without the v14 B8), v15 (without B8R2) and v16, same rules. Success as v14 for `COMBO16`; each v16 family's
walk-forward Sortino and gate are reported.
