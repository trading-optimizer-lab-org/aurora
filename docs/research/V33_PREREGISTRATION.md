# v33: changing the FREE members themselves: pre-registration

Written and committed on 2026-10-25, before any v33 result was computed, at the owner's request ("pruebalo todo" on
four changes to the strategy itself, not the account). v32 showed the account construction of v29's A1 is at its
best; v33 changes the trades. Code: `scripts/run_v33.py` (on `scripts/run_v32.py`), tests `tests/test_v33.py`,
workflows `v33.yml`, `v33-canary.yml`.

## 1. Facts it starts from (v29, the $5,000 level)

- The FREE members are four short families of v28's B block, all on daily data: DS1 (v19 run-up), RU (v20 run-up),
  ON1 (v19 night short), NS (v20 night short), plus C:SYMPATHY in 2019 and 2021. 1,109 of 1,325 trades are HOT;
  HOT trades carry 96% of the profit. Of the 50 worst trades, 27 are DS1, 15 ON1, 7 NS, 1 RU.
- v28 picked each family's configuration every year on the earlier years, under R4 costs and a 0.5% locate, with no
  TradeZero commission rules. The account pays HOT 3% / HTB 1% locates and TradeZero International's fees.

## 2. The four changes

1. **Re-pick under the account's costs.** Every configuration of the four families in v28's grid with no
   extended-session stop (FREE has none; the others are identical under FREE): 5,775 DS1, 5,775 RU, 6,930 ON1,
   6,930 NS = 25,410. Each is scored as the family alone in A1's account at the $5,000 level: v29's sizing (risk 2%,
   cap 20%), TradeZero costs with base locates, the $2.50 floor, gross 2x, at most 20 open and 3 new a session, the
   move order, TradeZero International's margin; no liquidation rule in this scoring. Its monthly returns and trades
   go through v22's walk-forward selection unchanged (v14's plateau over one-step neighbours, at least 50 trades and
   a trade in 40% of the earlier months, picks for 2018 onward from the years before).
2. **Limit entries.** For a short entered at a session's open: a sell limit at the previous close x (1 + k), k =
   5/10/20%, resting from the open. An open at or above the limit fills at the open; else the session's high must
   reach the limit x 1.01 (a touch is not a fill) and the fill is the limit, charged as a session leg (the spread is
   still paid; no maker rebate). Not reached: no trade. Entries at a close are unchanged.
3. **Emergency exit.** At the first close at or beyond the entry x (1 + X), X = 50%/100%, against a short, cover at
   the next session's open (decided on daily data, so FREE can run it). It adds to the configuration's own stop.
4. **HOT night shorts.** For ON1 and NS: skip HOT trades (tier at the entry as in v29), on or off.

Changes 2-4 are **variants**: limit none/5/10/20% x exit off/50/100% x (ON1, NS) HOT skip off/on, 12 or 24 a
configuration. They are computed for every configuration that is a v28 pick or a change-1 pick, scored as in change
1, and the variant of a family in year y is the one with the best v14 score on the months before y among those
active enough (none: no variant, the configuration as it is).

## 3. Accounts compared

Each is A1's account (size 20%, move order, 3 new, 20 open, gross 2x, $2.50 floor, base locates, v31's liquidation at
θ = 15%, 4,000 one-year bootstrap paths from $5,000, ruin = at or under $1,250 at any time) with these members:

| arm | configurations | variants |
|---|---|---|
| A1 | v28's picks | none (v29's A1: its median must be $12,831) |
| repick | change 1's picks | none |
| limit | v28's picks | limit only, chosen each year |
| exit | v28's picks | emergency exit only, chosen each year |
| nohot | v28's picks | HOT skip for ON1/NS only, chosen each year |
| no_night | v28's picks without ON1 and NS | none |
| all | change 1's picks | all variants, chosen each year |

C:SYMPATHY stays as in v28 in every arm.

## 4. The question

**An arm raises the median if its median beats A1's at the base costs, on paths drawn only from 2023+ sessions, with
HOT locates at 5% and with spreads x2, and its chance of ruin at the base costs is at most 1%.** Among the arms that
pass, the one with the highest base median is v33's choice. Also reported for every arm: the 2018-2022 paths, the
high costs, p10/p90, -50%, loss, the mean of the worst 5% of paths, the forced liquidations at $5,000, trades and
HOT share at $5,000; for change 1, each family's yearly picks against v28's; for changes 2-4, the chosen variants.

## 5. Caveats fixed now

- All selections are walk-forward by year, so each year's members were chosen on earlier years only; but the grid,
  the four changes and the 2023+ test were designed by a researcher who has seen v28-v32 results on all years.
- The scoring stream is the family alone; the members then share one account.
- Limit fills on daily bars cannot see the order of the high and the fill; a fill reached only by a spike that also
  hits the stop is counted as stopped, as v19 counts an open entry.
- v29's, v31's and v32's caveats hold (locates and borrow assumed; DSR 0; halts only as the next open's gap).
