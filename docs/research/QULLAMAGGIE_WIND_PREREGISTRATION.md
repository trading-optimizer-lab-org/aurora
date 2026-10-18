# Qullamaggie phase 2, exposure by the "wind": pre-registration

Written and committed on 2026-10-18 **before any result of this phase was computed**. Question: does his habit of
trading big when breakouts are working and staying out when they fail (his "situational awareness" post, his
streams) turn the setups into a portfolio that compounds? Phase 1
([QULLAMAGGIE_INTRADAY_RESULTS.md](QULLAMAGGIE_INTRADAY_RESULTS.md)) found a positive trade-level edge for
intraday breakouts that came almost only in 2019-2020, and portfolios that did not capture it.

Exact rules are the code in `research/qullamaggie_wind.py`. Everything not stated is as in the daily and
intraday pre-registrations (panel, costs, exits, intraday rules, minute data from the Actions cache).

## The wind indicator (known at each close)

- Breakout stream: every day the daily breakout of the `SCAN35` selection triggers (high reaches the pivot), with
  entry max(open, pivot) and stop entry x (1 - ADR).
- A breakout from day s **worked** if the close of s+3 is above the entry and no low from s to s+3 reached the stop.
- `W(t)` = share that worked among breakouts triggered from t-12 to t-3 (all outcomes known by t). Fewer than 5
  breakouts in that window counts as red ("absence of breakouts" is one of his red flags).
- **Green** when `W(t)` is at or above the 70th percentile of `W` over the prior 252 sessions, **red** at or below
  the 30th, **yellow** otherwise (yellow during the first year).
- `M1` (Nasdaq SMA10 > SMA20, both rising) as before.

## Exposure policies (base risk 0.5% per trade)

| policy | green | yellow | red | max gross exposure | position cap |
|---|---|---|---|---|---|
| `E0` | 0.5% | 0.5% | 0.5% | 1x | 20% |
| `E1` | 0.5% | 0.5% | no new trades | 1x | 20% |
| `E2` | 1% | 0.5% | no new trades | 1x | 20% |
| `E3_C20` | 1% | 0.5% | no new trades | 2x in green, else 1x | 20% |
| `E3_C10` | same as E3 | | | | 10% |
| `E4_C20` | 1% if also `M1` on | 0.5% | no new trades, or `M1` off | 2x in green with `M1`, else 1x | 20% |
| `E4_C10` | same as E4 | | | | 10% |

Margin (negative cash) pays the T-bill rate plus 1.5% a year. No forced selling when exposure is above the
limit: only new entries are restricted. Trade-level statistics use the trades each policy allows.

## Setups (chosen from the earlier studies, which is a stated source of optimism)

- Daily bars, 1995-2020 (train 1995-2010, validation 2011-2020 and its halves): `D_BO` = breakout `STOP`
  fill, `SCAN5`, exit `XQ3_20`; `D_EP` = episodic pivot `N1`, `A35`, close entry, exit `XQ3_20`.
- One-minute bars, 2016-2020 (2016-2018, 2019-2020): `I_BO` = `IBO_SCAN5_M0_K5_XQ3_20`;
  `I_EP` = `IEP_N1_Q05_K5_XQ3_20`; `I_MIX` = both in one book (exit `XQ3_20`).

**Trials: 5 setups x 7 policies = 35.** Pass criteria as before on the validation period (2011-2020 for daily,
2016-2020 for intraday). Deflated Sharpe over these plus all 249,107 earlier trials. Also reported: the share of
days in each state, and the share of the best 5% of trades each policy captured.

## Limits

The wind rule itself is new, but the setups and exits were chosen after seeing both daily periods and the intraday
period, so no period here is untouched: a positive result is a lead, not proof. The clean tests remain forward
paper trading and the locked 2021+ period, used once and only on the owner's request.
