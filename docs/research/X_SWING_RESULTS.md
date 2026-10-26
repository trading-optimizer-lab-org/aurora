# X traders momentum swing study: results

Pre-registration: [X_SWING_PREREGISTRATION.md](X_SWING_PREREGISTRATION.md). Run 40370841411 (2026-10-26, GitHub).
Full report: [X_SWING_REPORT.md](X_SWING_REPORT.md). Locked period (2021+) never read.

**All 8 candidates fail validation (2011-2020).** None meets any of the three criteria.

| candidate | validation CAGR | max drawdown | monthly Sortino | trades a year | win rate |
|---|---|---|---|---|---|
| SPY | 13.8% | -33.7% | 1.60 | - | - |
| b1_hold5 (Felipe breakout, 5 days) | -4.0% | -42.9% | -0.60 | 130 | 42% |
| b1_ma20 (breakout, MA20 trail) | 0.1% | -43.9% | 0.05 | 89 | 28% |
| b2_ma20 (ohiain pullback) | 2.2% | -51.3% | 0.27 | 171 | 30% |
| b3_quick (Stockbee burst) | 4.4% | -38.6% | 0.56 | 177 | 26% |
| best with industry filter: b3_quick_ind | 3.7% | -29.3% | 0.52 | 127 | 27% |

Train (1995-2010) is worse: every candidate loses money there.

**Industry filter (Steve Jacobs' claim):** it does not help every year. With minus without, the yearly difference
changes sign from year to year for all four rules (for example b2: +8.3% in 2011, -18.5% in 2013, -32.9% in 2020). It
lowers the drawdowns a little and the number of trades, not the return.

**Data caveat:** Yahoo returned 2,847 of the 5,332 symbols in the job (the rest were throttled or failed). The universe
is the 1,000 most liquid each day, so the missing names matter less, but the run is not the full catalog. With every
candidate far from the bar (best CAGR 4.4% vs SPY 13.8%, Sortino 0.56 vs 2.0), a full download would not change the
verdict.

## Reading

The published swing rules, made mechanical on liquid US stocks with daily bars, do not beat SPY: low win rates
(25-42%) and winners too small to pay for them after 10 bps a side. What the X traders report likely depends on
discretion (which setups to skip), intraday entries, or small caps outside this universe.
