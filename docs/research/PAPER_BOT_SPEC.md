# TradeZero paper bot: the 2026 book as it trades live

Written 2026-11-14, before the bot placed any order. The bot trades v58's book DS0.20-NS0.60-RU0.25-N5 on the
TradeZero paper account, sized on a virtual $5,000, and checks each short against a live locate quote that it
cancels. Its purpose is to measure how far live fills, locates and costs fall from the backtest.

## 1. Members (2026 walk-forward picks, v33 "limit" arm, as run by v35-v58)

Source: `docs/research/data/v33_summary.json` arms.limit, year 2026; configs decoded from `run_v28.registry()` and
`run_v26.source_registry()`.

| member | pick | signal on day t | entry | exit |
|---|---|---|---|---|
| DS1 (0.20) | DS1_RUNUP\|12936 = entry 1822 | close / min(5 prior closes) >= 4; close $1-20; 20-day dollar volume >= $1M | day t+1: sell limit at close_t x 1.20, day order | close of the 10th session counting the entry day; no stop, no target |
| RU (0.25) | RU_RUNUP\|12936 = entry 10897 | same as DS1 | same as DS1 | same as DS1 |
| NS (0.60) | NS_NIGHTSHORT\|20359 = entry 546 | open_t >= 1.30 x close_t-1; price <= 0.90 x open_t; price in the bottom 25% of the day's range; price $2-5 | day t: decided at 15:50 on IEX, market sell at 15:55 | cover at entry x 0.70 from day t+1 (good-till-cancel limit), else at the close of day t+3; no stop |

## 2. Book rules (run_v28_after, run_v33, run_v48, run_v49)

- Size per name = fraction x virtual equity, capped at 1% of the prior session's dollar volume.
- At most 5 new names a day across members, ranked by run-up (DS1, RU) or gap (NS); ties in the order DS1, RU, NS.
  One position per symbol. At most 20 open. Gross short at most 2 x equity.
- A symbol signals at most once in 20 sessions per member.
- Price floor $2.50 on the prior close (open entries) or the 15:50 price (close entries).
- SSR: no open entry on a name whose prior session's low was at or under 0.9 x its prior close.

## 3. Locates

- Paper treats every short as easy to borrow. Before each entry the bot asks the live account for a locate quote on
  that name and size, records offered or not and the price, and cancels it. It never accepts.
- Not offered: the trade is recorded as "no locate" and not placed. Offered: the trade is placed and the quoted
  price is charged against the virtual equity.
- Results go only into the owner's encrypted artifact, as the borrow logger's.

## 4. Known gaps from the backtest

- The backtest charges borrow fees from a model table; the paper account charges none. The bot reports P&L before
  and after the model's fee.
- The 0.8 x availability factor and the close-entry volume cap of the backtest are not applied; the 1% dollar
  volume cap is.
- IEX prices at 15:50 differ from the consolidated tape; v55 measured the cost of this at 6% of the median.
- Paper fills are TradeZero's simulation, not the market's.
