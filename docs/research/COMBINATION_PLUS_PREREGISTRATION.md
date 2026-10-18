# Phases 7b and 7c, more independent intraday streams, leverage and the full combination: pre-registration

Written and committed on 2026-10-18 **before any result of these phases was computed**. Phase 7a
([COMBINATION_RESULTS.md](COMBINATION_RESULTS.md)) showed that three weakly correlated intraday streams combine to
a monthly Sortino of 4.92 (2016-2020) and that a Sortino of 10 needs many more streams with low correlation.
This study adds five intraday streams (7b), tests leverage, and combines everything (7c).

Exact rules are the code in `research/intraday_more.py` and `research/combination_plus.py`. Everything not stated
is as in the Qullamaggie phases (eligibility, leader scan, Nasdaq filter not used, 0.5% risk, 20% cap, 10 bps a
side, T-bills on cash, minute data from Alpaca in the Actions cache, 2016-2020, nothing after 2020-12-31). The
eight phase 7a streams are reused as published (`docs/research/data/combination_streams_7a.csv`, run
39147489147).

## 7b: five new intraday streams (one-minute bars, 2016-2020)

- `EP_DAY`: the episodic-pivot entry of the earlier phases (gap >= 10%, opening range 5 minutes, volume pace 0.5,
  stop at the low of the day, all gaps without the "not rallied" filter), **sold at the close of the same day**
  unless stopped earlier.
- `BO_DAY`: the three best model-scored breakouts of the day (as in `BO_TOP3`), sold at the close of the same day.
- `PS_DAY`: parabolic short. As of the prior close: close at least 1.5 x the lowest low of the prior 10 sessions
  after 3 higher closes in a row, price >= $1 and $1.5M average dollar volume. Short when the price breaks the low
  of the first 5 minutes (before 11:00), at min(that low, the minute's open); stop at the high of the day so far,
  at most 1.5 ADR away; same-day stop when a later minute's high goes above it; **covered at the close**.
- `PS_SWING`: the same entry, held until the first close at or below the SMA10 (`XQC10`) with the stop from the
  entry day.
- `BD_DAY`: breakdown short, the mirror of his breakout. As of the prior close: eligible (ADR >= 3.5%) and among
  the weakest 2% by 1-, 3- or 6-month return within the last 63 sessions; some close in the last 63 sessions at
  most 0.70 x the highest high of the 63 sessions before it; last 5 sessions with a narrower range and a lower high
  than the 5 before; SMA10 < SMA20, SMA20 below its value 5 sessions earlier, close <= SMA20; pivot = lowest low of
  the last 10 sessions. Short when the price breaks min(5-minute opening-range low, pivot) before 11:00; stop at the
  high of the day so far, at most 1 ADR away; covered at the close.

New candidate days are fetched from Alpaca the same way as before. Our data only has today's survivors, which
hurts the short streams (the collapses that delisted are missing).

## Leverage

Constant leverage `L` on a combination's daily return: `cash + L x (r - cash) - (L - 1) x (T-bills + 1.5%)/252`.
This is the account-level approximation (as if every position were L times larger); it ignores that position caps
and liquidity would bind.

## 7c: everything together

- Sets: `INTRA8` (the three 7a intraday streams plus the five new ones) and `ALL13` (plus the five 7a daily
  streams).
- Methods: `EQ` (equal capital) and `RP` (risk parity as in 7a, with the 2% volatility floor).

## Trials (18)

The 5 new streams alone; `INTRA8_EQ`, `INTRA8_RP`, `ALL13_EQ`, `ALL13_RP`; leverage 1.5, 2 and 3 on
`INTRADAY_EQ` (7a), `INTRA8_EQ` and `ALL13_EQ`. Reported for 2016-2020 (and 2016-2018 / 2019-2020): monthly
Sortino, CAGR, max drawdown, total return, worst month, positive months, plus the monthly correlations of all 13
streams. Pass criteria as before on 2016-2020; deflated Sharpe over these plus all earlier trials.

## Limits

2016-2020 has been used throughout: a lead, not proof. The clean tests remain forward paper trading and the
locked 2021+ period, used once and only on the owner's request.
