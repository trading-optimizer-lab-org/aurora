# v27: v26 checked on symbols it never chose from, with each trade's own quotes, and extended: pre-registration

Written and committed on 2026-10-22, before any v26 or v27 result was read, at the owner's request ("prepara un run
nocturno ... haz un v27. arrancara cuando termine el v26 automaticamente"; plan approved "si, sin cripto"; "haz todo
esto hoy"). Exact rules: `scripts/run_v27.py` (on `scripts/run_v26.py` and `scripts/run_v22.py`); tests in
`tests/test_v27.py`. The run starts by itself when the latest v26 resume run has finished and reads v26's report.

## Why

No time window is clean any more (2018-2026 was seen through v14-v26). What is left clean is the cross-section: symbols
whose trades did not choose the configurations. And v26 exits in the after-hours and the premarket, where a tier table
of spreads is weakest; each trade's own quotes say what those exits cost.

## B. The halves of the symbols

- Every symbol is in half 0 or 1: the parity of the first 32 bits of the SHA-256 of its ticker (fixed, no seed).
- v26's whole grid (427,525 configurations, its rules unchanged) is evaluated on each half alone at the middle R4
  costs: 855,050 configurations on 300 shards x 4 processes.
- run_v22's selection (activity rule, plateau walk-forward picks each year on earlier data) on each half alone.
- Measures, per family: the walk-forward stream of each half's picks on the same half and on the other half (unseen);
  v26's own picks (chosen on all symbols) on each half; the equal-weight average of the family streams on the half they
  were picked on and on the unseen half. Monthly Sortino 2018+.
- Caveat stated in advance: the entries of v19-v25 were chosen on all symbols, so the halves are clean for v26's
  selection only.

## C. Rotation and adds on v26's picks

- For each family with v26 picks: each distinct pick (entry and shield fixed) crossed with
  - **rotation**: any; shares traded before the entry (intraday: in the session before the entry bar; daily: the entry
    session at a close, the session before at an open) over the shares outstanding at most 0.5, 1 or 2 (unknown
    shares outstanding: refused);
  - **adds** (intraday families only): none; a third of the position at the entry, a third at the first bar of the
    entry day reaching 10%, 20% or 30% over the entry and the last third at twice that, each below the stop, filled
    at the level or at the bar's open when it opens beyond; the adds keep the first part's stop and exit.
- run_v22's procedure: walk-forward, 500 placebos per selected configuration (the placebo trades pass the same filter),
  the gate, COMBO27C, PBO, SPA, deflated Sharpe. Same costs and sizing as v26.

## A. Each trade's own quotes (run today after v26's final report)

- The trades of v26's one-account book A at $100k (its pre-registered choice; with no choice, risk 0.5%, cap 20%,
  gross 1x), in the years their family was a COMBO26 member.
- Every entry and exit leg: Alpaca SIP quotes in that leg's minute (an exit inside a later day's daily bar: that day's
  last minute; an after-hours or premarket exit: its minute), the median quoted spread over the mid.
- The book rebuilt with each leg's measured half-spread (the tier value where no quote was found), and with 1.5 times
  it; the same trades with the tier values must reproduce v26's book.

## Runs

Wait for the latest v26 resume run -> canary (two configurations a family in B and C) -> B: 300 shards, failed shards
rerun once, selection (all shards), the holdout measure; C: 100 shards, rerun, selection, 300 shards of placebos,
rerun, report. Every job after a rerun step has an explicit condition (a skipped rerun must not skip what follows: the
failure of v26's first resumed stage). Market data stays in the Actions cache; artifacts hold reports and strategy
returns.
