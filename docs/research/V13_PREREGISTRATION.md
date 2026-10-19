# v13: an honest estimate, without overfitting: pre-registration

Written and committed on 2026-10-19 before any v13 result was computed, at the owner's request (proposal accepted:
"si"). v10-v12 searched up to 29 million configurations and judged them on one window (2021-2026) that had been
looked at many times; the best design results collapsed out of sample (v12: 8.35 -> 1.75). v13 changes the method:
a survivorship-free universe, a small hypothesis set fixed in advance, walk-forward selection, combinatorial
cross-validation with the probability of backtest overfitting (PBO), plateau selection and walk-forward
diversification. Target: a monthly Sortino of 4.

Exact rules are the code in `research/v13.py` and `scripts/run_v13.py`.

## 1. Survivorship-free universe (2016-2026)

All Alpaca `us_equity` assets, active and inactive, listed on NYSE, NASDAQ or AMEX (ARCA and BATS, the ETF venues,
excluded). Daily bars adjusted for splits and dividends (`adjustment=all`, SIP) from 2015-01-01 to 2026-10-16.
When a ticker's history has a gap of 20 or more sessions (usually a ticker reused by another company), only the
latest segment is kept; the number of such tickers is reported. Each series goes through the same data checks as
the earlier panel (`stock_data_checks`), and only stocks that at some point meet the rules' own liquidity floor
(price >= $1 and 20-session dollar volume >= $1.5M) are kept, so no candidate is lost (added before the run, for
memory). Industry is known only for the tickers of the earlier list (others: none).
The intraday rules, filters, minute-bar fills and costs are those of phases 1-7; minute bars and raw daily bars are
fetched for the new candidate days. The breakout model keeps its 1995-2010 training on the earlier panel (fixed
weights), applied to the new panel's features. Everything is also run on the earlier survivors-only panel, to measure
the survivorship effect.

## 2. Hypothesis set (144 configurations, nothing else)

Signal set {`MIX1`, `MIX3`, `EP_N1`} x exit {`XQ3_20`, `XQ5_20`} x market regime {`M1`, `N50`, `M1_N50`} x risk
{0.5%, 1%} x position cap {20%, 35%} x open positions {no limit, 8}; priority by 63-day relative strength, gross 1x.
These are only the levers that helped in v11-v12. Diversifiers: the five crypto trend streams at 1x and the 1,920 LT
index-trend configurations of v10.

## 3. Walk-forward (primary)

For each year Y from 2018 to 2026, using only data before Y: each configuration's score is the smaller of the
monthly Sortinos of the two halves of its training window (2016 to Y-1) (a stretch without a losing month counts
as 20, the cap, instead of infinity; added before the run), and its **plateau score** is the mean score
of itself and its neighbours (the configurations that differ from it in one dimension). Year Y is traded with:
- `WF_ONE`: the configuration with the best plateau score;
- `WF_ENS5`: equal capital in the 5 best plateau scores (**primary**);
- `WF_DIV`: `WF_ENS5` plus the best crypto stream and the best LT configuration by the same rule, each kept only
  if its training score is at least 1.5, with inverse-volatility weights from the trailing 252 sessions before Y.
The yearly pieces are stitched into one out-of-sample record, 2018-01-01 to 2026-10-16.

## 4. Combinatorial cross-validation and PBO

2016-01-04 to 2026-10-16 is cut into 10 contiguous blocks; for each of the 252 ways to train on 5 blocks and test on
the other 5, the configuration with the best training plateau score is chosen and its test Sortino and test rank
among the 144 are recorded. PBO = share of splits where it ranks below the test median. Reported with the
distribution of its test Sortino.

## 5. Success criterion

`WF_ENS5` (and separately `WF_DIV`) succeeds if its walk-forward monthly Sortino over 2018-2026 is **at least 4**, it
is at least 3 in both 2018-2021 and 2022-2026, and the PBO is below 20%, on the survivorship-free universe. Also
reported: CAGR, maximum drawdown, total, every year, the same on the survivors-only panel, and a gate check (the v11
robust pick rebuilt on the survivors-only panel must reproduce its published 2021-2026 Sortino of 3.59).

## Amendment before the analysis (2026-10-19)

The first run (GitHub run 39293921657) stopped at the gate: rebuilt from the v12 run's inputs, the v11 robust pick
made a 2021-2026 Sortino of 3.48 instead of the published 3.59. 2016-2020 is identical in every rebuild; the 2021+
Yahoo prices are downloaded again in each run and shift slightly, and that alone moves the pick from 3.59 to 3.48
(reported as a finding on data sensitivity). The survivors-only side now uses the inputs of the v11 run itself, so
the gate compares like with like; the survivorship-free side is unchanged. No result of the analysis had been seen.

The second run (39296910638) passed the gate (3.586781 against 3.586781) and was then stopped by the runner's
memory limit at the feature step of the 7,052-stock panel, before any configuration of that universe was run. The
workflow now adds swap and downloads the minute bars in their own step; the rules are unchanged.
