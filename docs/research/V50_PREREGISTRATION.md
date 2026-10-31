# v50: the size grid under TradeZero's costs and rules, and what each rule costs: pre-registration

Written and committed on 2026-10-31, before any v50 return was computed. The owner asked for a 100% yearly return
with realistic costs: a one-year median of $10,000 from $5,000. v49's answer is $8,498 with 0.0% ruin under TZC.
Code: `scripts/run_v50.py`, tests `tests/test_v50.py`, generator `scripts/gen_v50_wf.py`, workflow `v50.yml`.

## 1. Why this grid

v48 and v48b chose the sizes under TZA. Under TZC the ruin moves: RU 0.20 has 0.0% ruin, RU 0.25 has 7.1%. The
DS1 and NS sizes and the daily entry limit were never searched under TZC. The 2:1 rule caps the gross, so more size
only pays if it fills slots that sit empty.

## 2. The books (54)

DS1 0.20 / 0.30 / 0.40, NS 0.40 / 0.60 / 0.80, RU 0.15 / 0.20 / 0.25, at most 5 or 8 new positions a day.

## 3. The sets

Every set starts from v47's TZA rules on v43's minute replay with v48's 31-seed ensemble.

- **TZA**: v48b's rules.
- **TZC (the main set)**: v49's TZC, unchanged.
- **TZC-B2**: borrow rate doubled.
- **TZC-L0**: no failed locates.
- **TZC-L25**: locates fail on 25% of HOT and 5% of HTB entries.
- **TZC-T0**: the 2:1 rule not enforced.
- **TZC-V0**: close entries not capped by volume.

L0, L25, T0 and V0 only measure what each TZC rule costs. They never decide the answer.

## 4. The answer (decision rule fixed now)

Among the 54 books, keep those whose TZC ensemble mean ruin on all paths is at most 2.5% at base costs and at HOT 5%.
The answer is the one with the highest TZC ensemble mean median at base costs. The target is **MET** if that median
is at least $10,000. If no book passes, there is no answer.

## 5. Checks

DS1 0.20 / NS 0.40 / RU 0.20 / 5 under TZC reproduces v49: $8,498 and 0.0% ruin, within $200 and 0.3 points.

## 6. Caveats fixed now

- 54 books searched on the same 2018-2026 data. The best of 54 is biased upward; the 2023+ column and the seed p90
  are reported to show it.
- Borrow rates and locate failure rates are model assumptions, not TradeZero data. If L0 or L25 is far above TZC,
  the answer depends on a number only TradeZero can give.
- Recalls and buy-ins are not modelled.
