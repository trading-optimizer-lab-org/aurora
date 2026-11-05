# v55: v49's book decided on Alpaca's free IEX price at 15:50: pre-registration

Written and committed on 2026-11-05, before any v55 number was computed. The owner will run v49's book
(DS0.20-NS0.40-RU0.20-N5) as an automated bot on TradeZero. TradeZero's API has no market data, and the owner pays
for none. The book's close entries are decided at 15:50 (v47's O1): each member's daily signals rebuilt with the
15:50 price as the close and the regular session's high and low to 15:50, entered at market at 15:55. v47 left the
decision source untested (V47_PREREGISTRATION.md section 4). v55 asks whether Alpaca's free IEX feed, the free
real-time source the bot can read at 15:50, is good enough for those decisions.

## 1. Data

- **fetch**: Alpaca's IEX one-minute bars (`feed=iex`, raw prices), 09:30-15:49 ET, for every symbol-day of v43's
  minute store (the sessions v47's O1 can rebuild). Bars stay in the Actions cache; nothing is published.
- The historical IEX bars stand in for the real-time IEX snapshot the bot would read at 15:50.

## 2. Decision sources (the only change against v50's TZC run of the book)

- **sip**: v47's O1 on v43's consolidated bars, as v50 ran it. Check: it must reproduce v50's TZC answer for the
  book, median $8,498 within $200 and ruin 0.0% within 0.3 points.
- **iex**: price = the close of the last IEX bar before 15:50, high and low = the IEX bars' from 09:30 to 15:49,
  split-adjusted as the consolidated bars. A session with no IEX bar before 15:50 gets no close entry (the bot
  fails closed); open entries are unchanged.
- **iex10**: iex, but the last IEX bar must start at 15:40 or later, else no close entry.
- Everything else as v50's TZC set: v49's ensemble of seeds, costs, locates, the 2:1 rule, the volume cap, v29's
  bootstrap of one-year paths from $5,000, ruin at or under $1,250.

## 3. Decision

- **PASS** if **iex** has TZC ensemble median from $5,000 at least 0.90 times sip's, on all paths at base costs,
  and ruin at most 2.5% at every ensemble task (base and HOT5). Reading: the free feed is good enough; the bot
  decides on IEX.
- **NOT MET** otherwise. iex10 is descriptive; it is the candidate fix if iex fails on stale prices, and is not a
  second chance at the verdict.
- Descriptive, from the iex jobs: the share of sip's decision sessions with an IEX decision, the age of the last IEX
  bar, and the relative error of the IEX price, high and low against the consolidated ones (median, 90th and 99th
  percentile, share over 1%); O1's close entries kept, dropped and added against the real close.

## 4. Caveats fixed now

- As v47's O1: signals are rebuilt only on the book's own entry and holding sessions, so close entries that fire at
  15:50 but not at the close are undercounted, and the day's volume and dollar volume stay the full day's. The bot
  cannot read the day's consolidated volume from IEX; that is not tested here.
- Historical IEX bars may differ from the snapshot served live at 15:50 by a few seconds of trades.
- Every year 2018-2026 has been seen; v55 measures the data source, not the edge.
