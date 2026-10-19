# v12: everything that could raise the Sortino of the intraday book: pre-registration

Written and committed on 2026-10-19 before any v12 result was computed, at the owner's request ("centrate en el v12,
quiero que sea amplio y con 4cpu. pruebalo todo"). v11's lesson: the Nasdaq trend filter and a selection on the worse
design half were what carried the Sortino out of sample (best rule-chosen pick 3.59 in 2021-2026); adding weak
diversifiers hurt. v12 therefore tests, around the intraday book, everything that can cut losing months (market
regime, equity-curve and drawdown control, open-risk and sector limits, an index hedge) or remove weak trades (gap,
relative strength, freshness, exits), plus ensembles of the most robust configurations.

Exact rules are the code in `research/v12.py`, `scripts/run_v12.py` and three engine additions to
`stock_catalog.simulate`, all inactive by default: the `XN` ladder exits, `max_heat` and `groups`/`max_per_group`.
Inputs are those of v10/v11 (survivors-only stock list, 2016-01-04 to 2026-10-16), plus ^VIX from Yahoo.

## Grid

Base configurations (full cross product, 1,944,000):
- signal set (10): `MIX3`, `MIX1`, `MIXS3`, `EP_N1`, `EP_N0`, `EP_EARN`, `EP_NEWS`, `BO_ALL`, `ALL` (as in v10) and
  the new `EP_CLOSE` (an EP gap day that closes above its open in the top quarter of its range, bought at that close
  with the day's low as stop);
- exit (10): `XQ3_20`, `XQ5_20`, `XQ3_10`, `XQ1_20`, `XQC20`, `XG10_50_20_3`, and the new ladders `XN{a}_{b}_{m}_{n}`
  (a third sold at +a R, a third at +b R with the stop at break even after the first, the rest trailed on the m-day
  average from day 3; with n > 0, sold at the close of day n if still below the entry and no third was sold):
  `XN1_2_20_0`, `XN1_3_20_0`, `XN2_4_20_0`, `XN1_2_20_5`;
- market regime for new entries, as of the prior close (10): `NONE`, `M1` (Nasdaq 10-day average above the 20-day,
  both rising), `NEMA` (Nasdaq above its 10- and 20-day EMAs), `N20` (above its 20-day EMA), `N50` (above its 50-day
  average), `M1_N50`, `BR50` (at least half of the 1,000 most liquid stocks above their 50-day average), `NHNL` (more
  52-week highs than lows among them), `VIX25` (VIX below 25), `M1_BR50`;
- minimum opening gap for gap entries (3): 10%, 15%, 20%;
- minimum 63-day relative strength at the prior close (3): none, 70th, 90th percentile;
- freshness (2): all, or only gap entries without an earlier gap candidate in the stock within 63 sessions;
- risk per trade (3): 0.5%, 1%, 1.5%; cap (2): 20%, 35%; open positions (3): no limit, 8, 12;
- open-risk limit (3): none, 4%, 6% of equity; sector limit (2): none, at most 2 per industry.

Each base configuration is run with 5 equity overlays, computed from its own unfiltered equity curve as of the prior
close: `NONE`, `EQ20` / `EQ50` (no new entries while that curve is below its 20- / 50-day average), `DDH10` (half
risk while it is more than 10% below its peak), `DD15OFF` (no new entries while more than 15% below). Each run is
evaluated with 3 hedges: none, or a short QQQ position of 50% / 100% of the invested fraction (T-bills on the cash).
9,720,000 simulations, 29,160,000 evaluated configurations, on 320 runners with 4 worker processes each.

## Selection (pre-registered; 2021-2026 is never used to choose)

- Robust score: the smaller of the monthly Sortinos of 2016-2018 and 2019-2020 (both finite).
- `PICK`: the best robust score. `ENS5`, `ENS10`, `ENS25`: equal capital in the 5, 10 or 25 best robust scores.
- `ENS10_PLUS`: `ENS10` plus every non-intraday stream of v11's families (LT, CT, MR, TSMOM, XSETF, SEASON) with a
  robust score of at least 2.0, inverse-volatility weights from 2016-2020.

## Judgment

2021-01-01 to 2026-10-16, and its halves 2021-2023 and 2024-2026: monthly Sortino (owner's target 4), CAGR, max
drawdown, total, every year. Per lever value: the share of configurations with a robust score of at least 3 and their
median 2021-2026 Sortino, to show what helps. Deflated Sharpe over all v12 evaluations plus every earlier trial. The
2021-2026 window has been used by v10 and v11 for related books, so it is not clean; the halves check shows whether a
result holds in both.
