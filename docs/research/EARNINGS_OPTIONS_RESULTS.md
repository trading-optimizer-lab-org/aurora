# Earnings options: results

Run `earnings-options.yml` 40112074103 (2026-10-24), data to 2026-10-23, rules as in
`EARNINGS_OPTIONS_PREREGISTRATION.md`. The first run (40106168699) stopped in the data stage on cached files
without bars; the fix (they are skipped on load) changed no rule. Summary: `data/earnings_options_summary.json`.

**Not met.** No trial passes discovery; none passes validation. Every trial with 200+ trades loses at base costs in
both periods.

Notes, no decision:

- Implied moves were above realized moves: mean IM 8.2% vs mean |move| to 09:45 5.9% (discovery), 9.2% vs 6.1%
  (validation). Long straddles lose (H2_hold_all -6.3%). The short iron fly still loses (-9.0% on max loss)
  after paying spreads on four legs twice; its hit rate is 47%.
- H1 (run-up into the release, Gao-Xing-Zhang 2018) loses in every year, 2024 near zero at H1_runup_5.
- H2_cheap_06 shows +40% on 17 discovery trades (t 1.69) and +2% on 11 validation trades: too few to mean anything.
- About 2% of fly trades lose more than the maximum loss, from intrinsic-value exits on legs without a morning bar.
  Capping them at -100% moves the fly means by about 0.3 points; the sign does not change.

Caveats: spreads are a grid (no historical quotes); option prices are 15-minute trade VWAPs; data from 2024 only;
today's SEC ticker list (survivorship).

| trial | disc trades | mean | t | mean high | hit | val trades | mean | t | mean high | hit |
|---|---|---|---|---|---|---|---|---|---|---|
| H1_runup_3 | 1942 | -4.09% | -6.44 | -8.40% | 31.10% | 831 | -4.07% | -3.62 | -8.40% | 30.57% |
| H1_runup_5 | 1612 | -3.49% | -3.55 | -7.86% | 31.95% | 675 | -5.35% | -4.21 | -9.67% | 29.63% |
| H2_hold_all | 4100 | -6.27% | -6.74 | -10.56% | 31.10% | 1965 | -5.69% | -4.42 | -9.95% | 31.15% |
| H2_cheap_08 | 122 | 1.09% | 0.17 | -3.82% | 35.25% | 56 | 2.92% | 0.25 | -2.66% | 28.57% |
| H2_cheap_06 | 17 | 40.15% | 1.69 | 33.43% | 52.94% | 11 | 2.11% | 0.09 | -3.50% | 27.27% |
| H3_momentum | 4100 | -4.64% | -2.90 | -9.06% | 34.73% | 1965 | -3.96% | -1.36 | -8.32% | 36.03% |
| H3_last_reaction | 4067 | -7.78% | -4.44 | -12.07% | 34.10% | 1948 | -6.69% | -2.28 | -10.97% | 35.47% |
| H4_fly_all | 3287 | -9.03% | -10.07 | -17.78% | 47.55% | 1489 | -9.52% | -6.42 | -18.00% | 45.60% |
| H4_fly_12 | 2284 | -9.29% | -9.28 | -18.14% | 46.89% | 1089 | -9.10% | -7.16 | -17.63% | 45.09% |
| H4_fly_15 | 1661 | -8.44% | -7.96 | -17.46% | 47.26% | 843 | -10.30% | -8.26 | -18.97% | 42.94% |
