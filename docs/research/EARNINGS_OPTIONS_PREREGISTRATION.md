# Earnings options: pre-registration

Written and committed on 2026-10-24, at the owner's request ("an edge based on a backtest and historical data" for
a third portfolio around earnings releases), **before any option or stock price of the study was loaded for a
result.** Three probes checked the data formats only (`earnings-options-probe.yml`, runs 1-3): expired contracts
are listed with `status=inactive`; option bars exist from mid-January 2024; historical option quotes are not
served (404); every option bar of 2024-02-02 is missing although that day's trades exist; the SEC's
`acceptanceDateTime` is New York wall-clock time converted to UTC twice (JPM, WMT and PG at 06:30-07:00, MSFT,
META and NFLX at 16:00-16:10 once corrected). Code: `scripts/run_earnings_options.py`, tests
`tests/test_earnings_options.py`, workflows `earnings-options-canary.yml` and `earnings-options.yml`.

## Hypotheses (10 trials)

| Trial | Position | Entry | Exit |
|---|---|---|---|
| `H1_runup_3` | long ATM straddle | 3 sessions before the eve | the eve, before the release |
| `H1_runup_5` | long ATM straddle | 5 sessions before the eve | the eve, before the release |
| `H2_hold_all` | long ATM straddle, every event | the eve | the reaction session's morning |
| `H2_cheap_08` | long ATM straddle if IM/HM < 0.8 | the eve | the reaction session's morning |
| `H2_cheap_06` | long ATM straddle if IM/HM < 0.6 | the eve | the reaction session's morning |
| `H3_momentum` | long ATM call if the stock rose over the 60 sessions to the eve's prior close, else a put | the eve | the reaction session's morning |
| `H3_last_reaction` | long ATM call if the previous release's reaction was up, else a put | the eve | the reaction session's morning |
| `H4_fly_all` | short iron fly, every event | the eve | the reaction session's morning |
| `H4_fly_12` | short iron fly if IM/HM > 1.2 | the eve | the reaction session's morning |
| `H4_fly_15` | short iron fly if IM/HM > 1.5 | the eve | the reaction session's morning |

H1 follows Gao, Xing and Zhang (2018, JFQA): straddles bought before a release gain as implied volatility rises
into it (1996-2010 data). H2 and H4 follow Milian (2023, JRFM): straddle returns depend on the historical move
relative to the implied move. H3 adds direction. No other trial, parameter or filter enters the decision.

## Events

- **Releases**: SEC 8-K (not 8-K/A) with Item 2.02, from the submissions JSON (with `SEC_USER_AGENT`), filed
  2021-01-01 onward. Time = `acceptanceDateTime` corrected as above. Before 09:30 on a session day: the reaction
  session R is that session. At or after 16:00, or on a non-session day: R is the next session. Between 09:30 and
  16:00: dropped (released during the session). Two releases of one company within 20 sessions: the later one is
  dropped.
- **Scheduled only**: the company's previous Item 2.02 release was 70-110 calendar days earlier (a quarterly
  cadence known in advance; pre-announcements break it).
- **Eve** E: the session before R. Entry session for H1: E-3 or E-5 sessions.
- **Universe**: tickers of the SEC's `company_tickers.json` (today's list: names delisted since are missing, a
  survivorship bias the report states). At the entry session's prior close: price $10 or more and the median dollar
  volume of the 20 sessions before $50M or more (Alpaca daily bars, SIP, unadjusted).
- **Periods** by R: discovery 2024-02-01 to 2025-12-31; validation 2026-01-01 to the data's last day, computed in
  the same run, used only as below.

## Prices

- **Times** are New York. A price "at" a session is the volume-weighted price of its 15:30 bar (15:30-15:45); if
  that bar has no trade, the latest 15-minute bar with a trade from 14:30 on; otherwise there is no price and **no
  entry** (decided before entry). The morning exit price is the 09:45 bar's (09:45-10:00), else the first later
  bar with a trade that session, else the leg's intrinsic value at the stock's last price of R (for a short leg:
  intrinsic plus 10% of its entry price).
- **Stock** prices: Alpaca 15-minute SIP bars, same rule (needed for the strike and the intrinsic value).
- **Contracts**: Alpaca's contract list (inactive and active). Expiry: the first listed expiry after R's date.
  ATM strike: the listed strike nearest to the stock's price at entry (ties: the lower). Straddle = call + put at
  that strike. H1 uses that expiry with the strike set at its own entry.
- **Iron fly**: sell the ATM call and put, buy the call at the listed strike nearest to K x (1 + 1.5 IM) and the put
  nearest to K x (1 - 1.5 IM), each at least one strike away from K. Return on the maximum loss (wing width less
  the net credit).
- **IM** (implied move) = straddle price / stock price at the eve's entry. **HM** (historical move) = median of
  |close(R)/close(E) - 1| over the company's previous scheduled releases within three years, at least 4, at most
  8. H2_cheap, H3_last_reaction and H4_fly_12/15 need HM or the previous reaction; without it, no trade.
- **Missing data days**: a session on which the SPY contract nearest to the money of the next expiry has no
  15-minute bar is a gap day (2024-02-02 is one); events with an entry, eve or reaction on a gap day are dropped
  and counted (the gaps are the vendor's, not the event's).

## Costs

- Each leg pays a half-spread on entry and on exit. **Base**: max(2% of the price, $0.025) per contract leg.
  **High**: max(4%, $0.05). Fees $0.05 per contract per side (Alpaca charges no commission; regulatory fees).
- No historical quotes exist, so spreads are a grid, not measured. The report states it.
- Return of a long position = (exit value - entry cost) / entry cost; short iron fly on its maximum loss.

## Decision

- **Statistic**: mean net return a trade, t clustered by ISO week of R (cluster-robust standard error of the mean).
- **Discovery pass** (each trial): at least 200 trades; mean net > 0 at base costs with t >= 2.58 (Bonferroni over
  the 10 trials, one-sided 0.5%); mean net > 0 at high costs.
- **Validation** (only trials that passed discovery): mean net > 0 at base costs with t >= 1.65, and mean net > 0
  at high costs. **Met** if one trial passes both; then it is a candidate for the third portfolio.
- **Book** for each discovery-passing trial (reported, not part of the criterion): $100,000, each trade risks 2% of
  the equity (the premium, or the fly's maximum loss), at most 15% at risk at once; capacity first to the lowest
  IM/HM (H2), the highest (H4), else the highest dollar volume; equity marked at each exit; CAGR, maximum drawdown
  and worst session against the -20% limit of the challenges.
- Also reported for all trials (no decision): trades, mean, median, hit rate, by period, by release time
  (before-open/after-close), by dollar-volume tercile, by year, and the mean IM/|realized move| ratio.

## Caveats fixed now

Spreads are assumed; option bars are trade prices (no bid/ask), a 15-minute VWAP; Alpaca's data starts in 2024
(about 11 seasons); the release date is the realized one (the scheduled filter removes most surprises); today's
ticker list; the researcher read a vendor blog saying straddle buyers did well in the 2026-02 season, which is in
validation.
