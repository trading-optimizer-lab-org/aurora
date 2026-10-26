# v40: a large walk-forward grid of overlays on v39's best book: pre-registration

Written and committed on 2026-10-26, before any v40 result was computed, at the owner's request (a very large grid
around the best book and its members, with new ideas; 300 runners of 4 CPUs). Code: `scripts/run_v40.py`, tests
`tests/test_v40.py`, workflows `v40-canary.yml`, `v40.yml`.

The question is not the $30,000 target (closed in v39) but whether anything improves the book **when every choice
is made on earlier years only**.

## 1. The base book

v39's DS1 20%, RU 70%, NS 40%, ON1 out, no volatility cut (v33's run 40192951586 arm `limit` members, A1's account,
v31's liquidation at θ = 15%, TradeZero International costs, base locates HTB 1% / HOT 3%, $6 a month). Its trades
are fixed; v40 changes only what happens to them.

## 2. The overlays

Nine dimensions, all from data known before the trade (`s` = the session before the signal session `t`):

| dimension | values |
|---|---|
| regime | none, or {runners: names of the base universe at x2 or more in 5 sessions; breadth: the base universe's mean 20-session return, clipped to [-90%, +300%]; VIX high; VIX low} at or beyond its {70, 80, 90}th percentile of the 252 sessions before `s` -> {skip, half weight} (25) |
| cluster | none, or {5, 10, 20} or more of the book's trades entered in the 5 sessions before -> {skip, half} (7) |
| calendar | none, skip entries in June, skip the last 5 sessions of a quarter, both (4) |
| dilution | none, or {an EFFECT notice or an 8-K item 3.02 in the 120 sessions up to `s`; cash runway under 6; shares outstanding +25% or more over 250 sessions; a going-concern note in the 400 sessions; any of these} -> {x1.5 when present, x0.5 when absent} (11) |
| crowding | none, or {short interest / shares >= 15%; >= 30%; days to cover >= 5} -> {half, skip} (7) |
| stop (DS1, RU) | none, a buy stop at entry +30%, +60%, +100% (fills at the open if it gaps over, else at the stop) (4) |
| target (DS1, RU) | none, a buy limit at entry -30%, -50% (not on the entry session) (3) |
| hold (DS1, RU) | as picked, at most 5 sessions (2) |
| size scale | 0.6, 0.8, 1.0, 1.25 on every weight (4) |

25 x 7 x 4 x 11 x 7 x 4 x 3 x 2 x 4 = **5,174,400 variants**. On the entry session a stop is hit if the high
reaches it, and a stop beats a target on the same session. A shortened trade keeps the full entry costs. The variant
with every dimension at none / as picked / 1.0 is the base book.

## 3. The walk-forward choice

Every variant's daily returns at the $10,000 level; for each year its log growth and its worst drawdown inside the
year. For each year Y from 2019: among the variants whose worst yearly drawdown before Y is no worse than the base
book's, the one with the highest smoothed log growth over the years before Y (half its own, half the mean of the
variants that differ from it in one dimension). 2018 trades the base book. The chosen variants, year by year, make
the walk-forward book.

## 4. The question

Both books on v29's 4,000 one-year bootstrap paths from $5,000 (ruin = at or under $1,250 at any time), at base
costs and at HOT 5%, spreads x2 and the high costs. **v40 improves the book if the walk-forward book's median on all
paths is at least 1.15 x the base book's, with ruin at most 2.5% at base costs and at HOT 5%, and its median at the
high costs at least the base book's.** Reported too: the 2023+ paths, the picks, the in-sample best variants and each
dimension's mean effect (both in-sample, labelled so). The base book must reproduce v39 ($23,143, ruin 0.1%).

## 5. Caveats fixed now

The base book was itself chosen after five searches on all years, so even a walk-forward gain sits on an in-sample
base. 5.2 million variants: the walk-forward choice is the guard, not a deflated Sharpe. Daily bars for stops and
targets; short interest and SEC data as v28 loaded them (with their publication lags); locates assumed.
