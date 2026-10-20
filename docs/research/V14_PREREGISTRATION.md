# v14: many independent ideas on survivorship-free data: pre-registration

Written and committed on 2026-10-20, before any v14 strategy result was computed, at the owner's request ("si. te
encargo de que lo hagas todo tu"). Target: a monthly Sortino of 4. v13 showed that the earlier stock list carried
the edge (5.08 on it, 0.61 on all stocks), so every stock test here uses a survivorship-free universe, and the
search is wide in ideas but small in parameters. Exact rules are the code in `research/v14_*.py` and
`scripts/run_v14*.py`; this document fixes what the code must do.

## 1. Data (`scripts/run_v14_data.py`)

- **Universe:** every symbol in the FINRA Reg SHO daily files (consolidated NMS file; before it existed, the union of
  the three TRF files; the OTC file is excluded) from 2015-06-01 to 2026-10-16, with Alpaca SIP daily bars (raw and
  split-adjusted). A symbol whose bars stop for 5 or more sessions is treated as a new series after the gap (ticker
  reuse); no trade is held across a gap. Delisted stocks are kept up to their last bar; a position open at the last
  bar is closed at that bar's close. Coverage (share of FINRA symbol-days with an Alpaca bar) is reported.
- **Minute bars** (04:00-16:00 ET, raw, scaled to the split-adjusted daily series) for the event days only; the
  scopes use what is known at the open (open price, earlier days) or are supersets of every rule that uses them:
  gap-ups >= 15% (top 80 a day by gap) and runners with a high >= +40% over the prior close, both at an open of
  $0.50-$50; gap-downs <= -20%; the day after a +50% day; stocks in play (|gap| >= 3%, open >= $5, 20-day dollar
  volume >= $20M, top 30 by |gap|); SPY, QQQ, IWM every day.
- **SEC:** insider open-market purchases (Form 4 data sets), 424B/S-1/S-3/F-1/F-3 and SC 13D filings (EDGAR form
  index), 8-K items and 10-Q/10-K dates (submissions), shares outstanding and EPS (XBRL frames). Ticker-CIK history
  from the insider data sets and the current SEC list.
- **Crypto:** Binance spot daily klines of every USDT pair, delisted ones included (2017-08 to 2026-09-30); BTC and
  ETH hourly; BTC and ETH perpetual funding. Gaps of 3 days or more start a new series (ticker reuse, e.g. LUNA).
- **Macro:** CBOE VIX, VIX3M, VIX9D; scheduled FOMC statement days parsed from the Federal Reserve calendars; total-
  return daily bars for 30 ETFs; 3-month T-bill rate (FRED) for cash and excess returns.

## 2. Periods

- **Design:** 2016-01-04 to 2023-06-30 (crypto: 2018-01-01 to 2023-06-30). All selection happens here.
- **Sealed test:** 2023-07-01 to 2026-10-16 (crypto to 2026-09-30). The code refuses to compute any result in it
  unless run with the explicit unlock, which happens once, only when the owner asks, for the frozen finalists.
  Disclosure: the Qullamaggie-style stock books of phases 1-7 and v10-v13 were judged on 2021-2026, so the sealed
  window is not new for the family-A ideas that resemble episodic pivots (A1-A5); it is new for everything else.

## 3. Costs (selection always uses the middle scenario; low and high are reported)

- **Stocks, per side:** half-spread by raw price: < $2: 0.75%, $2-5: 0.40%, $5-10: 0.20%, $10-20: 0.10%, >= $20:
  0.05% (low x0.5, high x2), plus $0.005 a share commission. Fills at the trigger price or worse: a stop entry
  fills at max(trigger, bar open) for longs (min for shorts); a stop exit at min(stop, bar open) for longs (max for
  shorts). A bar gap of 5 or more minutes in the session is a halt: nothing fills inside it.
- **Short borrow:** low: no locate fee, 20% a year overnight; middle: locate fee 0.5% of notional per trade when the
  raw price is below $10, 50% a year overnight; high: locate 1.5% below $10 and 0.5% otherwise, 150% a year, and no
  short at all when the raw price is below $2 or the shares outstanding are below 10 million or unknown.
- **Short-sale restriction:** if the price is 10% or more below the prior close, a short fills only on a minute
  whose close is above the previous minute's close (within 15 minutes, else no trade).
- **Crypto:** 0.10% fee and 0.05% slippage per side. **ETFs:** 0.02% per side.
- **Size limits:** an assumed $100,000 account; a stock position is at most 2% of that stock's dollar volume traded
  that day before the entry minute (intraday) or 1% of its 20-day average dollar volume (swing).

## 4. Sizing (fixed, not searched)

- **Intraday stock families:** risk 0.5% of equity to the stop, at most 20% of equity per position, at most 5
  positions a day (priority: earliest entry, then the larger gap), gross at most 100%.
- **Swing stock families:** 5% of equity per position, at most 20 open, gross at most 100%.
- **ETF and crypto families:** as each rule says, gross at most 100%, no leverage.

## 5. Hypotheses (each line is one family; the grid is the product of the listed values)

Regular session minute 0 = 09:30. "OR k" = the high and low of the first k minutes. VWAP from 09:30. Price band of
families A and B: raw open $1-$20. PMV = premarket dollar volume (04:00-09:29, known at the open).

**A. Small caps, long, intraday (exit at the stop or the close; "VWAP" exit also leaves when a bar closes below VWAP
after 5 minutes in the trade)**
- A1 `GAPGO`: gap >= {20, 40, 80}%; buy the break of OR {1, 5, 15}; stop OR low; exit {close, VWAP}; PMV >= {$250k,
  $1M}. 36.
- A2 `PMHIGH`: gap >= {20, 40, 80}%; buy the break of the premarket high after the open; stop the session low so
  far; exit {close, VWAP}; PMV {$250k, $1M}. 12.
- A3 `VWAPPB`: gap >= {20, 40, 80}%; after 09:45, buy the close of the first bar that touched VWAP and closed above
  it; stop the session low so far; exit {close, VWAP}; PMV {$250k, $1M}. 12.
- A4 `DAY2`: prior day +{50, 100}% with its close in the top {25, 10}% of its range; buy the break of OR {5, 15};
  stop OR low; exit {close, VWAP}. 16.
- A5 `LOWFLOAT`: as A1 with gap {20, 40}%, OR {1, 5}, exit {close, VWAP}, shares outstanding < {10, 20} million. 16.
- A6 `HALTUP`: gap >= 20%; after a halt preceded by a rise of {10, 20}% in the 5 minutes before it, buy the first bar
  after it if it opens above the last close before it; stop that last close; exit {close, VWAP}. 4.
- A7 `GAPDOWN`: gap <= -{20, 35}%; buy the break of OR {5, 15}; stop OR low; exit {close, VWAP}; PMV {$250k, $1M}.
  16.

**B. Small caps, short**
- B8 `GAPFADE`: gap >= {30, 50, 100}%; short on {break of OR 5 low, break of OR 15 low, first close below VWAP after
  having been above}; stop the session high so far; exit {close, VWAP (cover when a bar closes above VWAP)}; PMV
  {$250k, $1M}. 36.
- B9 `LATEFADE`: at {15:00, 15:30}, price >= prior close x (1 + {40, 80}%), {below VWAP required, not required};
  short; stop the session high; cover at the close. 8.
- B10 `OVERNIGHT`: whole daily universe, raw close $1-$20; short at the close after a day of +{40, 80, 150}% with
  the close in the bottom {50, 100}% of the day's range; cover at the next open. 6.
- B11 `FIRSTRED`: after a rise of {100, 200}% within 3 days, short the first day that {opens below the prior close
  (at the open), breaks the prior day's low (at that low)}; hold {1, 5} days; stop the highest high since the
  rise began. 8.
- B12 `FADE`: short the next open after a day of +{50, 100}%; hold {5, 10, 20} days; stop {50, 100}% above entry. 12.
- B13 `DILUTION`: short the next open after an offering filing (424B, S-1, S-3, F-1, F-3) dated within {5, 20} days
  after a day of +50% or more {required, not required}; hold {5, 20} days; stop 50% above entry. 8.
- B14 `DELIST`: short the next open after an 8-K with item 3.01; hold {5, 20, 60} days; stop 50%. 3.

**C. Larger stocks, intraday and events**
- C15 `INPLAY` (after Zarattini and Aziz): stocks in play, relative volume of the first 5 minutes (against the
  20-day average volume / 78) ranked, the top {5, 20}; direction of the first {5, 15}-minute bar; enter on the break
  of its high (long) or low (short); stop {10% of the 14-day ATR, 25% of it, the opposite side of the bar}; exit at
  the close; sides {both, long only}. 24.
- C16 `IDXMOM`: SPY, QQQ, IWM, or the three equally: if the return from the prior close to 10:00 is beyond +-{0, 0.25,
  0.5}%, trade 15:30-16:00 in its direction. 12. And the "noise area" breakout: bands at the open +- the 14-day
  average absolute move from the open to each minute; long above, short below, checked every {30, 60} minutes, stop
  at the band or VWAP, flat at the close; SPY or QQQ. 4.
- C17 `LETFFLOW`: if SPY's or QQQ's return from the prior close to 15:30 is beyond +-{0.5, 1, 2}%, trade 15:30-16:00
  in its direction. 6.
- C18 `NIGHT`: buy the close and sell the next open: SPY, QQQ, IWM always (3); the same only after a day of -{1,
  2}% (6); small caps ($1-$20) after a day of -{20, 40}% (2). 11.
- C19 `PEAD`: price >= $5, 20-day dollar volume >= $5M; surprise = (EPS of the quarter - EPS a year earlier) / prior
  close, event day = the first 8-K item 2.02 within 60 days after the quarter end, else the 10-Q date; long the next
  open when the surprise is in the top decile of the trailing year's events, {and short the bottom decile, long
  only}; {any gap, the event-day gap agrees}; hold {20, 60} days. 8.
- C20 `INSIDER`: at least {2, 3} distinct insiders buying in the open market within 10 days for at least {$100k,
  $500k} in total; long the next open after the last filing; hold {20, 60} days; price >= $1, dollar volume >= $1M. 8.
- C21 `ACTIVIST`: long the next open after an SC 13D; hold {20, 60} days; price >= $2, dollar volume >= $1M. 2.
- C22 `RUSSELL`: estimated market cap (shares outstanding x price) ranked on the last trading day of April; long the
  predicted additions (rank 1001-3000 now, not in that range a year earlier) from {that day, the first trading day of
  June} to {the reconstitution day (last Friday of June), 5 days after}. 4.

**D. ETFs, volatility and calendar (total-return prices)**
- D23 `VIXTERM`: hold SVXY when the prior close's VIX/VIX3M is below {0.90, 0.95, 1.00} {and VIX < 20, no extra
  condition}, else cash {or VIXY when the ratio is above 1.05}. 12.
- D24 `FOMC`: long {SPY, QQQ} from the prior close to {the close, 14:00} of each scheduled FOMC statement day (4);
  long SPY from the close {1, 4} days before month end to the close of the third day of the new month (2). 6.
- D25 `MONTHEND`: when SPY's month-to-date return exceeds TLT's by more than {2, 4}% five days before month end,
  {short SPY and long TLT, hold cash instead of SPY} for the last 5 days (and the reverse when TLT leads). 4.
- D26 `SECTORS`: the 11 sector SPDRs, top {2, 3} by {63, 126, 252}-day return, monthly, {only when SPY is above its
  200-day average, always}. 12.

**E. Crypto (liquid = 30-day median quote volume >= $10M; long only, spot)**
- E27 `CTREND`: per coin, {the 20/50/100-day average ensemble, 14-, 28-, 56-day momentum above cash}, the {10, 30}
  most liquid coins, weight min(1, 30% / 30-day volatility) / N. 8.
- E28 `CXMOM`: the top {3, 5, 10} liquid coins by {7, 14, 28}-day return, weekly, {only when BTC is above its 50-day
  average, always}. 18.
- E29 `CHOURLY`: BTC and ETH, hold when the {24, 72, 168}-hour return is above zero, checked every {4, 24} hours. 6.
- E30 `CCALENDAR`: BTC held {only Friday close to Monday close, only the other days} (2); BTC and ETH dropped for 3
  days when the 3-day average funding rate exceeds {0.03, 0.05}% per 8 hours, {to cash, to a short perpetual} (4).
  6.

Total: about 350 configurations; every one counts as a trial for the deflated Sharpe.

## 6. Placebos

For every configuration, 200 placebo runs with the same days, the same number of trades a day, the same direction
and exit rule: intraday and swing stock families draw the traded stocks at random from the family's scope that day
(intraday entries at the real trade's minute); ETF and crypto families shift their signal by a random 60-500
sessions. The placebo p-value is the share of runs whose design Sortino is at least the configuration's.

## 7. Selection and combination

1. Each configuration's daily returns, 2016-01-04 to 2023-06-30, middle costs.
2. **Family walk-forward:** for each year Y from 2018 to 2023 (2023 to June), using only data before Y, each
   configuration's score is the smaller monthly Sortino of the two halves of its training window (capped at 20), its
   plateau score the mean over itself and its one-step neighbours; Y is traded with the best plateau score. The
   stitched record 2018-01-01 to 2023-06-30 is the family stream.
3. **Family gate:** the family stream's monthly Sortino >= 1.0, and the configurations it chose in at least two
   thirds of its years have a placebo p-value <= 0.05.
4. **Combination:** each year, the families that passed the gate on data before that year and whose stream's trailing
   training Sortino is >= 1.0, inverse-volatility weights from the trailing 252 sessions, at most 35% each; stitched
   2018-01-01 to 2023-06-30 = `COMBO`.
5. **CPCV and PBO** over the design period (10 blocks, 252 splits) for each family and for the combination.
6. **Deflated Sharpe** over all configurations of v14 plus every earlier trial.

## 8. Success criteria

- **Design:** `COMBO` monthly Sortino >= 4 over 2018-01 to 2023-06, >= 3 in both 2018-2020 and 2021-2023H1, PBO
  below 20%.
- **Sealed test** (once, when the owner asks): the frozen finalists (each passing family's configuration chosen on
  all design data, and `COMBO` with weights from the last 252 design sessions) on 2023-07-01 to 2026-10-16:
  Sortino >= 4 = success, 3-4 = promising, below 3 = failure.
- Reported for everything: Sortino, CAGR, maximum drawdown, total, profit factor where trades exist, every year, the
  three cost scenarios, placebo p-values, PBO, deflated Sharpe.

## Amendments while writing the code (2026-10-20, before any v14 result was computed)

1. **Daily-bar shorts and the short-sale restriction:** a short opened at a daily open 10% or more below the prior
   close pays 0.5% more (the minute rule applies only to the intraday families).
2. **C16 noise area:** at each check, long when the price is above the upper band and above VWAP, short below the
   lower band and below VWAP, otherwise flat. Its placebo flips the sign of each day at random (its position is
   decided within the day, so it cannot be shifted).
3. **D25:** the two variants are {short the leader and long the laggard, 50% each; long the laggard only}.
4. **D24 turn of the month:** held over the last {1, 4} sessions of each month and the first 3 of the next.
5. **E30 funding:** the short leg is a short perpetual: minus the spot return plus three times the day's mean
   funding rate.
6. **Combination, year Y:** a family enters if the configuration its walk-forward picks for Y has a plateau score
   of at least 1.0 and a placebo p-value of at most 0.05, both on months before Y. (This replaces "passed the gate
   on data before that year and trailing Sortino >= 1.0", which needs a stream history before 2018.)
7. **PBO of the combination:** in each of the 252 CPCV splits, every family's best plateau configuration on the
   training blocks enters if its training score is at least 1.0, with inverse-volatility weights (cap 35%) from the
   training months; the combination's test Sortino is ranked among the test Sortinos of all configurations; PBO =
   share of splits where it ranks below the median.
8. Crypto families start their walk-forward in 2019 (a year of training is needed from 2018). The intraday and swing
   stock families use the symbols that had a price of $1 or more and a dollar volume of $1M or more on at least 5
   days; B10 and the small-cap part of C18 use the day's own close and dollar volume (known at the close they trade).
