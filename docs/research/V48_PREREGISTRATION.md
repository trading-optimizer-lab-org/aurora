# v48: per-name sizes judged on an ensemble of trade sets: pre-registration

Written and committed on 2026-10-30, before any v48 return was computed, at the owner's request after
RUINA_SOLUCION_ES.md. Code: `scripts/run_v48.py`, tests `tests/test_v48.py`, generator `scripts/gen_v48_wf.py`,
workflows `v48-canary.yml`, `v48.yml`.

## 0. Why

v47d and v48d showed that the book's 0.1% ruin rests on luck. Each trade enters at
`min(member size, 1% of the prior day's dollar volume / equity)`: DS1 0.20, NS 0.40, RU 0.70 of equity in one name.
At RU 0.70 the 2.0 gross cap holds about two RU positions, so the account takes 72 of 230 RU candidates, and which
ones depends on the calendar. The 72 taken have no trade under -50%; the 230 candidates have 5.2% under -50% and
1.3% under -100% (worst -187%). Small changes in which trades fill let the catastrophes in, and ruin moves to 6-10%.
v32-v39 chose the sizes on that one lucky trade set.

v48 asks whether smaller sizes per name, with more names, keep the growth and remove the single-trade ruin, judged
on many trade sets instead of one.

## 1. The engine

v47's engine unchanged: v43's minute replay and central realism case (`next_open` fills, 10% of a bar's volume,
liquidation at `next_vwap`, closing-auction entries and exits), TradeZero International costs, v29's bootstrap
(4,000 one-year paths from $5,000; ruin at or under $1,250; the same paths for every book and seed) at the five
levels and from $2,000, gross cap 2.0, at most 20 open positions.

## 2. The ensemble

Seed 0 is the historical trade set. Seeds 1-30 each drop every candidate trade with probability 10%, fixed by the
seed, the symbol, the entry session and the member, and rebuild the account. This changes which trades fill, as
missed days, refused locates and timing do in practice. For each book and cost set: the mean over the 31 seeds of
the bootstrap median and of the ruin, and the 90th percentile of ruin over the seeds. The cost sets base and HOT 5%
get the ensemble; spreads x2 and high get seed 0 only.

## 3. The grid (126 books)

| dimension | values |
|---|---|
| RU size | 0.70, 0.50, 0.40, 0.30, 0.25, 0.20, 0.15 |
| NS size | 0.40, 0.30, 0.25 |
| DS1 size | 0.20, 0.25, 0.30 |
| new positions a day | 3, 5 |

The size is each trade's cap; the 1% of dollar volume cap stays. The base book is RU 0.70, NS 0.40, DS1 0.20, 3 new a
day.

## 4. The choice (on 2018-2022 paths only)

A book is eligible when its ensemble mean ruin on 2018-2022 paths is at most 2.5% at base costs and at HOT 5%. The
choice is the eligible book with the highest ensemble mean median on 2018-2022 paths. If none is eligible, there is
no choice and Q1 fails.

## 5. The questions and the pass marks

- **Q1 (the fix works)**: the choice, on all paths, has ensemble mean ruin at most 2.5% at base costs and at HOT 5%;
  ensemble mean median at least the base book's on all paths and on 2023+ paths; and summed log growth at $10,000
  positive on both symbol halves (seed 0).
- **Q2 (descriptive)**: every book's ensemble and seed-0 numbers.
- **Q3 (operable)**: the choice and the base book under v47's API rules (TZA: close entries decided at 15:50 and
  entered at market at 15:55, close covers at market at 15:55, locate $0.01 / $0.03 a share, no trade under $0.50, no
  entry under the short-sale price test), with the same ensemble. The choice passes Q3 when its ensemble mean ruin
  is at most 2.5% at base costs and at HOT 5%.
- **Checks**: the base book at seed 0 reproduces v47's base ($22,006, ruin 0.1%) within $200 and 0.2 points, and
  its TZA at seed 0 reproduces v47's TZA ($20,742, ruin 5.9%) within $300 and 0.5 points.

## 6. Caveats fixed now

- Every year 2018-2026 has been seen. The 2018-2022 choice and the 2023+ check reduce, not remove, the selection.
  Earlier studies (v32-v39) already searched sizes on these years.
- The 10% dropout is one model of which trades fill. It does not model new kinds of squeezes.
- Correlated squeeze days (June 2020, February 2024) stay as history had them; the bootstrap resamples 20-session
  blocks, so it keeps them together.
- The TradeZero 2:1 rule at 15:45 is measured in v47, not enforced.
