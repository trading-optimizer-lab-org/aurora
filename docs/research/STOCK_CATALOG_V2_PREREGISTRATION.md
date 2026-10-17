# US stock strategy catalog v2: pre-registration

Written and committed on 2026-10-17 **before any v2 result was computed**,
but **after** the v1 results (docs/research/STOCK_CATALOG_RESULTS.md) were
seen. v2 was designed from what worked in v1, so its validation period
(2011-2020) is no longer a clean out-of-sample test: a v2 pass is only a
candidate for the untouched locked period (2021+), never a result on its own.

Everything not stated here (data, data checks, universe, indicators, filters
`MF`/`ADR4`/`IND50`, setups S1-S8, exits, costs, sizing, periods, pass
criteria, trade-level view) is exactly as in
docs/research/STOCK_CATALOG_PREREGISTRATION.md and its Amendment 1.
Survivorship bias is not adjusted (owner's choice).

## New building blocks

- `IND85`: industry RS >= 85 (Jacobs: the edge grows with the threshold).
- `STAGE2`: close above SMA150 and SMA150 above its value 20 days earlier.
- `BREADTH` market filter (Felipe): every day count universe stocks with
  EMA8 > EMA20 > EMA50 and close > EMA20 (bull) and with EMA8 < EMA20 < EMA50
  and close < EMA20 (bear); long entries only when bull count > bear count.
  Replaces `MF` where listed.
- `XS50`: sell at the first close below SMA50.
- Ranking when signals exceed capacity (portfolio view only): `RS` (v1
  default), `IND` (industry RS, highest first), `CLOSE` (closest to EMA21,
  i.e. smallest `close/EMA21 - 1` first), `RANDOM` (fixed seed 2026).
- **S2T qulla_traits** (Muninn's traits of Qullamaggie's 5R+ winners): S2 with
  a run-up of at least 50% (instead of 30%), a quiet last month
  (`close[t-1]/close[t-22] - 1 < 2 x ADR`), no big gap at the open
  (`open/close[t-1] - 1 < ADR`) and a calm index (S&P 500 21-day return < 5%).
- **S8L bnf_large**: S8 restricted to the 500 stocks with the highest 50-day
  dollar volume, with a stop 3 x ADR (in dollars of the signal-day close)
  below the limit price, checked from the day after the fill.
- **S9 parabolic_short** (Qullamaggie): close at least 50% above the close 5
  days earlier and at least 3 consecutive higher closes up to yesterday;
  today closes below yesterday (first red close): **short at today's close**.
  Stop: the higher of today's and yesterday's high (a stop fills at the stop or
  at the open if it gaps above). Cover at the first close at or below SMA10, or
  after 10 days. Filters: universe and `ADR4` only. Short sizing as longs (0.5%
  risk, max 20%); the short's collateral earns T-bills; costs 10 bps per side.
  Survivorship bias works against shorts (failed companies, the best shorts,
  are missing), so this result is conservative.

## Candidates (14 trials)

| # | Name | Setup | Exit | Filters | Rank | Risk |
|---|---|---|---|---|---|---|
| 1 | pullback_stage2 | S3 + STAGE2 | XS20 | MF ADR4 IND50 | RS | 0.5% |
| 2 | pullback_ind85 | S3 | XS20 | MF ADR4 IND85 | RS | 0.5% |
| 3 | pullback_rank_ind | S3 | XS20 | MF ADR4 IND50 | IND | 0.5% |
| 4 | pullback_rank_close | S3 | XS20 | MF ADR4 IND50 | CLOSE | 0.5% |
| 5 | pullback_rank_random | S3 | XS20 | MF ADR4 IND50 | RANDOM | 0.5% |
| 6 | pullback_risk025 | S3 | XS20 | MF ADR4 IND50 | RS | 0.25% |
| 7 | weinstein_s50 | S7 | XS50 | MF ADR4 IND50 | RS | 0.5% |
| 8 | darvas_s50 | S6 | XS50 | MF ADR4 IND50 | RS | 0.5% |
| 9 | felipe_s50 | S1 | XS50 | MF ADR4 IND50 | RS | 0.5% |
| 10 | qulla_traits_s20 | S2T | XS20 | MF ADR4 IND50 | RS | 0.5% |
| 11 | bnf_large | S8L | own (S8) + stop | none | deepest | 10% each |
| 12 | parabolic_short | S9 | cover rule | ADR4 | RS (strongest) | 0.5% |
| 13 | pullback_breadth | S3 | XS20 | BREADTH ADR4 IND50 | RS | 0.5% |
| 14 | felipe_s20_breadth | S1 | XS20 | BREADTH ADR4 IND50 | RS | 0.5% |

Candidates 3-6 share the signals of v1's `pullback_s20`; they differ only in
the portfolio view (their trade-level rows equal pullback_s20's and are shown
once). Deflated Sharpe uses all 14 v2 trials plus the 24 of v1 (38).

## Pass criteria

Same as v1 (validation monthly Sortino >= 2.0, annualised return above SPY,
max drawdown no deeper than -25%), with the caveat above. Only the best
passing candidate may be proposed for the locked test, on the owner's request.
