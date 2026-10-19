# Locked test of the phase 7 intraday combination: results (FAILED)

GitHub run 39214106550 (2026-10-19), pre-registered in
[INTRADAY_LOCKED_PREREGISTRATION.md](INTRADAY_LOCKED_PREREGISTRATION.md). The rehearsal reproduced the published
2016-2020 streams (largest difference 4.8e-11 against a 1e-9 limit) before anything from 2021+ was read. The window
2021-01-04 to 2026-09-30 is now spent for this combination.

## Summary

- **FAILED**: INTRADAY_EQ meets two of the three criteria. Monthly Sortino 2.15 (>= 2) and max drawdown -17.5%
  pass; annualised return 13.1% is below SPY's 14.8%.
- Out-of-sample decay: Sortino 4.92 -> 2.15, drawdown -7.7% -> -17.5%, CAGR 16.5% -> 13.1%.
- Leverage does not rescue it: at 2x the Sortino drops to 1.92 and the drawdown reaches -34.3%.
- Earnings EPs (1.54) and news EPs (1.49) hold up better than the model breakouts (0.92).
- **Survivorship is worse than the pre-registration assumed.** Every one of the 2,886 panel symbols active at the
  end of 2020 still had Yahoo data, so the stock list contains only companies still listed when it was made:
  stocks that collapsed or were delisted during 2021-2026 are missing, which flatters long-only EP and breakout
  books. Even with that tailwind the combination does not beat SPY.

## Full report

One-shot test pre-registered in docs/research/INTRADAY_LOCKED_PREREGISTRATION.md. Survivorship: 2875 symbols spliced into 2021+, 0 active at the end of 2020 had no Yahoo data (delisted or renamed), 0 did not splice, 11 failed the data checks; companies listed after 2020 are not included.

| stream | monthly Sortino | CAGR | max DD | total | worst month | worst day | positive months |
|---|---|---|---|---|---|---|---|
| INTRADAY_EQ | 2.15 | 13.1% | -17.5% | +103% | -4.0% | -4.1% | 52% |
| INTRADAY_EQ_L2 | 1.92 | 20.3% | -34.3% | +188% | -8.4% | -8.2% | 48% |
| EP_EARN | 1.54 | 13.9% | -16.2% | +110% | -7.4% | -3.6% | 62% |
| EP_NEWS | 1.49 | 13.2% | -27.6% | +103% | -5.7% | -5.9% | 58% |
| BO_TOP3 | 0.92 | 8.9% | -33.2% | +63% | -14.7% | -10.0% | 39% |
| SPY | 1.23 | 14.8% | -24.5% | +120% | -9.2% | -5.9% | 65% |

2016-2020 reference for INTRADAY_EQ: Sortino 4.92, CAGR 16.5%, max DD -7.7%.

## Yearly returns

| stream | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| INTRADAY_EQ | +5.5% | +11.1% | +13.5% | +20.0% | +32.5% | -4.3% |
| INTRADAY_EQ_L2 | +7.6% | +18.1% | +19.8% | +32.9% | +61.9% | -12.2% |
| EP_EARN | +2.8% | +10.0% | +18.8% | +39.3% | +24.1% | -9.4% |
| EP_NEWS | -2.9% | +7.8% | +19.6% | +20.4% | +25.7% | +7.3% |
| BO_TOP3 | +11.8% | +13.8% | +1.6% | +0.9% | +39.6% | -10.6% |
| SPY | +28.7% | -18.2% | +26.2% | +24.9% | +17.7% | +12.7% |

## Pre-registered criteria (INTRADAY_EQ at 1x)

- monthly Sortino >= 2.0: yes
- annualised return above SPY: NO
- max drawdown no deeper than -25%: yes
