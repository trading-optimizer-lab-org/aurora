# Crypto trend following: pre-registration

Written and committed on 2026-10-17 **before any crypto price history was
loaded or inspected for this study.** Earlier Aurora work on crypto was
intraday (BTC 5-minute ML campaigns) and never evaluated these daily rules.

## Hypothesis

Large crypto assets show time-series momentum at daily to monthly horizons
(e.g. Liu & Tsyvinski, *Risks and Returns of Cryptocurrency*, RFS 2021).
Holding them only while their trend is up, sized by volatility, should keep
much of the upside while avoiding most of the deep bear markets, raising the
downside-risk-adjusted return relative to buy and hold.

## Data

- Daily USD closes from Yahoo Finance (`BTC-USD`, `ETH-USD`, ...), every
  calendar day (crypto trades 24/7).
- Cash: 3-month T-bill (FRED DTB3, Yahoo `^IRX` fallback), as in the
  multi-asset study; flat on non-business days.
- Assets enter only after 200 days of history.

## Periods

| Period | Dates | Use |
|---|---|---|
| Train | start of data to 2021-12-31 | sanity check only, no tuning |
| Validation | 2022-01-01 to 2023-12-31 | pass/fail on the criteria below |
| Locked | 2024-01-01 onward | closed; opened once, only on the owner's request |

## Execution rules (common to all candidates)

- Signals use closes up to and including the signal day; trades execute at the
  next day's close-to-close return.
- Rebalance every **Sunday** (UTC daily bars). Robustness also reports
  Wednesday and Friday, and daily.
- Long or cash only: no shorts and no leverage; total exposure is capped at 100%.
- Costs: **30 bps per unit of one-way turnover** (Alpaca crypto taker fee is
  at most 25 bps; the rest is spread).
- Volatility sizing: each held asset gets weight `min(1, 0.30 / vol_30d) / N`,
  where `vol_30d` is the annualised (sqrt 365) 30-day realised volatility and N
  is the number of assets in the universe. The rest is cash.

## Candidates (4) and benchmark

| Name | Universe | Signal (per asset) |
|---|---|---|
| `btc_buy_hold` (benchmark) | BTC | always 100% |
| `ma_ensemble` | BTC, ETH | fraction of {close > SMA20, close > SMA50, close > SMA100}; weight = fraction x vol size |
| `tsmom_28` | BTC, ETH | hold if the 28-day return is above the cash return |
| `donchian_20_10` | BTC, ETH | enter on a 20-day high close, exit on a 10-day low close |
| `ma_ensemble_alts` | BTC, ETH, LTC, BCH, LINK, DOGE | as `ma_ensemble`; **survivorship-biased** (today's survivors) |

No other candidates, parameters or universes will be added to the
validation comparison. Every one of the 4 candidates counts as a trial for the
deflated Sharpe ratio.

## Pass criteria (validation 2022-2023, then locked)

All three must hold:

1. Monthly Sortino ratio (calendar-month excess returns over cash) >= 2.0.
2. Monthly Sortino above BTC buy and hold over the same period.
3. Maximum drawdown no deeper than half of BTC buy and hold's over the same
   period.

Only a candidate that passes validation may be proposed for the locked test,
and only the best one by validation monthly Sortino.

## Reporting

Train, validation and robustness (rebalance weekday, costs 15-60 bps) are
reported for every candidate, including the ones that fail.
