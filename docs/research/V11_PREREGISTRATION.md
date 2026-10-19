# v11: a Sortino-first combination of independent strategies: pre-registration

Written and committed on 2026-10-19 before any v11 result was computed. The owner needs a monthly Sortino of 4 or more
and dropped the drawdown limit ("olvidate del drawdown limite de -60%. ahora no hay limite - quiero el camino v11").
v10 showed that single strategies keep about half of their design Sortino out of sample (design 4-5 gives a median of
1.4 in 2021-2026), so the only route to 4 is combining several weakly correlated streams that each keep a real edge.
Expectation stated to the owner before the run: about 2.5-3 out of sample, not 4.

Exact rules are the code in `research/v11.py` and `scripts/run_v11.py`, reusing v10's inputs, engine and families.

## Candidates (all computed with the published rules, 2021-2026 never used to choose)

- `QB`: the v10 intraday grid at gross 1x (the Sortino barely depends on scale): 9 signal sets x 45 exits x 3 stops x
  4 priorities x 3 regimes x risk {0.5%, 1%} x cap {20%, 35%} x pyramid {no, yes} x position limit {none, 8}
  = 349,920 configurations.
- `LT` (1,920), `CT` (25) and `MR` (576): the v10 grids unchanged.
- `TSMOM` (60), `XSETF` (72) and `SEASON` (30): the v9 ETF families, extended to 2026-10-16 with the same rules and
  the 36 ETFs from Yahoo.

## Selection (pre-registered)

1. For every configuration, the monthly Sortino of each half of its design period: QB and CT 2016-2018 and
   2019-2020; LT and the ETF families 2000-2010 and 2011-2020 (each from its first trade); MR 1995-2007 and
   2008-2020. Its **robust score** is the smaller of the two (it must be finite in both).
2. Shortlist: QB the 30 best robust scores with at most 6 per signal set; LT, MR the 10 best; CT the five base
   streams at 1x; TSMOM, XSETF, SEASON the 5 best each.
3. **Greedy combination** on 2016-2020 (the window every candidate covers): start with the shortlisted stream with
   the best 2016-2020 monthly Sortino; repeatedly add the stream that raises the 2016-2020 Sortino of the
   inverse-volatility combination the most (weights from 2016-2020 daily volatility, fixed afterwards, rebalanced
   daily); stop when no stream adds at least 0.05 or at 12 streams. This is `COMBO_GREEDY`.
4. `COMBO_FAMILY`: the best robust score of each family, inverse-volatility weights from 2016-2020. `COMBO_FAMILY_EQ`:
   the same, equal weights.

## Judgment

2021-01-01 to 2026-10-16: monthly Sortino (primary; the owner's target is 4), CAGR, maximum drawdown, total, worst
month and every year, for the three combinations, each member and SPY. Also the hindsight bound: the best 2021-2026
Sortino among the shortlisted streams, labelled as hindsight. Deflated Sharpe over all v11 trials plus every earlier
one. 2021-2026 had already been opened for the related intraday books and crypto streams; the selection never sees it.

Total 352,603 configurations on 320 runners (300 for QB, 20 for the rest), 4 worker processes each.
