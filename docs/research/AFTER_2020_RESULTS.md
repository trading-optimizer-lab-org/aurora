# Follow-up results: the Sortino 4+ strategies from 2021 to today

Requested by the owner on 2026-10-19 ([AFTER_2020_FOLLOWUP.md](AFTER_2020_FOLLOWUP.md)). Descriptive, nothing selected.

## Summary

- Every strategy with a 2016-2020 monthly Sortino of 4 or more fell to about 1-2.3 from 2021 to today.
- Intraday stocks (GitHub run 39239220624, rehearsal reproduced 2016-2020 within 5e-11): the best is the plain
  episodic pivot book `I_EP_E0` (Sortino 2.31, 23.1% a year, max drawdown -29.6%), above SPY's 14.7% a year but
  with a deeper drawdown than SPY's -24.5%; `INTRADAY_EQ` 2.11 but 12.9% a year, below SPY. The stock list holds
  only companies still listed when it was made, which flatters all of them.
- Crypto trend (fixed code, data to 2026-10-18): 0.65-1.45, below 2 and with drawdowns of -27% to -33%.
  `tsmom_28`, which was below 4 in 2016-2020 and so not in the group, did better (2.11); picking it now would be
  selection after the fact.

## Intraday stocks, 2021-01-04 to 2026-10-16

| strategy | monthly Sortino | CAGR | max DD | total | worst month | worst day | Sortino 2021-24 | Sortino 2025-26 |
|---|---|---|---|---|---|---|---|---|
| INTRADAY_EQ | 2.11 | 12.9% | -17.4% | +102% | -4.0% | -4.1% | 2.15 | 1.98 |
| INTRADAY_EQ_L2 | 1.88 | 19.9% | -34.1% | +185% | -8.4% | -8.2% | 1.93 | 1.74 |
| INTRADAY_EQ_L3 | 1.80 | 25.6% | -48.0% | +272% | -12.6% | -12.3% | 1.86 | 1.63 |
| I_EP_E0 | 2.31 | 23.1% | -29.6% | +231% | -6.9% | -6.2% | 2.25 | 2.38 |
| I_MIX_MODEL_N3_E0 | 2.08 | 26.8% | -42.5% | +293% | -11.8% | -12.7% | 1.80 | 2.65 |
| SIZE_S2_P0_C0_X1 | 2.07 | 25.1% | -38.2% | +264% | -9.2% | -9.5% | 1.70 | 2.83 |
| EP_EARN | 1.53 | 13.8% | -16.2% | +111% | -7.4% | -3.6% | 2.60 | 0.39 |
| EP_NEWS | 1.40 | 12.7% | -27.6% | +99% | -5.7% | -5.9% | 1.23 | 1.71 |
| BO_TOP3 | 0.93 | 9.0% | -33.2% | +64% | -14.7% | -10.0% | 0.70 | 1.89 |
| SPY | 1.22 | 14.7% | -24.5% | +120% | -9.2% | -5.9% | 1.04 | 1.96 |

| strategy | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| INTRADAY_EQ | +5.7% | +11.1% | +13.5% | +20.0% | +32.5% | -4.8% |
| INTRADAY_EQ_L2 | +7.9% | +18.1% | +19.8% | +33.0% | +61.9% | -13.4% |
| INTRADAY_EQ_L3 | +8.2% | +24.5% | +25.6% | +45.2% | +93.1% | -21.6% |
| I_EP_E0 | +0.8% | +14.2% | +19.8% | +54.0% | +61.1% | -3.3% |
| I_MIX_MODEL_N3_E0 | +15.9% | +20.5% | +16.9% | +37.2% | +107.7% | -15.5% |
| SIZE_S2_P0_C0_X1 | +9.9% | +17.3% | +15.1% | +39.3% | +103.6% | -13.6% |
| EP_EARN | +2.8% | +10.0% | +18.8% | +39.3% | +24.1% | -9.2% |
| EP_NEWS | -2.9% | +7.8% | +19.6% | +20.4% | +25.7% | +4.9% |
| BO_TOP3 | +12.4% | +13.8% | +1.6% | +0.9% | +39.6% | -10.3% |
| SPY | +28.7% | -18.2% | +26.2% | +24.9% | +17.7% | +12.8% |

## Crypto trend, 2021-01-01 to 2026-10-18 (2021 was in the crypto study's training period; 2024 onward was locked)

| strategy | 2016-2020 Sortino | 2021-today Sortino | CAGR | max DD | total | worst month | 2024-today Sortino (locked) |
|---|---|---|---|---|---|---|---|
| ma_ensemble | 5.30 | 1.08 | 13.6% | -32.5% | +110% | -15.4% | 1.08 |
| donchian_20_10 | 4.70 | 0.65 | 8.7% | -26.5% | +63% | -15.1% | 0.45 |
| ma_ensemble_alts | 4.48 | 1.45 | 14.1% | -26.7% | +115% | -6.4% | 1.00 |
| tsmom_28 | 3.28 | 2.11 | 25.0% | -20.6% | +264% | -15.1% | 1.98 |
| btc_buy_hold | 3.37 | 0.91 | 19.6% | -76.6% | +183% | -37.8% | 1.16 |

| strategy | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| ma_ensemble | +43.6% | -22.4% | +33.4% | +33.8% | +5.7% | -0.3% |
| donchian_20_10 | +30.0% | -19.6% | +27.4% | +13.7% | +7.8% | -0.5% |
| ma_ensemble_alts | +60.0% | -18.3% | +20.3% | +34.2% | +4.9% | -3.0% |
| tsmom_28 | +68.2% | -12.4% | +46.0% | +51.3% | +22.0% | -8.2% |
| btc_buy_hold | +59.7% | -64.3% | +155.4% | +121.1% | -6.3% | -6.3% |
