# v43: v39's best book replayed on one-minute bars, and a large minute grid: pre-registration

Written and committed on 2026-10-27, after the data job (run 40461750579: trades and bar coverage only) and before
any v43 return was computed, at the owner's request: replay the best book on one-minute bars, measure how much the
daily model's fills, halts, thin minutes and the broker's liquidation flatter it, and search a large grid of minute
rules on at least 300 four-CPU runners. Code: `scripts/run_v43_data.py` (done), `scripts/run_v43.py`, tests
`tests/test_v43.py`, workflows `v43-data.yml` (done), `v43-canary.yml`, `v43.yml`.

## 1. The book and the data

v39's DS1 20%, RU 70%, NS 40%, ON1 out, exactly as in v40 to v42: the same trades (the same daily selection), v31's
liquidation at 15%, TradeZero International costs (base locates HTB 1% / HOT 3%), $6 a month.

The data job recorded, at the five levels ($2,500 to $60,000) and the four cost sets (base, HOT 5%, spreads x2,
high), every trade of the book (1,009 distinct, 20,180 rows, every one with its shield facts: entry, stop, hold,
scale-out, emergency level, target, limit entry, the daily exit), and Alpaca SIP one-minute bars, 04:00-19:59 ET, raw
prices, of every symbol-day from the entry session to the session after the exit: 4,927 symbol-days, 4,914 with bars
(99.7%), 3,102 with 300 or more of the 390 regular-session minutes. A minute without a bar is a minute without a
trade (Alpaca builds a bar only when there are trades): nothing fills in it. Minute prices are put on the daily
split-adjusted scale with the session's factor `F` (as v26's night stops).

A trade whose entry session has no bars (13 symbol-days) keeps its daily path; they are counted.

## 2. The minute replay

Each trade is walked minute by minute with the shield's own rules (v26 and v33): the entry, the stop, the stop live
in the after-hours and the next premarket where the trade's shield has it, the rally exit, the emergency cover at the
next open, the target, the scale-out at closes, the hold. What changes is only where each event happens and fills:

- **stop**: the first bar whose high reaches the stop (in the regular session; in the extended sessions where live);
- **opens and closes**: the 09:30 open and the 16:00 close are the auctions, filled at the daily open and close;
- **every other exit** (stops, emergency, rally, target, the new rules of section 4) fills by the realism case below;
- **liquidation**: the account is checked every minute from 04:00 to 19:59 on all open positions together, each
  marked at its last trade (carried through bar-less minutes): when equity falls to 15% of the positions' market
  value the broker covers everything, filled by the realism case; the account then waits for the next session.
  The day's equity starts from the last close, as in v31.

Costs: each trade keeps the daily model's whole cost (its first session's move before costs minus after, the locate
apart), charged on its first session; the spread x2 and high cost sets carry it. The minute replay adds only the
fills' own slippage. The share count of a trade is its weight x the account level / its raw price.

## 3. The realism cases (measured, not chosen)

| dimension | values |
|---|---|
| stop and intraday exit fill | `slip`: the daily model's rule on the bar (the bar's open if past the level, else level + 25% of the way to the bar's high); `next_open`: the open of the next bar after the one that crosses; `next_vwap`: its VWAP; `next_high`: its high (4) |
| participation | none; at most 20%, 10%, 5% of each bar's volume, the rest in the following bars at the same fill rule on each bar (4) |
| liquidation fill | `threshold`: interpolated at the 15% level, as v31; `next_vwap`; `next_high`, under the participation cap (3) |
| open entry fill | the 09:30 auction (the daily open); the first regular bar's VWAP (2) |

4 x 4 x 3 x 2 = **96 cases**. A gap of 5 or more regular minutes with no bar, followed by a bar that opens 10% or more
away from the last trade, is counted as an inferred halt (Alpaca does not mark halts); a fill after it is at the
reopening bar under every case except `slip`. **The central case**: `next_open`, 10% of volume, liquidation at
`next_vwap`, auction entry. The **daily-like case** (`slip`, no cap, `threshold`, auction) should come near v39's
book; its gap from v39 is reported.

## 4. The strategy grid (chosen by walk-forward)

| dimension | values |
|---|---|
| entry delay (open entries; a limit entry's order rests from then) | 0, 1, 5, 15, 30 minutes after 09:30 (5) |
| stop distance x | 0.75, 1, 1.25, 1.5, none (no stop; the emergency cover and the broker still act) (5) |
| flat time | the shield's hold (as now); covered at the close of the entry session; at 15:55; at 15:45 (a close entry: of the session after) (4) |
| intraday cover on a fall from the entry | none, 10%, 20%, 30% (4) |
| trailing stop | none; once the low is 10% under the entry, the lowest low x 1.10; the same at 20% (3) |
| size x | 0.75, 1, 1.25 (3) |

5 x 5 x 4 x 4 x 3 x 3 = **3,600 rules**; the shield's own rule is (0, 1, hold, none, none, 1). A delayed entry is at
the open of the first bar from the delay (or its VWAP in the VWAP entry case), its stop the same percentage away;
a trade that does not fill is dropped. Every rule changes only the exits and the entry minute; the account (v28's
joint caps, one position a symbol, the order) is rerun on the new returns.

**The grid**: 3,600 rules x 96 cases x 4 cost sets = **1,382,400 books**, each the full 2018-2026 book at the
$10,000 level, kept as yearly log growth and worst drawdown. Spread over 300 runners of 4 CPUs (two matrix jobs of
150), after a canary.

The walk-forward choice, as v41: within each realism case, for each year from 2019, among the rules whose worst
yearly drawdown before it (base costs) is no worse than the shield's rule's, the highest log growth summed over the
years before. 2018 trades the shield's rule. No smoothing.

## 5. The questions

Bootstrap: v29's 4,000 one-year paths from $5,000, ruin = at or under $1,250 at any time, at the four cost sets.

- **Q1, realism.** The shield's rule in the central case, base costs: **the book survives the minute replay if its
  median >= $15,000 and ruin <= 2%.** Reported for every case and cost set, and the daily-like case's gap from v39.
- **Q2, the grid.** In the central case: **the minute rules improve the book if** the walk-forward median >= 1.15 x
  the shield's rule's (both on minutes), ruin <= 2.5% at base costs and at HOT 5%, and the median at high costs >=
  the shield's rule's. Reported too for the other 95 cases (how often the choice beats the shield's rule), the picks,
  and the top fixed rules (in-sample, labelled so).
- **Q3, $2,000.** The central case's shield's rule and walk-forward book from $2,000 (ruin = at or under $500), with
  a $2,000 level added to the five (the same trades, whole shares). Descriptive, no pass mark.

Also reported: counts of stop fills after inferred halts, of fills cut by the participation cap, of liquidations,
and the worst fill seen.

## 6. Caveats fixed now

Same years as v40 to v42; the book was chosen on all of them on daily bars. There is no order book: thin markets are
approximated by the bars' volume and the next bar's prices. The auctions are filled in full at the daily prices. The
daily model's costs are kept per trade, not rebuilt per minute. The halt flag is inferred. The trades come from the
daily selection; a rule cannot add a trade the daily model did not take, only drop or change it.
