# Where is the gap to Qullamaggie's returns? Pre-registration

Written on 2026-10-19 before computing, at the owner's request ("Ellos consiguen muchisima mas rentabilidad.
Solucionalo y encuentra el gap"). Self-reported public figures (interviews, not audited): $9,100 in May 2013,
$1.4M in 2018, $3.5M at the start of 2020 and $36M at its end (about +930% in 2020), $82M in March 2021, more than
half lost in 2022; win rate 25-35%; risk 0.5-1% per trade. Our best rules-based book (EP + top-3 model breakouts)
made 39.8% a year in 2016-2020 and 26.8% in 2021-2026.

This is a diagnostic study, not a strategy search: every configuration is reported, nothing is selected.
Window 2016-01-04 to 2026-10-16 (both periods are already open), same data as the follow-up run
([AFTER_2020_FOLLOWUP.md](AFTER_2020_FOLLOWUP.md)), minute bars of both periods merged.

## Gate

The base book (`I_MIX_MODEL_N3_E0`) computed over 2016-2026 must reproduce its published 2016-2020 monthly Sortino
and CAGR within 1e-9 (the portfolio is path dependent, but nothing after 2020 can change 2016-2020).

## A. Monster moves: coverage, slots and exits

A monster is a stock of the panel whose close reaches at least 3x its lowest close of the prior 126 sessions,
with price >= $5 and 20-session average dollar volume >= $5M at that low; one per stock and calendar year (the
largest). For each monster: was there a candidate of ours (EP or breakout scan) before half of the move was done
(**coverage**); did the base book buy it during the move (**slot**); what share of the move did our best trade
in it capture (**exit**). Reported per year with the count of monsters.

## B. His levers on our signals (rules only, no foresight)

On both signal sets, `MIX` (EP N1 + top-3 model breakouts) and `EP` (EP N1 only), the full grid of:

- exit: `XQ3_20` (base: half sold on day 3, rest trailed on the 20-day average), `XQ5_20` (a third on day 5),
  `XQC20` (the whole position trailed on the 20-day average);
- risk per trade 0.5% or 1%; position cap 20% or 35%; maximum gross exposure 1x or 2x (margin at T-bills + 1.5%);
- pyramid: no, or add 50% once at +2R within 10 sessions.

96 configurations. Reported: CAGR, monthly Sortino, max drawdown, total, best year and 2020 for 2016-2020,
2021-2026 and 2016-2026.

## C. Foresight bounds (not tradable)

On `MIX` with the base sizing and with the most aggressive lever set (1%, 35%, 2x, pyramid, XQC20):
`O_TOP10`, only the trades whose return ends in the top 10% of that year's trades; `O_MONSTER`, only trades in
the monster stocks of part A. They measure how much of the gap is selection rather than rules.

## Limits

Survivors-only stock list (companies still listed when it was made), no IPOs after the list date, liquidity
filters of the earlier phases; his early account traded small, illiquid names our filters exclude. Self-reported
figures cannot be checked.
