# v9 results: twenty families aimed at a monthly Sortino of 10

GitHub run 39156191938 (2026-10-18): 320 runners with 4 worker processes each, plus two download jobs and the
report, about 35 minutes end to end. All 3,658 pre-registered trials ([V9_PREREGISTRATION.md](V9_PREREGISTRATION.md))
and the 18 combination trials were computed. Nothing after 2020-12-31 was read.

## Summary

- **No trial reached a monthly Sortino of 10 in its judgment period**, and every deflated Sharpe rounds to 0.00
  over 252,904 trials.
- **Daily market-neutral books collapse out of sample.** The selection-period picks look spectacular (reversal
  17.1, overnight 23.4, pairs 5.9 in 1995-2010) and are negative or near zero in 2011-2020 (-0.91, -2.79, 0.50).
  Across the eight daily families the median Sortino falls from 1.24 to -0.43. These anomalies were strongest
  before decimalisation (2001) and fast electronic trading; they do not survive in the later decade even at 2 bps.
- **Intraday books on many stocks lose after costs** (VWAP reversion, intraday reversal, periodicity, gaps:
  median judgment Sortino about -2 to -3, still negative at 2 bps).
- **Other markets are modest diversifiers, not engines**: ETF trend 0.61, ETF momentum 0.42, turn of the month
  1.36 (IWM pick; QQQ 2.67 and SPY 2.35 among the unpicked variants).
- **The final combinations fail**: COMBO_DAILY_RP 14.57 in 1995-2010 but 0.37 in 2011-2020; COMBO_DAILY_EQ
  5.64 -> 1.46; COMBO_ALL_EQ 1.85 in 2019-2020, below the phase 7 INTRADAY_EQ (7.55 in 2019-2020, 2.93 in
  2016-2018) that it dilutes.
- **The loss brake does not help reliably.** Chosen on 2016-2018, it lowers INTRADAY_EQ's 2019-2020 Sortino from
  7.55 to 4.28, EP_NEWS from 7.90 to 5.02 and DAILY_RP's 2011-2020 from 2.76 to 2.36; it helps BO_TOP3 (1.17 ->
  2.20) and ALL13_EQ (3.73 -> 4.27). The ten trials that pass the criteria are all brakes on streams whose
  2019-2020 windfall was already known from phases 1-7.
- Best lead remains the phase 7 intraday combination (Qullamaggie earnings and news EPs plus model breakouts).
  Its only clean test left is forward paper trading or the locked 2021+ period, on the owner's request.

## Deviation from the pre-registration found after launch

The SPY hedge legs of PEAD, EAPREM and GAP were charged the stock cost (5 bps) instead of the ETF cost (2 bps).
This is conservative and too small to change any conclusion (those families are below Sortino 1 out of sample at
every cost). BRAKE trials have no cost sensitivity because they act on already net streams.

## Full report


3,658 of 3,658 trials, plus the combinations; deflated Sharpe over 252,904 trials. Selection periods: 1995-2010 (daily families, from each one's start) and 2016-2018 (intraday); judgment periods: 2011-2020 and 2019-2020. Main costs: stocks 5 bps, ETFs 2 bps per unit of turnover. Survivorship bias NOT adjusted. Nothing after 2020-12-31 was read.

SPY judgment periods: 2011-2020 Sortino 1.60, CAGR 13.8%; 2019-2020 Sortino 1.87, CAGR 24.6%.

## 1. Monthly Sortino of 10 or more in the judgment period

none

## 2. Final combinations

COMBO_DAILY members (12): REV_L1_NIND_Q10_H5_U1000_XC, PAIRS_F252_Z1.0_P100_SIND_U1000, ON_L126_LEGBOTH_NRAW_Q10_U1000_WEQ, LOWVOL_MBETA_W252_Q30_HGBETA_U1000, TSMOM_LBLEND_KSIGN_SETRISK_RM, PEAD_T10_D42_G1_U1500_MLONG, XSETF_L21_K3_SETRISK_MLONG, EAPREM_K5_E1_U1000, ACCUM, SQUEEZE, LOWVOL, IPO.

COMBO_ALL members (17): REV_L1_NIND_Q10_H5_U1000_XC, PAIRS_F252_Z1.0_P100_SIND_U1000, ON_L126_LEGBOTH_NRAW_Q10_U1000_WEQ, LOWVOL_MBETA_W252_Q30_HGBETA_U1000, TSMOM_LBLEND_KSIGN_SETRISK_RM, PEAD_T10_D42_G1_U1500_MLONG, XSETF_L21_K3_SETRISK_MLONG, EAPREM_K5_E1_U1000, ACCUM, SQUEEZE, LOWVOL, IPO, EP_EARN, BO_TOP3, EP_DAY, BO_DAY, PS_DAY.

| combination | selection Sortino | judgment Sortino | CAGR | max DD | total | worst month | worst day | positive months | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO_DAILY_EQ_L1 | 5.64 | 1.46 | 4.9% | -9.3% | +61% | -3.9% | -1.8% | 67% | 0.00 | no |
| COMBO_DAILY_EQ_L2 | 5.16 | 1.17 | 7.5% | -19.4% | +105% | -8.1% | -3.5% | 66% | 0.00 | no |
| COMBO_DAILY_EQ_L3 | 5.03 | 1.07 | 9.8% | -30.8% | +155% | -12.1% | -5.3% | 63% | 0.00 | no |
| COMBO_DAILY_EQ_L5 | 4.98 | 1.00 | 13.8% | -49.9% | +264% | -19.7% | -8.8% | 62% | 0.00 | no |
| COMBO_DAILY_RP_L1 | 14.57 | 0.37 | 1.2% | -10.4% | +13% | -2.0% | -1.5% | 58% | 0.00 | no |
| COMBO_DAILY_RP_L2 | 12.37 | -0.04 | 0.3% | -28.8% | +3% | -4.2% | -3.1% | 50% | 0.00 | no |
| COMBO_DAILY_RP_L3 | 11.73 | -0.18 | -0.7% | -44.1% | -7% | -6.4% | -4.6% | 49% | 0.00 | no |
| COMBO_DAILY_RP_L5 | 11.28 | -0.28 | -2.9% | -66.3% | -26% | -10.8% | -7.7% | 49% | 0.00 | no |
| COMBO_DAILY_RP_BRK | 9.89 | 0.18 | 0.9% | -5.4% | +9% | -1.7% | -1.3% | 57% | 0.00 | no |
| COMBO_ALL_EQ_L1 | 1.73 | 1.85 | 8.9% | -9.2% | +19% | -4.7% | -2.1% | 75% | 0.00 | no |
| COMBO_ALL_EQ_L2 | 1.45 | 1.67 | 15.1% | -17.9% | +32% | -9.5% | -4.2% | 75% | 0.00 | no |
| COMBO_ALL_EQ_L3 | 1.38 | 1.65 | 21.2% | -25.9% | +47% | -14.1% | -6.3% | 75% | 0.00 | no |
| COMBO_ALL_EQ_L5 | 1.35 | 1.68 | 33.4% | -39.9% | +78% | -22.9% | -10.5% | 75% | 0.00 | no |
| COMBO_ALL_RP_L1 | 1.29 | 1.19 | 4.1% | -6.8% | +8% | -2.4% | -1.3% | 71% | 0.00 | no |
| COMBO_ALL_RP_L2 | 0.91 | 0.85 | 5.3% | -14.5% | +11% | -4.9% | -2.6% | 58% | 0.00 | no |
| COMBO_ALL_RP_L3 | 0.80 | 0.74 | 6.4% | -22.5% | +13% | -7.5% | -4.0% | 54% | 0.00 | no |
| COMBO_ALL_RP_L5 | 0.73 | 0.66 | 8.0% | -36.4% | +17% | -12.7% | -6.6% | 50% | 0.00 | no |
| COMBO_ALL_RP_BRK | 1.44 | 1.31 | 4.1% | -4.0% | +8% | -1.5% | -1.1% | 71% | 0.00 | no |

## 3. One pick per family (best selection-period Sortino; judgment never used to choose)

| family: pick | selection Sortino | judgment Sortino | CAGR | max DD | total | worst month | worst day | positive months | DSR | passed | Sortino low / high cost | qualifies | variants with judgment Sortino >= 2 | median judgment Sortino |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REV: REV_L1_NIND_Q10_H5_U1000_XC | 17.05 | -0.91 | -1.2% | -23.5% | -11% | -1.6% | -2.8% | 49% | 0.00 | no | 0.53 / -2.20 | yes | 0 of 1296 | -0.53 |
| PAIRS: PAIRS_F252_Z1.0_P100_SIND_U1000 | 5.94 | 0.50 | 1.0% | -3.5% | +10% | -1.4% | -1.2% | 64% | 0.00 | no | 0.83 / -0.00 | yes | 0 of 192 | 0.05 |
| XSMOM: XSMOM_L126_S21_Q20_NRAW_H3_U500 | 0.23 | 0.18 | 1.2% | -12.6% | +12% | -5.5% | -7.8% | 48% | 0.00 | no | 0.21 / 0.13 | no | 0 of 192 | -0.11 |
| ON: ON_L126_LEGBOTH_NRAW_Q10_U1000_WEQ | 23.39 | -2.79 | -11.9% | -72.9% | -72% | -3.1% | -2.0% | 9% | 0.00 | no | 1.10 / -3.34 | yes | 0 of 360 | -3.11 |
| INDMOM: INDMOM_GSEC_M6_S0_K3_H1_U1000 | 0.72 | 0.35 | 1.8% | -12.2% | +20% | -4.0% | -2.3% | 56% | 0.00 | no | 0.42 / 0.23 | no | 0 of 224 | 0.21 |
| MAX: MAX_W21_K5_Q20_NIND_U500 | 0.04 | -0.48 | -1.2% | -18.9% | -11% | -3.8% | -1.8% | 52% | 0.00 | no | -0.37 / -0.66 | no | 0 of 32 | -0.48 |
| HI52: HI52_W252_Q30_NRAW_H6_U500 | -0.11 | -0.05 | 0.1% | -20.0% | +1% | -7.2% | -6.5% | 57% | 0.00 | no | -0.04 / -0.08 | no | 0 of 48 | -0.27 |
| LOWVOL: LOWVOL_MBETA_W252_Q30_HGBETA_U1000 | 1.36 | 0.88 | 3.5% | -17.1% | +41% | -4.2% | -5.5% | 63% | 0.00 | no | 0.90 / 0.84 | yes | 0 of 72 | 0.12 |
| TSMOM: TSMOM_LBLEND_KSIGN_SETRISK_RM | 1.48 | 0.61 | 4.2% | -18.9% | +51% | -6.6% | -4.3% | 57% | 0.00 | no | 0.63 / 0.53 | yes | 0 of 60 | 0.44 |
| GAP: GAP_B4-8_DFOLLOW_E945_X1100_U200 | 0.63 | -1.08 | -16.7% | -50.8% | -31% | -11.9% | -4.2% | 50% | 0.00 | no | -0.48 / -1.75 | no | 0 of 192 | -2.05 |
| INTRAREV: INTRAREV_T1030_WOPEN_NRAW_Q10_PCLOSE_U500 | -2.42 | -2.42 | -22.6% | -41.0% | -40% | -6.6% | -1.4% | 17% | 0.00 | no | -1.50 / -3.00 | no | 0 of 288 | -3.22 |
| INTRAPER: INTRAPER_L5_SFIRST_Q10_U200 | -2.81 | -2.17 | -18.0% | -34.1% | -33% | -7.7% | -1.8% | 8% | 0.00 | no | -0.85 / -2.89 | no | 0 of 36 | -3.31 |
| PEAD: PEAD_T10_D42_G1_U1500_MLONG | 1.67 | -0.06 | 0.2% | -19.3% | +2% | -5.2% | -3.1% | 49% | 0.00 | no | 0.05 / -0.22 | yes | 0 of 240 | -0.29 |
| VWAPREV: VWAPREV_C60_ARAW_Q5_PCLOSE_NRAW_U200 | -2.91 | -2.27 | -19.1% | -37.4% | -35% | -5.1% | -1.3% | 12% | 0.00 | no | -1.14 / -2.90 | no | 0 of 192 | -3.28 |
| XSETF: XSETF_L21_K3_SETRISK_MLONG | 2.58 | 0.42 | 3.6% | -28.0% | +43% | -10.6% | -8.0% | 62% | 0.00 | no | 0.44 / 0.35 | yes | 0 of 72 | 0.35 |
| SEASON: SEASON_ETOM4-4_IIWM | 0.96 | 1.36 | 8.5% | -15.8% | +125% | -6.1% | -6.8% | 59% | 0.00 | no | 1.41 / 1.22 | no | 2 of 30 | 0.11 |
| EAPREM: EAPREM_K5_E1_U1000 | 1.79 | 0.27 | 1.5% | -26.0% | +16% | -5.7% | -3.0% | 50% | 0.00 | no | 0.81 / -0.46 | yes | 0 of 24 | 0.20 |
| MKTINTRA: MKTINTRA_IQQQ_SIGPC1530_TR1530_FBIG | -0.75 | -0.25 | 0.3% | -10.0% | +1% | -1.7% | -4.4% | 29% | 0.00 | no | 0.72 / -1.75 | no | 0 of 48 | -0.89 |
| ETFREV: ETFREV_L5_K1_SETBROAD | 0.76 | -0.39 | -8.2% | -69.4% | -58% | -22.2% | -10.7% | 45% | 0.00 | no | -0.34 / -0.54 | no | 0 of 12 | -0.23 |

## 4. Loss brake on the phase 7 streams

| brake | selection Sortino | judgment Sortino | CAGR | max DD | total | worst month | worst day | positive months | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| BRAKE_BEP_NEWS_MMONTH_X2 | -1.17 | 8.34 | 44.6% | -11.8% | +109% | -3.0% | -8.1% | 58% | 0.00 | YES |
| BRAKE_BEP_NEWS_MMONTH_X3 | -1.16 | 7.97 | 49.7% | -11.8% | +124% | -3.6% | -8.1% | 62% | 0.00 | YES |
| BRAKE_BEP_NEWS_MROLL_X0.5 | -1.44 | 5.33 | 34.7% | -24.4% | +82% | -6.2% | -8.1% | 58% | 0.00 | YES |
| BRAKE_BEP_NEWS_MROLL_X1 | -1.85 | 6.65 | 41.3% | -18.3% | +100% | -6.2% | -8.1% | 58% | 0.00 | YES |
| BRAKE_BEP_NEWS_MROLL_X2 | -1.05 | 5.02 | 42.6% | -15.7% | +104% | -7.1% | -8.1% | 54% | 0.00 | YES |
| BRAKE_BEP_NEWS_MROLL_X3 | -1.09 | 3.61 | 41.1% | -17.2% | +99% | -12.9% | -8.1% | 62% | 0.00 | YES |
| BRAKE_BBO_TOP3_MMONTH_X0.5 | 0.57 | 0.20 | 1.6% | -11.5% | +3% | -2.0% | -4.3% | 25% | 0.00 | no |
| BRAKE_BBO_TOP3_MMONTH_X1 | 2.64 | 3.20 | 13.8% | -9.6% | +30% | -2.0% | -4.8% | 42% | 0.00 | no |
| BRAKE_BBO_TOP3_MMONTH_X2 | 3.58 | 2.20 | 12.6% | -10.7% | +27% | -3.3% | -4.8% | 50% | 0.00 | no |
| BRAKE_BBO_TOP3_MMONTH_X3 | 3.35 | 1.40 | 9.7% | -11.5% | +20% | -4.7% | -4.8% | 50% | 0.00 | no |
| BRAKE_BBO_TOP3_MROLL_X0.5 | 1.40 | 1.79 | 9.6% | -12.7% | +20% | -4.6% | -4.8% | 42% | 0.00 | no |
| BRAKE_BBO_TOP3_MROLL_X1 | 1.63 | 1.91 | 11.3% | -11.0% | +24% | -4.6% | -4.8% | 42% | 0.00 | no |
| BRAKE_BBO_TOP3_MROLL_X2 | 2.74 | 1.00 | 6.5% | -11.5% | +13% | -4.8% | -4.8% | 46% | 0.00 | no |
| BRAKE_BBO_TOP3_MROLL_X3 | 2.80 | 1.45 | 10.0% | -11.5% | +21% | -4.8% | -4.8% | 46% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X0.5 | 2.07 | 2.01 | 5.0% | -6.2% | +63% | -1.9% | -2.8% | 48% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X1 | 2.54 | 2.05 | 6.2% | -7.3% | +82% | -3.1% | -2.8% | 60% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X2 | 2.57 | 2.29 | 7.7% | -6.6% | +110% | -3.1% | -2.7% | 68% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X3 | 2.60 | 2.36 | 7.9% | -7.8% | +114% | -3.6% | -2.7% | 68% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X0.5 | 2.22 | 2.12 | 6.1% | -7.2% | +81% | -3.8% | -2.8% | 62% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X1 | 2.16 | 2.35 | 6.8% | -6.3% | +93% | -3.6% | -2.7% | 65% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X2 | 2.47 | 2.00 | 7.2% | -7.1% | +101% | -5.3% | -2.7% | 68% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X3 | 2.55 | 2.31 | 7.9% | -8.7% | +114% | -5.8% | -2.7% | 68% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MMONTH_X0.5 | 2.73 | 3.87 | 11.8% | -7.8% | +25% | -2.2% | -3.7% | 33% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MMONTH_X1 | 2.92 | 4.28 | 17.4% | -7.3% | +38% | -2.2% | -3.7% | 46% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MMONTH_X2 | 2.77 | 4.34 | 19.4% | -8.5% | +43% | -2.9% | -3.7% | 58% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MMONTH_X3 | 2.50 | 7.60 | 26.9% | -7.7% | +61% | -2.0% | -3.7% | 67% | 0.00 | YES |
| BRAKE_BINTRADAY_EQ_MROLL_X0.5 | 1.96 | 6.86 | 22.7% | -6.4% | +51% | -1.7% | -3.7% | 50% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MROLL_X1 | 2.00 | 6.83 | 22.9% | -7.7% | +51% | -2.2% | -3.7% | 62% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MROLL_X2 | 1.88 | 4.64 | 21.7% | -9.3% | +48% | -3.9% | -3.7% | 62% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MROLL_X3 | 2.80 | 7.64 | 26.7% | -6.5% | +61% | -1.9% | -3.7% | 67% | 0.00 | YES |
| BRAKE_BALL13_EQ_MMONTH_X0.5 | 2.80 | 4.27 | 10.9% | -5.5% | +23% | -1.1% | -3.0% | 50% | 0.00 | no |
| BRAKE_BALL13_EQ_MMONTH_X1 | 2.24 | 4.08 | 11.9% | -5.4% | +25% | -1.4% | -3.0% | 58% | 0.00 | no |
| BRAKE_BALL13_EQ_MMONTH_X2 | 1.67 | 4.08 | 12.9% | -5.4% | +27% | -2.2% | -3.0% | 62% | 0.00 | no |
| BRAKE_BALL13_EQ_MMONTH_X3 | 1.63 | 3.77 | 12.6% | -5.4% | +27% | -2.7% | -3.0% | 62% | 0.00 | no |
| BRAKE_BALL13_EQ_MROLL_X0.5 | 1.65 | 1.28 | 6.5% | -9.2% | +14% | -4.0% | -3.0% | 54% | 0.00 | no |
| BRAKE_BALL13_EQ_MROLL_X1 | 1.50 | 1.82 | 8.6% | -8.0% | +18% | -2.9% | -3.0% | 62% | 0.00 | no |
| BRAKE_BALL13_EQ_MROLL_X2 | 1.52 | 1.60 | 7.8% | -8.3% | +16% | -3.2% | -3.0% | 54% | 0.00 | no |
| BRAKE_BALL13_EQ_MROLL_X3 | 1.44 | 3.69 | 12.5% | -5.4% | +27% | -2.7% | -3.0% | 62% | 0.00 | no |
| BRAKE_BEP_EARN_MMONTH_X0.5 | 4.33 | 2.04 | 8.9% | -6.1% | +19% | -3.7% | -3.7% | 46% | 0.00 | no |
| BRAKE_BEP_EARN_MMONTH_X1 | 4.44 | 1.54 | 7.6% | -6.6% | +16% | -3.7% | -3.7% | 50% | 0.00 | no |
| BRAKE_BEP_EARN_MMONTH_X2 | 3.73 | 2.01 | 11.1% | -4.8% | +24% | -3.7% | -3.7% | 62% | 0.00 | no |
| BRAKE_BEP_EARN_MMONTH_X3 | 3.59 | 2.34 | 12.8% | -5.4% | +27% | -3.7% | -3.7% | 67% | 0.00 | no |
| BRAKE_BEP_EARN_MROLL_X0.5 | 3.07 | 0.61 | 4.4% | -7.8% | +9% | -5.4% | -3.6% | 46% | 0.00 | no |
| BRAKE_BEP_EARN_MROLL_X1 | 3.63 | 1.39 | 8.5% | -8.5% | +18% | -5.9% | -3.6% | 42% | 0.00 | no |
| BRAKE_BEP_EARN_MROLL_X2 | 4.14 | 2.31 | 14.2% | -7.2% | +31% | -6.1% | -3.6% | 67% | 0.00 | no |
| BRAKE_BEP_EARN_MROLL_X3 | 4.63 | 2.54 | 15.4% | -7.2% | +33% | -6.1% | -3.6% | 71% | 0.00 | no |
| BRAKE_BEP_NEWS_MMONTH_X0.5 | -1.44 | 7.44 | 29.3% | -11.8% | +67% | -3.0% | -8.1% | 42% | 0.00 | YES |
| BRAKE_BEP_NEWS_MMONTH_X1 | -1.72 | 7.21 | 33.0% | -11.8% | +77% | -3.0% | -8.1% | 50% | 0.00 | YES |

## 5. The 40 best trials by judgment-period Sortino (choosing this way is overfitting; for information only)

| trial | selection Sortino | judgment Sortino | CAGR | max DD | total | worst month | worst day | positive months | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| BRAKE_BEP_NEWS_MMONTH_X2 | -1.17 | 8.34 | 44.6% | -11.8% | +109% | -3.0% | -8.1% | 58% | 0.00 | YES |
| BRAKE_BEP_NEWS_MMONTH_X3 | -1.16 | 7.97 | 49.7% | -11.8% | +124% | -3.6% | -8.1% | 62% | 0.00 | YES |
| BRAKE_BINTRADAY_EQ_MROLL_X3 | 2.80 | 7.64 | 26.7% | -6.5% | +61% | -1.9% | -3.7% | 67% | 0.00 | YES |
| BRAKE_BINTRADAY_EQ_MMONTH_X3 | 2.50 | 7.60 | 26.9% | -7.7% | +61% | -2.0% | -3.7% | 67% | 0.00 | YES |
| BRAKE_BEP_NEWS_MMONTH_X0.5 | -1.44 | 7.44 | 29.3% | -11.8% | +67% | -3.0% | -8.1% | 42% | 0.00 | YES |
| BRAKE_BEP_NEWS_MMONTH_X1 | -1.72 | 7.21 | 33.0% | -11.8% | +77% | -3.0% | -8.1% | 50% | 0.00 | YES |
| BRAKE_BINTRADAY_EQ_MROLL_X0.5 | 1.96 | 6.86 | 22.7% | -6.4% | +51% | -1.7% | -3.7% | 50% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MROLL_X1 | 2.00 | 6.83 | 22.9% | -7.7% | +51% | -2.2% | -3.7% | 62% | 0.00 | no |
| BRAKE_BEP_NEWS_MROLL_X1 | -1.85 | 6.65 | 41.3% | -18.3% | +100% | -6.2% | -8.1% | 58% | 0.00 | YES |
| BRAKE_BEP_NEWS_MROLL_X0.5 | -1.44 | 5.33 | 34.7% | -24.4% | +82% | -6.2% | -8.1% | 58% | 0.00 | YES |
| BRAKE_BEP_NEWS_MROLL_X2 | -1.05 | 5.02 | 42.6% | -15.7% | +104% | -7.1% | -8.1% | 54% | 0.00 | YES |
| BRAKE_BINTRADAY_EQ_MROLL_X2 | 1.88 | 4.64 | 21.7% | -9.3% | +48% | -3.9% | -3.7% | 62% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MMONTH_X2 | 2.77 | 4.34 | 19.4% | -8.5% | +43% | -2.9% | -3.7% | 58% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MMONTH_X1 | 2.92 | 4.28 | 17.4% | -7.3% | +38% | -2.2% | -3.7% | 46% | 0.00 | no |
| BRAKE_BALL13_EQ_MMONTH_X0.5 | 2.80 | 4.27 | 10.9% | -5.5% | +23% | -1.1% | -3.0% | 50% | 0.00 | no |
| BRAKE_BALL13_EQ_MMONTH_X2 | 1.67 | 4.08 | 12.9% | -5.4% | +27% | -2.2% | -3.0% | 62% | 0.00 | no |
| BRAKE_BALL13_EQ_MMONTH_X1 | 2.24 | 4.08 | 11.9% | -5.4% | +25% | -1.4% | -3.0% | 58% | 0.00 | no |
| BRAKE_BINTRADAY_EQ_MMONTH_X0.5 | 2.73 | 3.87 | 11.8% | -7.8% | +25% | -2.2% | -3.7% | 33% | 0.00 | no |
| BRAKE_BALL13_EQ_MMONTH_X3 | 1.63 | 3.77 | 12.6% | -5.4% | +27% | -2.7% | -3.0% | 62% | 0.00 | no |
| BRAKE_BALL13_EQ_MROLL_X3 | 1.44 | 3.69 | 12.5% | -5.4% | +27% | -2.7% | -3.0% | 62% | 0.00 | no |
| BRAKE_BEP_NEWS_MROLL_X3 | -1.09 | 3.61 | 41.1% | -17.2% | +99% | -12.9% | -8.1% | 62% | 0.00 | YES |
| BRAKE_BBO_TOP3_MMONTH_X1 | 2.64 | 3.20 | 13.8% | -9.6% | +30% | -2.0% | -4.8% | 42% | 0.00 | no |
| SEASON_ETOM4-4_IQQQ | 0.19 | 2.67 | 13.7% | -10.7% | +259% | -4.9% | -5.1% | 69% | 0.00 | no |
| BRAKE_BEP_EARN_MROLL_X3 | 4.63 | 2.54 | 15.4% | -7.2% | +33% | -6.1% | -3.6% | 71% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X3 | 2.60 | 2.36 | 7.9% | -7.8% | +114% | -3.6% | -2.7% | 68% | 0.00 | no |
| SEASON_ETOM4-4_ISPY | 0.83 | 2.35 | 10.3% | -12.2% | +167% | -4.6% | -4.7% | 66% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X1 | 2.16 | 2.35 | 6.8% | -6.3% | +93% | -3.6% | -2.7% | 65% | 0.00 | no |
| BRAKE_BEP_EARN_MMONTH_X3 | 3.59 | 2.34 | 12.8% | -5.4% | +27% | -3.7% | -3.7% | 67% | 0.00 | no |
| BRAKE_BEP_EARN_MROLL_X2 | 4.14 | 2.31 | 14.2% | -7.2% | +31% | -6.1% | -3.6% | 67% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X3 | 2.55 | 2.31 | 7.9% | -8.7% | +114% | -5.8% | -2.7% | 68% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X2 | 2.57 | 2.29 | 7.7% | -6.6% | +110% | -3.1% | -2.7% | 68% | 0.00 | no |
| BRAKE_BBO_TOP3_MMONTH_X2 | 3.58 | 2.20 | 12.6% | -10.7% | +27% | -3.3% | -4.8% | 50% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X0.5 | 2.22 | 2.12 | 6.1% | -7.2% | +81% | -3.8% | -2.8% | 62% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X1 | 2.54 | 2.05 | 6.2% | -7.3% | +82% | -3.1% | -2.8% | 60% | 0.00 | no |
| BRAKE_BEP_EARN_MMONTH_X0.5 | 4.33 | 2.04 | 8.9% | -6.1% | +19% | -3.7% | -3.7% | 46% | 0.00 | no |
| BRAKE_BEP_EARN_MMONTH_X2 | 3.73 | 2.01 | 11.1% | -4.8% | +24% | -3.7% | -3.7% | 62% | 0.00 | no |
| BRAKE_BDAILY_RP_MMONTH_X0.5 | 2.07 | 2.01 | 5.0% | -6.2% | +63% | -1.9% | -2.8% | 48% | 0.00 | no |
| BRAKE_BDAILY_RP_MROLL_X2 | 2.47 | 2.00 | 7.2% | -7.1% | +101% | -5.3% | -2.7% | 68% | 0.00 | no |
| LOWVOL_MBETA_W21_Q10_HGBETA_U500 | 0.28 | 1.96 | 11.3% | -21.0% | +191% | -6.8% | -6.3% | 68% | 0.00 | no |
| BRAKE_BBO_TOP3_MROLL_X1 | 1.63 | 1.91 | 11.3% | -11.0% | +24% | -4.6% | -4.8% | 42% | 0.00 | no |

## 6. Monthly-return correlations of the qualifying picks and phase 7 members, 2016-2020

| | EAPREM_K5_E1_U1000 | LOWVOL_MBETA_W252_Q30_HGBETA_U1000 | ON_L126_LEGBOTH_NRAW_Q10_U1000_WEQ | PAIRS_F252_Z1.0_P100_SIND_U1000 | PEAD_T10_D42_G1_U1500_MLONG | REV_L1_NIND_Q10_H5_U1000_XC | TSMOM_LBLEND_KSIGN_SETRISK_RM | XSETF_L21_K3_SETRISK_MLONG | ACCUM | BO_DAY | BO_TOP3 | EP_DAY | EP_EARN | IPO | LOWVOL | PS_DAY | SQUEEZE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EAPREM_K5_E1_U1000 | +1.00 | +0.15 | -0.12 | -0.11 | +0.55 | +0.43 | -0.18 | +0.21 | +0.50 | -0.07 | +0.11 | +0.39 | +0.27 | +0.46 | +0.38 | +0.54 | +0.57 |
| LOWVOL_MBETA_W252_Q30_HGBETA_U1000 | +0.15 | +1.00 | +0.23 | -0.28 | -0.00 | +0.00 | +0.03 | +0.07 | +0.09 | +0.01 | +0.03 | +0.05 | +0.13 | +0.01 | +0.59 | +0.40 | +0.21 |
| ON_L126_LEGBOTH_NRAW_Q10_U1000_WEQ | -0.12 | +0.23 | +1.00 | +0.17 | -0.05 | +0.08 | +0.05 | +0.00 | -0.38 | -0.03 | +0.09 | -0.16 | +0.09 | -0.16 | -0.05 | -0.05 | -0.07 |
| PAIRS_F252_Z1.0_P100_SIND_U1000 | -0.11 | -0.28 | +0.17 | +1.00 | +0.03 | +0.07 | +0.15 | -0.02 | -0.16 | +0.01 | +0.29 | +0.19 | +0.26 | -0.23 | -0.19 | -0.49 | -0.08 |
| PEAD_T10_D42_G1_U1500_MLONG | +0.55 | -0.00 | -0.05 | +0.03 | +1.00 | +0.44 | -0.26 | +0.15 | +0.44 | -0.01 | +0.34 | +0.12 | +0.34 | +0.51 | +0.20 | +0.31 | +0.55 |
| REV_L1_NIND_Q10_H5_U1000_XC | +0.43 | +0.00 | +0.08 | +0.07 | +0.44 | +1.00 | -0.24 | +0.25 | +0.10 | -0.11 | +0.14 | +0.12 | +0.21 | +0.18 | +0.15 | +0.26 | +0.23 |
| TSMOM_LBLEND_KSIGN_SETRISK_RM | -0.18 | +0.03 | +0.05 | +0.15 | -0.26 | -0.24 | +1.00 | +0.57 | +0.10 | +0.09 | +0.12 | +0.06 | +0.18 | +0.00 | +0.14 | -0.46 | -0.01 |
| XSETF_L21_K3_SETRISK_MLONG | +0.21 | +0.07 | +0.00 | -0.02 | +0.15 | +0.25 | +0.57 | +1.00 | +0.37 | +0.03 | +0.15 | +0.14 | +0.24 | +0.19 | +0.30 | +0.01 | +0.35 |
| ACCUM | +0.50 | +0.09 | -0.38 | -0.16 | +0.44 | +0.10 | +0.10 | +0.37 | +1.00 | +0.00 | +0.17 | +0.39 | +0.22 | +0.47 | +0.57 | +0.32 | +0.74 |
| BO_DAY | -0.07 | +0.01 | -0.03 | +0.01 | -0.01 | -0.11 | +0.09 | +0.03 | +0.00 | +1.00 | +0.38 | +0.15 | +0.14 | +0.11 | +0.01 | -0.02 | -0.04 |
| BO_TOP3 | +0.11 | +0.03 | +0.09 | +0.29 | +0.34 | +0.14 | +0.12 | +0.15 | +0.17 | +0.38 | +1.00 | -0.01 | +0.22 | +0.25 | +0.02 | -0.01 | +0.12 |
| EP_DAY | +0.39 | +0.05 | -0.16 | +0.19 | +0.12 | +0.12 | +0.06 | +0.14 | +0.39 | +0.15 | -0.01 | +1.00 | +0.37 | +0.12 | +0.38 | +0.17 | +0.46 |
| EP_EARN | +0.27 | +0.13 | +0.09 | +0.26 | +0.34 | +0.21 | +0.18 | +0.24 | +0.22 | +0.14 | +0.22 | +0.37 | +1.00 | +0.18 | +0.14 | -0.01 | +0.24 |
| IPO | +0.46 | +0.01 | -0.16 | -0.23 | +0.51 | +0.18 | +0.00 | +0.19 | +0.47 | +0.11 | +0.25 | +0.12 | +0.18 | +1.00 | +0.39 | +0.15 | +0.48 |
| LOWVOL | +0.38 | +0.59 | -0.05 | -0.19 | +0.20 | +0.15 | +0.14 | +0.30 | +0.57 | +0.01 | +0.02 | +0.38 | +0.14 | +0.39 | +1.00 | +0.33 | +0.66 |
| PS_DAY | +0.54 | +0.40 | -0.05 | -0.49 | +0.31 | +0.26 | -0.46 | +0.01 | +0.32 | -0.02 | -0.01 | +0.17 | -0.01 | +0.15 | +0.33 | +1.00 | +0.37 |
| SQUEEZE | +0.57 | +0.21 | -0.07 | -0.08 | +0.55 | +0.23 | -0.01 | +0.35 | +0.74 | -0.04 | +0.12 | +0.46 | +0.24 | +0.48 | +0.66 | +0.37 | +1.00 |

## 7. Pre-registered criteria on the judgment period (Sortino >= 2, CAGR above SPY, max drawdown no deeper than -25%)

Passed: 10: BRAKE_BEP_NEWS_MMONTH_X2, BRAKE_BEP_NEWS_MMONTH_X3, BRAKE_BEP_NEWS_MROLL_X0.5, BRAKE_BEP_NEWS_MROLL_X1, BRAKE_BEP_NEWS_MROLL_X2, BRAKE_BEP_NEWS_MROLL_X3, BRAKE_BINTRADAY_EQ_MMONTH_X3, BRAKE_BINTRADAY_EQ_MROLL_X3, BRAKE_BEP_NEWS_MMONTH_X0.5, BRAKE_BEP_NEWS_MMONTH_X1.

