# Crypto funding carry: pre-registration

Written and committed on 2026-10-17 **before any funding-rate, perpetual or
spot price history was loaded or inspected for this study.** Only the
existence of the public files below was checked (HTTP headers).

## Hypothesis

Perpetual futures pay a funding rate every 8 hours. When it is positive,
longs pay shorts. A delta-neutral position (long spot, short perpetual of the
same notional) collects that funding while the price risk of the two legs
cancels. Persistent demand for leveraged long exposure should make funding
positive on average, giving a low-volatility return above T-bills.

## Data (all public, Binance Data Vision, `data.binance.vision`)

- Funding: `futures/um/monthly/fundingRate/{SYMBOL}` (every funding event).
- Perpetual daily closes: `futures/um/monthly/klines/{SYMBOL}/1d`.
- Spot daily closes: `spot/monthly/klines/{SYMBOL}/1d`.
- Symbols: `BTCUSDT`, `ETHUSDT`. Days are UTC calendar days.
- Cash hurdle: 3-month T-bill index as in the other studies, accruing on US
  business days only. Idle USDT is assumed to earn nothing.

## Periods

| Period | Dates | Use |
|---|---|---|
| Train | first common day to 2021-12-31 | sanity check only, no tuning |
| Validation | 2022-01-01 to 2023-12-31 | pass/fail on the criteria below |
| Locked | 2024-01-01 onward | closed; opened once, only on the owner's request |

## Position and accounting (common to all candidates)

- Capital is split 50% spot, 50% USDT margin; the short perpetual has the same
  notional as the spot leg (1x on the margin, so a +100% move in one day is
  needed to exhaust it). Per asset, the notional is 50% of the capital
  allocated to that asset.
- Daily P&L per asset, on the previous day's notional N:
  `N * (spot return - perpetual return) + N * (sum of that day's funding rates)`.
  Positive funding is received by the short.
- Legs are rebalanced back to 50/50 every day; that rebalancing and every
  entry or exit pays fees on the traded notional of each leg.
- Fees: spot 10 bps, perpetual 5 bps per side (Binance regular taker tier).
- Funding events are attributed to the UTC day in which they occur.

## Candidates (3)

| Name | Universe | Rule |
|---|---|---|
| `carry_btc_always` | BTC | always hold the spread |
| `carry_btc_positive` | BTC | hold while the trailing 7-day mean funding rate is > 0; otherwise flat in USDT. Decided at the day's close, applied next day |
| `carry_btc_eth_positive` | BTC, ETH (50/50 of capital) | as `carry_btc_positive`, per asset |

Every candidate counts as a trial for the deflated Sharpe ratio. No other
candidate, parameter or symbol will be added to the validation comparison.

## Pass criteria (validation 2022-2023, then locked)

All three must hold:

1. Monthly Sortino ratio of returns in excess of T-bills >= 2.0.
2. Maximum drawdown no deeper than -10%.
3. Annualised return above the T-bill return over the same period.

Only a candidate that passes validation may be proposed for the locked test,
and only the best one by validation monthly Sortino.

## Known risks not captured by the backtest

Exchange failure or freezing of funds (as at FTX in November 2022), auto-
deleveraging, a funding regime that stays negative, and execution slippage
beyond the fee schedule. A pass in the backtest does not remove them.

## Implementation fixes after code review (2026-10-17)

The first run did not follow three rules above; the code was corrected and the
study re-run. No rule, parameter or candidate changed.

- The positive-funding state was applied two days after the funding it uses
  instead of one. It is now decided at the day's close and held the next day.
- `carry_btc_eth_positive` averaged daily sleeve returns, an implicit daily
  BTC/ETH rebalance that paid no fees. Each sleeve now starts with 50% of the
  capital and drifts.
- Missing funding archives were silently read as zero funding. The run now
  stops if any day after inception has no funding events.
