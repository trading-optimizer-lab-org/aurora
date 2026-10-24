# Options study 2 (0DTE, overnight, cross-section): pre-registration

Written and committed on 2026-10-24, at the owner's request ("more option strategies, also 0DTE"), after the
earnings options study failed (`EARNINGS_OPTIONS_RESULTS.md`) and **before any price of this study was loaded for
a result.** One probe checked data formats only (`options-study2-probe.yml`, run 1, counts and times): SPY and QQQ
list an expiry every weekday in 2024 and 2025 (IWM only Monday, Wednesday and Friday in early 2024, so it is not
used); 0DTE contracts near the money have a 15-minute bar every quarter hour from 09:30 to 16:00 and about 380-405
one-minute bars a day; a SPY weekly contract trades in every quarter hour of a day before its expiry.

## Literature behind the trials

- Vilkov (2024, revised 2026), "0DTE Trading Rules": SPX 0DTE positions from 10:00 ET to expiry, 2016-2026; a
  positive but small same-day variance risk premium; risk reversals the only structure with positive mean and median;
  iron butterflies/condors lose after spreads; put ratio spreads the strongest series (conditional).
- Muravyev and Ni (2020, JFE): delta-hedged S&P 500 option returns are negative overnight (-1.0%, -2.6% for options
  under three weeks) and positive intraday (+0.3%), 2004-2013.
- Jones and Shemesh (2018, JF): option returns are lower over non-trading periods (weekends), weak in index options.
- Goyal and Saretto (2009, JFE): straddles on stocks with historical volatility far above implied volatility beat
  straddles with implied far above historical, monthly.

## Trials (11)

| Trial | Underlying | Position | Entry | Exit |
|---|---|---|---|---|
| `Z1_short_straddle` | SPY, QQQ 0DTE | sell ATM call + put | 10:00 bar | 15:45 bar / expiry |
| `Z2_iron_fly` | SPY, QQQ 0DTE | Z1 plus long call at S0 x 1.01 and long put at S0 x 0.99 | 10:00 bar | 15:45 bar / expiry |
| `Z3_iron_condor` | SPY, QQQ 0DTE | sell call S0 x 1.005, put S0 x 0.995; buy call S0 x 1.01, put S0 x 0.99 | 10:00 bar | 15:45 bar / expiry |
| `Z4_risk_reversal` | SPY, QQQ 0DTE | buy call S0 x 1.005, sell put S0 x 0.995 | 10:00 bar | 15:45 bar / expiry |
| `Z5_put_ratio` | SPY, QQQ 0DTE | buy 1 put S0 x 0.995, sell 2 puts S0 x 0.99 | 10:00 bar | 15:45 bar / expiry |
| `N1_overnight_short` | SPY, QQQ | sell ATM straddle, delta-hedged with shares | 15:45 bar | next session's 09:45 bar |
| `N2_intraday_long` | SPY, QQQ | buy ATM straddle, delta-hedged with shares | 09:45 bar | 15:45 bar, same session |
| `N3_weekend_short` | SPY, QQQ | N1 when the next session is 3 or more calendar days later | 15:45 bar | next session's 09:45 bar |
| `X1_vol_spread` | single stocks | long straddles of the top HV-IV decile, short straddles of the bottom decile | monthly | expiry |
| `X2_long_cheap` | single stocks | long straddles of the top HV-IV decile | monthly | expiry |
| `X3_short_rich` | single stocks | short straddles of the bottom HV-IV decile | monthly | expiry |

No other trial, parameter or filter enters the decision.

## Common rules

- **Times** are New York. "The hh:mm bar" is the 15-minute bar starting at hh:mm; its price is its volume-weighted
  price (VWAP). Alpaca SIP bars for shares, Alpaca option bars (trades) for options, unadjusted.
- **Sessions**: days with regular-session SPY bars, from 2024-01-22 to 2026-10-23. **Discovery**: trades whose
  entry is 2024-02-01 to 2025-12-31; **validation**: entry 2026-01-01 onward, computed in the same run, used only as
  below.
- **Missing data**: a session on which the SPY ATM 0DTE call has no bar from 09:30 to 15:45 is a gap day (vendor
  gap, like 2024-02-02); no trade enters, exits or is held over a gap day; the count is reported.
- **Strikes**: listed strikes of the chosen expiry that exist as both call and put; "strike at X" is the listed
  strike nearest X, ties to the lower. ATM = strike at the underlying's entry-bar VWAP S0. A structure whose
  strikes collapse (a wing equal to or inside its short strike, or a ratio's two strikes equal) is skipped and
  counted.
- **Entry**: every leg needs a trade in the entry bar; otherwise no trade.
- **Exit price** of a leg: its exit-bar VWAP; else the first later bar with a trade that session up to the 15:45
  bar; else its intrinsic value at the underlying's last regular-session price (a short leg pays intrinsic plus 10%
  of its entry price). Fallbacks are counted.

## 0DTE (Z) rules

- The contract expires on the entry session. Entry at the 10:00 bar. At the 15:45 bar each leg is closed at its
  VWAP; a leg whose 15:45-bar VWAP is $0.05 or less, or that has no 15:45 bar, is left to expire and is worth its
  intrinsic value at the underlying's 15:45-bar close (the 16:00 price), with no exit cost. Assignment is ignored.
- **Statistic**: P&L per share net of costs divided by S0 (percent of spot, as in Vilkov). Also reported: P&L on
  the maximum loss for Z2 and Z3.

## Overnight and intraday (N) rules

- Expiry: the first listed expiry 7 or more calendar days after the entry session. ATM straddle at S0.
- **Delta hedge**: implied volatility from the straddle's entry price (Black-Scholes, no rate, no dividend, time to
  the expiry's 16:00 in calendar days / 365); straddle delta = 2N(d1) - 1; the position holds -delta shares per
  long straddle (+delta per short), opened at the underlying's entry-bar VWAP and closed at its exit-bar VWAP.
- **Statistic**: P&L per straddle net of costs divided by the straddle's entry price.

## Cross-section (X) rules

- **Universe**: Alpaca's active US equities with options enabled (today's list: survivorship, stated). Each month,
  the formation session F is the first session after the month's standard expiry (third Friday, or the listed
  expiry nearest it). At F's prior close: price $10 or more; then the 500 names with the highest 20-session median
  dollar volume (split-adjusted daily bars).
- **Expiry**: the listed expiry nearest the next month's third Friday (within 3 calendar days). ATM straddle at the
  stock's F 15:30-bar VWAP; entry price = the call's and put's 15:30-bar VWAP (else no position).
- **Signal**: HV = annualized standard deviation of daily log returns over the 252 sessions before F (Goyal and
  Saretto use 12 months); IV = Black-Scholes volatility of the straddle's entry price; signal = HV - IV. Deciles
  each month among names with a position.
- **Hold to expiry**: payoff = intrinsic value at the stock's last regular-session 15-minute close on the expiry
  date, no exit cost; early exercise and assignment are ignored.
- **Statistic**: the equal-weighted mean straddle return of the month (X1: long-decile mean plus short-decile mean,
  each on its own premium); t on the monthly series (each month one observation, i.i.d. standard error).

## Costs

- Each leg pays a half-spread on entry and on every exit that is not an expiry; fees $0.05 per contract per side.
- **SPY and QQQ options**: base half-spread max(0.25% of the price, $0.01); high max(0.75%, $0.03). Their quoted
  spread is usually a penny or two near the money; the grid is wider.
- **Shares** (N hedge): $0.01 per share per side, base and high.
- **Single-stock options** (X): base max(2%, $0.025); high max(4%, $0.05), as in the earnings study.
- No historical option quotes exist on Alpaca, so spreads are a grid, not measured.

## Decision

- **Discovery pass** (each trial): at least 200 trades (X: 200 straddle positions and 18 months); mean net > 0 at
  base costs with t >= 2.61 (Bonferroni over 11 trials, one-sided 0.45%); mean net > 0 at high costs. Z and N: t
  clustered by ISO week of entry. X: t on the monthly series.
- **Validation** (only discovery-passing trials): mean net > 0 at base costs with t >= 1.65 and mean net > 0 at high
  costs. **Met** if one trial passes both; then it is a candidate for a portfolio.
- Reported for every trial, no decision: trades, mean, median, hit rate, 1% expected shortfall, worst trade, by
  underlying, by year, by weekday (Z, N), fallback share.
- **Book** (reported, not part of the criterion), Z2 and Z3 only if they pass discovery: $100,000; each trade risks
  2% of equity on its maximum loss; at most 15% at risk at once; CAGR, maximum drawdown and worst session.

## Caveats fixed now

Spreads are assumed; option prices are 15-minute trade VWAPs, not quotes; data start in 2024 (about 2.8 years);
0DTE exits at 15:45-16:00 and settle at the 16:00 price without assignment; the delta hedge is computed once at
entry; X uses today's list of optionable stocks. The researcher has read the papers above; nothing about 2024-2026
SPY/QQQ option returns.
