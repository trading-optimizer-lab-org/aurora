# Qullamaggie phase 3, "5-star" setup selection: pre-registration

Written and committed on 2026-10-18 **before any result of this phase was computed**. Question: he did not buy
every breakout; he picked the few "5-star" setups out of hundreds. Does scoring each candidate with his measurable
criteria, and trading only the best one or three of the day, add to the phase 2 results
([QULLAMAGGIE_WIND_RESULTS.md](QULLAMAGGIE_WIND_RESULTS.md))?

Exact rules are the code in `research/qullamaggie_stars.py`. Everything not stated is as in the earlier phases.

## Features (as of the prior close; the gap is known at the open)

| feature | definition | "star" when |
|---|---|---|
| steady run-up | R² of log close against time over 63 sessions | >= 0.8 |
| tight base | 10-session high-low range / close / ADR | <= 2 |
| volume dry-up | mean volume of 5 sessions / of 50 sessions | <= 0.7 |
| surfing the SMA10 | abs(close / SMA10 - 1) | <= 2% |
| market not extended | Nasdaq 21-session return | < 5% |
| no big gap | open / prior close - 1 | < 2% |
| strong industry | industry RS percentile | >= 80 |
| leader | RS percentile | >= 90 |
| 1-month strength | 21-session gain | >= 25% |
| range (model only) | ADR | - |

Sources: Muninn's analysis of his best real trades (steady prior run, quiet last month under 2 ADR, no big gap that
morning, QQQ up less than 5% in the month), Deepvue's version of his continuation scan (1-month gain > 25%, within 2%
of the 10-day average) and his own rules (volume drying up in the base, leading stocks in leading groups).

## Scores

- `STARS`: number of stars, 0-9 (no fitting).
- `MODEL`: L2 logistic regression (penalty 1 on standardised features, clipped at 5 standard deviations) trained
  **only on 1995-2010** daily breakout trades (`SCAN35` stream, `STOP` fill, exit `XQ3_20`) to predict a return in
  the top 10% of those trades. Frozen afterwards.

## Selection

Before the open, the candidates are every stock in breakout setup (as of the prior close, `SCAN5` selection, as in
phase 2). Keep the `N` = 1 or 3 best by score (ties: higher RS); only those can be bought when they trigger.
Episodic pivots are not filtered.

## Trials (24)

Setups `D_BO` (daily, 1995-2020), `I_BO` and `I_MIX` (intraday, 2016-2020) x scores `STARS`, `MODEL` x `N` 1, 3 x
exposure `E0`, `E3_C10` (phase 2 policies) = 24. Pass criteria as before (2011-2020 daily, 2016-2020 intraday).
Deflated Sharpe over these plus all 249,142 earlier trials.

Also reported: the model's coefficients; how well each score ranks trades (AUC for the top-10% target, and the
average return by number of stars) in 1995-2010 and 2011-2020; the phase 2 rows without selection as reference.

## Limits

The daily 2011-2020 rows test the selection out of sample of its training (the model never saw 2011+), although
the setups were chosen after seeing that period. The intraday rows are a lead at most. The clean tests remain
forward paper trading and the locked 2021+ period, used once and only on the owner's request.
