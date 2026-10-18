# Qullamaggie phase 4, sizing and position management: pre-registration

Written and committed on 2026-10-18 **before any result of this phase was computed**. Question: do his ways of
pressing winners (his real size, adding to a working position, raising size only on a profit cushion, selling
into strength) improve the best portfolio found so far, `I_MIX_MODEL_N3` from phase 3
([QULLAMAGGIE_STARS_RESULTS.md](QULLAMAGGIE_STARS_RESULTS.md)): all intraday episodic pivots plus the three
best model-scored breakouts of the day, exit `XQ3_20`, 2016-2020?

Exact rules are the code in `research/qullamaggie_sizing.py` and `research/stock_catalog.py` (`simulate`).
Everything not stated is as in the earlier phases.

## The four tools (all decided with data up to the prior close or the current close; no look-ahead)

- **Size** `S1`: 0.25% risk per trade, 10% position cap (his broker-verified median: 0.24% risk, ~10%
  positions). `S2`: 0.5% risk, 20% cap (as in phases 1-3).
- **Pyramid** `P1`: once per position, within its first 10 sessions, when the close is at least 2 x the initial
  risk above the entry and is the highest close since entry, buy 50% more shares at that close (within cash and
  the position cap); the stop of the whole position then moves up to the first entry price. `P0`: never.
- **Cushion** `C1`: as of the prior close, if the account is at least 10% above its value 63 sessions earlier and
  within 5% of its peak, double the risk per new trade and allow 2x gross exposure (margin pays T-bills + 1.5%);
  if it is more than 10% below its peak, halve the risk. `C0`: constant.
- **Sell into strength** `X1`: once per position, sell a third of what is left at the first close at least 30%
  above the SMA10 (he sold NVAX aggressively at 36% above it). `X0`: never.

## Trials (16)

`SIZE_<S1|S2>_<P0|P1>_<C0|C1>_<X0|X1>`: 2 x 2 x 2 x 2 = 16. `SIZE_S2_P0_C0_X0` must reproduce
`I_MIX_MODEL_N3_E0` of phase 3 exactly.

## Reporting

Portfolio Sortino, CAGR, max drawdown and total return for 2016-2018, 2019-2020 and 2016-2020; pass criteria as
before on 2016-2020; deflated Sharpe over these plus all 249,166 earlier trials. The tools act on the portfolio;
trade-level statistics are those of the base rules. Also: the average contribution of each tool (mean of the 8
trials with it minus the 8 without).

## Limits

Same period as phases 1-3 (already seen): a lead at most. The clean tests remain forward paper trading and the
locked 2021+ period, used once and only on the owner's request.
