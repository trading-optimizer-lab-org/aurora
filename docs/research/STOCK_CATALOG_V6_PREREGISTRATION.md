# US stock strategy catalog v6 (everything x everything): pre-registration

Written and committed on 2026-10-17 **before any v6 result was computed**,
after v1-v5 were designed (v5 still running). Everything not stated (data,
checks, universe, indicators, costs, 0.5% risk / 20% cap sizing, engines,
trade-level view, periods, pass criteria) is as in v1-v5. Survivorship bias
not adjusted (owner's choice). Locked period 2021+ never read. Exact rules
are the code in `research/stock_catalog_v6.py` and the modules it reuses.

## Entries (51)

- **41 long entries already defined**: S1-S7, S2T, S10-S14, S18-S25 (S25 with
  its young-stock universe) and S26-S45. Not included: shorts (S9, S17),
  BNF (S8/S8L) and Connors RSI2 (S15), which need their own exits.
- **10 new volume entries**:
  - S46 OBV at a 50-day high while the close is within 5% of its 50-day high, above SMA50.
  - S47 accumulation/distribution line at a 50-day high and above its value 20 days ago, close above EMA21.
  - S48 50-day up/down volume ratio >= 1.5 (O'Neil), above a rising SMA50, new 20-day high.
  - S49 >= 5 accumulation days (up close on above-average volume) and <= 2 distribution days in 20, above SMA50.
  - S50 close crosses above the 50-day volume-weighted average price, above SMA200.
  - S51 volume >= 5 x average with an up close in the top 20% of the range.
  - S52 driest 20-day volume of 120 days within the last 10 days, then a 20-day-high breakout on 2 x volume.
  - S53 price-volume trend crosses above its 50-day EMA, above SMA50.
  - S54 high-volume hammer (>= 4 x volume, close in the top third) after a 20% fall in 20 days.
  - S55 close crosses above SMA50 on >= 2 x volume, above SMA200.

## Exits (23)

All exits defined so far (X5, XS10, XS20, XS50, XH3, XT2, XT3, XT5, XT8, XE21,
XS50T60, XO25, XBE, XR3, XTIME20, XTIME60, XLOW10, XLOW20, XRSI80, XEXT, XWK)
plus two volume exits:
- `XC_climax`: sell at the close of a climax day (volume >= 3 x the prior
  50-day average and the close up >= 5%).
- `XC_obvweak`: sell when OBV closes below its 20-day EMA.

## Filter sets (10)

G0 none · G1 MF+IND50+ADR4 · G2 SPX200+IND50+ADR4 · G3 MF+IND85+ADR4 ·
G4 MF+IND50+ADR4+RS80 · G5 MF+IND50+LIQ500 · G6 ADR4 · G7 IND85 ·
G8 MF+VOL · G9 MF+IND50+ADR4+VOL, where `VOL` = OBV above its 50-day average
and 50-day up/down volume ratio >= 1.2.

## Grid and selection

51 x 23 x 10 = **11,730 trials**. Train-only selection of the top **25** by
train profit factor (>= 300 train trades); the "stable" list (PF >= 1.3 and
>= 200 trades in both periods) is descriptive. Deflated Sharpe over the v6
trials plus the 1,084 of v1-v4 (v5 had not finished when v6 started).

## Execution

GitHub only (`stock-ideas-v6.yml`): 51 parallel jobs (one per entry), each
using its 4 vCPUs with 4 worker processes, plus a merge job.
