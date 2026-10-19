# v10: closing the gap to Qullamaggie, every idea at once: pre-registration

Written and committed on 2026-10-19 before any v10 result was computed. The owner rejected every result so far
("No me sirve ninguna. Ellos consiguen muchisima mas rentabilidad"), accepts a **maximum drawdown of -60%**, and asked
for a large run on at least 300 runners of 4 CPUs testing all kinds of ideas. The gap study
([GAP_RESULTS.md](GAP_RESULTS.md)) showed that our signals detect the monster moves but the book buys few of them
and exits far too early, and that his levers (size, margin) multiply returns and drawdowns.

Exact rules are the code in `research/v10.py`, `scripts/run_v10.py` and two additions to the engine
(`stock_catalog.simulate`): the `XG` exits and the `max_pos` limit, both inactive by default.

## Periods

Every family is **chosen on data up to 2020-12-31** and **judged on 2021 to 2026-10-16** (crypto 2026-10-16 too).
2021-2026 has already been opened for the earlier intraday books and the crypto trend strategies, so the judgment is
not fully clean; the new configurations have never been run on it. Survivors-only stock list as before.

## Gate

The intraday inputs are built once, saved sparse, reloaded, and the base book `I_MIX_MODEL_N3_E0` rebuilt from them
must reproduce its published 2016-2020 monthly Sortino and CAGR within 1e-9 before any shard runs.

## Families and grids

**QB, the Qullamaggie intraday book, 2016-2026** (design 2016-2020). Full cross product of:
- signal set (9): `EP_N1` (his not-rallied EPs), `EP_N0` (all 10% gaps), `EP_EARN` (EPs with an 8-K earnings filing),
  `EP_NEWS` (N1 EPs without one), `BO_ALL` (all intraday breakouts of the SCAN5 list), `MIX1` and `MIX3` (EP_N1 plus
  the best 1 or 3 model-scored breakouts), `MIXS3` (EP_N1 plus the 3 best by his star criteria), `ALL` (EP_N0 plus
  all breakouts);
- exit (45): `XQ3_20`, `XQ5_20`, `XQ3_10`, `XQ5_10`, `XQC10`, `XQC20`, `XE21`, `XS50T60`, `XO25`, and the new
  progressive `XG{a}_{b}_{u}_{d}` (named `XP` in the first version of this note; renamed before any run because `XPS` already exists): from day 3 the position is trailed on the a-session average until it has gained
  u% (then on the b-session average for good), with a third sold on day d (none when d = 0) and the stop moved to
  break even then; a in {10, 20}, b in {20, 50}, u in {20, 50, 100}, d in {0, 3, 5};
- initial stop (3): `DAY` (the day's low, same-day exits from the minute bars), `W1`, `W2` (1 or 2 ADR below the
  entry if lower; same-day exits then only from the daily low);
- priority when several entries compete (4): `RS63` (base), `GAP` (opening gap), `MODEL` (breakout model score),
  `DV` (dollar volume);
- regime (3): `NONE`, `M1` (Nasdaq filter of the earlier phases), `WIND` (no new entries in a red wind);
- risk per trade (4): 0.5%, 1%, 1.5%, 2%; position cap (3): 20%, 35%, 50%; gross exposure (3): 1x, 2x, 3x
  (margin at T-bills + 1.5%); pyramid (2): no / add 50% at +2R; open positions (2): no limit / at most 8.
2,099,520 configurations.

**LT, leveraged index trend, 2000-2026** (design 2000-2020): QQQ, SPY or IWM (Yahoo, adjusted); leverage 1, 1.5, 2,
2.5 or 3 rebalanced daily, paying T-bills + 1.5% on the borrowed part and 0.9% a year of fees; trend filter `NONE`,
`SMA50`, `SMA100`, `SMA150`, `SMA200`, `SMA200B` (2% band), `ABS12` (12-month return > 0), `SMA200_ABS12`; checked
daily or on Fridays; volatility target none, 20%, 30% or 40% a year (20-session realised volatility, leverage at most
the chosen one); out of the market in cash or IEF; 2 bps per unit traded. 1,920 configurations.

**CT, crypto trend with leverage, 2016-2026** (design 2016-2020): the five crypto trend streams of the fixed code
(`docs/research/data/after_2020_crypto_streams.csv`) at leverage 1, 1.5, 2, 2.5 or 3, paying T-bills + 5% on the
borrowed part. 25 configurations.

**MR, stock momentum rotation, 1995-2026** (design 1995-2020): among the top 500 or 1000 stocks by dollar volume,
the best K in {5, 10, 20} by 63-, 126- or 252-session return or 252 skipping 21; rebalanced monthly or every two
weeks; filter none or SPY above its 200-session average (else cash); weights equal or inverse 63-session
volatility; leverage 1, 1.5 or 2 (T-bills + 1.5%); 10 bps per unit of turnover. 576 configurations.

Total 2,102,041 configurations on 320 runners (300 for QB, 20 for the rest), 4 worker processes each.

## Selection (pre-registered) and judgment

- In each family, the **pick** is the configuration with the highest design-period CAGR among those whose
  design-period maximum drawdown is no deeper than **-40%** (a 20-point buffer under the owner's -60%, because
  drawdowns grow out of sample). Also reported: the picks under -30%, -50% and -60% caps, and the judgment-period
  median of the 100 best configurations by the same rule (to see whether the pick is a plateau or a spike).
- `COMBO`: equal capital in the four family picks, and the same at 1.5x leverage, judged on 2021-2026.
- A pick **passes** if in 2021-2026 its CAGR is above SPY's and its maximum drawdown no deeper than -60%. Reported
  next to it: CAGR, monthly Sortino, total, worst month, worst day, every calendar year, and for the QB pick the
  share of monster moves bought and captured.
- Deflated Sharpe over all v10 trials plus every earlier one.

## Limits

2.1 million configurations make the best design-period result very overfit; the judgment period, the plateau check
and the deflated Sharpe are there to measure that. Synthetic leveraged ETFs ignore tracking error beyond the fees.
The minute bars only cover candidate days, so wider stops use the daily low for same-day exits.
