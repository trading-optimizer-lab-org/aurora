# v30: $5,000 in one account, or $2,500 at full risk with a $2,500 reserve: pre-registration

Written and committed on 2026-10-24, before any v30 result was computed, at the owner's request: compare two ways of
running the TradeZero small-cap shorts with the same $5,000 budget. **A**: one $5,000 account run normally. **B**:
a $2,500 account run at the highest risk, and if it is lost, a second $2,500 deposited from a reserve; the owner's
aim is to avoid the tail losses. The trades, costs and books are v29's FREE plan ([V29_PREREGISTRATION.md](V29_PREREGISTRATION.md),
[V29_RESULTS.md](V29_RESULTS.md)) unchanged: v30 changes only how the money is managed. Code: `scripts/run_v30.py`
(on `scripts/run_v29.py`), tests `tests/test_v30.py`, workflows `v30.yml`, `v30-canary.yml`.

## 1. Accounts

- TradeZero International needs $500 of equity to use margin (its support page), and shorts need margin. So an
  account whose equity ends a session under $500 stops trading (frozen); its equity, whatever it is, stays in the
  result.
- A session's loss is **not** capped at the equity: a short can lose more than the account, and a negative equity is
  a debt owed to the broker (v29 stopped a path at zero; v30 keeps the debt).
- **A**: one account from $5,000.
- **B**: one account from $2,500; the other $2,500 waits outside. The first time the account ends a session under
  $500, the reserve is deposited (paying any debt first): equity + $2,500. If that is still under $500 (a debt over
  $2,000), the account freezes. After the deposit, the next session under $500 freezes it for good. One deposit only.
- Everything else as v29: equity levels $2.5k/$5k/$10k/$25k/$60k (the level at or below the equity, the $2.5k level
  below it), fixed costs $6 a month while the account trades, base locates HTB 1% / HOT 3%, middle spreads.

## 2. What is measured

- **Total wealth** W = the account's equity + the reserve not deposited ($2,500 in B if never used, else 0; 0 in A).
  Both start at W = $5,000.
- Paths: v29's 4,000 one-year stationary block-bootstrap paths (mean block 20, seed 29) of the 2018+ walk-forward
  stream; also 4,000 three-year paths (seed 30), reported.
- For each path set: median, mean, p10, p90 of W; the chance of W under $5,000, of W at or under $1,000 (losing 80% of
  the budget or more), of W at or under $500, of W under 0 (a debt); the mean of the worst 5% of W (tail); the
  worst W; in B the chance the reserve is deposited.

## 3. Books compared

- **A1**: v29's FREE choice (risk 2%, cap 20%, at most 20 open, 3 new a session, gross 2x, floor $2.50, the no-night-HOT
  rule off, locate gate off), as approach A.
- **B_max**: the literal maximum of v29's grid (risk 4%, cap 40%, 20 open, 5 new, gross 2x, no floor, both rules
  off), as approach B.
- **B_best**: the book of v29's FREE grid (2,304 books) with the highest one-year median W under B, with no risk
  limit (the owner's "risk the maximum"); ties go to the lower chance of W at or under $1,000.
- Also reported: **B_A1** (A1's book under B), **A_max** (B_max's book under A), **A_best** (the highest one-year
  median W under A, no risk limit).

## 4. The question, decided now

The owner's B is better than A if **B_best against A1**, one year: a higher median W, **and** a smaller tail (a
higher mean of the worst 5% of W), **and** no higher chance of W at or under $1,000. Each of the three is reported;
the claim "B avoids the tail" holds only if the last two hold.

## 5. Battery (A1, B_best, B_max, B_A1)

HOT locates 5% and 8%; the high costs (spreads x2, borrow x3); the three-year paths.

## 6. Caveats fixed now

v29's caveats hold (the construction chosen on the stream it is measured on, DSR 0, locates as a grid, 2023-07+ not
clean). Below $2,500 the $2,500 level's books are used, so share rounding and the $0.49 commission minimum are
milder than they would be at $500-2,500. A frozen account's debt is the session's loss as computed; a real broker
might close positions earlier or later.
