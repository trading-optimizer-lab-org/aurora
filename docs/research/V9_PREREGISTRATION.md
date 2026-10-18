# v9: everything aimed at a monthly Sortino of 10, at once: pre-registration

Written and committed on 2026-10-18 **before any v9 result was computed**. The owner's goal is a monthly Sortino of
10. Phases 1-7 found a ceiling of about 5 with a few strong but lumpy equity streams
([COMBINATION_PLUS_RESULTS.md](COMBINATION_PLUS_RESULTS.md)). A Sortino of 10 needs many small independent bets
(Grinold's fundamental law: skill x sqrt(breadth)), market neutrality, diversifiers from other markets and rules
that cut losing months. v9 tests twenty families of such strategies, each over a grid of variants, at once: 320
GitHub runners with 4 worker processes each (owner's request: at least 300 runners, all 4 cores used).

Exact rules are the code in `research/v9_*.py` and `scripts/run_v9.py`; the trial list is `v9_common.trials()`.
Common: survivors-only price panel (owner accepts the bias), industry and sector as listed today, 2021+ never read,
T-bills on cash, monthly Sortino on excess returns as before, worst month and worst day always reported.

## Accounting

- **Universe** `U{n}`: each day, the n stocks with the largest 50-session average dollar volume as of that close,
  price >= $5 and at least 252 sessions of history.
- **Long-short books**: weights decided at a close earn the following session(s); the long and the short leg each
  hold 0.5 of capital (gross 1), equal weight within a leg unless stated. Every book earns T-bills on its capital
  plus the positions' return over T-bills. A leg is formed only when at least 20 universe stocks have a signal.
- **Deciles** `Q{x}`: long the top x% of the signal, short the bottom x%.
- **Neutralisation**: `RAW` none; `IND` / `SEC` the signal minus its industry / sector mean (universe stocks);
  `MKT` the return minus beta (252 sessions) times SPY's.
- **Holding** `H{h}`: the average of the last h portfolios (overlapping, Jegadeesh-Titman).
- **Costs**, per unit of turnover (sum of absolute weight changes): stocks **5 bps** (sensitivity 2 and 10), ETFs
  **2 bps** (sensitivity 1 and 5). Shorts held overnight pay 1% a year. Intraday positions trade twice a day.
- **Intraday bars**: Alpaca SIP 15-minute bars, regular hours, 2016-2020, the daily top-500 universe (as of the prior
  close) plus SPY, QQQ, IWM, DIA; kept only in the Actions cache. A signal at the close of a bar is executed at the
  open of the next bar (this avoids trading at the price that formed the signal); exits at the close of a bar.
  Several check times in a day share the capital (1/K each) when their holdings overlap, otherwise each uses all of it.

## Families and grids (each line is the full cross product)

**Daily stock books, 1995-2020** (selection 1995-2010, judgment 2011-2020):
1. `REV` short-term reversal, signal minus the L-session return: L in {1,2,3,5,10,21}, N in {RAW, IND, SEC, MKT},
   Q in {10,20,30}, H in {1,2,5}, U in {200,500,1000}, execution X in {C (at the signal's close, close to close),
   O (at the next open, open to open)}. 1,296 trials.
2. `ON` overnight effect (Lou, Polk and Skouras), signal the mean close-to-open return over L sessions:
   L in {5,10,21,63,126}, leg in {ON (long high, close to next open), ID (long low, open to close), BOTH (half each)},
   N in {RAW, IND}, Q in {10,20}, U in {200,500,1000}, weights in {EQ, IV (inverse 63-session volatility)}. 360.
3. `PAIRS` (Gatev, Goetzmann and Rouwenhorst): every January and July the n pairs with the smallest sum of squared
   differences of normalised prices over F sessions, within scope; over the next 126 sessions a pair opens when the
   spread is z formation standard deviations away and closes when it crosses zero or at the end; each pair holds
   1/(2n) of capital per side. F in {126,252}, z in {1.0,1.5,2.0,2.5}, n in {10,20,50,100}, scope in {IND, SEC,
   ALL}, U in {500,1000}. 192.
4. `INDMOM` group momentum: at each month end the equal-weighted M-month return skipping S months of each group with
   at least 5 universe stocks; long the stocks of the best n groups, short the worst n. Industries: M in {1,3,6,12},
   S in {0,1}, n in {1,3,5,10}, H in {1,3} months, U in {500,1000} (128); sectors: same with n in {1,2,3} (96). 224.
5. `XSMOM` stock momentum: L-session return skipping S sessions, monthly: L in {21,63,126,252}, S in {0,21},
   Q in {10,20,30}, N in {RAW, IND}, H in {1,3} months, U in {500,1000}. 192.
6. `LOWVOL` low risk, monthly: measure in {VOL, BETA} over W in {21,63,252} sessions, long the lowest, Q in
   {10,20,30}, hedge in {DOLLAR (0.5 each leg), BETA (legs scaled to equal beta, Frazzini-Pedersen, gross 1)},
   U in {500,1000}. 72.
7. `HI52` nearness to the W-session high (George and Hwang), monthly: W in {126,252}, Q in {10,20,30},
   N in {RAW, IND}, H in {1,6} months, U in {500,1000}. 48.
8. `MAX` lottery stocks (Bali, Cakici and Whitelaw), long low, short high mean of the k largest daily returns over
   W sessions, monthly: W in {21,63}, k in {1,5}, Q in {10,20}, N in {RAW, IND}, U in {500,1000}. 32.

**Earnings events, SEC 8-K Item 2.02 filing dates, 2004-2020** (selection to 2010, judgment 2011-2020):
9. `PEAD` drift: reaction = return from the close before the filing date to the close after it minus SPY's; above
   +T long, below -T short, entered at the close G sessions after the filing date, held D sessions; a leg with no
   stock is replaced by SPY. T in {2,4,6,10}%, D in {5,10,21,42,63}, G in {1,2}, U in {500,1000,1500}, mode in
   {LS, LONG (long leg against 0.5 short SPY)}. 240.
10. `EAPREM` earnings announcement premium (Frazzini and Lamont): expected date = a past filing date + 364 days;
   long from the close K sessions before it to the close E sessions after it, against 0.5 short SPY (cash when no
   stock). K in {1,3,5,10}, E in {0,1,3}, U in {500,1000}. 24.

**ETFs (Yahoo, adjusted), each from its inception** (selection to 2010, judgment 2011-2020). Sets: `RISK` = SPY, EFA,
EEM, TLT, IEF, GLD, SLV, DBC, USO, UUP, FXE, FXY, VNQ; `SECT` = XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY;
`BROAD` = both plus QQQ, IWM, DIA, VGK, EWJ, SHY, LQD, HYG, TIP, UNG, DBA, FXB, FXA, FXC. An ETF enters once it has
252 sessions; a book needs at least 3.
11. `TSMOM` time-series momentum: signal over L in {21,63,126,252,BLEND (mean of the four signs)}, kind in {SIGN,
   SCALED (return / volatility, clipped to +-1)}, each asset sized to 10%/sqrt(N) annual volatility (63 sessions),
   gross at most 2, set in {RISK, SECT, BROAD}, rebalanced R in {M, W}. 60.
12. `XSETF` cross-sectional ETF momentum, monthly: L in {21,63,126,252}, best/worst n in {1,2,3}, set in {RISK,
   SECT, BROAD}, mode in {LS, LONG (best n against cash)}. 72.
13. `ETFREV` weekly ETF reversal: L in {1,5} sessions, n in {1,2,3}, set in {SECT, BROAD}. 12.
14. `SEASON` calendar effects on SPY, QQQ, IWM, TLT: turn of the month with windows (last a sessions, first b) in
   {(1,3),(2,3),(1,1),(4,4)}; the session before a market holiday; overnight only (close to open, also DIA);
   intraday only (open to close, also DIA). 30.

**Intraday stock books on 15-minute bars, 2016-2020** (selection 2016-2018, judgment 2019-2020):
15. `VWAPREV` reversion to the day's VWAP: checks every C in {30,60} minutes from 10:00 to 15:30, gap to VWAP
   divided by ADR (20 sessions) or not, long the most below, Q in {5,10,20}, held P in {15,30,60 minutes, to the
   close}, N in {RAW, IND}, U in {200,500}. 192.
16. `GAP` opening gaps from the daily panel within a band B in {0.5-1, 1-2, 2-4, 4-8}%, direction in {FADE, FOLLOW},
   entry at the open of the 9:45, 10:00 or 10:30 bar, exit at 11:00, 12:00, 14:00 or the close, U in {200,500};
   an empty leg is replaced by SPY. 192.
17. `INTRAREV` cross-sectional reversal within the day: at 10:30, 11:30, 12:30, 13:30, 14:30 or 15:00, the
   return since the open or over the last 30 minutes, N in {RAW, IND}, Q in {10,20}, held 30 or 60 minutes or to
   the close, U in {200,500}. 288.
18. `INTRAPER` intraday periodicity (Heston, Korajczyk and Sadka): signal = mean return of the same half hour over
   the last L in {5,10,20} days; traded in every half hour, only the first or only the last, Q in {10,20},
   U in {200,500}. 36.
19. `MKTINTRA` market intraday momentum (Gao, Han, Li and Zhou) on SPY, QQQ, IWM, DIA: signal from the prior close
   to 10:00, from the prior close to 15:30, or from the open to 10:00; traded 15:30-16:00 or 15:45-16:00 in its
   direction, always or only when the signal is larger in size than its 60-day median. ETF costs. 48.

**Loss brake on existing streams** (8a):
20. `BRAKE` on INTRADAY_EQ, ALL13_EQ, EP_EARN, EP_NEWS, BO_TOP3 (2016-2020, selection 2016-2018) and DAILY_RP
   (1995-2020): when the month-to-date return reaches -X (MONTH: cash until the month ends) or the trailing
   21-session return reaches -X (ROLL: cash for the next 5 sessions), X in {0.5,1,2,3}%, plus 10 bps each time it
   triggers. 48.

Total: 3,658 trials (2,416 daily stock books on one runner matrix, 1,242 others on the second), plus the 18 combination trials below.

## Final combination (pre-registered selection)

- In every family the variant with the best monthly Sortino (main cost) in its **selection period** is picked; a
  family qualifies when that Sortino is at least 1.0. The judgment period is never used to choose.
- `COMBO_DAILY`: the qualifying picks of families 1-14 plus the phase 7a daily streams (ACCUM, SQUEEZE, LOWVOL,
  IPO, PARA_SHORT) with a 1995-2010 Sortino of at least 1.0; 1995-2020, judged on 2011-2020, which is out of sample
  for every member's selection.
- `COMBO_ALL`: COMBO_DAILY's members plus the qualifying picks of families 15-19 and the phase 7 intraday streams
  (EP_EARN, EP_NEWS, BO_TOP3, EP_DAY, BO_DAY, PS_DAY, PS_SWING, BD_DAY) with a 2016-2018 Sortino of at least 1.0;
  2016-2020, judged on 2019-2020.
- Methods `EQ` (equal capital among the members trading that day) and `RP` (risk parity as in phase 7, over the
  members trading that day); leverage 1, 2, 3 and 5 at account level as in phase 7c; plus `RP_BRK`: RP with the
  MONTH 1% brake. 18 trials.

## Reporting

For every trial: monthly Sortino, CAGR, max drawdown, total return, worst month, worst day, positive months per
period, Sortino and CAGR at the sensitivity costs. Per family: the pick with its selection and judgment periods, the
share of variants with a judgment-period Sortino of at least 2, and the median. The 40 best trials by judgment
Sortino (a ranking that is itself overfit, shown for information). Monthly correlations of the picks. Pass criteria
as before on the judgment period (Sortino >= 2, CAGR above SPY, max drawdown no deeper than -25%), a "Sortino >= 10"
column, and the deflated Sharpe over all v9 trials plus the 249,228 earlier ones.

## Limits

Intraday data covers 2016-2020 only, and that period was used in phases 1-7. Bar prices are trade prices: the
spread is only in the cost assumption, which is the main risk for every high-turnover family. Liquidity limits and
the cost of closing positions when the brake triggers are ignored beyond the 10 bps. The clean tests remain forward
paper trading and the locked 2021+ period, used once and only on the owner's request.
