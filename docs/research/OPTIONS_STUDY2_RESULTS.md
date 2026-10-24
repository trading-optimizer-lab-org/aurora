# Options study 2 (0DTE, overnight, cross-section): results

Run `options-study2.yml` 40115411744 (2026-10-24), data to 2026-10-23, rules as in
`OPTIONS_STUDY2_PREREGISTRATION.md`. Summary: `data/options_study2_summary.json`.

**Not met.** No trial passes discovery; none passes validation.

| trial | disc trades | mean | t | mean high | val trades | mean | t | mean high |
|---|---|---|---|---|---|---|---|---|
| Z1_short_straddle | 957 | 0.032% | 1.31 | 0.018% | 408 | 0.025% | 1.07 | 0.015% |
| Z2_iron_fly | 957 | 0.014% | 1.47 | -0.008% | 407 | -0.007% | -0.40 | -0.024% |
| Z3_iron_condor | 958 | 0.013% | 2.53 | -0.006% | 406 | -0.000% | -0.01 | -0.015% |
| Z4_risk_reversal | 958 | -0.012% | -0.63 | -0.023% | 407 | 0.021% | 1.00 | 0.013% |
| Z5_put_ratio | 958 | -0.012% | -1.29 | -0.026% | 407 | 0.009% | 1.49 | -0.001% |
| N1_overnight_short | 922 | -0.70% | -1.50 | -1.80% | 396 | 0.39% | 0.68 | -0.63% |
| N2_intraday_long | 934 | -4.54% | -5.98 | -5.60% | 395 | -5.09% | -6.47 | -6.08% |
| N3_weekend_short | 191 | -1.44% | -1.29 | -2.56% | 84 | 3.34% | 2.00 | 2.33% |
| X1_vol_spread | 324 | -4.01% | -0.42 | -8.18% | 108 | 8.59% | 0.44 | 4.27% |
| X2_long_cheap | 161 | -0.62% | -0.07 | -2.66% | 54 | 15.15% | 1.00 | 12.91% |
| X3_short_rich | 163 | -3.39% | -0.56 | -5.53% | 54 | -6.56% | -0.42 | -8.64% |

Z in percent of spot a day; N on the straddle price; X monthly mean straddle return (trades = positions).

Notes, no decision:

- 0DTE: short premium earns a small positive mean (Z1 +0.03% of spot a day, Z3 t 2.53 in discovery), gone at
  high costs and in 2026, as Vilkov reports for SPX. Iron condor on its maximum loss: +3.7% (discovery), +0.5%
  (validation) a trade.
- Overnight and intraday: the sign of Muravyev and Ni (2020) does not appear in 2024-2026. Short straddles
  overnight lose on average; long straddles intraday lose clearly.
- N2 has 10.7% intrinsic-value exits (a leg without a 15:45 trade). Without them (exploratory run 40118515212):
  -1.2% (t -1.85) in discovery and -1.7% (t -2.40) in validation; still negative.
- X is underpowered: 13,519 planned positions had no trade in the 15:30 bar of one leg (Alpaca's option bars are
  sparse even for large names), leaving about 7 positions a decile a month. With the earnings study's entry rule
  (latest bar from 14:30), exploratory: X1 -7.6% (t -1.05) discovery, +15.4% (t 0.82) validation, about 22
  positions a decile a month; no effect either.

Caveats: spreads are a grid; option prices are 15-minute trade VWAPs; data from 2024; today's optionable list for X.
