# v48b: the RU size dial under TradeZero API rules, and the capital plans: pre-registration

Written and committed on 2026-10-30, before any v48b return was computed, after V48_RESULTS.md, at the owner's
request ("pruebalo todo y dame la estrategia definitiva", with the $2,500 plus $2,500 reserve plan of v30). Code:
`scripts/run_v48b.py`, tests `tests/test_v48b.py`, generator `scripts/gen_v48b_wf.py`, workflow `v48b.yml`.

## 1. The books (8)

DS1 0.20, NS 0.40, at most 5 new positions a day, RU 0.70 / 0.50 / 0.40 / 0.30 / 0.25 / 0.20 / 0.15; and the base
book (RU 0.70, 3 new a day). v48 found DS1 0.20 and NS 0.40 best at every RU size and 5 new a day equal to 3.

## 2. The engine

v47's API rules (TZA: close entries decided at 15:50 and entered at market at 15:55, close covers at market at 15:55,
locate $0.01 / $0.03 a share, no trade under $0.50, no entry under the short-sale price test) on v43's minute
replay, TradeZero International costs, v48's ensemble (seed 0 = history, seeds 1-30 drop 10% of candidates), base
costs and HOT 5%.

## 3. The measures

- **Bootstrap (v29)**: 4,000 one-year paths from $5,000, ruin at or under $1,250; ensemble mean median and ruin, the
  90th percentile of ruin over seeds, on all, 2018-2022 and 2023+ paths.
- **Capital plans (v30's accounts)**: an account ending a session under $500 deposits the reserve once (paying any
  debt), else freezes; losses are not capped; total wealth W = equity plus any reserve not deposited. Paths: v30's
  block bootstrap, 4,000 paths of one year (seed 29) and three years (seed 30). Plans:
  - **A**: $5,000 in one account;
  - **B**: $2,500 at the start and a $2,500 reserve;
  - **C**: $2,000 alone.
  Per plan and horizon, the ensemble mean over seeds of the median W, the 10th percentile, the share of paths with
  W at or under $1,000, the mean of the worst 5% (es5) and the share that deposits the reserve.

## 4. The definitive strategy (decision rules fixed now)

1. **Book**: among books whose ensemble mean ruin on all paths is at most 2.5% at base costs and at HOT 5%, the one
   with the highest ensemble mean median at base costs. If none passes, there is no definitive book and the report
   gives the frontier.
2. **Capital plan**: B replaces A for the chosen book when, at one year and base costs (ensemble means), B has a
   higher median W, a higher es5 and no larger share at or under $1,000 (v30's rule). The three-year numbers are
   reported, not used.
3. Reported, not used: the 2023+ numbers, HOT 5%, plan C.

## 5. Checks

The base book at seed 0 reproduces v47's TZA ($20,742, ruin 5.9%) within $300 and 0.5 points, and the RU 0.70 book
at 5 a day v48's chosen TZA ensemble ($18,765, ruin 7.7%) within $300 and 0.5 points.

## 6. Caveats fixed now

- Every year 2018-2026 has been seen; v32-v39 and v48 searched sizes on them. The rule picks among 7 points of one
  dial, which limits but does not remove the selection.
- The dropout ensemble is one model of which trades fill.
- The 2:1 rule at 15:45 is measured in v47, not enforced.
