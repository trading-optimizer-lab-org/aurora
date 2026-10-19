# Follow-up: how the strategies with a 2016-2020 Sortino of 4 or more did until today

Written on 2026-10-19 at the owner's request ("las que tienen sortino 4 o mas mira como rindieron
hasta hoy"). Descriptive only: nothing is selected or tuned, and the rules are the published ones. The crypto part was computed
locally just before this note; the stock part is fixed here before it runs.

Strategies (2016-2020 monthly Sortino >= 4 in [RANKING_2016_2020_ES.md](RANKING_2016_2020_ES.md)):

- Intraday stocks (phases 1-7), from 2021-01-04 to 2026-10-16 (last close before today): `INTRADAY_EQ`, its 2x and
  3x account leverage, `I_EP_E0` (phase 2), `I_MIX_MODEL_N3_E0` (phase 3), `SIZE_S2_P0_C0_X1` (phase 4). Same data
  method as the locked test ([INTRADAY_LOCKED_PREREGISTRATION.md](INTRADAY_LOCKED_PREREGISTRATION.md)), extended to
  2026-10-16. A rehearsal must first reproduce the published 2016-2020 results: the phase 7a streams within 1e-9
  and the published monthly Sortino and CAGR of the three phase 2-4 strategies within 1e-9.
- Crypto trend (fixed code of PR #393), from 2021-01-01 to 2026-10-18: `ma_ensemble`, `donchian_20_10`,
  `ma_ensemble_alts`, with BTC buy and hold. The rehearsal reproduces the published train and validation Sortinos
  on the published prices. Rerun with the fixed code, their 2016-2020 Sortinos are 5.30, 4.70 and 4.48 (the ranking
  used the earlier unfixed run); `tsmom_28` stays below 4 (3.28) and is shown for reference only. 2024 onward was the
  crypto study's locked period, never opened before.

Reported: monthly Sortino, CAGR, max drawdown, total return, worst month and yearly returns from 2021 to today,
next to SPY. Survivorship in the stock list (only companies still listed when the list was made) flatters the stock
strategies after 2020.
