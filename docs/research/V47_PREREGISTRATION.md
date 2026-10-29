# v47: the book under TradeZero's real API rules: pre-registration

Written and committed on 2026-10-29, before any v47 return was computed, at the owner's request after the review in
SMALLCAP_PENDIENTE_2_ES.md. Code: `scripts/run_v47.py`, tests `tests/test_v47.py`, generator
`scripts/gen_v47_wf.py`, workflows `v47-canary.yml`, `v47.yml`.

## 0. Why

TradeZero's developer documentation, read on 2026-10-29, says:
- `POST /order` takes only Market, Limit, Stop and StopLimit. There is no market-on-close or limit-on-close order.
- Opening-auction orders (`AtTheOpening`) exist: Market or Limit, sent from 04:00 to 09:25.
- Market and Stop orders work only in regular hours.
- The API gives no market data.
- Locates are priced per share and refused under $0.50.
- Leveraged accounts must be at 2:1 from 15:45 and going into the close.

The book was tested with closing-auction entries for NS and closing-auction exits, both decided on the day's close.
v47 asks whether the book survives the rules an API bot can actually follow. It does not search for a better book.

## 1. The book and the engine

v43/v44/v46's book (DS1 20%, RU 70%, NS 40%), v43's minute replay and central realism case (`next_open` fills, 10%
of a bar's volume, liquidation at `next_vwap`), TradeZero International costs, the four cost sets, v29's bootstrap
(4,000 one-year paths from $5,000; ruin at or under $1,250) at the five levels and from $2,000. v43's replay gains one
hook, inactive by default: covers at a close set off as a market order at a chosen minute instead of the closing
auction.

## 2. The variants (each alone, then two combined books)

| id | change |
|---|---|
| base | as v43 |
| O1 | close entries decided at 15:50: each member's daily signals rebuilt with the 15:50 price as the close, the high and low to 15:50; the close entries kept are those signals, entered at market at 15:55. Open entries unchanged |
| C955 | close entries at market at 15:55 on the real close's signals (v46's Q3, the control for O1) |
| X951, X955, X958 | covers at a close sent at market at 15:51, 15:55, 15:58; what the volume cap leaves fills at the last bar's close |
| L1, L2, L3 | locate per share instead of a share of value: HTB / HOT at $0.01 / $0.03, $0.02 / $0.05, $0.03 / $0.10, scaled in the HOT 5% and high cost sets as their percentages are |
| F050, F100, F200, F250 | no trade under $0.50, $1, $2, $2.50 |
| SSR | no short entry while the SEC's short-sale price test is on: a low 10% or more under the prior close on the day before, or on the entry day before the entry |
| U10, U25, U50 | 10%, 25%, 50% of HTB and HOT trades find no locate (seeded by symbol and day) |
| M05, M10, M20 | 5%, 10%, 20% of days send no entries (seeded by day; exits still run) |
| TZA | O1 + X955 + L1 + F050 + SSR: the book as the API can run it |
| TZB | TZA with L3, F200, U25 and M10: the stress case |
| TZA0 | TZA with C955 instead of O1 |

Diagnostics for base, TZA and TZB: the share of sessions whose short market value exceeds twice the equity at
15:45 and at the close; the broker-rule liquidations counted in the same process; O1's close entries kept, dropped
and added against the real close's.

## 3. The questions and the pass marks

- **Q1 (the book is operable through the API)**: TZA's median from $5,000 >= 0.85 x the base's, ruin <= 2.5% at base
  costs and at HOT 5%, and summed log growth positive on both symbol halves.
- **Q2 (descriptive)**: each variant's median, ruin, p10 and change against the base, at each cost set.
- **Q3 (descriptive)**: TZB, the stress case; and TZA from $2,000.
- **Check**: the base reproduces v43's central case (median $22,006, ruin 0.1%) within $200 and 0.2 points.

## 4. Caveats fixed now

- Every year 2018-2026 has been seen; v47 measures robustness, not edge.
- O1 rebuilds signals only where minute bars exist: the entry and holding sessions of the book's own trades. A
  close entry that fires at 15:50 but not at the close is added only on those sessions, so additions are
  undercounted. The day's volume and dollar volume stay the full day's.
- Per-share locates are charged once a trade. Overnight borrow on HOT names stays as v29 modelled it.
- The TradeZero sub-$2 cash-only rule conflicts between two support pages; F200 bounds it.
- The 2:1 rule is measured, not enforced.
- Stops are unchanged: the book's stops are checked in regular hours, where Stop orders exist, and the FREE plan has
  no extended-hours stops.
- The decision data source is not tested: the bot needs a 15:50 price from a feed outside the TradeZero API.
- The API agreement's exclusion of fully unattended systems is a contract question, not a backtest; M05-M20 measure
  missed days if the owner has to approve each day's orders.
