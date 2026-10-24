# v31: v30 with the broker's forced liquidation: pre-registration

Written and committed on 2026-10-24, before any v31 result was computed and while v30 was still running, at the
owner's request. v30 ([V30_PREREGISTRATION.md](V30_PREREGISTRATION.md)) lets a short keep losing for days past its
size, with no broker stepping in: its worst trade (a short held through a run-up, -474% of the position) would be
about -190% of a $2,500 account at risk 4% and cap 40%. A broker closes an account long before that unless the price jumps
overnight or through a halt. v31 adds that forced liquidation and asks v30's question again. Code:
`scripts/run_v31.py` (on `scripts/run_v30.py`), tests `tests/test_v31.py`, workflows `v31.yml`, `v31-canary.yml`.

v31 does not use any v30 result: it computes its own grid, choice and battery. Its workflow waits for v30's run
(40120558984) to end, whether it succeeds or fails, then starts.

## 1. The liquidation rule

- TradeZero International publishes no threshold: it may close positions "at its discretion and without prior notice
  if your account poses a risk" (its support page). TradeZero America's published policy: if during the session the
  account's equity falls to 15% or less (of the positions' market value), it may buy in or liquidate the whole
  account. v31 uses that rule, θ = 15%.
- Each session, for the account's open positions: from the previous close (the entry on the entry day) each moves
  to the session's open, then to its adverse extreme (the high for a short, the low for a long), **all at the same
  moment** (the worst case for the account: daily bars cannot order the moves). A position that leaves within the
  session (stop, target, open exit) goes to its exit price instead of the extreme.
- Equity and market value are in units of the session's starting equity: equity = 1 + the positions' gains so far
  that session; market value = the sum of each position's entry weight x price / entry price.
- If at the open equity <= θ x market value, everything is closed at the open. Else, if at the worst moment equity
  <= θ x market value, everything is closed at the point between the open and the worst moment where equity =
  θ x market value (prices moving in a straight line). The session's return is then that equity - 1.
- The closed positions' later sessions drop out. No new position takes their place (the account's limits stay as
  in v30). The forced close costs nothing beyond the trades' own costs.

## 2. Unchanged from v30

Accounts A ($5,000) and B ($2,500 + one $2,500 reserve deposit), the $500 freeze, losses past the equity kept as a
debt, total wealth W, the 4,000 one-year (seed 29) and three-year (seed 30) bootstrap paths, the statistics, v29's
FREE grid (24 cells, 2,304 books) at the five equity levels, the books A1, B_max, B_best, A_best and their choice
rules, and the question: **B is better than A if B_best against A1, one year, has a higher median W, a higher mean
of the worst 5% of W and no higher chance of W at or under $1,000; "B avoids the tail" holds only if the last two
hold.** All of it with the liquidation rule on.

## 3. Battery (A1, B_best, B_max, A_best)

HOT locates 5% and 8%; the high costs (spreads x2, borrow x3); θ = 30% (an earlier liquidation); the rule off (v30's
model, to show what the rule changes). Also reported for each book at the base costs: the forced liquidations in the
2018+ stream at the $2,500 and $5,000 levels, and the worst session with and without the rule.

## 4. Caveats fixed now

All extremes at the same moment overstates liquidations; closing at the exact threshold understates the loss in a
fast squeeze (θ = 30% shows an earlier close); halts are not in the data, so a halt that reopens far away is only
the next open's gap; the broker's real threshold is unknown and may differ. v29's and v30's caveats hold.
