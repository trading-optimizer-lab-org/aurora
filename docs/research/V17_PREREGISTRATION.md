# v17: real spreads for the gap fade, and independent streams: pre-registration

Written and committed on 2026-10-20, before any v17 result was computed, at the owner's request ("haz v17 con
nuevas ideas a probar"). v16 met its design criterion, but its combination rests mostly on one effect (shorting
small-cap gap-ups without news) and that effect is sensitive to spreads (S1 6.55 at the middle half-spreads, 2.72
at twice them). v17 does two things: it measures the real quoted spreads of those trades, and it tests ideas meant
to be independent of them. Universe, periods (design 2016-01-04 to 2023-06-30; the sealed window is not used by
v17), placebos, walk-forward, gate and combination are those of v14; costs are v15's R1. Exact rules are the code in
`research/v17_ideas.py` and `scripts/run_v17*.py`.

## 1. Real spreads (a cost study, not a family)

For every trade of the S1 and B8R1 configurations the walk-forward chose in v16 (design period), the Alpaca SIP
quotes in the minute of the entry and the minute of the exit; the median quoted spread (ask - bid) / mid of each
minute is that leg's spread, and half of it the leg's cost (instead of the price-tier table). Reported: the quoted
half-spreads by price band against the table, and the walk-forward of S1 and B8R1 with each trade's own measured
cost (trades without quotes keep the table). Nothing is selected on it.

## 2. Hypotheses (44 configurations)

Liquid stocks (the v14 "in play" scope: open >= $5, 20-day dollar volume >= $20M), intraday, R1 costs:
- `N1_LIQFADE`: gap >= {4, 8}% without news; short the break of the 5-minute low; stop at the session high; cover
  {at the close, when a bar closes above VWAP}. 4.
- `N2_LIQBOUNCE`: gap <= -{4, 8}% without news; buy the break of the 5-minute high; stop at the 5-minute low; exit
  {close, VWAP}. 4.
- `N3_EARNGO`: an 8-K item 2.02 the session before or that day, |gap| >= {4, 8}%; trade in the gap's direction on
  the break of the 5-minute range; stop at its other side; exit {close, VWAP}. 4.

Small caps (raw $1-$20), intraday, no news, R1 costs:
- `N4_OPENFADE`: gap >= {50, 100}%; short the first bar's open; stop {30, 60}% above; cover at the close. 4.
- `N5_LATEFADE`: gap >= {30, 50}%, the 5-minute low not broken by 10:00; short the break of the 30-minute low; stop
  at the session high; cover at the close. 2.
- `N6_PMFADE`: gap >= {30, 50}%, the 09:29 price {10, 20}% or more below the premarket high; short the first bar's
  open; stop at the premarket high; cover at the close. 4.
- `N7_OFFERDAY`: a 424B the session before or that day, gap <= -{20, 30}%; short the break of the 5-minute low
  (short-sale restriction applied); stop at the 5-minute high; cover at the close. 2.
- `N8_HALTDOWN`: after a halt preceded by a fall of 10% or more in the 5 minutes before it, {buy the first bar after
  it if it opens above the last price before it, short it if it opens below}; stop at that last price; cover at the
  close. 2.

Index and ETFs (total-return or minute bars):
- `N9_IDXGAP`: SPY or IWM gap beyond +-{0.5, 1}%; trade against it at the open; exit {at the close, when the prior
  close is reached (else the close)}. 8.
- `N10_VIXSPIKE`: buy SPY at the close after VIX rises {20, 30}% or more in a day; hold {5, 10} sessions. 4.
- `N11_WEEKREV` (raw price >= {$5, $10}, dollar volume >= $20M): weekly, buy the bottom decile of the week's return
  among stocks without news that week {only, and short the top decile without news}; at most 20 a side, 5% each. 4.
- `N12_SECTORREV`: weekly, buy the sector SPDR with the worst week {alone, the worst two}. 2.

## 3. Placebos, selection, combination, criteria

As v16 (intraday: random stock of the same scope that day at the same minute, side, stop distance and exit; daily
and weekly: random names or shifted positions). `COMBO17` = the families of v14-v17 (the v14 B8 and v15's B8R2
excluded), same rules. Success as v14 for `COMBO17`; each v17 family's walk-forward, gate and its daily correlation
with S1 are reported.
