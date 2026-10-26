# v42: a long small-cap sleeve beside v39's best book: pre-registration

Written and committed on 2026-10-26, before any v42 result was computed, at the owner's request (idea 2 after v41:
a long sleeve that gains when the shorts lose). Code: `scripts/run_v42.py`, tests `tests/test_v42.py`, workflows
`v42-canary.yml`, `v42.yml`.

The base book's worst stretches (-45% around May 2026, -41% around June 2020) are small-cap euphorias, when run-ups
keep running. v40 showed that skipping shorts then loses more than it saves. v42 asks the other question: does a
long sleeve that buys small-cap momentum, in the same account, raise the book's growth or cut its worst stretches?

## 1. The base book

v39's DS1 20%, RU 70%, NS 40%, ON1 out, exactly as in v40 and v41 (v31's liquidation at 15%; TradeZero International
costs, base locates HTB 1% / HOT 3%; $6 a month). Its trades are fixed.

## 2. The long rules

All on v28's base universe (valid, dollar volume >= $500,000 that session), price >= $1, signals at the close of
session `t`, bought at that close (v19's "close" entry: costs, slippage and the 1% of dollar volume limit as for
every v19 trade; no locate). At most 3 longs a session, the biggest day gains first. In the account the longs rank
behind every short (they only take room the shorts leave), one position a symbol.

| rule | signal at the close of `t` | exit |
|---|---|---|
| `breakout` | close above the highest close of the 20 sessions before; dollar volume >= 2 x its 20-session mean before; up >= 5% on the day; close in the top 25% of the day's range | close under the 10-session mean (v19's `ma10`), stop 10%, at most 20 sessions |
| `burst` | up >= 10% on the day; dollar volume >= 3 x its 20-session mean before; the session before had a range (high / low - 1) no larger than the 20-session mean range before it | after 3 sessions, stop 8% |
| `follow` | up >= 50% over 5 sessions; close at or above the highest close of the 5 sessions before; close in the top 25% of the day's range | a close under the prior session's low (v19's `weak`), stop 15%, at most 5 sessions |

| dimension | values |
|---|---|
| rule | breakout, burst, follow (3) |
| gate | always; only when the count of base names up x2 or more in 5 sessions, at the session before `t`, is at or over its 80th percentile of the 252 sessions before (v40's `runners` flag) (2) |
| size | 5%, 10%, 15% of equity a long (3) |

3 x 2 x 3 = 18 variants plus the base book: **19**.

## 3. The walk-forward choice

As v41: every variant's daily returns at the $10,000 level at base costs; for each year Y from 2019, among the
variants (the base book included) whose worst yearly drawdown before Y is no worse than the base book's, the one with
the highest log growth summed over the years before Y. 2018 trades the base book.

## 4. The question

Both books on v29's 4,000 one-year bootstrap paths from $5,000 (ruin = at or under $1,250 at any time), at base
costs, HOT 5%, spreads x2 and the high costs, and on the historical path at the $10,000 level. **v42 improves the
book if (a) or (b) holds:**

(a) growth, as v41: walk-forward median on all paths >= 1.10 x the base book's; ruin <= 2.5% at base costs and at
HOT 5%; median at the high costs >= the base book's; median on the 2023+ paths >= the base book's.

(b) hedge: walk-forward median on all paths >= the base book's; ruin no higher than the base book's at base costs
and at HOT 5%; and on the historical path both the worst 21-session return and the maximum drawdown at least 5
points better than the base book's.

Reported too: the picks; every fixed variant (in-sample, labelled so) with its sleeve alone and the sleeve's mean
return on the base book's worst 5% of sessions. The base book must reproduce v39 ($23,143, ruin 0.1%).

## 5. Caveats fixed now

Same years as v40 and v41. The base book was chosen on all years. The long side uses the same daily small-cap data
as the shorts, entered at the close the signal is computed on (a market-on-close order placed minutes before). v24's
one-minute longs failed alone; here the sleeve does not need to win alone, only to help the book.
