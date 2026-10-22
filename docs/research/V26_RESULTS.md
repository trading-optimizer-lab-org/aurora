# v26 results: the squeeze shield for the small-cap shorts (427,525 configurations)

Pre-registered in [V26_PREREGISTRATION.md](V26_PREREGISTRATION.md).

| run | GitHub run | what happened |
|---|---|---|
| v26 data | 39651846112 | night store: 2,702 of 2,702 nights, 364,616 symbol-nights, 21.3M bars; 2,580 of 3,000 quote minutes |
| v26 early canaries | 39658938040, 39659915571 | without the night store; the first found a quick-mode bug in the final report (fixed), the second passed |
| v26, attempt 1 | 39656506041 | its canary stopped on that bug (the fix came after the run started); nothing else ran |
| v26, attempt 2 | 39662052414 | canary, 300 real shards and the selection passed; the placebo jobs were skipped (a skipped rerun job upstream skips jobs with the default condition), so the report failed |
| **v26 resume** | **39731260564** (2026-10-22) | **this report**: that run's selection artifact, then placebos, report, robustness, one account; same code and rules |

427,525 of 427,525 configurations, no errors, 500 placebos for each selected configuration, R4 costs with the measured
extended-session half-spreads (after hours <$2 0.46%, $2-5 0.41%, $5-10 0.25%, $10-20 0.18%; premarket similar).

## Summary

- **The pre-registered criterion is met.** `COMBO26`: walk-forward monthly Sortino **5.58** (14.04 in 2018-2020, 4.21
  in 2021-2026), 13.2% a year, drawdown -5.2%, PBO 0%, 2023-07+ **3.75**; deflated Sharpe 0.00 over all trials. Every
  year positive (+5.5% to +24.2%). All 23 families pass the gate (best AS 4.80, IV 4.74, OR 4.42, PS 4.14).
- **The shield helps the one-minute families, not the daily ones.** Against each family's own exit at the same costs:
  v23/v25 families improve (OR 2.36 -> 4.42, SR 1.96 -> 3.68, AS 3.08 -> 4.80, MP 1.40 -> 2.77, VW 1.44 -> 2.71) with
  lower drawdowns; v19/v20 families lose (RU 5.63 -> 2.72, XS1 5.04 -> 3.20, DS1 3.78 -> 2.84, IV 5.99 -> 4.74): their
  own exits held longer than the shield's five sessions. Own exits of v22c, v23b and v25 reproduce their source runs
  exactly.
- **What the shield picked**: hold to the third close; the after-hours stop in most picks, but it adds only hundredths
  of Sortino against no extended-session stop; rally exits and split covers hurt; the shares-outstanding filters hurt
  a lot (bigger floats fade less), the offering filter hurts.
- **The tail is still there**: worst single trades -89% to -473% of the position (overnight gaps the after-hours and
  premarket bars do not catch).
- **Fragile to costs.** At the high costs (spreads x2, borrow x3) families fall to -0.8..1.3; spreads break even at x2.5
  to x7.5; borrow x5 kills most; without the best 5% of trades most go negative; with half the trades not borrowable the
  median family Sortino is ~1.2.
- **The tail rule** (comparison only; the owner chose Sortino alone) would have lowered most families.
- **One account (book A, v26 picks), the owner's rule**: $100k -> risk 1%, cap 40%, gross 1x: Sortino 4.63, compounded
  CAGR 113.5% (overstated: liquidity caps on a fixed account), max DD -54.2%, worst day -27.6%, p75 0.1% at the middle
  costs; **at the high costs CAGR -15.6%, DD -95%, p75 89%**. Book B (own exits) at $100k: Sortino 3.96, 70% CAGR,
  DD -31.9%, high costs also ruinous.

## Report

Configurations evaluated 427525 of 427525; errors 0. R4 costs (middle) unless stated; 500 placebos for each selected configuration; a configuration can be picked only with at least 50 trades and a trade in 40% of the months before. Target: COMBO26 monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | low | high | auction | gross | years placebo-ok | gate | PBO | SPA p (best t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v19:XS1 | 3.20 | 16.44 | 1.99 | 16.2% | -8.0% | 4.01 | -0.09 | 3.35 | 10.68 | 8/9 | pass | 2% | 0.000 (7.0) |
| v19:XS2 | 2.01 | 12.20 | 0.88 | 11.8% | -11.8% | 2.83 | -0.36 | 2.14 | 11.00 | 9/9 | pass | 3% | 0.000 (5.7) |
| v19:DS1 | 2.84 | 8.61 | 2.40 | 20.5% | -19.2% | 3.34 | 1.23 | 3.19 | 5.17 | 9/9 | pass | 0% | 0.000 (5.1) |
| v19:ON1 | 3.63 | 4.95 | 3.32 | 13.8% | -10.3% | 4.30 | 0.73 | 3.71 | 10.56 | 9/9 | pass | 1% | 0.000 (5.0) |
| v20:GF | 2.45 | 10.11 | 1.77 | 12.1% | -8.2% | 2.94 | 0.29 | 2.54 | 6.33 | 6/9 | pass | 0% | 0.000 (7.3) |
| v20:RF | 2.51 | 5.12 | 1.87 | 12.2% | -9.0% | 3.24 | 0.33 | 2.66 | 8.16 | 9/9 | pass | 3% | 0.000 (6.6) |
| v20:RU | 2.72 | 4.51 | 2.45 | 20.5% | -17.7% | 3.10 | 1.32 | 2.98 | 4.74 | 9/9 | pass | 0% | 0.000 (5.6) |
| v20:NS | 1.40 | 2.14 | 1.24 | 8.4% | -14.0% | 1.63 | 0.06 | 1.49 | 3.02 | 9/9 | pass | 0% | 0.000 (5.2) |
| v22:IV | 4.74 | 12.26 | 4.06 | 19.9% | -9.7% | 6.41 | 0.11 | 5.00 | 20.00 | 9/9 | pass | 0% | 0.000 (8.0) |
| v22:IR | 1.85 | 3.17 | 1.19 | 15.6% | -22.4% | 2.65 | -0.43 | 1.97 | 9.07 | 9/9 | pass | 4% | 0.000 (4.7) |
| v22:IF | 2.35 | 3.67 | 1.71 | 9.8% | -4.9% | 2.84 | -0.08 | 2.43 | 7.04 | 9/9 | pass | 0% | 0.000 (5.6) |
| v23:SR | 3.68 | 11.03 | 2.47 | 14.0% | -8.8% | 4.20 | 1.34 | 3.75 | 7.65 | 9/9 | pass | 0% | 0.000 (5.7) |
| v23:VW | 2.71 | 8.85 | 2.18 | 11.8% | -7.9% | 3.42 | 0.18 | 2.84 | 8.49 | 9/9 | pass | 5% | 0.000 (6.0) |
| v23:EM | 2.69 | 3.14 | 2.57 | 17.0% | -10.4% | 3.99 | -0.77 | 2.89 | 15.48 | 8/9 | pass | 0% | 0.000 (7.5) |
| v23:OS | 1.81 | 3.14 | 1.42 | 11.7% | -12.8% | 2.89 | -0.63 | 1.97 | 11.42 | 9/9 | pass | 0% | 0.000 (7.7) |
| v23:MD | 1.22 | 1.32 | 1.16 | 10.3% | -18.8% | 1.95 | -0.82 | 1.33 | 8.11 | 6/9 | pass | 4% | 0.000 (5.1) |
| v23:SQ | 2.01 | 2.30 | 1.84 | 12.6% | -11.2% | 2.88 | -0.77 | 2.15 | 10.04 | 9/9 | pass | 0% | 0.000 (5.6) |
| v23:PT | 3.33 | 4.02 | 2.97 | 11.6% | -5.8% | 4.03 | 0.57 | 3.45 | 9.41 | 8/9 | pass | 0% | 0.002 (4.4) |
| v23:OR | 4.42 | 8.75 | 2.96 | 13.6% | -4.5% | 5.44 | 0.91 | 4.61 | 13.22 | 8/9 | pass | 0% | 0.000 (6.7) |
| v25:AS | 4.80 | 7.93 | 4.57 | 18.1% | -7.3% | 5.85 | 0.38 | 4.98 | 17.34 | 9/9 | pass | 0% | 0.000 (8.3) |
| v25:MP | 2.77 | 5.80 | 2.15 | 13.6% | -7.8% | 3.53 | 0.19 | 2.89 | 9.13 | 9/9 | pass | 2% | 0.000 (8.7) |
| v25:IS | 3.32 | 5.84 | 2.85 | 15.8% | -9.2% | 4.81 | -0.64 | 3.56 | 18.29 | 9/9 | pass | 3% | 0.000 (8.3) |
| v25:PS | 4.14 | 3.79 | 4.28 | 13.4% | -5.8% | 5.16 | 0.75 | 4.33 | 11.96 | 8/9 | pass | 2% | 0.000 (7.2) |

## 2. COMBO26 (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO26 | 5.58 | 14.04 | 4.21 | 13.2% | -5.2% | +196% | 3.75 | 0.00 | 0% | met |

Members by year: 2018: v19:DS1, v19:ON1, v19:XS2, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:OS, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP; 2019: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2020: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2021: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2022: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2023: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2024: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2025: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2026: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS

COMBO26 by year: 2018 +9.8%, 2019 +8.8%, 2020 +23.9%, 2021 +10.0%, 2022 +5.5%, 2023 +17.0%, 2024 +10.0%, 2025 +24.2%, 2026 +7.9%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| v19:XS1 | 1.02 | 11.1% | -8.0% |
| v19:XS2 | 0.96 | 10.3% | -11.8% |
| v19:DS1 | 3.13 | 36.4% | -19.2% |
| v19:ON1 | 3.19 | 15.4% | -8.5% |
| v20:GF | 1.61 | 13.8% | -8.2% |
| v20:RF | 1.71 | 14.0% | -9.0% |
| v20:RU | 2.42 | 28.3% | -17.7% |
| v20:NS | 0.84 | 9.5% | -14.0% |
| v22:IV | 3.95 | 25.0% | -9.7% |
| v22:IR | 0.44 | 7.8% | -22.4% |
| v22:IF | 1.58 | 10.5% | -4.9% |
| v23:SR | 2.92 | 18.2% | -8.8% |
| v23:VW | 2.07 | 14.7% | -7.9% |
| v23:EM | 3.17 | 25.6% | -10.4% |
| v23:OS | 0.59 | 8.2% | -12.8% |
| v23:MD | 0.78 | 10.0% | -17.0% |
| v23:SQ | 1.91 | 16.6% | -10.1% |
| v23:PT | 4.29 | 17.4% | -4.4% |
| v23:OR | 3.03 | 14.7% | -4.5% |
| v25:AS | 4.53 | 27.1% | -7.3% |
| v25:MP | 2.06 | 15.3% | -7.8% |
| v25:IS | 2.96 | 19.5% | -9.2% |
| v25:PS | 4.14 | 19.2% | -5.8% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| v19:XS1 | 32.0 | +2.9% | 59% | -170% |
| v19:XS2 | 34.7 | +2.4% | 56% | -122% |
| v19:DS1 | 7.6 | +6.3% | 67% | -303% |
| v19:ON1 | 7.8 | +5.4% | 68% | -151% |
| v20:GF | 17.5 | +3.8% | 59% | -170% |
| v20:RF | 32.0 | +2.3% | 59% | -108% |
| v20:RU | 6.8 | +7.2% | 67% | -222% |
| v20:NS | 4.7 | +5.8% | 67% | -160% |
| v22:IV | 37.8 | +2.5% | 55% | -146% |
| v22:IR | 46.5 | +1.7% | 53% | -473% |
| v22:IF | 13.9 | +3.8% | 59% | -172% |
| v23:SR | 12.6 | +5.3% | 55% | -89% |
| v23:VW | 26.1 | +3.1% | 60% | -193% |
| v23:EM | 42.8 | +1.7% | 50% | -185% |
| v23:OS | 51.7 | +1.5% | 55% | -102% |
| v23:MD | 52.3 | +1.6% | 56% | -200% |
| v23:SQ | 30.3 | +1.9% | 53% | -156% |
| v23:PT | 13.5 | +4.5% | 58% | -242% |
| v23:OR | 23.3 | +3.9% | 60% | -170% |
| v25:AS | 21.7 | +4.2% | 58% | -183% |
| v25:MP | 30.0 | +3.3% | 58% | -194% |
| v25:IS | 39.5 | +1.9% | 54% | -182% |
| v25:PS | 29.4 | +3.7% | 62% | -201% |

## 5. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| v19:XS1 | entry | XS1_GAPFADE|111 0.01 (3) / XS1_GAPFADE|127 -0.20 (1) / XS1_GAPFADE|319 -0.08 (4) / XS1_GAPFADE|607 0.80 (1) |
| v19:XS1 | hold | d1 -1.01 (0) / d2 0.06 (1) / d3 0.19 (6) / d5 0.07 (2) |
| v19:XS1 | stop | own 0.61 (6) / pct10 -0.11 (0) / pct20 0.61 (1) / pct35 0.09 (2) / pct50 -0.25 (0) / atr2 -0.29 (0) / atr4 0.36 (0) |
| v19:XS1 | ext | none 0.07 (0) / ah 0.10 (6) / pm 0.08 (1) / both 0.08 (2) |
| v19:XS1 | rally | none 0.31 (8) / r5 -0.14 (0) / r15 0.14 (1) |
| v19:XS1 | scale | all 0.57 (7) / half -0.18 (0) / third 0.06 (2) |
| v19:XS1 | filt | none 1.28 (7) / so10 -0.58 (0) / so20 -1.36 (0) / offer90 0.37 (0) / nosq60 1.00 (2) |
| v19:XS2 | entry | XS2_RUNFADE|107 -0.81 (3) / XS2_RUNFADE|152 1.26 (4) / XS2_RUNFADE|154 1.26 (2) / XS2_RUNFADE|155 1.26 (0) / XS2_RUNFADE|167 1.89 (0) / XS2_RUNFADE|35 -0.41 (0) / XS2_RUNFADE|95 -0.16 (0) |
| v19:XS2 | hold | d1 -0.30 (0) / d2 0.31 (2) / d3 0.35 (6) / d5 0.22 (1) |
| v19:XS2 | stop | own 0.45 (5) / pct10 0.01 (0) / pct20 0.45 (0) / pct35 0.31 (3) / pct50 0.14 (0) / atr2 -0.18 (0) / atr4 0.46 (1) |
| v19:XS2 | ext | none 0.28 (0) / ah 0.33 (5) / pm 0.26 (1) / both 0.28 (3) |
| v19:XS2 | rally | none 0.35 (9) / r5 0.20 (0) / r15 0.29 (0) |
| v19:XS2 | scale | all 0.49 (5) / half 0.14 (4) / third 0.27 (0) |
| v19:XS2 | filt | none 1.54 (7) / so10 -0.05 (0) / so20 -0.74 (0) / offer90 0.68 (0) / nosq60 1.52 (2) |
| v19:DS1 | entry | DS1_RUNUP|1281 -0.26 (5) / DS1_RUNUP|1295 -0.26 (0) / DS1_RUNUP|1822 -0.28 (2) / DS1_RUNUP|1930 -1.38 (0) / DS1_RUNUP|2001 -0.31 (2) |
| v19:DS1 | hold | d1 -0.51 (3) / d2 -0.43 (3) / d3 -0.48 (1) / d5 -0.48 (2) |
| v19:DS1 | stop | own 0.66 (9) / pct10 -1.47 (0) / pct20 -0.93 (0) / pct35 -0.24 (0) / pct50 -0.12 (0) / atr2 -0.58 (0) / atr4 -0.21 (0) |
| v19:DS1 | ext | none -0.47 (5) / ah -0.47 (1) / pm -0.48 (1) / both -0.48 (2) |
| v19:DS1 | rally | none -0.33 (6) / r5 -0.55 (3) / r15 -0.51 (0) |
| v19:DS1 | scale | all -0.48 (2) / half -0.48 (4) / third -0.46 (3) |
| v19:DS1 | filt | none -0.31 (7) / so10 -0.24 (0) / so20 -0.62 (0) / offer90 -0.47 (2) / nosq60 -0.42 (0) |
| v19:ON1 | entry | ON1_NIGHTSHORT|10 0.05 (2) / ON1_NIGHTSHORT|11 0.02 (5) / ON1_NIGHTSHORT|14 0.05 (0) / ON1_NIGHTSHORT|15 0.02 (1) / ON1_NIGHTSHORT|25 1.15 (0) / ON1_NIGHTSHORT|8 0.69 (1) |
| v19:ON1 | hold | d1 0.24 (0) / d2 0.35 (3) / d3 0.31 (1) / d5 0.42 (5) |
| v19:ON1 | stop | own 0.39 (0) / pct10 0.04 (0) / pct20 0.32 (0) / pct35 0.35 (0) / pct50 0.42 (0) / atr2 0.34 (0) / atr4 0.46 (9) |
| v19:ON1 | ext | none 0.42 (1) / ah 0.41 (8) / pm 0.23 (0) / both 0.24 (0) |
| v19:ON1 | rally | none 1.06 (9) / r5 -0.40 (0) / r15 0.45 (0) |
| v19:ON1 | scale | all 0.33 (3) / half 0.32 (5) / third 0.33 (1) |
| v19:ON1 | filt | none 1.51 (9) / so10 0.29 (0) / so20 -0.31 (0) / offer90 0.06 (0) / nosq60 1.42 (0) |
| v20:GF | entry | GF_GAPFADE|2813 0.03 (1) / GF_GAPFADE|2821 -0.04 (1) / GF_GAPFADE|2859 0.17 (2) / GF_GAPFADE|6593 0.29 (1) / GF_GAPFADE|6602 0.31 (0) / GF_GAPFADE|6604 0.31 (2) / GF_GAPFADE|6649 0.37 (2) |
| v20:GF | hold | d1 -0.60 (0) / d2 0.18 (1) / d3 0.28 (5) / d5 0.26 (3) |
| v20:GF | stop | own 0.46 (6) / pct10 0.25 (1) / pct20 0.48 (1) / pct35 0.03 (0) / pct50 -0.43 (0) / atr2 0.10 (0) / atr4 0.37 (1) |
| v20:GF | ext | none 0.21 (4) / ah 0.25 (3) / pm 0.22 (1) / both 0.22 (1) |
| v20:GF | rally | none 0.47 (7) / r5 -0.01 (0) / r15 0.29 (2) |
| v20:GF | scale | all 0.48 (8) / half 0.02 (0) / third 0.18 (1) |
| v20:GF | filt | none 1.71 (9) / so10 -0.49 (0) / so20 -1.32 (0) / offer90 0.25 (0) / nosq60 1.41 (0) |
| v20:RF | entry | RF_RUNFADE|400 1.25 (1) / RF_RUNFADE|404 1.25 (1) / RF_RUNFADE|406 1.25 (2) / RF_RUNFADE|690 1.45 (1) / RF_RUNFADE|70 0.16 (3) / RF_RUNFADE|931 0.24 (1) |
| v20:RF | hold | d1 0.16 (0) / d2 0.65 (4) / d3 0.70 (4) / d5 0.51 (1) |
| v20:RF | stop | own 0.90 (4) / pct10 0.57 (0) / pct20 0.88 (3) / pct35 0.63 (0) / pct50 0.35 (1) / atr2 0.33 (0) / atr4 0.79 (1) |
| v20:RF | ext | none 0.61 (0) / ah 0.64 (5) / pm 0.61 (2) / both 0.62 (2) |
| v20:RF | rally | none 0.77 (8) / r5 0.43 (0) / r15 0.65 (1) |
| v20:RF | scale | all 0.76 (1) / half 0.50 (7) / third 0.63 (1) |
| v20:RF | filt | none 2.20 (9) / so10 -0.13 (0) / so20 -0.91 (0) / offer90 1.04 (0) / nosq60 2.00 (0) |
| v20:RU | entry | RU_RUNUP|10635 -0.22 (0) / RU_RUNUP|10636 -0.22 (0) / RU_RUNUP|10897 -0.28 (1) / RU_RUNUP|4818 -0.46 (7) / RU_RUNUP|4876 -0.46 (1) |
| v20:RU | hold | d1 -0.25 (0) / d2 -0.26 (6) / d3 -0.31 (0) / d5 -0.30 (3) |
| v20:RU | stop | own 0.82 (8) / pct10 -1.32 (0) / pct20 -0.66 (0) / pct35 -0.18 (1) / pct50 -0.11 (0) / atr2 -0.44 (0) / atr4 -0.19 (0) |
| v20:RU | ext | none -0.24 (2) / ah -0.29 (5) / pm -0.25 (1) / both -0.33 (1) |
| v20:RU | rally | none -0.13 (5) / r5 -0.38 (0) / r15 -0.30 (4) |
| v20:RU | scale | all -0.30 (3) / half -0.27 (1) / third -0.26 (5) |
| v20:RU | filt | none -0.07 (8) / so10 -0.16 (0) / so20 -0.60 (0) / offer90 -0.30 (0) / nosq60 -0.26 (1) |
| v20:NS | entry | NS_NIGHTSHORT|228 -0.28 (1) / NS_NIGHTSHORT|308 -0.55 (1) / NS_NIGHTSHORT|418 0.58 (1) / NS_NIGHTSHORT|540 -0.17 (3) / NS_NIGHTSHORT|546 0.29 (1) / NS_NIGHTSHORT|548 -0.17 (2) |
| v20:NS | hold | d1 -0.24 (0) / d2 -0.01 (4) / d3 -0.05 (4) / d5 -0.03 (1) |
| v20:NS | stop | own 0.08 (7) / pct10 -0.32 (0) / pct20 -0.16 (0) / pct35 -0.04 (0) / pct50 -0.03 (0) / atr2 -0.11 (0) / atr4 -0.05 (2) |
| v20:NS | ext | none -0.02 (5) / ah -0.04 (1) / pm -0.13 (3) / both -0.13 (0) |
| v20:NS | rally | none 0.47 (9) / r5 -0.40 (0) / r15 -0.00 (0) |
| v20:NS | scale | all -0.03 (7) / half -0.13 (0) / third -0.09 (2) |
| v20:NS | filt | none 0.85 (9) / so10 -0.27 (0) / so20 -0.74 (0) / offer90 -0.31 (0) / nosq60 0.75 (0) |
| v22:IV | entry | IV_VWAPBAND|1609 1.16 (2) / IV_VWAPBAND|745 1.36 (3) / IV_VWAPBAND|781 0.50 (4) |
| v22:IV | hold | d1 -0.08 (0) / d2 0.86 (0) / d3 1.05 (9) / d5 0.79 (0) |
| v22:IV | stop | own 1.55 (8) / pct10 0.57 (0) / pct20 1.55 (1) / pct35 0.98 (0) / pct50 0.46 (0) / atr2 1.00 (0) / atr4 1.15 (0) |
| v22:IV | ext | none 0.85 (0) / ah 0.91 (5) / pm 0.90 (3) / both 0.89 (1) |
| v22:IV | rally | none 1.29 (9) / r5 0.56 (0) / r15 1.01 (0) |
| v22:IV | scale | all 1.08 (6) / half 0.70 (2) / third 0.90 (1) |
| v22:IV | filt | none 1.98 (9) / so10 -0.14 (0) / so20 -0.91 (0) / offer90 1.59 (0) / nosq60 1.73 (0) |
| v22:IR | entry | IR_RSI1M|310 0.31 (4) / IR_RSI1M|313 0.35 (5) |
| v22:IR | hold | d1 -0.09 (0) / d2 0.40 (0) / d3 0.47 (9) / d5 0.19 (0) |
| v22:IR | stop | own 0.36 (0) / pct10 0.25 (3) / pct20 0.59 (3) / pct35 0.50 (3) / pct50 0.19 (0) / atr2 0.20 (0) / atr4 0.54 (0) |
| v22:IR | ext | none 0.34 (6) / ah 0.33 (1) / pm 0.34 (1) / both 0.33 (1) |
| v22:IR | rally | none 0.59 (9) / r5 0.16 (0) / r15 0.36 (0) |
| v22:IR | scale | all 0.32 (5) / half 0.30 (2) / third 0.38 (2) |
| v22:IR | filt | none 1.05 (7) / so10 -0.35 (0) / so20 -1.05 (0) / offer90 0.50 (0) / nosq60 0.81 (2) |
| v22:IF | entry | IF_FLAG|169 0.04 (0) / IF_FLAG|439 0.19 (4) / IF_FLAG|481 0.36 (2) / IF_FLAG|754 0.43 (3) / IF_FLAG|763 0.43 (0) |
| v22:IF | hold | d1 -0.86 (0) / d2 0.23 (0) / d3 0.39 (3) / d5 0.32 (6) |
| v22:IF | stop | own 0.63 (0) / pct10 0.75 (2) / pct20 0.56 (4) / pct35 -0.03 (3) / pct50 -0.65 (0) / atr2 0.41 (0) / atr4 -0.04 (0) |
| v22:IF | ext | none 0.26 (5) / ah 0.30 (2) / pm 0.29 (2) / both 0.29 (0) |
| v22:IF | rally | none 0.52 (9) / r5 0.00 (0) / r15 0.39 (0) |
| v22:IF | scale | all 0.56 (7) / half -0.01 (0) / third 0.16 (2) |
| v22:IF | filt | none 1.37 (9) / so10 -0.34 (0) / so20 -1.04 (0) / offer90 0.33 (0) / nosq60 1.42 (0) |
| v23:SR | entry | SR_LEVEL|26674 0.63 (6) / SR_LEVEL|34450 0.18 (0) / SR_LEVEL|55186 0.73 (3) / SR_LEVEL|57778 0.25 (0) |
| v23:SR | hold | d1 -0.43 (0) / d2 0.35 (1) / d3 0.51 (7) / d5 0.51 (1) |
| v23:SR | stop | own 1.09 (0) / pct10 1.09 (0) / pct20 0.60 (9) / pct35 -0.07 (0) / pct50 -0.65 (0) / atr2 0.58 (0) / atr4 0.15 (0) |
| v23:SR | ext | none 0.42 (1) / ah 0.47 (6) / pm 0.43 (2) / both 0.46 (0) |
| v23:SR | rally | none 0.67 (9) / r5 0.16 (0) / r15 0.53 (0) |
| v23:SR | scale | all 0.72 (9) / half 0.22 (0) / third 0.36 (0) |
| v23:SR | filt | none 1.82 (9) / so10 -0.11 (0) / so20 -0.89 (0) / offer90 0.23 (0) / nosq60 1.60 (0) |
| v23:VW | entry | VW_VWAP|3127 0.06 (0) / VW_VWAP|3130 0.31 (9) / VW_VWAP|538 0.13 (0) |
| v23:VW | hold | d1 -0.43 (0) / d2 0.26 (3) / d3 0.30 (5) / d5 -0.01 (1) |
| v23:VW | stop | own 0.26 (0) / pct10 0.26 (0) / pct20 0.31 (4) / pct35 0.15 (5) / pct50 -0.28 (0) / atr2 0.34 (0) / atr4 0.32 (0) |
| v23:VW | ext | none 0.14 (3) / ah 0.17 (5) / pm 0.17 (1) / both 0.17 (0) |
| v23:VW | rally | none 0.56 (9) / r5 -0.06 (0) / r15 0.29 (0) |
| v23:VW | scale | all 0.25 (6) / half 0.06 (0) / third 0.22 (3) |
| v23:VW | filt | none 0.67 (9) / so10 -0.61 (0) / so20 -1.18 (0) / offer90 0.63 (0) / nosq60 0.63 (0) |
| v23:EM | entry | EM_EMA|1438 -0.09 (0) / EM_EMA|2515 0.16 (1) / EM_EMA|355 0.71 (4) / EM_EMA|358 -0.02 (0) / EM_EMA|718 0.16 (4) |
| v23:EM | hold | d1 -0.45 (0) / d2 0.21 (1) / d3 0.20 (8) / d5 -0.08 (0) |
| v23:EM | stop | own 0.03 (2) / pct10 0.03 (0) / pct20 0.61 (7) / pct35 0.16 (0) / pct50 -0.10 (0) / atr2 0.02 (0) / atr4 0.26 (0) |
| v23:EM | ext | none 0.07 (1) / ah 0.11 (6) / pm 0.09 (0) / both 0.10 (2) |
| v23:EM | rally | none 0.44 (9) / r5 -0.16 (0) / r15 0.21 (0) |
| v23:EM | scale | all 0.17 (7) / half 0.01 (0) / third 0.16 (2) |
| v23:EM | filt | none 0.79 (9) / so10 -0.83 (0) / so20 -1.31 (0) / offer90 0.70 (0) / nosq60 0.50 (0) |
| v23:OS | entry | OS_OSC|430 -0.81 (0) / OS_OSC|6838 -0.36 (0) / OS_OSC|7846 0.54 (2) / OS_OSC|931 0.30 (0) / OS_OSC|934 0.84 (7) |
| v23:OS | hold | d1 -0.53 (0) / d2 -0.28 (3) / d3 -0.24 (6) / d5 -0.36 (0) |
| v23:OS | stop | own -0.29 (0) / pct10 -0.29 (0) / pct20 -0.29 (5) / pct35 -0.34 (3) / pct50 -0.53 (1) / atr2 -0.15 (0) / atr4 -0.18 (0) |
| v23:OS | ext | none -0.29 (6) / ah -0.28 (1) / pm -0.31 (1) / both -0.30 (1) |
| v23:OS | rally | none -0.14 (9) / r5 -0.46 (0) / r15 -0.35 (0) |
| v23:OS | scale | all -0.16 (2) / half -0.40 (3) / third -0.33 (4) |
| v23:OS | filt | none 1.02 (8) / so10 -0.69 (0) / so20 -1.34 (0) / offer90 0.65 (0) / nosq60 0.75 (1) |
| v23:MD | entry | MD_MACD|1258 0.42 (6) / MD_MACD|175 -0.40 (3) / MD_MACD|178 -0.17 (0) |
| v23:MD | hold | d1 -0.60 (0) / d2 -0.02 (3) / d3 -0.06 (6) / d5 -0.33 (0) |
| v23:MD | stop | own -0.11 (1) / pct10 -0.11 (0) / pct20 -0.08 (2) / pct35 -0.03 (4) / pct50 -0.30 (2) / atr2 -0.24 (0) / atr4 -0.12 (0) |
| v23:MD | ext | none -0.18 (2) / ah -0.15 (6) / pm -0.16 (0) / both -0.15 (1) |
| v23:MD | rally | none 0.18 (9) / r5 -0.46 (0) / r15 -0.07 (0) |
| v23:MD | scale | all -0.13 (7) / half -0.24 (0) / third -0.08 (2) |
| v23:MD | filt | none 0.41 (9) / so10 -0.85 (0) / so20 -1.33 (0) / offer90 0.44 (0) / nosq60 0.24 (0) |
| v23:SQ | entry | SQ_SQUEEZE|1075 -0.49 (0) / SQ_SQUEEZE|1345 -0.27 (6) / SQ_SQUEEZE|1435 -0.74 (0) / SQ_SQUEEZE|985 -0.16 (3) |
| v23:SQ | hold | d1 -1.35 (0) / d2 -0.49 (3) / d3 -0.35 (5) / d5 -0.53 (1) |
| v23:SQ | stop | own -0.53 (3) / pct10 -0.53 (0) / pct20 -0.21 (5) / pct35 -0.46 (0) / pct50 -0.79 (1) / atr2 -0.49 (0) / atr4 -0.22 (0) |
| v23:SQ | ext | none -0.49 (5) / ah -0.45 (3) / pm -0.49 (1) / both -0.49 (0) |
| v23:SQ | rally | none -0.17 (9) / r5 -0.74 (0) / r15 -0.35 (0) |
| v23:SQ | scale | all -0.21 (8) / half -0.68 (0) / third -0.51 (1) |
| v23:SQ | filt | none 0.24 (8) / so10 -1.10 (0) / so20 -1.55 (0) / offer90 -0.14 (1) / nosq60 0.05 (0) |
| v23:PT | entry | PT_PATTERN|1345 -1.49 (1) / PT_PATTERN|1888 0.26 (5) / PT_PATTERN|2065 0.50 (2) / PT_PATTERN|2068 0.40 (1) |
| v23:PT | hold | d1 -1.17 (0) / d2 -0.49 (0) / d3 -0.33 (7) / d5 -0.43 (2) |
| v23:PT | stop | own -0.24 (1) / pct10 -0.24 (0) / pct20 -0.21 (6) / pct35 -0.54 (2) / pct50 -1.03 (0) / atr2 -0.17 (0) / atr4 -0.60 (0) |
| v23:PT | ext | none -0.41 (4) / ah -0.41 (3) / pm -0.42 (2) / both -0.43 (0) |
| v23:PT | rally | none -0.27 (9) / r5 -0.64 (0) / r15 -0.39 (0) |
| v23:PT | scale | all -0.13 (8) / half -0.68 (0) / third -0.53 (1) |
| v23:PT | filt | none 1.12 (7) / so10 -0.76 (0) / so20 -1.40 (0) / offer90 0.12 (0) / nosq60 1.14 (2) |
| v23:OR | entry | OR_ORB|3712 0.21 (2) / OR_ORB|3715 0.75 (7) / OR_ORB|5011 0.42 (0) |
| v23:OR | hold | d1 -0.87 (0) / d2 0.40 (1) / d3 0.59 (8) / d5 0.38 (0) |
| v23:OR | stop | own 0.59 (1) / pct10 0.59 (0) / pct20 0.57 (3) / pct35 0.33 (5) / pct50 -0.01 (0) / atr2 0.21 (0) / atr4 0.85 (0) |
| v23:OR | ext | none 0.40 (3) / ah 0.44 (2) / pm 0.44 (4) / both 0.44 (0) |
| v23:OR | rally | none 0.80 (9) / r5 0.10 (0) / r15 0.61 (0) |
| v23:OR | scale | all 0.78 (6) / half 0.17 (0) / third 0.40 (3) |
| v23:OR | filt | none 1.36 (9) / so10 -0.23 (0) / so20 -1.11 (0) / offer90 0.77 (0) / nosq60 1.18 (0) |
| v25:AS | entry | AS_ABCD|1615 0.89 (0) / AS_ABCD|1618 0.35 (0) / AS_ABCD|1975 1.44 (5) / AS_ABCD|1978 0.75 (4) |
| v25:AS | hold | d1 -0.19 (0) / d2 0.66 (0) / d3 0.86 (5) / d5 0.75 (4) |
| v25:AS | stop | own 0.95 (0) / pct10 1.16 (0) / pct20 1.21 (8) / pct35 0.38 (1) / pct50 -0.09 (0) / atr2 0.92 (0) / atr4 0.76 (0) |
| v25:AS | ext | none 0.73 (2) / ah 0.76 (7) / pm 0.74 (0) / both 0.74 (0) |
| v25:AS | rally | none 1.10 (9) / r5 0.34 (0) / r15 0.81 (0) |
| v25:AS | scale | all 0.95 (7) / half 0.57 (2) / third 0.68 (0) |
| v25:AS | filt | none 2.02 (9) / so10 0.05 (0) / so20 -0.91 (0) / offer90 0.83 (0) / nosq60 1.87 (0) |
| v25:MP | entry | MP_MORNPOP|1040 0.07 (0) / MP_MORNPOP|1054 1.33 (3) / MP_MORNPOP|136 0.87 (1) / MP_MORNPOP|334 1.21 (0) / MP_MORNPOP|859 1.65 (5) |
| v25:MP | hold | d1 0.28 (0) / d2 0.79 (0) / d3 0.86 (8) / d5 0.71 (1) |
| v25:MP | stop | own 0.90 (1) / pct10 0.94 (0) / pct20 1.06 (3) / pct35 0.74 (5) / pct50 0.25 (0) / atr2 0.69 (0) / atr4 0.88 (0) |
| v25:MP | ext | none 0.77 (6) / ah 0.78 (0) / pm 0.78 (0) / both 0.78 (3) |
| v25:MP | rally | none 1.01 (9) / r5 0.56 (0) / r15 0.80 (0) |
| v25:MP | scale | all 0.91 (7) / half 0.67 (0) / third 0.78 (2) |
| v25:MP | filt | none 2.10 (8) / so10 -0.02 (0) / so20 -0.65 (0) / offer90 1.32 (1) / nosq60 1.83 (0) |
| v25:IS | entry | IS_IND|15835 0.45 (0) / IS_IND|2878 0.83 (1) / IS_IND|5467 0.36 (1) / IS_IND|6766 0.84 (4) / IS_IND|8062 -0.06 (3) |
| v25:IS | hold | d1 -0.36 (0) / d2 0.50 (1) / d3 0.52 (8) / d5 0.17 (0) |
| v25:IS | stop | own 0.42 (0) / pct10 0.20 (1) / pct20 0.97 (7) / pct35 0.46 (1) / pct50 0.08 (0) / atr2 0.15 (0) / atr4 0.64 (0) |
| v25:IS | ext | none 0.34 (2) / ah 0.38 (5) / pm 0.36 (1) / both 0.34 (1) |
| v25:IS | rally | none 0.86 (9) / r5 -0.01 (0) / r15 0.52 (0) |
| v25:IS | scale | all 0.47 (5) / half 0.20 (1) / third 0.43 (3) |
| v25:IS | filt | none 1.28 (9) / so10 -0.57 (0) / so20 -1.25 (0) / offer90 1.16 (0) / nosq60 1.05 (0) |
| v25:PS | entry | PS_PATTERN|5899 0.59 (9) / PS_PATTERN|6475 0.37 (0) / PS_PATTERN|6619 -0.10 (0) / PS_PATTERN|6908 -0.57 (0) |
| v25:PS | hold | d1 -1.13 (0) / d2 0.00 (2) / d3 0.23 (7) / d5 0.14 (0) |
| v25:PS | stop | own 0.16 (0) / pct10 0.02 (0) / pct20 0.49 (1) / pct35 -0.07 (8) / pct50 -0.50 (0) / atr2 0.32 (0) / atr4 0.24 (0) |
| v25:PS | ext | none 0.12 (0) / ah 0.14 (4) / pm 0.11 (5) / both 0.08 (0) |
| v25:PS | rally | none 0.37 (7) / r5 -0.17 (1) / r15 0.17 (1) |
| v25:PS | scale | all 0.49 (5) / half -0.21 (2) / third 0.02 (2) |
| v25:PS | filt | none 1.35 (9) / so10 -0.30 (0) / so20 -0.91 (0) / offer90 -0.16 (0) / nosq60 1.30 (0) |

## 6. Latest pick of each family

- v19:XS1 2026: v19:XS1_GAPFADE|14369 = {'entry': 'XS1_GAPFADE|607', 'hold': 'd5', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v19:XS2 2026: v19:XS2_RUNFADE|5263 = {'entry': 'XS2_RUNFADE|152', 'hold': 'd3', 'stop': 'own', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'nosq60'}
- v19:DS1 2026: v19:DS1_RUNUP|13878 = {'entry': 'DS1_RUNUP|1822', 'hold': 'd5', 'stop': 'own', 'ext': 'pm', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v19:ON1 2026: v19:ON1_NIGHTSHORT|9910 = {'entry': 'ON1_NIGHTSHORT|11', 'hold': 'd5', 'stop': 'atr4', 'ext': 'ah', 'rally': 'none', 'scale': 'half', 'filt': 'none'}
- v20:GF 2026: v20:GF_GAPFADE|25454 = {'entry': 'GF_GAPFADE|6649', 'hold': 'd5', 'stop': 'own', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v20:RF 2026: v20:RF_RUNFADE|13111 = {'entry': 'RF_RUNFADE|690', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'third', 'filt': 'none'}
- v20:RU 2026: v20:RU_RUNUP|13878 = {'entry': 'RU_RUNUP|10897', 'hold': 'd5', 'stop': 'own', 'ext': 'pm', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v20:NS 2026: v20:NS_NIGHTSHORT|22680 = {'entry': 'NS_NIGHTSHORT|546', 'hold': 'd3', 'stop': 'own', 'ext': 'none', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v22:IV 2026: v22:IV_VWAPBAND|1304 = {'entry': 'IV_VWAPBAND|1609', 'hold': 'd3', 'stop': 'own', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v22:IR 2026: v22:IR_RSI1M|5479 = {'entry': 'IR_RSI1M|313', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v22:IF 2026: v22:IF_FLAG|5659 = {'entry': 'IF_FLAG|439', 'hold': 'd3', 'stop': 'pct35', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:SR 2026: v23:SR_LEVEL|9294 = {'entry': 'SR_LEVEL|55186', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:VW 2026: v23:VW_VWAP|5659 = {'entry': 'VW_VWAP|3130', 'hold': 'd3', 'stop': 'pct35', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:EM 2026: v23:EM_EMA|9294 = {'entry': 'EM_EMA|355', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:OS 2026: v23:OS_OSC|17104 = {'entry': 'OS_OSC|934', 'hold': 'd3', 'stop': 'pct35', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:MD 2026: v23:MD_MACD|1664 = {'entry': 'MD_MACD|1258', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:SQ 2026: v23:SQ_SQUEEZE|13109 = {'entry': 'SQ_SQUEEZE|985', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:PT 2026: v23:PT_PATTERN|9294 = {'entry': 'PT_PATTERN|2065', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v23:OR 2026: v23:OR_ORB|5659 = {'entry': 'OR_ORB|3715', 'hold': 'd3', 'stop': 'pct35', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v25:AS 2026: v25:AS_ABCD|9294 = {'entry': 'AS_ABCD|1975', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v25:MP 2026: v25:MP_MORNPOP|16915 = {'entry': 'MP_MORNPOP|859', 'hold': 'd3', 'stop': 'pct20', 'ext': 'none', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v25:IS 2026: v25:IS_IND|13109 = {'entry': 'IS_IND|6766', 'hold': 'd3', 'stop': 'pct20', 'ext': 'ah', 'rally': 'none', 'scale': 'all', 'filt': 'none'}
- v25:PS 2026: v25:PS_PATTERN|1853 = {'entry': 'PS_PATTERN|5899', 'hold': 'd3', 'stop': 'pct35', 'ext': 'pm', 'rally': 'none', 'scale': 'all', 'filt': 'none'}

## After the report (FINAL.md)

## 1. The shield against each family's own exit (walk-forward 2018+, middle R4 costs)

| family | v26 Sortino | v26 CAGR | v26 max DD | own exit Sortino (v26 costs) | own CAGR | own max DD | source run's Sortino | nights in the night store |
|---|---|---|---|---|---|---|---|---|
| v19:DS1 | 2.84 | 20.5% | -19.2% | 3.78 | 37.0% | -22.0% | 3.94 | 100% |
| v19:ON1 | 3.63 | 13.8% | -10.3% | 3.77 | 17.6% | -12.6% | 4.05 | 100% |
| v22:IV | 4.74 | 19.9% | -9.7% | 5.99 | 23.9% | -10.4% | 5.99 | 100% |
| v23:EM | 2.69 | 17.0% | -10.4% | 2.82 | 27.1% | -21.1% | 2.82 | 100% |
| v23:MD | 1.22 | 10.3% | -18.8% | 1.63 | 18.0% | -22.7% | 1.63 | 100% |
| v23:OR | 4.42 | 13.6% | -4.5% | 2.36 | 18.4% | -22.1% | 2.36 | 100% |
| v23:OS | 1.81 | 11.7% | -12.8% | 1.10 | 9.8% | -20.5% | 1.10 | 100% |
| v23:PT | 3.33 | 11.6% | -5.8% | 2.71 | 15.1% | -11.0% | 2.71 | 100% |
| v23:SQ | 2.01 | 12.6% | -11.2% | 1.24 | 11.1% | -15.3% | 1.24 | 100% |
| v23:SR | 3.68 | 14.0% | -8.8% | 1.96 | 11.7% | -18.4% | 1.96 | 100% |
| v23:VW | 2.71 | 11.8% | -7.9% | 1.44 | 14.8% | -21.9% | 1.44 | 100% |
| v25:AS | 4.80 | 18.1% | -7.3% | 3.08 | 20.9% | -15.2% | 3.08 | 100% |
| v19:XS1 | 3.20 | 16.2% | -8.0% | 5.04 | 21.3% | -7.6% | 5.21 | 100% |
| v25:IS | 3.32 | 15.8% | -9.2% | 2.51 | 20.4% | -20.6% | 2.51 | 100% |
| v25:MP | 2.77 | 13.6% | -7.8% | 1.40 | 11.7% | -17.4% | 1.40 | 100% |
| v25:PS | 4.14 | 13.4% | -5.8% | 3.30 | 20.2% | -11.2% | 3.30 | 100% |
| v19:XS2 | 2.01 | 11.8% | -11.8% | 2.51 | 16.1% | -13.4% | 2.67 | 100% |
| v20:GF | 2.45 | 12.1% | -8.2% | 3.49 | 12.3% | -7.9% | 3.63 | 100% |
| v20:NS | 1.40 | 8.4% | -14.0% | 1.47 | 8.9% | -14.0% | 1.59 | 100% |
| v20:RF | 2.51 | 12.2% | -9.0% | 2.77 | 14.6% | -8.6% | 2.91 | 100% |
| v20:RU | 2.72 | 20.5% | -17.7% | 5.63 | 37.9% | -21.3% | 5.80 | 100% |
| v22:IF | 2.35 | 9.8% | -4.9% | 3.22 | 12.1% | -6.4% | 3.22 | 100% |
| v22:IR | 1.85 | 15.6% | -22.4% | 1.52 | 16.9% | -24.3% | 1.52 | 100% |

## 2. Robustness battery (walk-forward Sortino 2018+ of each family's v26 stream)

| family | base | entry +1 min | +5 min | slippage x2 | spreads x1.25 | x1.5 | x2 | borrow x2 | x3 | x5 | no SSR shorts | without best 1% | 5% | without best year | spreads to break even | 80% borrowable (median / 5th pct) | 65% | 50% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v19:DS1 | 2.84 | - | - | 2.84 | 2.60 | 2.37 | 1.95 | 2.36 | 1.93 | 1.22 | 1.73 | 2.44 | 1.19 | 2.37 | x6.00 | 2.36 / 1.64 | 1.89 / 1.08 | 1.36 / 0.70 |
| v19:ON1 | 3.63 | - | - | 2.49 | 3.32 | 3.03 | 2.49 | 2.44 | 1.47 | 0.09 | 1.66 | 3.12 | 1.25 | 2.97 | x6.50 | 2.82 / 1.83 | 2.23 / 1.39 | 1.48 / 0.70 |
| v22:IV | 4.74 | 4.94 | 5.43 | 2.74 | 4.03 | 3.39 | 2.30 | 2.83 | 1.43 | -0.37 | 2.85 | 2.27 | -0.66 | 3.98 | x4.00 | 3.83 / 3.01 | 2.75 / 2.02 | 2.17 / 0.92 |
| v23:EM | 2.69 | 2.39 | 2.19 | 1.44 | 2.13 | 1.64 | 0.80 | 1.34 | 0.31 | -1.06 | 1.22 | 0.93 | -1.51 | 2.13 | x3.00 | 2.07 / 1.57 | 1.38 / 0.84 | 1.10 / 0.47 |
| v23:MD | 1.22 | 1.16 | 0.36 | 0.48 | 0.91 | 0.62 | 0.11 | 0.51 | -0.08 | -0.96 | 0.66 | 0.39 | -1.28 | 0.96 | x2.50 | 1.02 / 0.76 | 0.81 / 0.41 | 0.59 / 0.02 |
| v23:OR | 4.42 | 3.50 | 3.80 | 3.20 | 3.96 | 3.53 | 2.73 | 3.15 | 2.08 | 0.46 | 2.22 | 2.99 | 0.24 | 3.56 | x5.50 | 3.52 / 2.78 | 2.69 / 1.94 | 1.84 / 1.09 |
| v23:OS | 1.81 | 2.15 | 1.37 | 0.86 | 1.36 | 0.96 | 0.29 | 1.00 | 0.36 | -0.57 | 1.05 | 0.61 | -1.25 | 1.45 | x3.00 | 1.43 / 1.07 | 1.16 / 0.44 | 0.81 / 0.09 |
| v23:PT | 3.33 | 2.75 | 2.87 | 2.18 | 3.01 | 2.70 | 2.14 | 2.30 | 1.41 | -0.01 | 2.26 | 2.58 | 0.51 | 2.34 | x6.00 | 2.64 / 2.10 | 2.07 / 1.17 | 1.21 / 0.49 |
| v23:SQ | 2.01 | 2.10 | 2.06 | 1.07 | 1.63 | 1.28 | 0.67 | 0.87 | 0.00 | -1.13 | 1.03 | 0.93 | -1.06 | 1.68 | x3.50 | 1.75 / 1.17 | 1.41 / 0.91 | 0.97 / 0.62 |
| v23:SR | 3.68 | 3.57 | 3.79 | 2.85 | 3.43 | 3.19 | 2.73 | 2.85 | 2.09 | 0.79 | 3.01 | 2.62 | 0.48 | 2.79 | x7.50 | 3.05 / 2.21 | 2.41 / 1.67 | 1.89 / 1.13 |
| v23:VW | 2.71 | 2.42 | 3.69 | 1.88 | 2.38 | 2.07 | 1.51 | 1.79 | 1.02 | -0.15 | 1.60 | 1.75 | -0.29 | 2.17 | x5.00 | 2.09 / 1.55 | 1.73 / 1.06 | 1.29 / 0.44 |
| v25:AS | 4.80 | 3.43 | 3.80 | 3.01 | 4.33 | 3.89 | 3.10 | 2.79 | 1.28 | -0.64 | 2.75 | 3.04 | 0.34 | 3.88 | x6.00 | 3.90 / 3.03 | 2.99 / 1.93 | 2.09 / 1.32 |
| v19:XS1 | 3.20 | 2.72 | 2.64 | 2.13 | 2.82 | 2.45 | 1.77 | 1.96 | 0.89 | -0.66 | 2.41 | 2.22 | 0.09 | 2.35 | x4.50 | 2.67 / 2.15 | 2.26 / 1.46 | 1.53 / 0.91 |
| v25:IS | 3.32 | 2.92 | 2.22 | 1.67 | 2.69 | 2.11 | 1.13 | 1.77 | 0.59 | -0.92 | 1.87 | 1.51 | -1.15 | 2.77 | x3.50 | 2.40 / 1.79 | 1.57 / 0.90 | 1.22 / 0.45 |
| v25:MP | 2.77 | 1.96 | 2.33 | 1.74 | 2.43 | 2.11 | 1.53 | 1.81 | 1.02 | -0.17 | 1.47 | 1.62 | -0.49 | 2.28 | x4.50 | 2.18 / 1.59 | 1.57 / 0.91 | 1.17 / 0.62 |
| v25:PS | 4.14 | 3.81 | 4.11 | 2.98 | 3.68 | 3.24 | 2.45 | 2.94 | 1.92 | 0.35 | 2.30 | 2.66 | 0.18 | 3.10 | x5.50 | 3.38 / 2.49 | 2.68 / 1.85 | 1.98 / 1.23 |
| v19:XS2 | 2.01 | 1.19 | 1.59 | 1.10 | 1.65 | 1.32 | 0.74 | 1.19 | 0.51 | -0.52 | 0.92 | 1.02 | -0.77 | 1.34 | x3.50 | 1.56 / 1.13 | 1.08 / 0.60 | 0.76 / 0.11 |
| v20:GF | 2.45 | 2.32 | 2.45 | 1.82 | 2.22 | 2.00 | 1.59 | 1.66 | 0.94 | -0.25 | 1.81 | 1.74 | 0.15 | 2.08 | x5.50 | 2.05 / 1.55 | 1.63 / 1.04 | 1.37 / 0.62 |
| v20:NS | 1.40 | - | - | 1.28 | 1.29 | 1.18 | 0.97 | 0.84 | 0.37 | -0.35 | 0.44 | 1.02 | 0.60 | 1.01 | x7.00 | 1.10 / 0.72 | 0.86 / 0.25 | 0.50 / -0.14 |
| v20:RF | 2.51 | 2.53 | 2.25 | 1.73 | 2.18 | 1.87 | 1.30 | 1.83 | 1.24 | 0.29 | 1.82 | 1.79 | -0.36 | 1.92 | x4.50 | 2.03 / 1.64 | 1.32 / 0.90 | 1.04 / 0.52 |
| v20:RU | 2.72 | - | - | 2.62 | 2.53 | 2.36 | 2.02 | 2.29 | 1.90 | 1.24 | 1.95 | 2.29 | 1.20 | 2.65 | x7.00 | 2.30 / 1.57 | 1.93 / 1.28 | 1.36 / 0.68 |
| v22:IF | 2.35 | 2.00 | 2.37 | 1.35 | 2.11 | 1.88 | 1.45 | 1.39 | 0.56 | -0.70 | 1.25 | 1.60 | 0.11 | 1.85 | x5.50 | 1.91 / 1.39 | 1.35 / 0.81 | 0.74 / 0.27 |
| v22:IR | 1.85 | 2.01 | 1.27 | 0.88 | 1.50 | 1.17 | 0.58 | 1.11 | 0.48 | -0.49 | 1.14 | 0.83 | -1.16 | 1.53 | x3.00 | 1.58 / 1.16 | 1.33 / 0.90 | 1.19 / 0.62 |

## 3. The tail rule (comparison only; the owner chose selection by Sortino alone)

A configuration may be picked for a year only if no trade it took before that year lost more than 100% of the position.

| family | Sortino 2018+ (monthly) with the rule | without (the report's) |
|---|---|---|
| v19:XS1 | 4.28 | 3.20 |
| v19:XS2 | 1.58 | 2.01 |
| v19:DS1 | 0.46 | 2.84 |
| v19:ON1 | 3.57 | 3.63 |
| v20:GF | 1.87 | 2.45 |
| v20:RF | 1.94 | 2.51 |
| v20:RU | 1.63 | 2.72 |
| v20:NS | 1.67 | 1.40 |
| v22:IV | 4.25 | 4.74 |
| v22:IR | 1.86 | 1.85 |
| v22:IF | 2.18 | 2.35 |
| v23:SR | 3.27 | 3.68 |
| v23:VW | 1.71 | 2.71 |
| v23:EM | 2.13 | 2.69 |
| v23:OS | 1.81 | 1.81 |
| v23:MD | 1.37 | 1.22 |
| v23:SQ | 1.47 | 2.01 |
| v23:PT | 2.55 | 3.33 |
| v23:OR | 2.07 | 4.42 |
| v25:AS | 4.54 | 4.80 |
| v25:MP | 2.51 | 2.77 |
| v25:IS | 3.06 | 3.32 |
| v25:PS | 3.65 | 4.14 |

## 4. One account: COMBO26's members traded together (A: v26; B: the same families, own exits)

Walk-forward 2018-2026, liquidity caps on the account, one position a symbol, at most 20 open. p75: the chance of a 75% drawdown in ten years (block bootstrap). The choice: the owner's rule of v19s (p75 <= 1% at the middle costs, gross <= 2x, the highest median bootstrap CAGR).

- $25,000, book A: A_A25k_R1_C40_G1_mid: Sortino 4.97, CAGR 122.6%, max DD -52.7%, worst day -27.6%, p75 0.2%, median bootstrap CAGR 122.8%; high costs: CAGR -15.0%, DD -95.2%, p75 88.7%
- $25,000, book B: B_A25k_R0.5_C40_G1.5_mid: Sortino 4.11, CAGR 72.8%, max DD -32.9%, worst day -17.0%, p75 0.0%, median bootstrap CAGR 73.8%; high costs: CAGR -15.9%, DD -91.6%, p75 85.5%
- $100,000, book A: A_A100k_R1_C40_G1_mid: Sortino 4.63, CAGR 113.5%, max DD -54.2%, worst day -27.6%, p75 0.1%, median bootstrap CAGR 113.8%; high costs: CAGR -15.6%, DD -95.1%, p75 89.1%
- $100,000, book B: B_A100k_R0.5_C40_G1.5_mid: Sortino 3.96, CAGR 70.0%, max DD -31.9%, worst day -17.0%, p75 0.0%, median bootstrap CAGR 70.8%; high costs: CAGR -16.0%, DD -91.7%, p75 85.6%
- $250,000, book A: A_A250k_R1_C60_G1.5_mid: Sortino 4.39, CAGR 105.4%, max DD -54.6%, worst day -27.6%, p75 0.2%, median bootstrap CAGR 106.0%; high costs: CAGR -15.8%, DD -94.9%, p75 88.3%
- $250,000, book B: B_A250k_R1_C100_G1_mid: Sortino 4.50, CAGR 161.2%, max DD -51.4%, worst day -34.1%, p75 0.5%, median bootstrap CAGR 163.6%; high costs: CAGR -29.9%, DD -99.3%, p75 99.5%

| book | account | risk | cap | gross | Sortino | CAGR | max DD | worst day | p75 | median CAGR | CAGR high | p75 high |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 25,000 | 0.25% | 20% | 1 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 20% | 1.5 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 20% | 2 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 20% | 3 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 40% | 1 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 40% | 1.5 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 40% | 2 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 40% | 3 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 60% | 1 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 60% | 1.5 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 60% | 2 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 60% | 3 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 100% | 1 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 100% | 1.5 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 100% | 2 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.25% | 100% | 3 | 4.12 | 24.7% | -15.5% | -6.9% | 0.0% | 24.7% | -2.4% | 0.4% |
| A | 25,000 | 0.50% | 20% | 1 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 20% | 1.5 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 20% | 2 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 20% | 3 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 40% | 1 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 40% | 1.5 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 40% | 2 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 40% | 3 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 60% | 1 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 60% | 1.5 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 60% | 2 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 60% | 3 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 100% | 1 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 100% | 1.5 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 100% | 2 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 0.50% | 100% | 3 | 4.60 | 53.1% | -29.5% | -13.8% | 0.0% | 53.2% | -6.0% | 31.8% |
| A | 25,000 | 1.00% | 20% | 1 | 4.97 | 122.6% | -52.7% | -27.6% | 0.2% | 122.8% | -15.0% | 88.7% |
| A | 25,000 | 1.00% | 20% | 1.5 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 20% | 2 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 20% | 3 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 40% | 1 | 4.97 | 122.6% | -52.7% | -27.6% | 0.2% | 122.8% | -15.0% | 88.7% |
| A | 25,000 | 1.00% | 40% | 1.5 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 40% | 2 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 40% | 3 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 60% | 1 | 4.97 | 122.6% | -52.7% | -27.6% | 0.2% | 122.8% | -15.0% | 88.7% |
| A | 25,000 | 1.00% | 60% | 1.5 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 60% | 2 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 60% | 3 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 100% | 1 | 4.97 | 122.6% | -52.7% | -27.6% | 0.2% | 122.8% | -15.0% | 88.7% |
| A | 25,000 | 1.00% | 100% | 1.5 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 100% | 2 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.00% | 100% | 3 | 4.93 | 121.4% | -52.7% | -27.6% | 0.2% | 121.8% | -15.5% | 89.4% |
| A | 25,000 | 1.50% | 20% | 1 | 4.96 | 196.4% | -65.7% | -41.4% | 7.0% | 196.7% | -23.9% | 99.2% |
| A | 25,000 | 1.50% | 20% | 1.5 | 5.17 | 206.8% | -69.9% | -41.4% | 8.5% | 207.4% | -26.7% | 99.1% |
| A | 25,000 | 1.50% | 20% | 2 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 1.50% | 20% | 3 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 1.50% | 40% | 1 | 4.96 | 196.4% | -65.7% | -41.4% | 7.0% | 196.7% | -23.9% | 99.2% |
| A | 25,000 | 1.50% | 40% | 1.5 | 5.17 | 206.8% | -69.9% | -41.4% | 8.5% | 207.4% | -26.7% | 99.1% |
| A | 25,000 | 1.50% | 40% | 2 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 1.50% | 40% | 3 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 1.50% | 60% | 1 | 4.96 | 196.4% | -65.7% | -41.4% | 7.0% | 196.7% | -23.9% | 99.2% |
| A | 25,000 | 1.50% | 60% | 1.5 | 5.17 | 206.8% | -69.9% | -41.4% | 8.5% | 207.4% | -26.7% | 99.1% |
| A | 25,000 | 1.50% | 60% | 2 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 1.50% | 60% | 3 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 1.50% | 100% | 1 | 4.96 | 196.4% | -65.7% | -41.4% | 7.0% | 196.7% | -23.9% | 99.2% |
| A | 25,000 | 1.50% | 100% | 1.5 | 5.17 | 206.8% | -69.9% | -41.4% | 8.5% | 207.4% | -26.7% | 99.1% |
| A | 25,000 | 1.50% | 100% | 2 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 1.50% | 100% | 3 | 5.14 | 204.8% | -69.9% | -41.4% | 8.5% | 205.8% | -27.3% | 99.2% |
| A | 25,000 | 2.00% | 20% | 1 | 5.33 | 256.8% | -76.1% | -54.1% | 21.7% | 257.8% | -27.0% | 99.8% |
| A | 25,000 | 2.00% | 20% | 1.5 | 5.16 | 283.5% | -81.3% | -55.2% | 44.7% | 285.0% | -40.2% | 100.0% |
| A | 25,000 | 2.00% | 20% | 2 | 5.36 | 304.5% | -82.0% | -55.2% | 44.6% | 306.7% | -39.2% | 99.9% |
| A | 25,000 | 2.00% | 20% | 3 | 5.32 | 300.0% | -82.0% | -55.2% | 44.9% | 302.1% | -40.0% | 100.0% |
| A | 25,000 | 2.00% | 40% | 1 | 5.33 | 257.2% | -76.1% | -54.1% | 21.7% | 257.9% | -26.9% | 99.8% |
| A | 25,000 | 2.00% | 40% | 1.5 | 5.15 | 283.2% | -81.3% | -55.2% | 44.8% | 284.6% | -40.2% | 100.0% |
| A | 25,000 | 2.00% | 40% | 2 | 5.36 | 304.1% | -82.0% | -55.2% | 44.7% | 306.4% | -39.3% | 99.9% |
| A | 25,000 | 2.00% | 40% | 3 | 5.31 | 299.6% | -82.0% | -55.2% | 45.0% | 301.7% | -40.0% | 100.0% |
| A | 25,000 | 2.00% | 60% | 1 | 5.33 | 257.2% | -76.1% | -54.1% | 21.7% | 257.9% | -26.9% | 99.8% |
| A | 25,000 | 2.00% | 60% | 1.5 | 5.15 | 283.2% | -81.3% | -55.2% | 44.8% | 284.6% | -40.2% | 100.0% |
| A | 25,000 | 2.00% | 60% | 2 | 5.36 | 304.1% | -82.0% | -55.2% | 44.7% | 306.4% | -39.3% | 99.9% |
| A | 25,000 | 2.00% | 60% | 3 | 5.31 | 299.6% | -82.0% | -55.2% | 45.0% | 301.7% | -40.0% | 100.0% |
| A | 25,000 | 2.00% | 100% | 1 | 5.33 | 257.2% | -76.1% | -54.1% | 21.7% | 257.9% | -26.9% | 99.8% |
| A | 25,000 | 2.00% | 100% | 1.5 | 5.15 | 283.2% | -81.3% | -55.2% | 44.8% | 284.6% | -40.2% | 100.0% |
| A | 25,000 | 2.00% | 100% | 2 | 5.36 | 304.1% | -82.0% | -55.2% | 44.7% | 306.4% | -39.3% | 99.9% |
| A | 25,000 | 2.00% | 100% | 3 | 5.31 | 299.6% | -82.0% | -55.2% | 45.0% | 301.7% | -40.0% | 100.0% |
| A | 25,000 | 3.00% | 20% | 1 | 5.66 | 365.2% | -78.3% | -57.6% | 30.4% | 370.8% | -17.8% | 99.7% |
| A | 25,000 | 3.00% | 20% | 1.5 | 4.82 | 313.9% | -87.1% | -56.0% | 58.3% | 313.5% | -55.7% | 100.0% |
| A | 25,000 | 3.00% | 20% | 2 | 5.12 | 342.4% | -87.7% | -56.0% | 71.0% | 342.3% | -61.1% | 100.0% |
| A | 25,000 | 3.00% | 20% | 3 | 5.04 | 343.3% | -89.2% | -56.0% | 73.2% | 345.1% | -61.7% | 100.0% |
| A | 25,000 | 3.00% | 40% | 1 | 5.90 | 426.7% | -69.9% | -49.8% | 40.3% | 433.7% | -12.3% | 99.9% |
| A | 25,000 | 3.00% | 40% | 1.5 | 5.29 | 426.2% | -95.1% | -81.2% | 93.9% | 432.4% | -50.9% | 100.0% |
| A | 25,000 | 3.00% | 40% | 2 | 5.37 | 477.2% | -95.5% | -82.7% | 95.7% | 479.5% | -60.7% | 100.0% |
| A | 25,000 | 3.00% | 40% | 3 | 5.47 | 483.6% | -94.7% | -82.7% | 95.1% | 486.6% | -65.1% | 100.0% |
| A | 25,000 | 3.00% | 60% | 1 | 5.90 | 426.7% | -69.9% | -49.8% | 40.3% | 433.7% | -12.3% | 99.9% |
| A | 25,000 | 3.00% | 60% | 1.5 | 5.29 | 426.2% | -95.1% | -81.2% | 93.9% | 432.4% | -50.9% | 100.0% |
| A | 25,000 | 3.00% | 60% | 2 | 5.37 | 477.2% | -95.5% | -82.7% | 95.7% | 479.5% | -60.7% | 100.0% |
| A | 25,000 | 3.00% | 60% | 3 | 5.47 | 483.6% | -94.7% | -82.7% | 95.1% | 486.6% | -65.1% | 100.0% |
| A | 25,000 | 3.00% | 100% | 1 | 5.90 | 426.7% | -69.9% | -49.8% | 40.3% | 433.7% | -12.3% | 99.9% |
| A | 25,000 | 3.00% | 100% | 1.5 | 5.29 | 426.2% | -95.1% | -81.2% | 93.9% | 432.4% | -50.9% | 100.0% |
| A | 25,000 | 3.00% | 100% | 2 | 5.37 | 477.2% | -95.5% | -82.7% | 95.7% | 479.5% | -60.7% | 100.0% |
| A | 25,000 | 3.00% | 100% | 3 | 5.47 | 483.6% | -94.7% | -82.7% | 95.1% | 486.6% | -65.1% | 100.0% |
| A | 100,000 | 0.25% | 20% | 1 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 20% | 1.5 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 20% | 2 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 20% | 3 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 40% | 1 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 40% | 1.5 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 40% | 2 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 40% | 3 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 60% | 1 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 60% | 1.5 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 60% | 2 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 60% | 3 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 100% | 1 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 100% | 1.5 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 100% | 2 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.25% | 100% | 3 | 3.94 | 23.8% | -15.8% | -6.9% | 0.0% | 23.9% | -2.7% | 0.4% |
| A | 100,000 | 0.50% | 20% | 1 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 20% | 1.5 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 20% | 2 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 20% | 3 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 40% | 1 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 40% | 1.5 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 40% | 2 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 40% | 3 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 60% | 1 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 60% | 1.5 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 60% | 2 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 60% | 3 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 100% | 1 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 100% | 1.5 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 100% | 2 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 0.50% | 100% | 3 | 4.32 | 50.3% | -30.3% | -13.8% | 0.0% | 50.5% | -6.5% | 33.3% |
| A | 100,000 | 1.00% | 20% | 1 | 4.63 | 113.5% | -54.2% | -27.6% | 0.1% | 113.8% | -15.6% | 89.1% |
| A | 100,000 | 1.00% | 20% | 1.5 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 20% | 2 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 20% | 3 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 40% | 1 | 4.63 | 113.5% | -54.2% | -27.6% | 0.1% | 113.8% | -15.6% | 89.1% |
| A | 100,000 | 1.00% | 40% | 1.5 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 40% | 2 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 40% | 3 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 60% | 1 | 4.63 | 113.5% | -54.2% | -27.6% | 0.1% | 113.8% | -15.6% | 89.1% |
| A | 100,000 | 1.00% | 60% | 1.5 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 60% | 2 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 60% | 3 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 100% | 1 | 4.63 | 113.5% | -54.2% | -27.6% | 0.1% | 113.8% | -15.6% | 89.1% |
| A | 100,000 | 1.00% | 100% | 1.5 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 100% | 2 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.00% | 100% | 3 | 4.62 | 112.9% | -54.2% | -27.6% | 0.1% | 113.3% | -15.9% | 89.4% |
| A | 100,000 | 1.50% | 20% | 1 | 4.63 | 178.5% | -64.8% | -41.4% | 6.5% | 178.1% | -25.2% | 99.1% |
| A | 100,000 | 1.50% | 20% | 1.5 | 4.74 | 184.4% | -71.4% | -41.4% | 10.0% | 185.1% | -27.7% | 99.2% |
| A | 100,000 | 1.50% | 20% | 2 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 1.50% | 20% | 3 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 1.50% | 40% | 1 | 4.63 | 178.5% | -64.8% | -41.4% | 6.5% | 178.1% | -25.2% | 99.1% |
| A | 100,000 | 1.50% | 40% | 1.5 | 4.74 | 184.4% | -71.4% | -41.4% | 10.0% | 185.1% | -27.7% | 99.2% |
| A | 100,000 | 1.50% | 40% | 2 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 1.50% | 40% | 3 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 1.50% | 60% | 1 | 4.63 | 178.5% | -64.8% | -41.4% | 6.5% | 178.1% | -25.2% | 99.1% |
| A | 100,000 | 1.50% | 60% | 1.5 | 4.74 | 184.4% | -71.4% | -41.4% | 10.0% | 185.1% | -27.7% | 99.2% |
| A | 100,000 | 1.50% | 60% | 2 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 1.50% | 60% | 3 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 1.50% | 100% | 1 | 4.63 | 178.5% | -64.8% | -41.4% | 6.5% | 178.1% | -25.2% | 99.1% |
| A | 100,000 | 1.50% | 100% | 1.5 | 4.74 | 184.4% | -71.4% | -41.4% | 10.0% | 185.1% | -27.7% | 99.2% |
| A | 100,000 | 1.50% | 100% | 2 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 1.50% | 100% | 3 | 4.73 | 183.6% | -71.4% | -41.4% | 10.0% | 184.4% | -28.0% | 99.2% |
| A | 100,000 | 2.00% | 20% | 1 | 5.03 | 235.4% | -77.0% | -54.7% | 25.4% | 237.8% | -28.3% | 99.8% |
| A | 100,000 | 2.00% | 20% | 1.5 | 4.71 | 251.1% | -81.9% | -55.2% | 47.1% | 252.5% | -40.7% | 100.0% |
| A | 100,000 | 2.00% | 20% | 2 | 4.92 | 265.0% | -82.9% | -55.2% | 46.0% | 266.5% | -39.9% | 99.9% |
| A | 100,000 | 2.00% | 20% | 3 | 4.92 | 265.1% | -82.9% | -55.2% | 46.0% | 266.7% | -39.8% | 99.9% |
| A | 100,000 | 2.00% | 40% | 1 | 5.02 | 235.1% | -77.0% | -54.7% | 25.4% | 237.5% | -28.3% | 99.8% |
| A | 100,000 | 2.00% | 40% | 1.5 | 4.72 | 251.5% | -81.9% | -55.2% | 47.2% | 253.0% | -40.6% | 100.0% |
| A | 100,000 | 2.00% | 40% | 2 | 4.91 | 264.7% | -82.9% | -55.2% | 46.1% | 266.2% | -39.9% | 99.9% |
| A | 100,000 | 2.00% | 40% | 3 | 4.91 | 264.7% | -82.9% | -55.2% | 46.1% | 266.4% | -39.9% | 99.9% |
| A | 100,000 | 2.00% | 60% | 1 | 5.02 | 235.1% | -77.0% | -54.7% | 25.4% | 237.5% | -28.3% | 99.8% |
| A | 100,000 | 2.00% | 60% | 1.5 | 4.72 | 251.5% | -81.9% | -55.2% | 47.2% | 253.0% | -40.6% | 100.0% |
| A | 100,000 | 2.00% | 60% | 2 | 4.91 | 264.7% | -82.9% | -55.2% | 46.1% | 266.2% | -39.9% | 99.9% |
| A | 100,000 | 2.00% | 60% | 3 | 4.91 | 264.7% | -82.9% | -55.2% | 46.1% | 266.4% | -39.9% | 99.9% |
| A | 100,000 | 2.00% | 100% | 1 | 5.02 | 235.1% | -77.0% | -54.7% | 25.4% | 237.5% | -28.3% | 99.8% |
| A | 100,000 | 2.00% | 100% | 1.5 | 4.72 | 251.5% | -81.9% | -55.2% | 47.2% | 253.0% | -40.6% | 100.0% |
| A | 100,000 | 2.00% | 100% | 2 | 4.91 | 264.7% | -82.9% | -55.2% | 46.1% | 266.2% | -39.9% | 99.9% |
| A | 100,000 | 2.00% | 100% | 3 | 4.91 | 264.7% | -82.9% | -55.2% | 46.1% | 266.4% | -39.9% | 99.9% |
| A | 100,000 | 3.00% | 20% | 1 | 4.34 | 256.0% | -87.6% | -56.2% | 63.3% | 257.7% | -35.0% | 100.0% |
| A | 100,000 | 3.00% | 20% | 1.5 | 4.71 | 292.3% | -89.3% | -56.0% | 64.0% | 291.6% | -55.0% | 100.0% |
| A | 100,000 | 3.00% | 20% | 2 | 4.82 | 312.2% | -88.7% | -56.0% | 71.9% | 310.3% | -59.9% | 100.0% |
| A | 100,000 | 3.00% | 20% | 3 | 4.87 | 318.6% | -89.0% | -56.0% | 72.0% | 317.7% | -59.6% | 100.0% |
| A | 100,000 | 3.00% | 40% | 1 | 5.31 | 349.9% | -72.4% | -50.8% | 43.8% | 352.0% | -21.5% | 99.9% |
| A | 100,000 | 3.00% | 40% | 1.5 | 4.86 | 376.3% | -96.7% | -82.0% | 93.0% | 383.3% | -51.6% | 100.0% |
| A | 100,000 | 3.00% | 40% | 2 | 5.10 | 406.3% | -94.9% | -82.7% | 94.8% | 411.2% | -60.9% | 100.0% |
| A | 100,000 | 3.00% | 40% | 3 | 5.08 | 412.3% | -94.7% | -82.7% | 94.7% | 419.1% | -63.9% | 100.0% |
| A | 100,000 | 3.00% | 60% | 1 | 5.31 | 349.9% | -72.4% | -50.8% | 43.8% | 352.0% | -21.5% | 99.9% |
| A | 100,000 | 3.00% | 60% | 1.5 | 4.86 | 376.3% | -96.7% | -82.0% | 93.0% | 383.3% | -51.6% | 100.0% |
| A | 100,000 | 3.00% | 60% | 2 | 5.10 | 406.3% | -94.9% | -82.7% | 94.8% | 411.2% | -60.9% | 100.0% |
| A | 100,000 | 3.00% | 60% | 3 | 5.08 | 412.3% | -94.7% | -82.7% | 94.7% | 419.1% | -63.9% | 100.0% |
| A | 100,000 | 3.00% | 100% | 1 | 5.31 | 349.9% | -72.4% | -50.8% | 43.8% | 352.0% | -21.5% | 99.9% |
| A | 100,000 | 3.00% | 100% | 1.5 | 4.86 | 376.3% | -96.7% | -82.0% | 93.0% | 383.3% | -51.6% | 100.0% |
| A | 100,000 | 3.00% | 100% | 2 | 5.10 | 406.3% | -94.9% | -82.7% | 94.8% | 411.2% | -60.9% | 100.0% |
| A | 100,000 | 3.00% | 100% | 3 | 5.08 | 412.3% | -94.7% | -82.7% | 94.7% | 419.1% | -63.9% | 100.0% |
| A | 250,000 | 0.25% | 20% | 1 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 20% | 1.5 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 20% | 2 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 20% | 3 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 40% | 1 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 40% | 1.5 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 40% | 2 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 40% | 3 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 60% | 1 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 60% | 1.5 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 60% | 2 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 60% | 3 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 100% | 1 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 100% | 1.5 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 100% | 2 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.25% | 100% | 3 | 3.75 | 23.0% | -16.3% | -6.9% | 0.0% | 23.1% | -2.9% | 0.4% |
| A | 250,000 | 0.50% | 20% | 1 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 20% | 1.5 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 20% | 2 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 20% | 3 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 40% | 1 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 40% | 1.5 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 40% | 2 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 40% | 3 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 60% | 1 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 60% | 1.5 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 60% | 2 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 60% | 3 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 100% | 1 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 100% | 1.5 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 100% | 2 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 0.50% | 100% | 3 | 4.08 | 47.9% | -31.1% | -13.8% | 0.0% | 48.1% | -6.7% | 33.1% |
| A | 250,000 | 1.00% | 20% | 1 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 20% | 1.5 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 20% | 2 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 20% | 3 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 40% | 1 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 40% | 1.5 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 40% | 2 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 40% | 3 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 60% | 1 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 60% | 1.5 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 60% | 2 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 60% | 3 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 100% | 1 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 100% | 1.5 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 100% | 2 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.00% | 100% | 3 | 4.39 | 105.4% | -54.6% | -27.6% | 0.2% | 106.0% | -15.8% | 88.3% |
| A | 250,000 | 1.50% | 20% | 1 | 4.79 | 171.2% | -63.6% | -41.4% | 5.2% | 171.9% | -23.3% | 98.8% |
| A | 250,000 | 1.50% | 20% | 1.5 | 4.59 | 171.4% | -70.7% | -41.4% | 8.5% | 172.0% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 20% | 2 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 20% | 3 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 40% | 1 | 4.79 | 171.2% | -63.6% | -41.4% | 5.2% | 171.9% | -23.3% | 98.8% |
| A | 250,000 | 1.50% | 40% | 1.5 | 4.59 | 171.4% | -70.7% | -41.4% | 8.5% | 172.0% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 40% | 2 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 40% | 3 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 60% | 1 | 4.79 | 171.2% | -63.6% | -41.4% | 5.2% | 171.9% | -23.3% | 98.8% |
| A | 250,000 | 1.50% | 60% | 1.5 | 4.59 | 171.4% | -70.7% | -41.4% | 8.5% | 172.0% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 60% | 2 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 60% | 3 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 100% | 1 | 4.79 | 171.2% | -63.6% | -41.4% | 5.2% | 171.9% | -23.3% | 98.8% |
| A | 250,000 | 1.50% | 100% | 1.5 | 4.59 | 171.4% | -70.7% | -41.4% | 8.5% | 172.0% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 100% | 2 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 1.50% | 100% | 3 | 4.59 | 171.5% | -70.7% | -41.4% | 8.5% | 172.1% | -26.4% | 99.0% |
| A | 250,000 | 2.00% | 20% | 1 | 4.97 | 229.0% | -79.0% | -54.7% | 20.1% | 231.2% | -26.2% | 99.5% |
| A | 250,000 | 2.00% | 20% | 1.5 | 4.68 | 235.0% | -80.9% | -55.2% | 40.7% | 234.9% | -38.3% | 99.9% |
| A | 250,000 | 2.00% | 20% | 2 | 4.68 | 240.3% | -81.9% | -55.2% | 41.6% | 240.8% | -38.2% | 99.9% |
| A | 250,000 | 2.00% | 20% | 3 | 4.71 | 242.0% | -81.9% | -55.2% | 41.6% | 242.7% | -37.9% | 99.9% |
| A | 250,000 | 2.00% | 40% | 1 | 4.97 | 228.8% | -79.1% | -54.7% | 20.1% | 231.0% | -26.3% | 99.5% |
| A | 250,000 | 2.00% | 40% | 1.5 | 4.67 | 234.7% | -80.9% | -55.2% | 40.8% | 234.5% | -38.3% | 99.9% |
| A | 250,000 | 2.00% | 40% | 2 | 4.68 | 239.9% | -81.9% | -55.2% | 41.8% | 240.3% | -38.3% | 99.9% |
| A | 250,000 | 2.00% | 40% | 3 | 4.70 | 241.7% | -81.9% | -55.2% | 41.7% | 242.4% | -38.0% | 99.9% |
| A | 250,000 | 2.00% | 60% | 1 | 4.97 | 228.8% | -79.1% | -54.7% | 20.1% | 231.0% | -26.3% | 99.5% |
| A | 250,000 | 2.00% | 60% | 1.5 | 4.67 | 234.7% | -80.9% | -55.2% | 40.8% | 234.5% | -38.3% | 99.9% |
| A | 250,000 | 2.00% | 60% | 2 | 4.68 | 239.9% | -81.9% | -55.2% | 41.8% | 240.3% | -38.3% | 99.9% |
| A | 250,000 | 2.00% | 60% | 3 | 4.70 | 241.7% | -81.9% | -55.2% | 41.7% | 242.4% | -38.0% | 99.9% |
| A | 250,000 | 2.00% | 100% | 1 | 4.97 | 228.8% | -79.1% | -54.7% | 20.1% | 231.0% | -26.3% | 99.5% |
| A | 250,000 | 2.00% | 100% | 1.5 | 4.67 | 234.7% | -80.9% | -55.2% | 40.8% | 234.5% | -38.3% | 99.9% |
| A | 250,000 | 2.00% | 100% | 2 | 4.68 | 239.9% | -81.9% | -55.2% | 41.8% | 240.3% | -38.3% | 99.9% |
| A | 250,000 | 2.00% | 100% | 3 | 4.70 | 241.7% | -81.9% | -55.2% | 41.7% | 242.4% | -38.0% | 99.9% |
| A | 250,000 | 3.00% | 20% | 1 | 4.58 | 261.8% | -88.2% | -55.8% | 48.6% | 263.4% | -31.3% | 99.9% |
| A | 250,000 | 3.00% | 20% | 1.5 | 4.52 | 274.1% | -85.9% | -56.0% | 61.7% | 273.9% | -53.6% | 100.0% |
| A | 250,000 | 3.00% | 20% | 2 | 4.73 | 296.8% | -87.8% | -56.0% | 68.0% | 296.1% | -56.5% | 100.0% |
| A | 250,000 | 3.00% | 20% | 3 | 4.77 | 304.4% | -87.9% | -56.0% | 67.8% | 304.3% | -55.9% | 100.0% |
| A | 250,000 | 3.00% | 40% | 1 | 5.13 | 360.5% | -88.9% | -52.0% | 73.4% | 369.1% | -16.8% | 99.9% |
| A | 250,000 | 3.00% | 40% | 1.5 | 4.83 | 385.9% | -94.3% | -82.0% | 94.3% | 391.3% | -46.2% | 100.0% |
| A | 250,000 | 3.00% | 40% | 2 | 4.56 | 334.5% | -93.9% | -82.7% | 94.6% | 338.7% | -61.7% | 100.0% |
| A | 250,000 | 3.00% | 40% | 3 | 4.82 | 374.0% | -94.3% | -82.7% | 94.0% | 377.8% | -60.6% | 100.0% |
| A | 250,000 | 3.00% | 60% | 1 | 5.13 | 360.5% | -88.9% | -52.0% | 73.4% | 369.1% | -16.8% | 99.9% |
| A | 250,000 | 3.00% | 60% | 1.5 | 4.83 | 385.9% | -94.3% | -82.0% | 94.3% | 391.3% | -46.2% | 100.0% |
| A | 250,000 | 3.00% | 60% | 2 | 4.56 | 334.5% | -93.9% | -82.7% | 94.6% | 338.7% | -61.7% | 100.0% |
| A | 250,000 | 3.00% | 60% | 3 | 4.82 | 374.0% | -94.3% | -82.7% | 94.0% | 377.8% | -60.6% | 100.0% |
| A | 250,000 | 3.00% | 100% | 1 | 5.13 | 360.5% | -88.9% | -52.0% | 73.4% | 369.1% | -16.8% | 99.9% |
| A | 250,000 | 3.00% | 100% | 1.5 | 4.83 | 385.9% | -94.3% | -82.0% | 94.3% | 391.3% | -46.2% | 100.0% |
| A | 250,000 | 3.00% | 100% | 2 | 4.56 | 334.5% | -93.9% | -82.7% | 94.6% | 338.7% | -61.7% | 100.0% |
| A | 250,000 | 3.00% | 100% | 3 | 4.82 | 374.0% | -94.3% | -82.7% | 94.0% | 377.8% | -60.6% | 100.0% |
| B | 25,000 | 0.25% | 20% | 1 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 20% | 1.5 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 20% | 2 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 20% | 3 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 40% | 1 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 40% | 1.5 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 40% | 2 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 40% | 3 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 60% | 1 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 60% | 1.5 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 60% | 2 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 60% | 3 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 100% | 1 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 100% | 1.5 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 100% | 2 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.25% | 100% | 3 | 3.73 | 33.0% | -17.7% | -8.5% | 0.0% | 33.5% | -7.4% | 17.6% |
| B | 25,000 | 0.50% | 20% | 1 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 20% | 1.5 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 20% | 2 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 20% | 3 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 40% | 1 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 40% | 1.5 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 40% | 2 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 40% | 3 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 60% | 1 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 60% | 1.5 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 60% | 2 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 60% | 3 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 100% | 1 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 100% | 1.5 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 100% | 2 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 0.50% | 100% | 3 | 4.11 | 72.8% | -32.9% | -17.0% | 0.0% | 73.8% | -15.9% | 85.5% |
| B | 25,000 | 1.00% | 20% | 1 | 4.41 | 167.5% | -57.2% | -34.0% | 1.5% | 171.4% | -34.1% | 99.8% |
| B | 25,000 | 1.00% | 20% | 1.5 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 20% | 2 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 20% | 3 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 40% | 1 | 4.41 | 167.5% | -57.2% | -34.0% | 1.5% | 171.4% | -34.1% | 99.8% |
| B | 25,000 | 1.00% | 40% | 1.5 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 40% | 2 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 40% | 3 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 60% | 1 | 4.41 | 167.5% | -57.2% | -34.0% | 1.5% | 171.4% | -34.1% | 99.8% |
| B | 25,000 | 1.00% | 60% | 1.5 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 60% | 2 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 60% | 3 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 100% | 1 | 4.41 | 167.5% | -57.2% | -34.0% | 1.5% | 171.4% | -34.1% | 99.8% |
| B | 25,000 | 1.00% | 100% | 1.5 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 100% | 2 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.00% | 100% | 3 | 4.41 | 169.1% | -57.2% | -34.0% | 1.9% | 171.6% | -35.4% | 99.8% |
| B | 25,000 | 1.50% | 20% | 1 | 4.42 | 261.1% | -72.5% | -48.6% | 35.2% | 267.4% | -36.4% | 100.0% |
| B | 25,000 | 1.50% | 20% | 1.5 | 4.59 | 276.2% | -73.6% | -51.0% | 39.9% | 281.9% | -53.5% | 100.0% |
| B | 25,000 | 1.50% | 20% | 2 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 1.50% | 20% | 3 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 1.50% | 40% | 1 | 4.42 | 261.1% | -72.5% | -48.6% | 35.2% | 267.4% | -36.4% | 100.0% |
| B | 25,000 | 1.50% | 40% | 1.5 | 4.59 | 276.2% | -73.6% | -51.0% | 39.9% | 281.9% | -53.5% | 100.0% |
| B | 25,000 | 1.50% | 40% | 2 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 1.50% | 40% | 3 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 1.50% | 60% | 1 | 4.42 | 261.1% | -72.5% | -48.6% | 35.2% | 267.4% | -36.4% | 100.0% |
| B | 25,000 | 1.50% | 60% | 1.5 | 4.59 | 276.2% | -73.6% | -51.0% | 39.9% | 281.9% | -53.5% | 100.0% |
| B | 25,000 | 1.50% | 60% | 2 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 1.50% | 60% | 3 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 1.50% | 100% | 1 | 4.42 | 261.1% | -72.5% | -48.6% | 35.2% | 267.4% | -36.4% | 100.0% |
| B | 25,000 | 1.50% | 100% | 1.5 | 4.59 | 276.2% | -73.6% | -51.0% | 39.9% | 281.9% | -53.5% | 100.0% |
| B | 25,000 | 1.50% | 100% | 2 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 1.50% | 100% | 3 | 4.63 | 278.8% | -73.6% | -51.0% | 42.0% | 283.1% | -54.8% | 100.0% |
| B | 25,000 | 2.00% | 20% | 1 | 5.35 | 396.1% | -75.3% | -63.3% | 57.6% | 404.5% | -26.5% | 100.0% |
| B | 25,000 | 2.00% | 20% | 1.5 | 4.49 | 343.4% | -86.1% | -68.5% | 91.5% | 354.7% | -62.7% | 100.0% |
| B | 25,000 | 2.00% | 20% | 2 | 4.68 | 360.8% | -84.2% | -68.2% | 92.4% | 370.6% | -71.4% | 100.0% |
| B | 25,000 | 2.00% | 20% | 3 | 4.80 | 374.2% | -84.2% | -68.2% | 93.8% | 385.5% | -71.9% | 100.0% |
| B | 25,000 | 2.00% | 40% | 1 | 5.35 | 396.1% | -75.3% | -63.3% | 57.6% | 404.5% | -26.5% | 100.0% |
| B | 25,000 | 2.00% | 40% | 1.5 | 4.49 | 343.4% | -86.1% | -68.5% | 91.5% | 354.7% | -62.7% | 100.0% |
| B | 25,000 | 2.00% | 40% | 2 | 4.68 | 360.8% | -84.2% | -68.2% | 92.4% | 370.6% | -71.4% | 100.0% |
| B | 25,000 | 2.00% | 40% | 3 | 4.80 | 374.2% | -84.2% | -68.2% | 93.8% | 385.5% | -71.9% | 100.0% |
| B | 25,000 | 2.00% | 60% | 1 | 5.35 | 396.1% | -75.3% | -63.3% | 57.6% | 404.5% | -26.5% | 100.0% |
| B | 25,000 | 2.00% | 60% | 1.5 | 4.49 | 343.4% | -86.1% | -68.5% | 91.5% | 354.7% | -62.7% | 100.0% |
| B | 25,000 | 2.00% | 60% | 2 | 4.68 | 360.8% | -84.2% | -68.2% | 92.4% | 370.6% | -71.4% | 100.0% |
| B | 25,000 | 2.00% | 60% | 3 | 4.80 | 374.2% | -84.2% | -68.2% | 93.8% | 385.5% | -71.9% | 100.0% |
| B | 25,000 | 2.00% | 100% | 1 | 5.35 | 396.1% | -75.3% | -63.3% | 57.6% | 404.5% | -26.5% | 100.0% |
| B | 25,000 | 2.00% | 100% | 1.5 | 4.49 | 343.4% | -86.1% | -68.5% | 91.5% | 354.7% | -62.7% | 100.0% |
| B | 25,000 | 2.00% | 100% | 2 | 4.68 | 360.8% | -84.2% | -68.2% | 92.4% | 370.6% | -71.4% | 100.0% |
| B | 25,000 | 2.00% | 100% | 3 | 4.80 | 374.2% | -84.2% | -68.2% | 93.8% | 385.5% | -71.9% | 100.0% |
| B | 25,000 | 3.00% | 20% | 1 | 6.49 | 609.6% | -71.9% | -64.2% | 55.9% | 619.8% | -0.9% | 99.8% |
| B | 25,000 | 3.00% | 20% | 1.5 | 5.44 | 512.1% | -86.1% | -66.0% | 92.5% | 530.8% | -57.8% | 100.0% |
| B | 25,000 | 3.00% | 20% | 2 | 5.55 | 523.8% | -89.1% | -68.1% | 97.0% | 539.6% | -72.9% | 100.0% |
| B | 25,000 | 3.00% | 20% | 3 | 5.57 | 525.6% | -89.3% | -69.5% | 98.0% | 546.1% | -77.3% | 100.0% |
| B | 25,000 | 3.00% | 40% | 1 | 5.20 | 434.1% | -99.0% | -98.5% | 95.7% | 448.5% | -29.6% | 100.0% |
| B | 25,000 | 3.00% | 40% | 1.5 | 5.35 | 533.7% | -98.6% | -97.2% | 99.9% | 562.2% | -63.7% | 100.0% |
| B | 25,000 | 3.00% | 40% | 2 | 4.83 | 298.7% | -99.9% | -99.5% | 100.0% | 326.5% | -87.7% | 100.0% |
| B | 25,000 | 3.00% | 40% | 3 | 5.16 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 25,000 | 3.00% | 60% | 1 | 5.20 | 434.1% | -99.0% | -98.5% | 95.7% | 448.5% | -29.6% | 100.0% |
| B | 25,000 | 3.00% | 60% | 1.5 | 5.35 | 533.7% | -98.6% | -97.2% | 99.9% | 562.2% | -63.7% | 100.0% |
| B | 25,000 | 3.00% | 60% | 2 | 4.83 | 298.7% | -99.9% | -99.5% | 100.0% | 326.5% | -87.7% | 100.0% |
| B | 25,000 | 3.00% | 60% | 3 | 5.16 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 25,000 | 3.00% | 100% | 1 | 5.20 | 434.1% | -99.0% | -98.5% | 95.7% | 448.5% | -29.6% | 100.0% |
| B | 25,000 | 3.00% | 100% | 1.5 | 5.35 | 533.7% | -98.6% | -97.2% | 99.9% | 562.2% | -63.7% | 100.0% |
| B | 25,000 | 3.00% | 100% | 2 | 4.83 | 298.7% | -99.9% | -99.5% | 100.0% | 326.5% | -87.7% | 100.0% |
| B | 25,000 | 3.00% | 100% | 3 | 5.16 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 100,000 | 0.25% | 20% | 1 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 20% | 1.5 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 20% | 2 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 20% | 3 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 40% | 1 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 40% | 1.5 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 40% | 2 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 40% | 3 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 60% | 1 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 60% | 1.5 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 60% | 2 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 60% | 3 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 100% | 1 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 100% | 1.5 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 100% | 2 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.25% | 100% | 3 | 3.66 | 32.4% | -17.6% | -8.5% | 0.0% | 32.8% | -7.3% | 17.1% |
| B | 100,000 | 0.50% | 20% | 1 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 20% | 1.5 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 20% | 2 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 20% | 3 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 40% | 1 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 40% | 1.5 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 40% | 2 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 40% | 3 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 60% | 1 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 60% | 1.5 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 60% | 2 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 60% | 3 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 100% | 1 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 100% | 1.5 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 100% | 2 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 0.50% | 100% | 3 | 3.96 | 70.0% | -31.9% | -17.0% | 0.0% | 70.8% | -16.0% | 85.6% |
| B | 100,000 | 1.00% | 20% | 1 | 4.51 | 167.3% | -53.3% | -34.2% | 1.1% | 170.0% | -31.6% | 99.6% |
| B | 100,000 | 1.00% | 20% | 1.5 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 20% | 2 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 20% | 3 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 40% | 1 | 4.51 | 167.3% | -53.3% | -34.2% | 1.1% | 170.0% | -31.6% | 99.6% |
| B | 100,000 | 1.00% | 40% | 1.5 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 40% | 2 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 40% | 3 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 60% | 1 | 4.51 | 167.3% | -53.3% | -34.2% | 1.1% | 170.0% | -31.6% | 99.6% |
| B | 100,000 | 1.00% | 60% | 1.5 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 60% | 2 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 60% | 3 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 100% | 1 | 4.51 | 167.3% | -53.3% | -34.2% | 1.1% | 170.0% | -31.6% | 99.6% |
| B | 100,000 | 1.00% | 100% | 1.5 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 100% | 2 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.00% | 100% | 3 | 4.44 | 165.0% | -53.3% | -34.2% | 1.4% | 167.6% | -33.4% | 99.8% |
| B | 100,000 | 1.50% | 20% | 1 | 4.61 | 267.9% | -67.4% | -50.8% | 29.4% | 272.3% | -32.8% | 100.0% |
| B | 100,000 | 1.50% | 20% | 1.5 | 4.80 | 284.9% | -69.4% | -51.4% | 33.5% | 291.7% | -48.8% | 100.0% |
| B | 100,000 | 1.50% | 20% | 2 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 1.50% | 20% | 3 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 1.50% | 40% | 1 | 4.61 | 267.9% | -67.4% | -50.8% | 29.4% | 272.3% | -32.8% | 100.0% |
| B | 100,000 | 1.50% | 40% | 1.5 | 4.80 | 284.9% | -69.4% | -51.4% | 33.5% | 291.7% | -48.8% | 100.0% |
| B | 100,000 | 1.50% | 40% | 2 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 1.50% | 40% | 3 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 1.50% | 60% | 1 | 4.61 | 267.9% | -67.4% | -50.8% | 29.4% | 272.3% | -32.8% | 100.0% |
| B | 100,000 | 1.50% | 60% | 1.5 | 4.80 | 284.9% | -69.4% | -51.4% | 33.5% | 291.7% | -48.8% | 100.0% |
| B | 100,000 | 1.50% | 60% | 2 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 1.50% | 60% | 3 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 1.50% | 100% | 1 | 4.61 | 267.9% | -67.4% | -50.8% | 29.4% | 272.3% | -32.8% | 100.0% |
| B | 100,000 | 1.50% | 100% | 1.5 | 4.80 | 284.9% | -69.4% | -51.4% | 33.5% | 291.7% | -48.8% | 100.0% |
| B | 100,000 | 1.50% | 100% | 2 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 1.50% | 100% | 3 | 4.69 | 272.6% | -69.4% | -51.4% | 36.9% | 278.6% | -51.7% | 100.0% |
| B | 100,000 | 2.00% | 20% | 1 | 4.81 | 381.7% | -83.8% | -64.1% | 72.2% | 392.9% | -25.5% | 100.0% |
| B | 100,000 | 2.00% | 20% | 1.5 | 4.84 | 380.0% | -82.4% | -68.3% | 86.2% | 393.8% | -56.8% | 100.0% |
| B | 100,000 | 2.00% | 20% | 2 | 5.00 | 396.0% | -80.9% | -68.6% | 89.6% | 407.5% | -65.4% | 100.0% |
| B | 100,000 | 2.00% | 20% | 3 | 4.83 | 365.4% | -80.9% | -68.6% | 91.8% | 376.0% | -68.5% | 100.0% |
| B | 100,000 | 2.00% | 40% | 1 | 4.81 | 381.7% | -83.8% | -64.1% | 72.2% | 392.9% | -25.5% | 100.0% |
| B | 100,000 | 2.00% | 40% | 1.5 | 4.84 | 380.0% | -82.4% | -68.3% | 86.2% | 393.8% | -56.8% | 100.0% |
| B | 100,000 | 2.00% | 40% | 2 | 5.00 | 396.0% | -80.9% | -68.6% | 89.6% | 407.5% | -65.4% | 100.0% |
| B | 100,000 | 2.00% | 40% | 3 | 4.83 | 365.4% | -80.9% | -68.6% | 91.8% | 376.0% | -68.5% | 100.0% |
| B | 100,000 | 2.00% | 60% | 1 | 4.81 | 381.7% | -83.8% | -64.1% | 72.2% | 392.9% | -25.5% | 100.0% |
| B | 100,000 | 2.00% | 60% | 1.5 | 4.84 | 380.0% | -82.4% | -68.3% | 86.2% | 393.8% | -56.8% | 100.0% |
| B | 100,000 | 2.00% | 60% | 2 | 5.00 | 396.0% | -80.9% | -68.6% | 89.6% | 407.5% | -65.4% | 100.0% |
| B | 100,000 | 2.00% | 60% | 3 | 4.83 | 365.4% | -80.9% | -68.6% | 91.8% | 376.0% | -68.5% | 100.0% |
| B | 100,000 | 2.00% | 100% | 1 | 4.81 | 381.7% | -83.8% | -64.1% | 72.2% | 392.9% | -25.5% | 100.0% |
| B | 100,000 | 2.00% | 100% | 1.5 | 4.84 | 380.0% | -82.4% | -68.3% | 86.2% | 393.8% | -56.8% | 100.0% |
| B | 100,000 | 2.00% | 100% | 2 | 5.00 | 396.0% | -80.9% | -68.6% | 89.6% | 407.5% | -65.4% | 100.0% |
| B | 100,000 | 2.00% | 100% | 3 | 4.83 | 365.4% | -80.9% | -68.6% | 91.8% | 376.0% | -68.5% | 100.0% |
| B | 100,000 | 3.00% | 20% | 1 | 5.83 | 509.9% | -71.5% | -63.6% | 62.7% | 518.0% | -12.7% | 99.8% |
| B | 100,000 | 3.00% | 20% | 1.5 | 5.38 | 485.3% | -83.8% | -64.6% | 90.3% | 507.2% | -57.1% | 100.0% |
| B | 100,000 | 3.00% | 20% | 2 | 5.73 | 535.7% | -86.3% | -68.5% | 94.8% | 554.0% | -69.5% | 100.0% |
| B | 100,000 | 3.00% | 20% | 3 | 5.67 | 528.0% | -86.7% | -69.9% | 97.0% | 546.8% | -73.6% | 100.0% |
| B | 100,000 | 3.00% | 40% | 1 | 4.55 | 391.8% | -95.7% | -94.7% | 98.6% | 402.0% | -33.4% | 100.0% |
| B | 100,000 | 3.00% | 40% | 1.5 | 5.18 | 511.8% | -98.2% | -94.5% | 99.9% | 533.7% | -62.4% | 100.0% |
| B | 100,000 | 3.00% | 40% | 2 | 4.59 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 100,000 | 3.00% | 40% | 3 | 5.04 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 100,000 | 3.00% | 60% | 1 | 4.55 | 391.8% | -95.7% | -94.7% | 98.6% | 402.0% | -33.4% | 100.0% |
| B | 100,000 | 3.00% | 60% | 1.5 | 5.18 | 511.8% | -98.2% | -94.5% | 99.9% | 533.7% | -62.4% | 100.0% |
| B | 100,000 | 3.00% | 60% | 2 | 4.59 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 100,000 | 3.00% | 60% | 3 | 5.04 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 100,000 | 3.00% | 100% | 1 | 4.55 | 391.8% | -95.7% | -94.7% | 98.6% | 402.0% | -33.4% | 100.0% |
| B | 100,000 | 3.00% | 100% | 1.5 | 5.18 | 511.8% | -98.2% | -94.5% | 99.9% | 533.7% | -62.4% | 100.0% |
| B | 100,000 | 3.00% | 100% | 2 | 4.59 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 100,000 | 3.00% | 100% | 3 | 5.04 | -100.0% (ruined) | -100.0% | -100.0% | 100.0% | -100.0% | -100.0% | 100.0% |
| B | 250,000 | 0.25% | 20% | 1 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 20% | 1.5 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 20% | 2 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 20% | 3 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 40% | 1 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 40% | 1.5 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 40% | 2 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 40% | 3 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 60% | 1 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 60% | 1.5 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 60% | 2 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 60% | 3 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 100% | 1 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 100% | 1.5 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 100% | 2 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.25% | 100% | 3 | 3.60 | 31.7% | -16.5% | -8.5% | 0.0% | 32.1% | -7.2% | 16.2% |
| B | 250,000 | 0.50% | 20% | 1 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 20% | 1.5 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 20% | 2 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 20% | 3 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 40% | 1 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 40% | 1.5 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 40% | 2 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 40% | 3 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 60% | 1 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 60% | 1.5 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 60% | 2 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 60% | 3 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 100% | 1 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 100% | 1.5 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 100% | 2 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 0.50% | 100% | 3 | 4.06 | 69.6% | -29.6% | -17.1% | 0.0% | 70.2% | -14.6% | 81.9% |
| B | 250,000 | 1.00% | 20% | 1 | 4.50 | 161.2% | -51.4% | -34.1% | 0.5% | 163.6% | -29.9% | 99.5% |
| B | 250,000 | 1.00% | 20% | 1.5 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 20% | 2 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 20% | 3 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 40% | 1 | 4.50 | 161.2% | -51.4% | -34.1% | 0.5% | 163.6% | -29.9% | 99.5% |
| B | 250,000 | 1.00% | 40% | 1.5 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 40% | 2 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 40% | 3 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 60% | 1 | 4.50 | 161.2% | -51.4% | -34.1% | 0.5% | 163.6% | -29.9% | 99.5% |
| B | 250,000 | 1.00% | 60% | 1.5 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 60% | 2 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 60% | 3 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 100% | 1 | 4.50 | 161.2% | -51.4% | -34.1% | 0.5% | 163.6% | -29.9% | 99.5% |
| B | 250,000 | 1.00% | 100% | 1.5 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 100% | 2 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.00% | 100% | 3 | 4.35 | 156.4% | -51.4% | -34.1% | 1.1% | 158.6% | -31.9% | 99.7% |
| B | 250,000 | 1.50% | 20% | 1 | 4.47 | 242.3% | -66.4% | -50.2% | 29.2% | 249.3% | -35.0% | 100.0% |
| B | 250,000 | 1.50% | 20% | 1.5 | 4.60 | 250.8% | -67.1% | -50.5% | 32.8% | 256.4% | -48.9% | 100.0% |
| B | 250,000 | 1.50% | 20% | 2 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 1.50% | 20% | 3 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 1.50% | 40% | 1 | 4.47 | 242.3% | -66.4% | -50.2% | 29.2% | 249.3% | -35.0% | 100.0% |
| B | 250,000 | 1.50% | 40% | 1.5 | 4.60 | 250.8% | -67.1% | -50.5% | 32.8% | 256.4% | -48.9% | 100.0% |
| B | 250,000 | 1.50% | 40% | 2 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 1.50% | 40% | 3 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 1.50% | 60% | 1 | 4.47 | 242.3% | -66.4% | -50.2% | 29.2% | 249.3% | -35.0% | 100.0% |
| B | 250,000 | 1.50% | 60% | 1.5 | 4.60 | 250.8% | -67.1% | -50.5% | 32.8% | 256.4% | -48.9% | 100.0% |
| B | 250,000 | 1.50% | 60% | 2 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 1.50% | 60% | 3 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 1.50% | 100% | 1 | 4.47 | 242.3% | -66.4% | -50.2% | 29.2% | 249.3% | -35.0% | 100.0% |
| B | 250,000 | 1.50% | 100% | 1.5 | 4.60 | 250.8% | -67.1% | -50.5% | 32.8% | 256.4% | -48.9% | 100.0% |
| B | 250,000 | 1.50% | 100% | 2 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 1.50% | 100% | 3 | 4.52 | 248.3% | -67.1% | -50.5% | 35.2% | 252.1% | -49.9% | 100.0% |
| B | 250,000 | 2.00% | 20% | 1 | 5.14 | 375.9% | -72.1% | -63.5% | 56.5% | 385.9% | -23.2% | 100.0% |
| B | 250,000 | 2.00% | 20% | 1.5 | 4.40 | 308.5% | -84.3% | -66.3% | 87.1% | 321.1% | -60.2% | 100.0% |
| B | 250,000 | 2.00% | 20% | 2 | 4.55 | 317.2% | -80.1% | -66.9% | 90.2% | 325.5% | -66.5% | 100.0% |
| B | 250,000 | 2.00% | 20% | 3 | 4.59 | 324.5% | -80.5% | -66.9% | 91.1% | 332.7% | -66.4% | 100.0% |
| B | 250,000 | 2.00% | 40% | 1 | 5.14 | 375.9% | -72.1% | -63.5% | 56.5% | 385.9% | -23.2% | 100.0% |
| B | 250,000 | 2.00% | 40% | 1.5 | 4.40 | 308.5% | -84.3% | -66.3% | 87.1% | 321.1% | -60.2% | 100.0% |
| B | 250,000 | 2.00% | 40% | 2 | 4.55 | 317.2% | -80.1% | -66.9% | 90.2% | 325.5% | -66.5% | 100.0% |
| B | 250,000 | 2.00% | 40% | 3 | 4.59 | 324.5% | -80.5% | -66.9% | 91.1% | 332.7% | -66.4% | 100.0% |
| B | 250,000 | 2.00% | 60% | 1 | 5.14 | 375.9% | -72.1% | -63.5% | 56.5% | 385.9% | -23.2% | 100.0% |
| B | 250,000 | 2.00% | 60% | 1.5 | 4.40 | 308.5% | -84.3% | -66.3% | 87.1% | 321.1% | -60.2% | 100.0% |
| B | 250,000 | 2.00% | 60% | 2 | 4.55 | 317.2% | -80.1% | -66.9% | 90.2% | 325.5% | -66.5% | 100.0% |
| B | 250,000 | 2.00% | 60% | 3 | 4.59 | 324.5% | -80.5% | -66.9% | 91.1% | 332.7% | -66.4% | 100.0% |
| B | 250,000 | 2.00% | 100% | 1 | 5.14 | 375.9% | -72.1% | -63.5% | 56.5% | 385.9% | -23.2% | 100.0% |
| B | 250,000 | 2.00% | 100% | 1.5 | 4.40 | 308.5% | -84.3% | -66.3% | 87.1% | 321.1% | -60.2% | 100.0% |
| B | 250,000 | 2.00% | 100% | 2 | 4.55 | 317.2% | -80.1% | -66.9% | 90.2% | 325.5% | -66.5% | 100.0% |
| B | 250,000 | 2.00% | 100% | 3 | 4.59 | 324.5% | -80.5% | -66.9% | 91.1% | 332.7% | -66.4% | 100.0% |
| B | 250,000 | 3.00% | 20% | 1 | 6.47 | 573.9% | -71.9% | -61.8% | 50.1% | 583.8% | -0.3% | 99.9% |
| B | 250,000 | 3.00% | 20% | 1.5 | 5.33 | 485.4% | -83.2% | -66.1% | 90.6% | 500.2% | -54.1% | 100.0% |
| B | 250,000 | 3.00% | 20% | 2 | 5.64 | 504.6% | -85.3% | -68.2% | 94.8% | 520.2% | -67.3% | 100.0% |
| B | 250,000 | 3.00% | 20% | 3 | 5.50 | 488.9% | -85.3% | -68.2% | 96.4% | 507.3% | -70.4% | 100.0% |
| B | 250,000 | 3.00% | 40% | 1 | 5.70 | 572.7% | -87.6% | -79.0% | 94.9% | 580.0% | -5.1% | 100.0% |
| B | 250,000 | 3.00% | 40% | 1.5 | 5.31 | 565.3% | -88.9% | -76.7% | 99.8% | 582.9% | -55.4% | 100.0% |
| B | 250,000 | 3.00% | 40% | 2 | 4.65 | 381.2% | -96.3% | -87.1% | 100.0% | 405.8% | -81.3% | 100.0% |
| B | 250,000 | 3.00% | 40% | 3 | 4.99 | 386.0% | -95.9% | -89.5% | 100.0% | 407.8% | -87.9% | 100.0% |
| B | 250,000 | 3.00% | 60% | 1 | 5.70 | 572.7% | -87.6% | -79.0% | 94.9% | 580.0% | -5.1% | 100.0% |
| B | 250,000 | 3.00% | 60% | 1.5 | 5.31 | 565.3% | -88.9% | -76.7% | 99.8% | 582.9% | -55.4% | 100.0% |
| B | 250,000 | 3.00% | 60% | 2 | 4.65 | 381.2% | -96.3% | -87.1% | 100.0% | 405.8% | -81.3% | 100.0% |
| B | 250,000 | 3.00% | 60% | 3 | 4.99 | 386.0% | -95.9% | -89.5% | 100.0% | 407.8% | -87.9% | 100.0% |
| B | 250,000 | 3.00% | 100% | 1 | 5.70 | 572.7% | -87.6% | -79.0% | 94.9% | 580.0% | -5.1% | 100.0% |
| B | 250,000 | 3.00% | 100% | 1.5 | 5.31 | 565.3% | -88.9% | -76.7% | 99.8% | 582.9% | -55.4% | 100.0% |
| B | 250,000 | 3.00% | 100% | 2 | 4.65 | 381.2% | -96.3% | -87.1% | 100.0% | 405.8% | -81.3% | 100.0% |
| B | 250,000 | 3.00% | 100% | 3 | 4.99 | 386.0% | -95.9% | -89.5% | 100.0% | 407.8% | -87.9% | 100.0% |
