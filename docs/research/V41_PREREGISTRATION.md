# v41: a dilution tilt at equal exposure on v39's best book: pre-registration

Written and committed on 2026-10-26, before any v41 result was computed, at the owner's request (continue from v40).
Code: `scripts/run_v41.py`, tests `tests/test_v41.py`, workflows `v41-canary.yml`, `v41.yml`.

v40 found one new signal with a consistent sign: run-up shorts in names with dilution flags did better, but boosting
them also added exposure, and v40's walk-forward gain was mostly leverage. v41 asks whether the flags carry
information **at the same average exposure**: flagged trades get more weight and unflagged trades less, so that the
mean weight multiplier over the book's earlier trades is 1.

## 1. The base book

v39's DS1 20%, RU 70%, NS 40%, ON1 out, no volatility cut, exactly as in v40 (its trades are fixed; v31's liquidation
at 15%; TradeZero International costs, base locates HTB 1% / HOT 3%; $6 a month).

## 2. The variants

The flags are v40's, known at the session before the signal session: `event` (an EFFECT notice or an 8-K item 3.02 in
the 120 sessions up to it), `runway` (cash runway under 6), `so` (shares outstanding +25% or more over 250 sessions),
`gc` (a going-concern note in the 400 sessions), `any` (any of the four), and `score` (how many of the four, 0-4).

A trade's raw multiplier is `k` when its flag is set and 1 otherwise; for `score` it is `1 + (k - 1) x n / 4`. Its
multiplier is the raw one divided by the mean raw multiplier of the in-scope trades entered strictly before it (1
until 30 such trades exist). So the weight moves from unflagged to flagged trades without raising the average.

| dimension | values |
|---|---|
| flag | event, runway, so, gc, any, score (6) |
| strength `k` | 1.25, 1.5, 2, 3 (4) |
| scope | all three members; the run-up shorts only (DS1, RU) (2) |

6 x 4 x 2 = 48 variants, plus the base book: **49**.

## 3. The walk-forward choice

Every variant's daily returns at the $10,000 level at base costs; each year's log growth and worst drawdown inside the
year. For each year Y from 2019: among the variants (the base book included) whose worst yearly drawdown before Y is
no worse than the base book's, the one with the highest log growth summed over the years before Y. No smoothing.
2018 trades the base book. The yearly picks make the walk-forward book.

## 4. The question

Both books on v29's 4,000 one-year bootstrap paths from $5,000 (ruin = at or under $1,250 at any time), at base costs,
HOT 5%, spreads x2 and the high costs. **v41 improves the book if all of these hold:**

- walk-forward median on all paths >= 1.10 x the base book's;
- walk-forward ruin <= 2.5% at base costs and at HOT 5%;
- walk-forward median at the high costs >= the base book's;
- walk-forward median on the 2023+ paths >= the base book's.

Reported too: the picks, and every fixed variant on all paths at base costs and its all-years log growth (in-sample,
labelled so), which answers v40's open point (information or leverage). The base book must reproduce v39 ($23,143,
ruin 0.1%).

## 5. Caveats fixed now

Same years as v40, and v40's in-sample result is what suggested this test, so even a pass is weaker evidence than a
fresh period would give. The base book was itself chosen on all years. SEC data as v28 loaded it, with its
publication lags; locates assumed. 49 variants: the walk-forward choice is the guard.
