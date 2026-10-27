# v44: new one-minute ideas on small caps (flow, filings and news by the minute, crypto, sympathy, statistics), the book's
meta-labels and execution, and their combination: pre-registration

Written and committed on 2026-10-27, before any v44 data was fetched and before any v44 return was computed, at the
owner's request ("pruebalo todo, hazlo mas grande, combinaciones e ideas", after the 30 ideas proposed on
2026-10-27). Every test runs on one-minute bars. Code: `scripts/run_v44_data.py`, `research/v44_stats.py`,
`research/v44_new1m.py`, `scripts/run_v44n.py` (part N), `scripts/run_v44m.py` (part M), `scripts/run_v44c.py`
(part C), tests `tests/test_v44.py`, workflows `v44-data.yml`, `v44-canary.yml`, `v44.yml`.

Not re-tested (already failed or already inside the book): v23's one-minute technical analysis, v24's long setups
and v25's mirror (incl. inferred halts without news, premarket-high breaks and fails, ORB), v28's daily event shorts
(EFFECT, PIPE, NT, sympathy on daily bars), v40's regime and calendar overlays, v43's stop, flat-time, cover, trail and
size rules. Real halt records (Nasdaq Trader) have no free history: halts stay inferred from the bars.

## 0. Data (v44-data)

| set | content | kept |
|---|---|---|
| news | Alpaca news (Benzinga): id, created_at, headline, symbols, for every symbol-day of the event (v14), liquid (v23), mover (v24) and new filing stores and of the book (v43), from 16:00 of the session before to 16:00, 2018-01 to 2026-10 | Actions cache |
| edgar | acceptance date-time, form and 8-K items of every filing of the forms of N2 by the companies of v14's ticker history, 2018+, from SEC's submissions bulk file | Actions cache |
| filing store | one-minute bars (Alpaca SIP, 04:00-15:59) of the symbol-days with a filing of those forms accepted from 16:00 the session before to 15:30, prior close $1-$20, prior 20-day dollar volume >= $0.5M, not already in a store; at most 150 a day by dollar volume; built with v23's store builder | Actions cache |
| index | SPY and IWM one-minute bars, 04:00-19:59, 2018+ | Actions cache |
| btc | BTCUSDT one-minute klines (data.binance.vision; Coinbase BTC-USD candles if unavailable), 2018+ | Actions cache |
| ticks | for each distinct trade of the book (v43's trades), the Alpaca SIP trades of its entry session 04:00-16:00 and its quotes from 15 minutes before to 30 minutes after the entry (open entries 09:15-10:00, close entries 15:30-16:00), aggregated per minute: buy and sell volume (Lee-Ready against the quote midpoint inside the quote window, the tick rule elsewhere), intermarket sweep (condition F) volume, odd-lot (< 100 shares) volume, block (>= 10,000 shares or >= $100,000) volume, trade count; mean relative spread, mean depth imbalance (bid size - ask size) / (bid size + ask size), quote count. Raw ticks are not kept | Actions cache |

Times map to sessions: an event from 16:00 of session t-1 to 09:29 of session t is a **pre** event of session t;
from 09:30 to 15:59 an **intra** event at its minute; later, a pre event of the next session.

News classes (case-insensitive headline patterns, the first that matches): `priced` (priced/prices/pricing ...
offering), `offering` (offering, private placement, registered direct, at-the-market, warrant exercise or
inducement, shelf), `rsplit` (reverse split), `fda` (FDA, approval, approves, clearance, 510(k), breakthrough or
orphan designation, PDUFA), `trial` (phase 1-3, trial, topline, data readout, clinical), `merger` (merger, acquire,
acquisition, definitive agreement, buyout, takeover, tender offer), `contract` (contract, order, partnership,
agreement, collaboration, award), `earnings` (earnings, results, revenue, EPS, quarter, fiscal), `buzz` (bitcoin,
crypto, blockchain, ethereum, AI, artificial intelligence, quantum, treasury reserve), `buyback` (buyback, repurchase,
insider buying); else `other`.

## 1. Part M: the book's trades (v43's engine, central realism case)

The book is v39's DS1 20%, RU 70%, NS 40% replayed on minutes as in v43 (central case: stop and time exits at the
next bar's open, 10% of each bar's volume, liquidation at the next bar's VWAP, auction entries), base costs, the
$10,000 level. New dimensions:

| dimension | values |
|---|---|
| filter (meta-label at the entry) | none; skip the trade when one of the 26 features below is in its top or bottom tercile (52); a model trained each year on the trades before it (logistic regression on the 26 standardized features, or gradient boosting of depth 3, 100 trees), target net return > 0: skip when p < 0.4, skip when p < 0.5, or size x (0.5 + p) (6): **59** |
| entry trigger (open entries) | none; after the open, at the first of: T1 a lower high under VWAP after the session's high; T2 the 5-bar BVC flow imbalance below 0; T3 the first red bar after 3 or more green; T4 the steady-state Kalman velocity below 0; T5 a BOCPD change point with a lower new mean; T6 a break of the 5-minute opening range low; T7 a z-score to VWAP of 2 or more, then a red bar; T8 a 30-bar variance ratio under 0.8; waited at most 15, 30, 60 or 120 minutes; on timeout skipped or entered at the deadline: **65** |
| execution | the auction (as now); TWAP of 3 slices 5 minutes apart; TWAP of 5 slices 5 minutes apart; a passive sell limit at the ask (the quote when known, else the bar's close + its tier's half-spread), filled when a later bar's high trades above it within 5 minutes, else at the next bar's open: **4** |
| emergency exit (all held sessions, regular hours) | none; X1 5-bar BVC buy imbalance >= 0.6 or 0.7 with the price up >= 5% in 5 bars; X2 a BOCPD change point with a higher new mean (hazard 1/30 or 1/90) while in profit; X3 Kalman velocity above 1 or 2 of its standard deviations; X4 bar volume >= 5 or 10 times the session's median with a green bar of 3% or more; X5 a new session high 5% or 10% above the entry; X6 a z-score to VWAP of 3 or 4: **13** |
| locate | as now; HOT trades flat at 15:55 of the entry session; HOT and HTB trades flat at 15:55: **3** |
| partial | as now; half covered at the entry session's close (the rest follows the shield): **2** |

59 x 65 x 4 x 13 x 3 x 2 = **1,196,520 books**, plus the 1,300 pairs of tercile filters on two different features
(skip when both hold) x locate x partial with the other dimensions as now: **7,800**. The base rule is (none, none,
auction, none, as now, as now).

Features at the entry (open entries: the premarket bars 04:00-09:29 and the daily data before; close entries: the
session's bars to 15:49, since a market-on-close order is sent before 15:50): premarket or session dollar volume over
the prior 20-day average; premarket range; gap (open entries) or the day's move (close entries); distance to VWAP;
distance to the high so far; 30-bar BVC imbalance; mean trade size of the last 30 bars over the session's; rotation
(volume / shares outstanding); 30-bar realized volatility; 60-bar variance ratio; Kalman velocity; BOCPD change
probability over the last 15 bars; z-score to VWAP; news count over the prior 24 hours; an offering-type headline
(`priced`, `offering`, `rsplit`) in the prior 24 hours; a 424B, S-1 or S-3 filing in the prior 7 days; the day's count
of small caps gapping 20% or more over its trailing 60-day median; IWM's move from the prior close; BTC's 24-hour move;
SPY above its VWAP; and from the ticks: 30-minute Lee-Ready imbalance, sweep share, odd-lot share, block share,
relative spread and depth imbalance over the last 10 minutes. A missing feature keeps the trade (the models use the
median). Tercile cuts are those of the book's trades in the years before the trade's year; 2018 trades are never
filtered.

Walk-forward choice as v43: for each year from 2019, among the books whose worst yearly drawdown before it is no
worse than the base rule's, the highest summed log growth before it.

## 2. Part N: fifteen new one-minute families (run_v22's procedure)

Stores: event (v14), liquid (v23), mover (v24), filing (new). Every family is pre-registered as a grid; the
selection, the activity rule (50 trades, a trade in 40% of the months), the 500 placebos of each pick (each real
trade moved to a random candidate of its scope that day at the same minute, same stop distance and exit), the gate,
PBO, SPA, the deflated Sharpe ratio over all configurations and COMBO44 are run_v22's. Costs R4 (mid, low, high,
auction, gross) plus a **strict** case: stops filled at the crossing bar's extreme (slip 1.0, about v43's
`next_high`). Entries at the open of the bar after the signal bar (or a stop-type fill inside the signal bar for a
level break), one trade per configuration and symbol-day (the first signal), no entry after 15:00 except N5.

Shared dimensions: band `1-3`, `3-8`, `8-20` (open price); context `none`, `hot` (the day's count of small caps
gapping 20% or more at the open in the top third of its trailing 60 sessions), `cold` (bottom third), `news` (a news
item in the 24 hours before the entry), `nonews` (none); N1, N2 and N15 use only none, hot and cold. Stops `pctX`:
X% from the entry; `ext`: 1% beyond the day's extreme so far on the stop side.

| family | dimensions | configs |
|---|---|---|
| N1 `NW_NEWS` | class (any + the 10 classes), when (pre: entry at the open + delay; intra: the bar after the news minute + delay), delay 0/2/5 min, side long/short, move (none; `with5`: 5% or more in the side's direction from the reference by the entry; `against`: none or against), stop pct5/10/20, exit t5/t15/t30/t60/close/next_open/d3, scope any | 74,844 |
| N2 `ED_EDGAR` | form (424B, S-1/F-1 incl. amendments, S-3/F-3, EFFECT, 8-K items 1.01, 2.02, 3.01, 3.02, 5.02, 8.01, SC 13D, SC 13G, 6-K), when, delay 0/2/5, side, move (none, up 5%, up 20% from the prior close at the entry), stop pct5/10/20, exit as N1, scope any | 88,452 |
| N3 `BC_BTC` | stocks whose 60-session daily correlation with BTC is >= 0.3 or 0.5; BTC's k-minute return (k 1/5/15) beyond z = 2/3/4 of its standard deviation over the prior 5 sessions' regular-hour minutes; lag (any; the stock moved less than half of beta x BTC's move since the trigger), side with/against BTC, window first 60 minutes / all, stop pct3/5/10, exit t5/t15/t30/t60/close, scope liquid/any | 64,800 |
| N4 `SY_SYMPATHY` | peers = same SIC code (4, 3 or 2 digits) in any store that day; leader = the group's top gainer at that minute, up 20% or 40%; event: the leader makes a new session high, or closes under VWAP after being up; peer lagging (up < 10%) or running (>= 10%); side follow (long on a high, short on a VWAP loss) or fade; stop pct5/10/20; exit t15/t30/t60/close/d3 | 10,800 |
| N5 `LV_LEVETF` | at 15:30, 15:45, 15:50; IWM's move from the prior close beyond 0.5/1/1.5/2%; side with/against; beta (any; 60-session beta to IWM >= 1); same sign (any; the stock's day move has IWM's sign); exit close/next_open; stop pct5/10; scope liquid/any | 11,520 |
| N6 `ZV_ZSCORE` | clock time bars / volume bars (each 1% of the prior 20-day average volume); z = log(close / VWAP) over its standard deviation since the open or over the last 60 bars; z 2/3/4; confirm none / a bar against the extreme / a dry bar (volume under half the 10-bar mean); side fade the top (short) / fade the bottom (long); extension from the open 0 or 20%; stop pct5/pct10/ext; exit to VWAP/t15/t30/close/next_open; scope runner/mover_up/mover_dn/liquid | 129,600 |
| N7 `CP_BOCPD` | Bayesian online change point (Gaussian, run length up to 120) on one-minute log returns, hazard 1/30 or 1/120; change probability over the last 5 bars >= 0.3 or 0.6 with the new mean against the prior run; prior run from the open 10/20/40%; side fade (short after a rise, long after a fall); confirm none / VWAP crossed; stop pct5/pct10/ext; exit t15/t30/t60/close/d3; scope gapup/runner/mover/liquid | 43,200 |
| N8 `HU_FRACTAL` | measure: variance ratio VR(5) over 30 or 60 bars (under 0.8 / 0.6), or permutation entropy of order 3 over 60 bars (over 0.95 / 0.98), after a run of 10/20/40% from the open; side fade/follow; confirm none / a bar against the run; stop pct5/pct10/ext; exit t15/t30/t60/close/d3; scope gapup/runner/mover/liquid | 64,800 |
| N9 `KF_KALMAN` | steady-state Kalman (alpha-beta) local linear trend, q/r 0.001/0.01/0.1; signal: velocity sign flip, or velocity beyond 1 or 2 of its standard deviations against the run; run 10/30% from the open; side fade/follow; filter none/VWAP; stop pct5/pct10/ext; exit t15/t30/t60/close/d3/the opposite flip; scope gapup/runner/mover/liquid | 77,760 |
| N10 `LP_LPPL` (short) | stocks risen 40% or 80% from the prior close by the bars before; every 15 minutes a log-periodic power law fit over the last 60, 120 bars or since the open (grid of m 0.3/0.5/0.7, omega 6/9/12, critical time 5-60 minutes ahead, linear least squares for the rest); R-squared >= 0.85/0.95 and the critical time within 15/30 minutes; confirm none / a red bar; stop pct10/pct20/ext; exit t15/t30/t60/close/d3; scope runner/any | 21,600 |
| N11 `SS_SSR` | trigger: the short-sale rule set today (10% under the prior close) or carried from yesterday; setup long on the first green 5-minute bar after it, long on a VWAP reclaim, short on a lower high under VWAP after a 5% bounce, short on a new low after it; window first 60 minutes / all; stop pct5/pct10/ext; exit t15/t30/t60/close/next_open; scope mover_dn/gapdown/liquid/any | 14,400 |
| N12 `RO_ROTATION` | the session's volume over shares outstanding crosses 0.5/1/2/4; state: within 2% of the high, 10% or more under it, under VWAP; side; time before 11:00 / all; stop pct5/pct10/ext; exit t15/t30/t60/close/d3; scope gapup/runner/mover_up/liquid/filing | 54,000 |
| N13 `FB_FLOWBAR` | bulk volume classification on the bars (a bar's buy share = Phi(its price change / the session's standard deviation of price changes)); imbalance over 5/15/30 bars >= 0.3/0.5; pattern absorption (price moved < 1% over the window) / continuation (>= 3% with the flow); side with/against the flow; run 0/10/30%; stop pct5/pct10/ext; exit t15/t30/t60/close/d3; scope gapup/runner/mover/liquid | 64,800 |
| N14 `SQ_SQUEEZE` (long) | FINRA short interest over shares outstanding >= 10/20/30%; days to cover any / >= 3; rotation >= 0.5/1/2; trigger a new high after 10:00 / the 15-minute opening range high / a VWAP reclaim; stop pct5/pct10/VWAP x 0.99; exit trail10/t30/t60/close/d3; scope gapup/runner/mover_up/liquid | 48,600 |
| N15 `HN_HALTNEWS` | an inferred halt (no bar for 5+ minutes after a move of 10% or 15% over the 5 bars before), up or down; with or without news in the prior 24 hours; side; entry at the resumption bar / the first green (long) or red (short) bar after it; stop pct5/10/20; exit t15/t30/close/next_open; scope any | 3,456 |

Total **772,632 configurations**. The counts are the products of the listed dimensions with the shared band and
context dimensions; the code's registry must give the same numbers.

## 3. Part C: the combination in the $5,000 TradeZero account

The book (base rule, or part M's walk-forward book if it passes Q1) plus a sleeve of COMBO44's members of each year
(run_v22's rule: the pick's Sortino before the year >= 1 and its placebo p <= 0.05), each member's trades sized as v26
(risk to the stop, the cap, 2% of the dollar volume before the entry, five a day), TradeZero International costs at
the strict fills, the PAID plan ($105 a month) whenever the sleeve is on. The sleeve's size is (risk, cap) in (0.5%,
10%), (1%, 10%), (1%, 20%), (2%, 20%) or off, chosen each year by v43's walk-forward rule on the historical path at
the $10,000 level. v28's joint caps; the broker's 15% rule checked every minute on the book's trades and at the close
on the sleeve's (their intraday marks are not modelled).

## 4. The questions and the pass marks (v29's bootstrap: 4,000 one-year paths from $5,000; ruin = at or under $1,250)

- **Q1 (part M).** The walk-forward book improves the book if its median >= 1.15 x the base rule's, ruin <= 2.5% at
  base costs and at HOT 5%, its high-cost median >= the base rule's, and its summed log growth beats the base rule's
  on both symbol halves of the historical path (v28's halves).
- **Q2 (part N).** run_v22's family table and COMBO44 criterion (Sortino >= 4 from 2018, >= 3 in each half and in
  2023-07+, PBO < 20%), also reported at the strict fills. Reported too: each pick's returns on the two symbol
  halves.
- **Q3 (part C).** The sleeve improves the account if the walk-forward account's median >= 1.15 x the book alone's
  (both computed in part C), ruin <= 2.5% at base costs and at HOT 5%, and its high-cost median >= the book alone's.
- **Q4.** From $2,000 (ruin at or under $500): the book alone and the part C account. Descriptive.

## 5. Caveats fixed now

Every year 2018-2026 has been seen; the book was chosen on them; no window is clean, so the deflated Sharpe ratio,
PBO, the placebos and the symbol halves are the only guards. News coverage is Benzinga's through Alpaca and may be
thinner in early years; headline classes are keyword rules, not reading. EDGAR acceptance times are when SEC accepted
the filing, not when the market read it. SIC codes are today's. Short interest and shares outstanding are as v28.
BTC trades around the clock, the stocks only in their sessions. The tick features exist only for the book's trades.
TWAP is modelled as one entry at the last slice's minute at the slices' average price. The sleeve's intraday marks do
not enter the broker's check.

## 6. Implementation notes (added 2026-10-27 after the code review, before the full run and before any return on v44 data)

- BOCPD: a change point is a probability of 0.5 or more that the run began within the last five bars; T5 uses hazard
  1/30, the M feature `bocpd15` hazard 1/60.
- Close entries: TWAP slices cannot start before 15:50 (the decision), so TWAP 5 at the close has the same three
  slices as TWAP 3 (15:50, 15:55, the auction).
- Tercile filters use strict inequalities (above the upper cut, below the lower cut), so a binary feature flags only
  its rarer value; the models train on trades whose last session is before the year.
- "In the prior 24 hours" and "in the prior 7 days" are clock time from the decision minute.
- A filing-store symbol-day is in the universe only after its first filing of the N2 forms (8-K only with the listed
  items), in the real trades and in the placebo pool.
- run_v22's COMBO rule is used as is: a member's "Sortino before the year" is the pick's plateau score there.
- The strict-fill COMBO44 line uses the members' monthly strict returns with the middle-cost weights.
