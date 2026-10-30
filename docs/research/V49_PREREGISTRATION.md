# v49: the RU size dial with TradeZero's real borrow costs and broker rules: pre-registration

Written and committed on 2026-10-30, before any v49 return was computed, after REVISION_ESTRATEGIA_ES.md, at the
request relayed by CENTRAL for the owner. Code: `scripts/run_v49.py`, tests `tests/test_v49.py`, generator
`scripts/gen_v49_wf.py`, workflow `v49.yml`.

## 1. The books (5)

DS1 0.20, NS 0.40, at most 5 new positions a day, RU 0.40 / 0.30 / 0.25 / 0.20 / 0.15.

## 2. The cost and rule sets

Every set starts from v47's TZA rules (v48b) on v43's minute replay with v48's 31-seed ensemble.

- **TZA**: v48b unchanged (reference and check).
- **TZC (the main set)**, TZA plus:
  1. **Borrow by calendar day.** The model's borrow rate (the v19 cell fee, doubled, at least 100% a year) is charged
     for every calendar day between the first and the last session the short is held, not per session; weekends
     and holidays pay, as TradeZero charges every night until the cover settles (three nights from a Thursday).
     100-share lots stay as in v29.
  2. **Margin interest** of 9% a year on the short's value, per calendar day held (conservative: TradeZero may
     charge it only on a debit balance).
  3. **Locates that fail in squeezes**: a HOT-tier entry finds no locate with probability 50%, an HTB-tier entry 10%,
     fixed by the symbol and the session.
  4. **The 2:1 rule enforced**: when the short market value is over twice the equity at 15:45, every open position
     is covered in proportion at market from 15:45 down to 2:1, and the positions stay reduced afterwards.
  5. **Close entries capped by volume**: a close entry at market at 15:55 gets at most 10% of the shares traded
     from 15:55 to 15:59; the rest is not entered.
  6. **Halts**: unchanged; the replay already fills after a halt at the reopening price.
- **TZC-M0**: TZC without margin interest.
- **TZC-B2**: TZC with the borrow rate doubled.

## 3. The measures

v29's bootstrap: 4,000 one-year paths from $5,000, ruin at or under $1,250; ensemble mean median and ruin, 90th
percentile of ruin over seeds, on all, 2018-2022 and 2023+ paths, base costs and HOT 5%. Counts of forced 2:1
covers, failed locates and capped entries.

## 4. The answer (decision rule fixed now)

Among the 5 books, those whose TZC ensemble mean ruin on all paths is at most 2.5% at base costs and at HOT 5%; the
answer is the one with the highest TZC ensemble mean median at base costs. Its one number each: the TZC ensemble
mean median and ruin at base costs, all paths. If none passes, there is no answer and the report gives the book
with the lowest TZC ruin and its numbers.

## 5. Checks

The RU 0.30 book under TZA reproduces v48b: ensemble median $14,411 and ruin 1.0%, within $200 and 0.3 points.

## 6. Caveats fixed now

- Borrow rates are the model's cell rates, not TradeZero's quotes, which change daily; TZC-B2 bounds that.
- Every year 2018-2026 has been seen. The dropout ensemble is one model of which trades fill.
- Recalls and buy-ins are not modelled.
