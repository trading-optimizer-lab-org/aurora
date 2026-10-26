# v37: new daily small-cap members: pre-registration

Written and committed on 2026-10-26, before any v37 result was computed, at the owner's request ("si" to v36 B:
look for new, independent daily members to reach a one-year median of $30,000 with ruin at most 2.5%). Code:
`scripts/run_v37.py`, tests `tests/test_v37.py`, workflow `v37.yml`.

## 1. Three new daily short families (FREE plan: daily bars only)

Every setup uses only the setup day's and earlier daily bars; the entry is at the next open ("open") or at the
next open after the first red session ("redclose", v19's trigger); a symbol enters a family at most once in 20
sessions; base filter: valid and 20-day dollar volume >= $500k (v28's), price band low ($1-5) or high ($5-20).

- **C:FRD_SHORT** (first red day of a runner): the prior close at least (1 + x) times the lowest close of the w
  sessions before it, the prior session green (close above its prior close), the setup session red (close below
  the prior close). x in {50, 100, 200%}, w in {3, 5, 10}.
- **C:ROT_SHORT** (float rotation): the setup session's volume at least r times the shares outstanding and its
  close at least 20% over the prior close (v28's rot1 inputs). r in {1, 3, 5}.
- **C:BOUNCE_SHORT** (dead-cat bounce): the highest close of the 20 prior sessions at least twice the lowest
  close of the 40 sessions before the setup, the prior close at most 60% of that high, and the setup session up at
  least b. b in {20, 40%}.

Exits by the shield (v26/v28): hold d1/d2/d3/d5/d10; stop own (none), pct20, pct35, pct50, atr4; no extended-session
stop (FREE). 9 + 3 + 2 = 14 parameter sets x 2 bands x 2 triggers x 5 holds x 5 stops = **1,400 configurations**.

## 2. Selection (unchanged machinery)

Each configuration alone in A1's account at 20% (v33's real stage, TradeZero costs, base locates); per family and
year, v22's walk-forward pick on earlier years only (v14 plateau score, eligibility 50 trades and a trade in 40% of
earlier months). No pick in a year: the family is out that year.

## 3. The account and the question

Books: member base {v34's limit members (all), without ON1 and SYMPATHY} x size {25, 30%} x new members {without,
with the year's picks of the three families} = 8 books; A1's account otherwise (move order, 3 new and 20 open, gross
2x, $2.50 floor, v31's liquidation at θ = 15%), v29's 4,000 one-year bootstrap paths from $5,000, ruin = at or
under $1,250 at any time.

**Choice**: on paths drawn only from 2018-2022 sessions, the highest median among books with ruin at most 2.5%
there. **The target is met if that book's median on all paths is at least $30,000 with ruin at most 2.5%.**
Reported: every book on all / 2018-2022 / 2023+ paths and at HOT 5%, spreads x2 and the high costs; each new
family's walk-forward picks and its monthly Sortino alone.

## 4. Caveats fixed now

All three families are small-cap shorts after a rise, like DS1/RU: they may not be independent. Shares outstanding
come from filings and may lag. The members without ON1/SYMPATHY were suggested by v35's all-years diagnostic.
2023-07+ is not clean; locates assumed; DSR 0.
