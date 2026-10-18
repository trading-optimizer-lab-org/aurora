# Phase 7a, combining the best strategy streams: pre-registration

Written and committed on 2026-10-18 **before any combined result was computed** (the single streams were already
seen). Question: the owner's goal is a monthly Sortino of 10. No single stream found reaches it (best 5.07 over
2016-2020). Combining streams that do not lose in the same months, and hedging the market, is the only way the
arithmetic allows (about sqrt(N) for N independent streams). How far does it get?

Exact rules are the code in `research/combination.py`. Each stream is rebuilt exactly as in its study (checked
against the published results) and run as its own portfolio (0.5% risk per trade, 20% cap, 10 bps a side, cash at
T-bills); the combination then splits capital between the streams.

## Streams (chosen from earlier results, which is a stated source of optimism)

Intraday, 2016-2020:
- `EP_EARN` = `CAT_EARN_N0_EP` (episodic pivots on earnings releases).
- `EP_NEWS` = `CAT_NOEARN_N1_EP` (episodic pivots without an earnings release).
- `BO_TOP3` = `I_BO_MODEL_N3_E0` (the three best model-scored breakouts of the day).

Daily, 1995-2020:
- `ACCUM` = `S49_XTIME60_G10_A3`, `SQUEEZE` = `S21_XT8H_G10_A3`, `LOWVOL` = `S70_XT8_G5_A8`, `IPO` = `S25_XR3_G0_SS`
  (catalog v7), and `PARA_SHORT` = `QPS_P100_XQC10` (parabolic shorts, Qullamaggie daily study).

## Sets and methods

- Sets: `INTRADAY` (the 3 intraday streams), `DAILY` (the 5 daily streams), `ALL` (all 8).
- `EQ`: equal capital, rebalanced daily.
- `RP`: weights proportional to 1 / volatility of each stream's daily returns over the prior 126 sessions,
  rebalanced on the first session of each month (equal weights until 126 sessions exist).
- `RPH`: `RP` minus a short SPY hedge of beta x (SPY - T-bills), beta from the prior 126 sessions, kept in [0, 1.5].
- `RPH_VT`: `RPH` scaled to 15% annualised volatility (prior 63 sessions), at most 3x; the extra exposure pays
  T-bills + 1.5% a year.

**Trials: 3 sets x 4 methods = 12** (`<set>_<method>`).

## Reporting

- Monthly-return correlations between the streams and SPY, 2016-2020.
- Each stream alone and each combination: monthly Sortino, CAGR, max drawdown, total return, worst month and share
  of positive months, for 2016-2020; for `DAILY` also 1995-2010 and 2011-2020.
- Pass criteria as before on 2016-2020 (2011-2020 for `DAILY`); deflated Sharpe over these plus all earlier trials.

## Limits

Streams were picked after seeing 2016-2020, so the combinations are a lead, not proof; the `DAILY` set on
1995-2010 is the least contaminated view. Rebalancing costs between streams are ignored. The clean tests remain
forward paper trading and the locked 2021+ period, used once and only on the owner's request.
