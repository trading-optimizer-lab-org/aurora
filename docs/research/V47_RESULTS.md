# v47 results: the book under TradeZero's real API rules

Run 40922375997: 23 variant shards and the report, all succeeded; canary 40911268107 first. Report in the artifact
`v47-report` (V47_REPORT.md, v47_summary.json). Pre-registration: V47_PREREGISTRATION.md. Follow-ups: v47h (run
40925260303, three years from $2,000, artifact `v47h-report`) and v47d (run 40933324435, the worst sessions,
artifact `v47d-report`).

Check: the base reproduces v43's central case ($22,006 median, 0.1% ruin).

## Pass marks

| question | result |
|---|---|
| Q1: TZA operable (median >= 0.85 x base, ruin <= 2.5% at base and HOT 5%, both halves positive) | **NOT MET**: median $20,742 (0.94 x) but ruin 5.9% / 6.0% |
| Q3: TZB stress case | $11,935, ruin 13.0% |
| Q3: TZA from $2,000 | $7,561, ruin 5.4% |

## Data (one year from $5,000, base costs)

| variant | median | ruin | halves |
|---|---|---|---|
| base | $22,006 | 0.1% | 6.22 / 6.84 |
| O1 (decide at 15:50, market 15:55) | $16,036 | 6.6% | 4.34 / 6.32 |
| C955 (market 15:55 on the close's signals) | $23,061 | 0.2% | 6.34 / 7.13 |
| X951 / X955 / X958 (close covers at market) | $22,371 / $22,147 / $22,169 | 0.1-0.2% | ~6.2 / 6.9-7.0 |
| L1 / L2 / L3 (per-share locate) | $31,821 / $30,314 / $26,763 | 0.0-0.1% | 7.99 / 8.62 (L1) |
| F050-F250 (price floors) | $22,006 | 0.1% | no trade under $2.50 in the book |
| SSR | $17,541 | 0.1% | 5.28 / 5.90 |
| U10 / U25 / U50 (no locate) | $17,339 / $13,432 / $10,066 | 10.3% / 11.3% / 8.2% | |
| M05 / M10 / M20 (missed days) | $18,014 / $19,046 / $15,685 | 7.8% / 7.4% / 7.7% | |
| TZA | $20,742 | 5.9% | 6.34 / 6.70 |
| TZB | $11,935 | 13.0% | 4.48 / 4.25 |
| TZA0 (TZA with C955 instead of O1) | $25,102 | 0.0% | 6.84 / 7.45 |

The 2:1 rule at 15:45 and at the close: 0.1% of sessions over it (base, TZA, TZB); worst ratio 2.19 / 2.90 / 2.37.
O1: of 530 close entries, 489 kept, 41 dropped, 3 added.

## Three years from $2,000 (v47h, 4,000 paths of 756 sessions)

| variant | costs | year 1 median | year 3 p10 / median / p90 | ruin by year 3 |
|---|---|---|---|---|
| base | base | $8,149 | $26,996 / $124,527 / $409,596 | 0.5% |
| base | HOT 5% | $5,800 | $9,868 / $57,423 / $207,175 | 2.1% |
| C955 | base | $8,640 | $29,762 / $136,911 / $443,320 | 0.9% |
| X955 | base | $8,215 | $27,219 / $126,911 / $426,399 | 0.5% |
| TZA | base | $7,576 | $13,684 / $110,719 / $421,965 | 6.8% |

The top level is $150,000; above it the paths use that level's returns, so year 3's upper quantiles ignore the
book's capacity.

## The ruin jumps (v47d)

Variants that only remove a few trades (O1, U10, M05, M10) raise ruin from 0.1% to 6-10%, while SSR, which removes
192 trades, does not. v47d shows why: the removal frees a slot, and the account then takes a run-up close entry that
the base crowds out by capacity. Those trades are single names at 37-54% of equity:

- TROO, RU close 2021-07-09, weight 0.54: -39.8% of the account in one session (O1, with a liquidation).
- HOLO, RU close 2024-02-07, weight 0.37: -72.1% of the account on 2024-02-16 (M05, M10, with a liquidation).
- RVSN, RU close 2024-01-23, weight 0.47: -34 to -37% (O1, M05, M10, TZA).

The base's own worst sessions are -40% (UONE 2020-06-16) and -35% (GFAI, RU close, weight 0.45).

## Inference

- Exits at a close need no auction: market covers at 15:51-15:58 match the base. Entries at market 15:55 match too
  when decided on the close (C955), but that decision uses the close and is not operable as such.
- Deciding at 15:50 (O1), the honest version, loses most of its median through one extra catastrophic RU trade, not
  through a general loss of edge.
- The base's 0.1% ruin is fragile: it depends on which trades capacity crowds out. Any small change in which trades
  fill (missed days, refused locates, the decision time) lets a 40-55% single-name RU entry in, and ruin moves to
  6-10%. The realistic ruin of the book as sized is nearer 6-10% than 0.1%.
- Per-share locates at TZ's example prices are much cheaper than the share of value assumed since v29, because the
  book trades nothing under $2.50. The real locate price is the largest single lever (+22% to +45%).
- SSR costs a fifth of the median but no ruin.

## Caveats

- In sample: every year 2018-2026 has been seen.
- v47 fixes no rule. A per-name weight cap on RU close entries is the obvious candidate, but it was not
  pre-registered here and would need its own run.
- The TZ API has no MOC/LOC; the platform does, and Nasdaq's closing cross includes resting Day limit orders, so
  close covers can still reach the auction through a direct route. Close entries decided on the close are not
  possible at any broker (Nasdaq MOC cutoff 15:55, LOC 15:58).
